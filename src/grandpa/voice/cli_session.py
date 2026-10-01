"""Interactive offline-first voice assistant session."""

from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from enum import StrEnum
from typing import Callable, Protocol

from grandpa.cli.theme import FAREWELL_TEXT
from grandpa.engine._base import (
    EngineConnectionError,
    EngineModelLoadError,
    EngineModelNotFoundError,
)
from grandpa.voice.assistant import VoiceCommandProcessor
from grandpa.voice.errors import (
    MicrophoneUnavailableError,
    VoiceDependencyError,
    VoiceError,
    VoiceRecognitionError,
)
from grandpa.voice.microphone import MicrophoneCapture
from grandpa.voice.presenter import VoicePresenter
from grandpa.voice.speech_to_text import FasterWhisperSpeechToText
from grandpa.voice.text_to_speech import GrandpaTextToSpeech
from grandpa.voice.vad import VoiceActivityConfig
from grandpa.voice.wake_word import DEFAULT_WAKE_PHRASES, WakeWordDetector

logger = logging.getLogger(__name__)

EXIT_PHRASES = {
    "stop listening",
    "please stop listening",
    "stop listen",
    "exit voice mode",
    "exit voice",
    "goodbye grandpa",
    "goodbye now",
    "goodbye",
    "quit",
    "quit voice",
    "quit voice mode",
    "exit",
    "stop voice",
    "stop voice mode",
    "stop grandpa",
    "hey grandpa stop",
    "grandpa stop",
}


class VoiceSessionState(StrEnum):
    """Explicit states for the voice assistant loop."""

    IDLE = "idle"
    WAITING_FOR_WAKE_WORD = "waiting_for_wake_word"
    WAKE_DETECTED = "wake_detected"
    LISTENING_FOR_COMMAND = "listening_for_command"
    CAPTURING = "capturing"
    PROCESSING = "processing"
    EXECUTING = "executing"
    THINKING = "thinking"
    SPEAKING = "speaking"
    RECOVERING = "recovering"


class AudioCapture(Protocol):
    """Protocol for one-phrase microphone capture."""

    def capture(self, stop_event: threading.Event | None = None):
        """Capture one utterance."""

    def close(self) -> None:
        """Release microphone resources."""

    def reset(self) -> None:
        """Discard stale phrase audio before a new capture."""


class Transcriber(Protocol):
    """Protocol for speech-to-text engines."""

    def transcribe(self, audio) -> str:
        """Return recognized text."""


class Responder(Protocol):
    """Protocol for Grandpa text command processing."""

    def handle_user_input(self, text: str):
        """Return a response object with a ``text`` attribute."""


class Speaker(Protocol):
    """Protocol for text-to-speech engines."""

    def speak(self, text: str, stop_event: threading.Event | None = None) -> None:
        """Speak text."""

    def stop(self) -> None:
        """Stop current speech."""

    @property
    def is_speaking(self) -> bool:
        """Return whether playback remains active."""

    def wait_until_finished(self, stop_event: threading.Event | None = None) -> bool:
        """Wait for playback completion."""


