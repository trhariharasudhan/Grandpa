"""Hold a key, speak, release. No voice activity detection at all.

Why this exists
---------------

The adaptive detector in :mod:`grandpa.voice.vad` decides for itself when
speech begins, from a threshold derived from a noise floor it estimates as it
goes. Three rounds of fixes went into that decision and a user still could not
get a sentence through: the capture either never started, or started and ended
mid-word, and the only levers were numbers nobody can tune by ear.

A held key removes the decision. The user says when the utterance starts and
when it ends, the recorder keeps every frame in between, and the detector is
configured so it cannot refuse anything:

* ``minimum_rms=0.0`` -- every chunk is above the threshold, so speech is
  "detected" on the first chunk and :class:`MicrophoneCapture` starts appending
  immediately rather than holding 0.3s of pre-roll.
* ``minimum_speech_seconds=0.0`` -- the onset window is satisfied at once.
* ``silence_seconds`` large -- trailing silence can never finalise the
  utterance, because no chunk is ever classified as silence.
* ``silence_before_speech_seconds=0.0`` -- disables the no-speech timeout,
  which is the bound that ended every failing live capture at 8.0s.

What then ends the capture is the key coming up, which sets the stop event, and
``maximum_utterance_seconds`` as a backstop so a stuck key cannot record
forever.

This module holds no console or PortAudio code of its own. The key probe and
the recorder are injected, so the whole loop is exercised in tests with the
audio guard armed and no microphone opened.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from grandpa.voice.vad import VoiceActivityConfig

#: Keys offered on the command line, mapped to Windows virtual-key codes.
#:
#: Deliberately short. A modifier is the natural choice for push-to-talk
#: because holding it does not type anything, and a function key is the choice
#: for anyone who uses modifiers for something else.
KEY_CODES: dict[str, int] = {
    "space": 0x20,
    "ctrl": 0x11,
    "shift": 0x10,
    "alt": 0x12,
    "f8": 0x77,
    "f9": 0x78,
    "f10": 0x79,
}

#: Longest single utterance a held key can produce, in seconds. A backstop for
#: a key that sticks or a user who walks away, not a limit anyone should meet.
MAXIMUM_HOLD_SECONDS = 60.0

#: How often the key is sampled while waiting and while recording.
POLL_SECONDS = 0.02


def hold_to_talk_vad_config(
    maximum_seconds: float = MAXIMUM_HOLD_SECONDS,
) -> VoiceActivityConfig:
    """A detector that accepts everything, so the key is the only gate.

    Every field here is set to defeat a specific way the adaptive path refused
    or truncated a live capture. See this module's docstring.
    """
    return VoiceActivityConfig(
        minimum_rms=0.0,
        noise_multiplier=0.0,
        minimum_speech_seconds=0.0,
        onset_window_seconds=1.0,
        silence_seconds=maximum_seconds * 2,
        maximum_utterance_seconds=max(1.0, maximum_seconds),
        silence_before_speech_seconds=0.0,
    )


class KeyProbe(Protocol):
    """Reports whether a key is physically down right now."""

    def is_down(self, key: str) -> bool:
        """True while the key is held."""


class WindowsKeyProbe:
    """Reads keyboard state through ``GetAsyncKeyState``.

    Read-only: it asks Windows what the keyboard is doing and synthesises
    nothing, so it is not actuation and the default-deny guard has no quarrel
    with it. It is also global -- it sees the key whichever window has focus,
    which is what makes a push-to-talk key usable while another application is
    in front.
    """

    def __init__(self, user32: Any = None) -> None:
        self._user32 = user32 or self._load_user32()

    @staticmethod
    def _load_user32() -> Any:
        import ctypes

        return ctypes.windll.user32  # type: ignore[attr-defined]

    @staticmethod
    def available() -> bool:
        try:
            WindowsKeyProbe._load_user32()
        except Exception:
            return False
        return True

    def is_down(self, key: str) -> bool:
        code = KEY_CODES.get(key.lower())
        if code is None:
            return False
        # The low bit means "pressed since last call" and is not wanted; the
        # high bit (0x8000) means "down now", which is the question.
        return bool(self._user32.GetAsyncKeyState(code) & 0x8000)


@dataclass
class HoldResult:
    """One pass of the loop, as something a test can assert on."""

    transcript: str = ""
    held_seconds: float = 0.0
    reason: str = ""
    response: str | None = None
    audio: Any = None


@dataclass
class PushToTalkSession:
    """Wait for the key, record while it is held, transcribe, route, repeat."""

    capture: Any
    transcriber: Any
    probe: KeyProbe
    key: str = "space"
    responder: Any = None
    speaker: Any = None
    echo: Callable[[str], None] = print
    sleep: Callable[[float], None] = field(default=time.sleep)
    clock: Callable[[], float] = field(default=time.monotonic)
    maximum_seconds: float = MAXIMUM_HOLD_SECONDS
    poll_seconds: float = POLL_SECONDS
    #: Called between polls; return True to leave the loop. The CLI uses this
    #: to notice Esc and to drain whatever the held key typed into the console.
    on_idle: Callable[[], bool] | None = None
    #: Shortest hold worth transcribing. A tap is a tap, not an utterance.
    minimum_hold_seconds: float = 0.2
    #: Deduped, so a standing fallback is not reprinted on every hold.
    _last_warning: str | None = None

    def wait_for_press(self) -> bool:
        """Block until the key goes down. False means the caller asked to stop."""
        while True:
            if self.on_idle is not None and self.on_idle():
                return False
            if self.probe.is_down(self.key):
                return True
            self.sleep(self.poll_seconds)

    def record_while_held(self) -> tuple[Any, float, str]:
        """Record until the key is released, the cap is reached, or stop is set."""
        stop = threading.Event()
        started = self.clock()
        released_at: list[float] = []

        def watch() -> None:
            while self.probe.is_down(self.key):
                if self.clock() - started >= self.maximum_seconds:
                    released_at.append(self.clock())
                    stop.set()
                    return
                self.sleep(self.poll_seconds)
            released_at.append(self.clock())
            stop.set()

        watcher = threading.Thread(target=watch, name="grandpa-ptt-key", daemon=True)
        watcher.start()
        try:
            audio = self.capture.capture(stop_event=stop)
        finally:
            stop.set()
            watcher.join(timeout=2.0)
        held = (released_at[0] if released_at else self.clock()) - started
        reason = "key_released" if held < self.maximum_seconds else "maximum_hold"
        return audio, max(0.0, held), reason

    def _report_device_warning(self) -> None:
        """Say once if the recorder fell back, or if an index is not the device.

        The recorder has always recorded this and nothing ever printed it, so a
        requested index that pointed at the wrong microphone after a Bluetooth
        reshuffle recorded silently from whatever was at that position.
        """
        warning = getattr(self.capture, "last_warning", None)
        if warning and warning != self._last_warning:
            self.echo(str(warning))
            self._last_warning = str(warning)

    def _transcribe(self, audio: Any) -> tuple[str, str]:
        """Transcribe without passing through a gate that can refuse the audio.

        ``transcribe_trusted`` disables both Whisper's own speech suppression
        and this project's stricter copy of it, and returns an empty string with
        a reason instead of raising. A transcriber that does not offer it -- a
        test double, or another backend -- falls back to ``transcribe``, and its
        refusal is caught here rather than reaching the top level as a
        traceback.
        """
        trusted = getattr(self.transcriber, "transcribe_trusted", None)
        if callable(trusted):
            outcome = trusted(audio)
            return outcome.text, outcome.explanation
        from grandpa.voice.errors import VoiceError

        try:
            return (self.transcriber.transcribe(audio) or "").strip(), (
                "nothing recognisable was in it"
            )
        except VoiceError as exc:
            return "", str(exc).splitlines()[0]

    def run_once(self) -> HoldResult | None:
        """One utterance. None means the caller asked to stop."""
        self.echo(f"Hold {self.key.upper()} and speak. Esc or Ctrl+C to finish.")
        if not self.wait_for_press():
            return None
        self.echo("Recording...")
        audio, held, reason = self.record_while_held()
        self.echo(f"Released after {held:.1f}s. Transcribing...")
        self._report_device_warning()

        if held < self.minimum_hold_seconds:
            # No threshold is being applied to the audio here -- only to how
            # long the key was down, which the user controls and can see.
            self.echo(
                f"That was a {held:.2f}s tap, under the {self.minimum_hold_seconds}s "
                "minimum. Hold the key down while you speak."
            )
            return HoldResult(held_seconds=held, reason="too_short", audio=audio)

        frames = getattr(audio, "captured_frame_count", 0)
        if not frames:
            self.echo(
                "The microphone delivered no audio for that hold. "
                "Run 'grandpa voice doctor' to check the device."
            )
            return HoldResult(held_seconds=held, reason="no_audio", audio=audio)

        transcript, empty_note = self._transcribe(audio)
        result = HoldResult(
            transcript=transcript, held_seconds=held, reason=reason, audio=audio
        )
        if not transcript:
            # Deliberately not routed anywhere. An empty transcription is not a
            # command, and must not be read as one.
            self.echo(
                f"Nothing recognisable in {held:.1f}s of audio "
                f"(level {getattr(audio, 'rms_level', 0.0):.0f}) -- {empty_note}. "
                f"Try again."
            )
            result.reason = "empty_transcript"
            return result

        self.echo(f"You said: {transcript}")
        if self.responder is None:
            return result
        response = self.responder.handle_user_input(transcript)
        text = (getattr(response, "text", None) or "").strip()
        result.response = text
        if text:
            self.echo(text)
            if self.speaker is not None:
                self.speaker.speak(text)
        return result

    def run(self, once: bool = False) -> list[HoldResult]:
        """Loop until the caller asks to stop, or for exactly one utterance."""
        from grandpa.voice.cli_session import is_exit_phrase

        results: list[HoldResult] = []
        while True:
            result = self.run_once()
            if result is None:
                return results
            results.append(result)
            if once:
                return results
            if result.transcript and is_exit_phrase(result.transcript):
                self.echo("Goodbye.")
                return results


__all__ = [
    "KEY_CODES",
    "MAXIMUM_HOLD_SECONDS",
    "HoldResult",
    "KeyProbe",
    "PushToTalkSession",
    "WindowsKeyProbe",
    "hold_to_talk_vad_config",
]
