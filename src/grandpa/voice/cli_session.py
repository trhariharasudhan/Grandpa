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
    "goodbye",
    "quit",
    "exit",
}


class VoiceSessionState(StrEnum):
    """Explicit states for the voice assistant loop."""

    IDLE = "idle"
    WAITING_FOR_WAKE_WORD = "waiting_for_wake_word"
    WAKE_DETECTED = "wake_detected"
    LISTENING_FOR_COMMAND = "listening_for_command"
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
    post_tts_cooldown_ms: int = 400
    echo_window_seconds: float = 3.0
    echo_similarity_threshold: float = 0.85
    clock: Callable[[], float] = time.monotonic
    cooldown_wait: Callable[[threading.Event, float], bool] = field(
        default=lambda stop, seconds: stop.wait(seconds)
    )
    state: VoiceSessionState = VoiceSessionState.IDLE
    _last_spoken_text: str = field(default="", init=False, repr=False)
    _last_spoken_at: float | None = field(default=None, init=False, repr=False)

    def run(self) -> int:
        """Run until an exit phrase, Ctrl+C, or unrecoverable setup error."""

        stop = self.stop_event or threading.Event()
        self.stop_event = stop
        logger.info("Voice assistant session started")
        self.output("Grandpa Voice Assistant")
        self.output('Say "stop listening" to exit.')
        self.output("")

        exit_code = 0
        try:
            if self.wake_word_enabled:
                self._run_wake_word_loop(stop)
            else:
                self._run_direct_loop(stop)
        except KeyboardInterrupt:
            self.output("Stopping Grandpa Voice Assistant...")
            stop.set()
            logger.info("Voice assistant stopped by keyboard interrupt")
        except (VoiceDependencyError, MicrophoneUnavailableError) as exc:
            self.output(str(exc))
            logger.warning("Voice assistant setup error: %s", exc)
            exit_code = 1
        finally:
            stop.set()
            self._cleanup()
            self.output("Voice assistant stopped.")
        return exit_code

    def _run_direct_loop(self, stop: threading.Event) -> None:
        while not stop.is_set():
            transcript = self._listen_for_transcript("Listening...")
            if stop.is_set():
                break
            if transcript is None:
                continue
            self._handle_transcript(transcript, stop)

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
                self.output("Grandpa: Goodbye.")
                self._speak("Goodbye.")
                logger.info(
                    "Voice assistant stopped by exit phrase while waiting for wake word"
                )
                stop.set()
                break
            match = detector.detect(wake_transcript)
            if not match.matched:
                continue

            self.state = VoiceSessionState.WAKE_DETECTED
            self.output("Wake word detected.")
            if self.wake_response_enabled:
                self.output(f"Grandpa: {self.wake_response_text}")
                self._speak(self.wake_response_text)
            if stop.is_set():
                break

            # Support natural one-shot commands such as
            # "Hey Grandpa, open Chrome" without forcing the user to repeat
            # the command in a second microphone capture.
            if match.command_text:
                self._handle_transcript(match.command_text, stop)
                if not stop.is_set():
                    self.output("Returning to wake-word mode...")
                continue

            self.state = VoiceSessionState.LISTENING_FOR_COMMAND
            command = self._listen_for_transcript(
                "Listening for command...", quiet_empty=True
            )
            if stop.is_set():
                break
            if command is None:
                self.output("No command heard. Returning to wake-word mode.")
                self.output("Returning to wake-word mode...")
                continue
            self._handle_transcript(command, stop)
            if not stop.is_set():
                self.output("Returning to wake-word mode...")

    def _listen_for_transcript(
        self, prompt: str, *, quiet_empty: bool = False
    ) -> str | None:
        stop = self.stop_event or threading.Event()
        if not self._wait_for_speaker(stop) or stop.is_set():
            return None
        self._reset_microphone()
        self.output(prompt)
        try:
            audio = self.microphone.capture(stop_event=self.stop_event)
            warning = str(getattr(self.microphone, "last_warning", "") or "").strip()
            if warning:
                self.output(warning)
            if self.stop_event is not None and self.stop_event.is_set():
                return None
            transcript = self.transcriber.transcribe(audio).strip()
            if self.stop_event is not None and self.stop_event.is_set():
                return None
            if is_prompt_echo(transcript):
                logger.info("Ignoring Whisper initial prompt echo: %r", transcript)
                return None
        except VoiceRecognitionError as exc:
            self.output(str(exc))
            logger.info("Recoverable voice recognition error: %s", exc)
            return None
        except VoiceDependencyError:
            raise
        except MicrophoneUnavailableError as exc:
            recover = getattr(self.microphone, "recover", None)
            if callable(recover) and recover():
                self.state = VoiceSessionState.RECOVERING
                self.output("Microphone unavailable. Reconnecting...")
                logger.warning("Recoverable microphone error: %s", exc)
                return None
            raise
        except VoiceError as exc:
            self.output(str(exc))
            logger.info("Recoverable voice error: %s", exc)
            return None
        if not transcript:
            if not quiet_empty:
                self.output("I did not catch that.")
            return None
        if self._is_probable_echo(transcript):
            self.output("Ignoring probable speaker echo.")
            logger.debug(
                "Ignored probable TTS echo transcript_chars=%s", len(transcript)
            )
            return None
        return transcript

    def _handle_transcript(self, transcript: str, stop: threading.Event) -> None:
        self.output(f"You: {transcript}")
        if is_exit_phrase(transcript):
            self.output("Grandpa: Goodbye.")
            self._speak("Goodbye.")
            logger.info("Voice assistant stopped by exit phrase")
            stop.set()
            return

        self.state = VoiceSessionState.THINKING
        self.output("Thinking...")
        try:
            response = self.responder.handle_user_input(transcript)
        except (
            EngineConnectionError,
            EngineModelLoadError,
            EngineModelNotFoundError,
        ) as exc:
            response = str(exc)
            logger.warning("Voice assistant engine error: %s", exc)
        if stop.is_set():
            return
        response_text = str(getattr(response, "text", response)).strip()
        if not response_text:
            response_text = "I handled that."
        self.output(f"Grandpa: {response_text}")
        self.state = VoiceSessionState.SPEAKING
        self.output("Speaking...")
        self._speak(response_text)
        self.output("")

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
            self.output(
                f"Text-to-speech is unavailable. TTS failed: {type(exc).__name__}: {exc}"
            )
            logger.warning("Voice assistant TTS error: %s", exc)
            return
        self._last_spoken_text = normalize_echo_text(text)
        self._last_spoken_at = self.clock()
        cooldown_seconds = max(0, self.post_tts_cooldown_ms) / 1000
        if cooldown_seconds and self.cooldown_wait(stop, cooldown_seconds):
            return

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
    model: str,
    language: str,
    device: str,
    microphone: int | None,
    no_tts: bool,
    wake_word: bool = False,
    wake_phrases: tuple[str, ...] | None = None,
    wake_response_enabled: bool = True,
    output: Callable[[str], None] = print,
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
    capture = MicrophoneCapture(
        duration_seconds=(
            config.wake_command_timeout_seconds
            if config.wake_word_enabled
            else config.phrase_duration_limit
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
                else config.phrase_duration_limit
            ),
        ),
    )
    transcriber = FasterWhisperSpeechToText(
        language=config.language,
        model=config.stt_model,
        device=config.device,
        compute_type=config.compute_type,
    )
    responder = VoiceCommandProcessor(model_name=None)
    speaker = (
        None
        if no_tts
        else GrandpaTextToSpeech(
            enabled=config.tts_enabled,
            voice=config.tts_voice,
            rate=config.tts_rate,
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
    return VoiceSession(
        capture,
        transcriber,
        responder,
        speaker,
        output=output,
        wake_word_enabled=config.wake_word_enabled,
        wake_detector=WakeWordDetector(config.wake_phrases),
        wake_response_enabled=config.wake_response_enabled,
        wake_command_timeout_seconds=config.wake_command_timeout_seconds,
        post_tts_cooldown_ms=config.post_tts_cooldown_ms,
        echo_window_seconds=config.echo_window_seconds,
        echo_similarity_threshold=config.echo_similarity_threshold,
    )


def is_exit_phrase(text: str) -> bool:
    """Return True when recognized text asks to stop voice mode."""

    normalized = re.sub(r"\s+", " ", text.strip().casefold()).rstrip(".?!,")
    if normalized in EXIT_PHRASES:
        return True
    if "stop listening" in normalized or "stop listening" in normalized.replace("-", " "):
        return True
    return False


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
    similarity_threshold: float = 0.85,
) -> bool:
    if age_seconds > window_seconds or age_seconds < 0 or is_exit_phrase(transcript):
        return False
    candidate = normalize_echo_text(transcript)
    spoken = normalize_echo_text(last_spoken)
    if not candidate or not spoken:
        return False
    if candidate == spoken:
        return True
    candidate_tokens = candidate.split()
    if len(candidate_tokens) == 1 and candidate in {
        "you",
        "grandpa",
        "okay",
        "ok",
        "yes",
    }:
        return True
    if len(candidate_tokens) <= 3 and re.search(
        rf"(?:^| )({re.escape(candidate)})(?: |$)", spoken
    ):
        return True
    return SequenceMatcher(None, candidate, spoken).ratio() >= similarity_threshold


def is_prompt_echo(text: str) -> bool:
    """Return True if the transcribed text is likely just the Whisper prompt hint echo."""
    normalized = re.sub(r"[^\w\s]", "", text.strip().lower())
    prompt_words = {"grandpa", "assistant", "ollama", "the", "current", "year", "may", "be", "2026"}
    words = normalized.split()
    if len(words) < 2:
        return False
    if all(w in prompt_words for w in words):
        if len(words) == 2 and not any(w in {"assistant", "ollama", "may", "be"} for w in words):
            return False
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