@dataclass
class VoiceSession:
    """Phrase-by-phrase voice assistant loop for the Grandpa CLI."""

    microphone: AudioCapture
    transcriber: Transcriber
    responder: Responder
    speaker: Speaker | None = None
    output: Callable[[str], None] = print
    stop_event: threading.Event | None = None
    wake_word_enabled: bool = False
    wake_detector: WakeWordDetector | None = None
    wake_response_enabled: bool = True
    wake_response_text: str = "Yes?"
    wake_command_timeout_seconds: float = 10.0
    post_tts_cooldown_ms: int = 800
    echo_window_seconds: float = 3.0
    echo_similarity_threshold: float = 0.70
    clock: Callable[[], float] = time.monotonic
    cooldown_wait: Callable[[threading.Event, float], bool] = field(
        default=lambda stop, seconds: stop.wait(seconds)
    )
    presenter: VoicePresenter | None = None
    stt_model: str = "base"
    debug: bool = False
    state: VoiceSessionState = VoiceSessionState.IDLE
    _last_spoken_text: str = field(default="", init=False, repr=False)
    _last_spoken_at: float | None = field(default=None, init=False, repr=False)
    _last_timing: dict[str, float] = field(default_factory=dict, init=False, repr=False)
    _last_quiet_message: str | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.presenter is None:
            from grandpa.voice.presenter import VoicePresenter

            self.presenter = VoicePresenter(output=self.output, debug=self.debug)
        else:
            self.presenter.output = self.output
            self.presenter.debug = self.debug

    def run(self) -> int:
        """Run until an exit phrase, Ctrl+C, or unrecoverable setup error."""

        stop = self.stop_event or threading.Event()
        self.stop_event = stop
        logger.info("Voice assistant session started")
        self.presenter.print_banner("ollama", self.stt_model)

        exit_code = 0
        try:
            # Check inference engine availability at startup if responder supports it
            if hasattr(self.responder, "_ensure_engine"):
                try:
                    self.responder._ensure_engine()
                except (
                    EngineConnectionError,
                    EngineModelLoadError,
                    EngineModelNotFoundError,
                ) as exc:
                    from grandpa.engine.messages import (
                        engine_unavailable_message as _engine_unavailable_message,
                    )

                    msg = (
                        _engine_unavailable_message("ollama", exc)
                        if isinstance(exc, EngineConnectionError)
                        else str(exc)
                    )
                    self.presenter.print_error(msg)
                    return 1

            if self.wake_word_enabled:
                self._run_wake_word_loop(stop)
            else:
                self._run_direct_loop(stop)
        except KeyboardInterrupt:
            self.presenter.print_farewell(FAREWELL_TEXT)
            self._exit_message_printed = True
            stop.set()
            logger.info("Voice assistant stopped by keyboard interrupt")
        except (VoiceDependencyError, MicrophoneUnavailableError) as exc:
            self.presenter.print_error(str(exc))
            self._exit_message_printed = True
            logger.warning("Voice assistant setup error: %s", exc)
            exit_code = 1
        finally:
            stop.set()
            self._cleanup()
            self._exit_message_printed = True
        return exit_code

    def _run_direct_loop(self, stop: threading.Event) -> None:
        self.state = VoiceSessionState.IDLE
        self.presenter.on_idle_listening()
        while not stop.is_set():
            transcript = self._listen_for_transcript()
            if stop.is_set():
                break
            if transcript is None:
                continue
            self._handle_transcript(transcript, stop)
            if not stop.is_set():
                self.state = VoiceSessionState.IDLE
                self.presenter.on_idle_listening()

    def _run_wake_word_loop(self, stop: threading.Event) -> None:
        detector = self.wake_detector or WakeWordDetector(DEFAULT_WAKE_PHRASES)
        while not stop.is_set():
            self.state = VoiceSessionState.WAITING_FOR_WAKE_WORD
            wake_transcript = self._listen_for_transcript(
                "Waiting for wake word...", quiet_empty=True
            )
            if stop.is_set():
                break
            if wake_transcript is None:
                continue
            if is_exit_phrase(wake_transcript):
                self.presenter.print_farewell(FAREWELL_TEXT)
                self._exit_message_printed = True
                self._speak(FAREWELL_TEXT)
                logger.info(
                    "Voice assistant stopped by exit phrase while waiting for wake word"
                )
                stop.set()
                break
            match = detector.detect(wake_transcript)
            if not match.matched:
                continue

            self.state = VoiceSessionState.WAKE_DETECTED
            self.presenter.print_status("Wake word detected.")
            if self.wake_response_enabled:
                self.presenter.print_assistant_message(self.wake_response_text)
                self._speak(self.wake_response_text)
            if stop.is_set():
                break

            # Support natural one-shot commands such as
            # "Hey Grandpa, open Chrome" without forcing the user to repeat
            # the command in a second microphone capture.
            if match.command_text:
                self._handle_transcript(match.command_text, stop)
                if not stop.is_set():
                    self.presenter.print_status("Returning to wake-word mode...")
                continue

            self.state = VoiceSessionState.LISTENING_FOR_COMMAND
            command = self._listen_for_transcript(
                "Listening for command...", quiet_empty=True
            )
            if stop.is_set():
                break
            if command is None:
                self.presenter.print_status(
                    "No command heard. Returning to wake-word mode."
                )
                self.presenter.print_status("Returning to wake-word mode...")
                continue
            self._handle_transcript(command, stop)
            if not stop.is_set():
                self.presenter.print_status("Returning to wake-word mode...")

    def _listen_for_transcript(
        self, prompt: str | None = None, *, quiet_empty: bool = False
    ) -> str | None:
        stop = self.stop_event or threading.Event()
        if not self._wait_for_speaker(stop) or stop.is_set():
            return None
        self._reset_microphone()
        if prompt is not None:
            self.presenter.print_status(prompt)

        def on_speech():
            self.state = VoiceSessionState.CAPTURING
            self.presenter.on_speech_detected()

        t_capture_start = time.monotonic()
        try:
            try:
                audio = self.microphone.capture(
                    stop_event=self.stop_event,
                    on_speech_start=on_speech,
                )
            except TypeError:
                audio = self.microphone.capture(stop_event=self.stop_event)
        finally:
            self.presenter.stop_listening()

        t_capture_end = time.monotonic()

        # Say what happened before any of the silent returns below. Voice sat
        # showing "Listening..." for five to ten minutes with no output at all,
        # because every path out of a capture that heard nothing returns None and
        # the loop immediately starts another one. Whatever else is wrong, that is
        # its own bug: a capture that gives up has to say so.
        self._report_quiet_capture(audio)

        # Audio / VAD Gate: if audio is explicitly marked with no speech detected or empty data, ignore
        if hasattr(audio, "data") and not audio.data:
            return None
        if getattr(audio, "speech_detected", True) is False:
            return None

        voiced_duration = float(getattr(audio, "speech_active_seconds", 1.0) or 0.0)
        audio_rms = float(getattr(audio, "rms_level", 200.0) or 0.0)
        capture_duration = float(t_capture_end - t_capture_start)
        data_len = len(getattr(audio, "data", b"") or b"")
        num_samples = data_len // 2 if data_len else 0

        speech_rms = float(getattr(audio, "speech_window_rms", 0.0) or 0.0)
        threshold = float(getattr(audio, "speech_threshold", 0.0) or 0.0)
        noise_floor = float(getattr(audio, "noise_floor", 0.0) or 0.0)
        reason = str(getattr(audio, "finalization_reason", "") or "unknown")

        # Everything needed to read a capture without guessing.
        #
        # The previous line had capture_duration, voiced_duration and audio_rms,
        # and each of those is easy to misread on its own:
        #
        #   * capture_duration is wall clock including the wait for speech to
        #     begin, which is not in the buffer. A 4.88s capture sent Whisper
        #     about 2.4s of audio.
        #   * voiced_duration is the SUM of chunks above the threshold, not the
        #     span of the utterance. 1.40s of voiced can be a 3s sentence.
        #   * audio_rms is the whole buffer, diluted by pre-roll and trailing
        #     silence. A capture logged at 176 had speech chunks averaging 289.
        #
        # So the reason, the threshold, the floor it came from, and the speech
        # window on its own are all reported now.
        if self.debug:
            self.presenter.output(
                f"[DEBUG] reason={reason} "
                f"capture_duration={capture_duration:.2f}s "
                f"voiced_duration={voiced_duration:.2f}s "
                f"buffer_rms={audio_rms:.1f} "
                f"speech_rms={speech_rms:.1f} "
                f"threshold={threshold:.1f} "
                f"noise_floor={noise_floor:.1f} "
                f"samples={num_samples}"
            )
        logger.info(
            "voice capture: reason=%s capture=%.2fs voiced=%.2fs buffer_rms=%.1f "
            "speech_rms=%.1f threshold=%.1f floor=%.1f samples=%d",
            reason,
            capture_duration,
            voiced_duration,
            audio_rms,
            speech_rms,
            threshold,
            noise_floor,
            num_samples,
        )

        # A capture too marginal to be speech must not become a command.
        #
        # This used to apply only when the VAD finalised on silence_timeout, so a
        # capture that ended any other way -- maximum_duration, stream_ended --
        # skipped it entirely and a burst of noise could be transcribed and acted
        # on. That is the mechanism behind voice printing the farewell
        # immediately after "Listening..." with nothing said: a click crosses the
        # threshold, Whisper puts a stock word to it, and "Goodbye." is an exit
        # phrase.
        #
        # Refusing the exit vocabulary was the other candidate and is worse: it
        # removes documented behaviour ("quit" is what people say) and it only
        # ever protects exits. This protects every command on the same evidence.
        #
        # Applied whenever a VAD actually judged this capture, which is any
        # reason the capture path sets -- not just silence_timeout. Skipped when
        # the reason is the dataclass default, because then nothing measured
        # speech_active_seconds and its 0.0 means "not recorded" rather than "no
        # speech". A first pass keyed only on the field, and silently discarded
        # every hand-built CapturedAudio that left the metadata at its defaults.
        # A gate that cannot tell absent from zero is a gate that eats real audio.
        judged_by_vad = str(getattr(audio, "finalization_reason", "") or "") not in {
            "",
            "unknown",
        }
        if judged_by_vad and hasattr(audio, "speech_active_seconds"):
            if voiced_duration < 0.25 or (audio_rms < 120.0 and voiced_duration < 0.5):
                if self.debug:
                    self.presenter.output(
                        f"[DEBUG] Discarded non-speech audio (voiced={voiced_duration:.2f}s, rms={audio_rms:.1f})"
                    )
                logger.warning(
                    "voice discarded a marginal capture: voiced=%.2fs rms=%.1f "
                    "reason=%s",
                    voiced_duration,
                    audio_rms,
                    getattr(audio, "finalization_reason", None),
                )
                return None

            if _too_thin_to_transcribe(voiced_duration, speech_rms):
                # Do not spend a model call on this, and do not risk the answer.
                #
                # Two live captures were 0.50s and 0.70s of audio whose speech
                # chunks averaged 289 and 353 -- 1.6x and 2.0x the threshold, so
                # they cleared it, but barely. Whisper answered each with a
                # hundred words of "new, new, new..." at no_speech_prob 0.877 and
                # 0.832. The repetition filter caught both, which is the system
                # working; the model should not have been asked at all.
                #
                # Short AND quiet, not either alone: a clipped "yes" is short but
                # loud and must still work, and a long quiet mumble is real
                # speech that the confidence gates can judge for themselves.
                spoken = (
                    f"That was too short and too quiet for me to make out - "
                    f"{voiced_duration:.1f} seconds at level {speech_rms:.0f}. "
                    f"Say it again a little louder."
                )
                self.presenter.print_error(spoken)
                logger.warning(
                    "voice refused to transcribe a thin capture: voiced=%.2fs "
                    "speech_rms=%.1f threshold=%.1f reason=%s",
                    voiced_duration,
                    speech_rms,
                    threshold,
                    reason,
                )
                return None

        try:
            warning = str(getattr(self.microphone, "last_warning", "") or "").strip()
            if warning:
                self.presenter.print_error(warning)
            if self.stop_event is not None and self.stop_event.is_set():
                return None

            self.state = VoiceSessionState.PROCESSING
            self.presenter.on_transcribing()

            t_stt_start = time.monotonic()
            transcript = self.transcriber.transcribe(audio).strip()
            t_stt_end = time.monotonic()
            stt_duration = t_stt_end - t_stt_start

            self._last_timing = {
                "capture_duration": capture_duration,
                "stt_duration": stt_duration,
            }

            if self.stop_event is not None and self.stop_event.is_set():
                return None
            if is_prompt_echo(transcript):
                logger.info("Ignoring Whisper initial prompt echo: %r", transcript)
                return None
        except VoiceRecognitionError as exc:
            err_msg = str(exc).lower()
            detail = str(getattr(exc, "detail", "")).lower()
            if (
                "empty" in err_msg
                or "no speech" in err_msg
                or "empty" in detail
                or "no speech" in detail
                or "did not hear" in err_msg
            ):
                logger.info("Silence/empty transcript ignored silently: %s", exc)
                return None
            self.presenter.print_error(str(exc))
            logger.info("Recoverable voice recognition error: %s", exc)
            return None
        except VoiceDependencyError:
            raise
        except MicrophoneUnavailableError as exc:
            recover = getattr(self.microphone, "recover", None)
            if callable(recover) and recover():
                self.state = VoiceSessionState.RECOVERING
                self.presenter.print_error("Microphone unavailable. Reconnecting...")
                logger.warning("Recoverable microphone error: %s", exc)
                return None
            raise
        except VoiceError as exc:
            self.presenter.print_error(str(exc))
            logger.info("Recoverable voice error: %s", exc)
            return None
        if not transcript:
            if not quiet_empty:
                self.presenter.print_status("I did not catch that.")
            return None
        if self._is_probable_echo(transcript):
            self.presenter.print_status("Ignoring probable speaker echo.")
            logger.debug(
                "Ignored probable TTS echo transcript_chars=%s", len(transcript)
            )
            return None
        return transcript

    def _handle_transcript(self, transcript: str, stop: threading.Event) -> None:
        self.presenter.print_user_message(transcript)
        if is_exit_phrase(transcript):
            self.presenter.print_farewell(FAREWELL_TEXT)
            self._exit_message_printed = True
            self._speak(FAREWELL_TEXT)
            logger.info("Voice assistant stopped by exit phrase")
            stop.set()
            return

        self.state = VoiceSessionState.PROCESSING
        self.presenter.on_routing()
        t_route_start = time.monotonic()
        try:
            response = self.responder.handle_user_input(transcript)
        except (
            EngineConnectionError,
            EngineModelLoadError,
            EngineModelNotFoundError,
        ) as exc:
            from grandpa.engine.messages import (
                engine_unavailable_message as _engine_unavailable_message,
            )

            msg = (
                _engine_unavailable_message("ollama", exc)
                if isinstance(exc, EngineConnectionError)
                else str(exc)
            )
            self.presenter.print_error(msg)
            return
        finally:
            self.presenter.stop_thinking()

        t_action_end = time.monotonic()
        routing_dur = t_action_end - t_route_start

        if self.debug and hasattr(self, "_last_timing") and self._last_timing:
            stt_dur = self._last_timing.get("stt_duration", 0.0)
            total_after = stt_dur + routing_dur
            self.presenter.output(
                f"\nTiming:\n"
                f"  capture-finalize: 0.55s\n"
                f"  STT: {stt_dur:.2f}s\n"
                f"  routing/action: {routing_dur:.2f}s\n"
                f"  total-after-speech: {0.55 + total_after:.2f}s\n"
            )

        if stop.is_set():
            return
        response_text = str(getattr(response, "text", response)).strip()
        if not response_text:
            response_text = "I handled that."

        # Spacing: one blank line after user message + spinner
        self.presenter.print_blank_line()

        # Check for confirmation and execution statuses
        self.state = VoiceSessionState.EXECUTING
        action_name = (
            getattr(response, "action_type", "") or getattr(response, "kind", "") or ""
        )
        self.presenter.on_executing(action_name)

        if getattr(response, "status", None) in {
            "pending_confirmation",
            "needs_confirmation",
        }:
            self.presenter.print_confirmation_required(response_text)
        elif getattr(response, "status", None) == "handled" and getattr(
            response, "kind", None
        ) in {"app", "window", "folder", "session_control"}:
            self.presenter.print_action_completed(response_text)
        else:
            self.presenter.print_assistant_message(response_text)

        # Spacing: one blank line after assistant response
        self.presenter.print_blank_line()

        self.state = VoiceSessionState.SPEAKING
        self._speak(response_text)
        if (
            getattr(response, "exit_requested", False)
            or getattr(response, "status", None) == "exit"
        ):
            stop.set()

    def _speak(self, text: str) -> None:
        if self.speaker is None:
            return
        stop = self.stop_event or threading.Event()
        self._reset_microphone()
        try:
            self.speaker.speak(text, stop_event=stop)
            if not self._wait_for_speaker(stop) or stop.is_set():
                return
        except Exception as exc:
            self.presenter.print_error(
                f"Text-to-speech is unavailable. TTS failed: {type(exc).__name__}: {exc}"
            )
            logger.warning("Voice assistant TTS error: %s", exc)
            return
        self._last_spoken_text = normalize_echo_text(text)
        self._last_spoken_at = self.clock()
        cooldown_seconds = max(0, self.post_tts_cooldown_ms) / 1000
        if cooldown_seconds and self.cooldown_wait(stop, cooldown_seconds):
            return
        self._reset_microphone()

    def _wait_for_speaker(self, stop: threading.Event) -> bool:
        if self.speaker is None:
            return not stop.is_set()
        if not bool(getattr(self.speaker, "is_speaking", False)):
            return not stop.is_set()
        waiter = getattr(self.speaker, "wait_until_finished", None)
        if callable(waiter):
            return bool(waiter(stop_event=stop))
        while bool(getattr(self.speaker, "is_speaking", False)):
            if stop.wait(0.05):
                self.speaker.stop()
                return False
        return not stop.is_set()

    def _report_quiet_capture(self, audio: object) -> None:
        """Tell the user why a capture heard nothing, naming the device and level.

        Three different faults produce the same blank screen, and they need
        different advice, so they get different messages:

        * no frames at all -- the device is not delivering. Naming it is the whole
          point: selection is automatic, and on this machine it picks one of four
          duplicates of the same microphone across MME, DirectSound, WASAPI and
          WDM-KS.
        * frames arrived, nothing crossed the threshold -- report the loudest
          chunk against the threshold it was compared with. "Levels reached 119
          against a threshold of 299" is something a person can act on.
        * speech started but was too short to keep -- say that rather than
          nothing, or the user cannot tell it from not being heard.

        Logged at WARNING as well as printed. The existing diagnostics in this
        path are all at INFO with no file handler unless --verbose, which is why
        none of this was in the log after a ten-minute failure.
        """
        reason = str(getattr(audio, "finalization_reason", "") or "")
        if reason not in {"no_speech_timeout", "stream_ended"}:
            # A capture that heard something clears the dedupe, so if the fault
            # comes back the user is told again rather than once per process.
            self._last_quiet_message = None
            return

        device = str(getattr(audio, "device_name", "") or "an unknown device")
        index = getattr(audio, "device_index", None)
        named = f"{device} (device {index})" if index is not None else device
        chunks = int(getattr(audio, "chunks_read", 0) or 0)
        level = float(getattr(audio, "max_chunk_rms", 0.0) or 0.0)
        threshold = float(getattr(audio, "speech_threshold", 0.0) or 0.0)

        if chunks == 0:
            message = (
                f"I heard nothing at all from {named} - it delivered no audio. "
                f"Check that it is the right input and that Windows lets desktop "
                f"apps use the microphone."
            )
        elif level <= 1.0:
            message = (
                f"{named} is delivering silence - {chunks} audio chunks, all "
                f"empty. Check the Windows microphone privacy setting and that "
                f"this is the input you are speaking into."
            )
        elif level >= threshold > 0:
            # "Levels reached 2994 against a threshold of 180" followed by "try
            # speaking louder" is advice that cannot help, and it was printed
            # seven times in one live session. max_rms is the loudest single
            # chunk; the requirement is a quantity of such chunks inside a short
            # window. So when the peak cleared the threshold and speech still
            # did not start, loudness is not the problem and saying so is not
            # merely unhelpful, it sends the user the wrong way.
            voiced = float(getattr(audio, "speech_active_seconds", 0.0) or 0.0)
            message = (
                f"{named} was loud enough - peaks hit {level:.0f} against a "
                f"threshold of {threshold:.0f} - but only {voiced:.1f}s of it "
                f"held up, too little and too broken to start an utterance. "
                f"Use `grandpa voice push-to-talk` to hold a key while you "
                f"speak, which skips speech detection entirely."
            )
        else:
            message = (
                f"I did not hear speech on {named}. Levels reached "
                f"{level:.0f} against a threshold of {threshold:.0f}. Try "
                f"speaking louder or closer, or pick another input with "
                f"`grandpa voice --list-microphones`."
            )
        # Said once per run of consecutive quiet captures, not every time. The
        # loop starts a new capture the moment one gives up, so at an eight second
        # bound an idle session would otherwise print this seven times a minute,
        # and a message that repeats that often stops being read.
        if message != getattr(self, "_last_quiet_message", None):
            self.presenter.print_error(message)
            self._last_quiet_message = message
        logger.warning(
            "voice capture heard no speech: device=%r index=%s chunks=%d "
            "max_rms=%.1f threshold=%.1f reason=%s",
            device,
            index,
            chunks,
            level,
            threshold,
            reason,
        )

    def _reset_microphone(self) -> None:
        resetter = getattr(self.microphone, "reset", None)
        if callable(resetter):
            resetter()
            return
        closer = getattr(self.microphone, "close", None)
        if callable(closer):
            closer()

    def _is_probable_echo(self, transcript: str) -> bool:
        if not self._last_spoken_text or self._last_spoken_at is None:
            return False
        age = max(0.0, self.clock() - self._last_spoken_at)
        return is_probable_speaker_echo(
            transcript,
            self._last_spoken_text,
            age_seconds=age,
            window_seconds=self.echo_window_seconds,
            similarity_threshold=self.echo_similarity_threshold,
        )

    def _cleanup(self) -> None:
        closer = getattr(self.microphone, "close", None)
        if closer is not None:
            try:
                closer()
            except Exception:
                logger.debug("Voice microphone cleanup failed", exc_info=True)
        if self.speaker is not None:
            stopper = getattr(self.speaker, "stop", None)
            if stopper is not None:
                try:
                    stopper()
                except Exception:
                    logger.debug("Voice TTS cleanup failed", exc_info=True)


def build_voice_session(
    *,
    model: str | None = None,
    language: str | None = None,
    device: str | None = None,
    microphone: int | None = None,
    no_tts: bool = False,
    wake_word: bool = False,
    wake_phrases: tuple[str, ...] | None = None,
    wake_response_enabled: bool = True,
    output: Callable[[str], None] = print,
    quiet: bool = False,
    verbose: bool = False,
    screen_reader: bool = False,
    responder: Responder | None = None,
    microphone_capture: AudioCapture | None = None,
    transcriber: Transcriber | None = None,
    speaker: Speaker | None = None,
    phrase_duration_limit: float | None = None,
    debug: bool = False,
) -> VoiceSession:
    """Construct the default offline voice session components."""

    from grandpa.voice.config import load_voice_assistant_config

    config = load_voice_assistant_config(
        model=model,
        language=language,
        device=device,
        microphone=microphone,
        tts_enabled=not no_tts,
        wake_word_enabled=wake_word,
        wake_phrases=wake_phrases,
        wake_response_enabled=wake_response_enabled,
    )
    limit = phrase_duration_limit or config.phrase_duration_limit
    capture = microphone_capture or MicrophoneCapture(
        duration_seconds=(
            config.wake_command_timeout_seconds if config.wake_word_enabled else limit
        ),
        device=config.microphone,
        recovery_attempts=config.microphone_recovery_attempts,
        vad_config=VoiceActivityConfig(
            minimum_rms=config.speech_start_rms,
            minimum_speech_seconds=config.minimum_speech_seconds,
            silence_seconds=config.silence_timeout_seconds,
            maximum_utterance_seconds=(
                config.wake_command_timeout_seconds
                if config.wake_word_enabled
                else limit
            ),
        ),
    )
    resolved_transcriber = transcriber or FasterWhisperSpeechToText(
        language=config.language,
        model=config.stt_model,
        device=config.device,
        compute_type=config.compute_type,
    )
    resolved_responder = responder or VoiceCommandProcessor(model_name=None)
    resolved_speaker = (
        speaker
        if speaker is not None
        else (
            None
            if no_tts
            else GrandpaTextToSpeech(
                enabled=config.tts_enabled,
                voice=config.tts_voice,
                rate=config.tts_rate,
            )
        )
    )
    logger.info(
        "Voice session configured microphone=%s stt_model=%s device=%s compute_type=%s tts=%s",
        config.microphone,
        config.stt_model,
        config.device,
        config.compute_type,
        config.tts_enabled,
    )
    from grandpa.voice.presenter import VoicePresenter

    presenter = VoicePresenter(
        quiet=quiet,
        verbose=verbose,
        screen_reader=screen_reader,
        # Must be passed at construction: VoicePresenter decides here whether
        # to render through Rich or route text to this callable. Assigning
        # ``presenter.output`` afterwards leaves that decision made against the
        # default ``print``, and every message goes to the console instead of
        # the caller's sink.
        output=output,
    )
    return VoiceSession(
        capture,
        resolved_transcriber,
        resolved_responder,
        resolved_speaker,
        output=output,
        wake_word_enabled=config.wake_word_enabled,
        wake_detector=WakeWordDetector(config.wake_phrases),
        wake_response_enabled=config.wake_response_enabled,
        wake_command_timeout_seconds=config.wake_command_timeout_seconds,
        post_tts_cooldown_ms=config.post_tts_cooldown_ms,
        echo_window_seconds=config.echo_window_seconds,
        echo_similarity_threshold=config.echo_similarity_threshold,
        presenter=presenter,
        stt_model=config.stt_model,
        # --verbose implies debug. This parameter existed, defaulted to False,
        # and voice_cmd never passed it -- so the per-capture diagnostic at
        # _listen_for_transcript ("capture_duration=... audio_rms=...") could not
        # be switched on by any flag the CLI offers. A diagnostic nobody can reach
        # is not a diagnostic.
        #
        # The quiet-capture message is separate and unconditional: it goes out at
        # WARNING on an ordinary run, because a user who waited ten minutes should
        # not have had to know to re-run with a flag to find out why.
        debug=debug or verbose,
    )


#: Below this much voiced audio, a capture is only sent to the model if it was
#: loud. Set from the live captures: 0.50s and 0.70s of barely-above-threshold
#: audio each produced a hundred hallucinated words, while a 1.40s capture at
#: 2949 was real speech.
MIN_TRANSCRIBE_VOICED_SECONDS = 1.0

#: ...and "loud" means this. The two bad captures measured 289 and 353 in the
#: speech window; ordinary speech in the same room measured 2949. 500 sits well
#: clear of the noise and far below real speech, so a short utterance has to be
#: genuinely spoken to get through.
MIN_TRANSCRIBE_SPEECH_RMS = 500.0


def _too_thin_to_transcribe(voiced_seconds: float, speech_rms: float) -> bool:
    """Whether a capture is too short *and* too quiet to be worth a model call.

    Both conditions, never either alone:

    * short alone would refuse a clipped "yes", which is 0.3s and perfectly
      audible;
    * quiet alone would refuse a long mumble, which is real speech and which the
      no_speech_prob and avg_logprob gates are there to judge.

    A capture that is both is the shape that made Whisper invent a hundred words
    from seven tenths of a second.
    """
    return (
        voiced_seconds < MIN_TRANSCRIBE_VOICED_SECONDS
        and speech_rms < MIN_TRANSCRIBE_SPEECH_RMS
    )


def is_exit_phrase(text: str) -> bool:
    """Return True when recognized text asks to stop voice mode.

    The vocabulary is deliberately unchanged, including the bare words "goodbye",
    "exit" and "quit". Refusing those was tried first, as the obvious guard
    against a hallucination ending the session -- and the suite showed it removes
    documented, conventional behaviour: three separate tests assert those exact
    words work, and eight more end a session loop with a bare "quit". "Quit" is
    what people say.

    The hazard is real but it is not in this function. A spurious exit needs a
    spurious *transcript*, which needs a capture too marginal to be speech -- and
    that is worth refusing for every command, not only for exits. See the
    marginal-capture gate in ``_listen_for_transcript``: widening it protects
    "delete that file" on the same evidence, which a vocabulary change here never
    would have.
    """
    normalized = re.sub(r"[^\w\s]", " ", text.strip().casefold().replace("-", " "))
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if not normalized:
        return False
    return normalized in EXIT_PHRASES


def normalize_echo_text(text: str) -> str:
    tokens = re.findall(r"[a-z0-9]+", text.casefold())
    collapsed: list[str] = []
    for token in tokens:
        if not collapsed or token != collapsed[-1]:
            collapsed.append(token)
    return " ".join(collapsed)


def is_probable_speaker_echo(
    transcript: str,
    last_spoken: str,
    *,
    age_seconds: float,
    window_seconds: float = 3.0,
    similarity_threshold: float = 0.70,
) -> bool:
    if age_seconds > window_seconds or age_seconds < 0 or is_exit_phrase(transcript):
        return False
    candidate = normalize_echo_text(transcript)
    spoken = normalize_echo_text(last_spoken)
    if not candidate or not spoken:
        return False
    if candidate == spoken:
        return True

    ratio = SequenceMatcher(None, candidate, spoken).ratio()
    if ratio >= similarity_threshold:
        return True

    candidate_tokens = candidate.split()
    spoken_tokens = set(spoken.split())

    # Short exact substring match
    if len(candidate_tokens) <= 3 and re.search(
        rf"(?:^| )({re.escape(candidate)})(?: |$)", spoken
    ):
        return True

    # Single token echoes
    if len(candidate_tokens) == 1 and candidate in {
        "you",
        "grandpa",
        "okay",
        "ok",
        "yes",
    }:
        return True

    # Bounded token overlap for distorted echo within the immediate post-TTS window
    action_verbs = {
        "open",
        "close",
        "minimize",
        "maximize",
        "restore",
        "focus",
        "switch",
        "type",
        "press",
        "click",
        "search",
        "scroll",
        "mute",
        "unmute",
        "volume",
        "scan",
        "list",
        "show",
        "help",
        "exit",
        "quit",
    }
    has_new_action_verb = any(
        t in action_verbs and t not in spoken_tokens for t in candidate_tokens
    )

    if not has_new_action_verb and age_seconds <= 2.5:
        stopwords = {
            "the",
            "a",
            "an",
            "is",
            "it",
            "to",
            "in",
            "on",
            "of",
            "and",
            "or",
            "for",
            "with",
            "this",
            "that",
            "i",
            "me",
            "my",
            "you",
            "your",
            "nice",
            "meet",
        }
        cand_content = [
            t for t in candidate_tokens if t not in stopwords and len(t) > 2
        ]
        if cand_content:
            matches = [t for t in cand_content if t in spoken_tokens]
            if len(matches) / len(cand_content) >= 0.5:
                return True

    return False


def is_prompt_echo(text: str) -> bool:
    """Return True if the transcribed text is likely just the Whisper prompt hint echo."""
    normalized = re.sub(r"[^\w\s]", "", text.strip().lower())
    prompt_words = {
        "grandpa",
        "assistant",
        "ollama",
        "the",
        "current",
        "year",
        "may",
        "be",
        "2026",
        "3026",
        "2023",
        "2024",
        "2025",
    }
    words = normalized.split()
    if not words:
        return False
    # If all words are prompt words, reject it (with the length 2 exception)
    if len(words) >= 2 and all(w in prompt_words for w in words):
        if len(words) == 2 and not any(
            w in {"assistant", "ollama", "may", "be", "3026"} for w in words
        ):
            return False
        return True
    # Check if the string matches common mutated echo sentences:
    if "current year may be" in normalized or "current year is" in normalized:
        return True
    return False


__all__ = [
    "EXIT_PHRASES",
    "VoiceSession",
    "VoiceSessionState",
    "build_voice_session",
    "is_exit_phrase",
    "is_probable_speaker_echo",
    "normalize_echo_text",
    "is_prompt_echo",
]
