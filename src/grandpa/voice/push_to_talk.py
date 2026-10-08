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
#: Virtual-key codes for every key a hold may be built from. Verified present
#: on this layout with ``MapVirtualKeyW(vk, MAPVK_VK_TO_VSC)``, which returns a
#: scancode or 0 when the layout has no such key:
#:
#:     ctrl 29   shift 42   alt 56   space 57   f8 66   f9 67   f10 68
#:     win 91    rwin 92    menu 93  capslock 58
#:     pause 0  <- absent, which is why it is not offered
KEY_CODES: dict[str, int] = {
    "space": 0x20,
    "ctrl": 0x11,
    "shift": 0x10,
    "alt": 0x12,
    "f8": 0x77,
    "f9": 0x78,
    "f10": 0x79,
    # VK_LWIN. There is no "either Windows key" virtual key the way there is for
    # ctrl/shift/alt, so this is the left one -- which is the one a left hand
    # reaches, and the point of the default below is one-handed holding.
    "win": 0x5B,
    "rwin": 0x5C,
    #: The context-menu key. Offered because it is inert on every layout and
    #: holdable, for a keyboard where the default combination is awkward.
    "menu": 0x5D,
}

#: What separates the parts of a combination, e.g. ``ctrl+win``.
COMBO_SEPARATOR = "+"


def parse_hold_key(spec: str) -> tuple[str, ...]:
    """Split a hold-key spec into its parts, normalised and validated.

    ``"f9"`` gives ``("f9",)`` and ``"Ctrl+Win"`` gives ``("ctrl", "win")``, so
    a single key is just a combination of one and the probe has one code path
    rather than two. Raises :class:`ValueError` naming the offending part, so
    the CLI can turn it into a message instead of a traceback.
    """
    parts = [
        part.strip().lower()
        for part in spec.split(COMBO_SEPARATOR)
        if part.strip()
    ]
    if not parts:
        raise ValueError("a hold key cannot be empty")
    unknown = [part for part in parts if part not in KEY_CODES]
    if unknown:
        raise ValueError(
            f"unknown key(s) {', '.join(sorted(unknown))}; "
            f"choose from {', '.join(sorted(KEY_CODES))}"
        )
    # Duplicates collapse: "ctrl+ctrl" is "ctrl", not a combination that can
    # never be satisfied.
    return tuple(dict.fromkeys(parts))


def describe_hold_key(spec: str) -> str:
    """How the key is written for a person: ``ctrl+win`` -> ``CTRL+WIN``."""
    try:
        parts = parse_hold_key(spec)
    except ValueError:
        return spec.upper()
    return COMBO_SEPARATOR.join(part.upper() for part in parts)

#: The shipped hold key for every command that reads one -- ``grandpa bubble``,
#: ``grandpa voice push-to-talk`` and ``grandpa voice accuracy-test`` -- with the
#: reasoning, so the commands, the help text, the README and the manual QA cannot
#: disagree about it.
#:
#: The constraint that drives everything: the key is read globally with
#: ``GetAsyncKeyState``, so whatever it is also reaches whichever window has
#: focus. Three rounds of consequences:
#:
#: ``space`` shipped first and was the worst possible choice -- it typed into the
#: bubble's own text box and recorded nothing visible. Swallowing the character
#: in the entry fixes the bubble (see ``ui.tk_view.KEY_SYMS``) but not the
#: general case: a printable key still types into every *other* application while
#: held, and in a terminal it fills the prompt.
#:
#: ``f9`` replaced it and works, but needs ``Fn`` on this laptop, which is
#: awkward to hold while speaking -- the exact residual cost recorded when f9 was
#: chosen, now reported from use.
#:
#: A **combination** is the way out, because the test is "all of these at once"
#: and that is a chord no application claims. ``ctrl+win`` is the default:
#:
#: * one-handed without ``Fn`` -- left ctrl and left win are adjacent on the
#:   bottom row, reachable by one hand without looking
#: * inert together. Ctrl alone is a shortcut prefix and Win alone opens Start,
#:   but Windows binds nothing to the two held with nothing else
#: * present on this layout: ``MapVirtualKeyW`` gives ctrl scancode 29 and left
#:   win 91
#:
#: Rejected, with the reason in each case:
#:
#: * ``ctrl+shift`` -- Windows binds it to switching keyboard layout when more
#:   than one is installed, and it prefixes a great many application shortcuts
#: * ``ctrl+alt`` -- right alt *is* ctrl+alt on layouts with AltGr, so holding it
#:   types alternate characters
#: * ``alt+space`` -- opens the window menu
#: * ``win+shift`` / ``win+alt`` -- prefixes of live Windows shortcuts
#:   (Win+Shift+S screenshots, Win+Alt+R records)
#: * ``capslock`` -- a toggle, not a hold: it changes state on press and the
#:   state outlives the utterance
#: * ``pause`` -- ``MapVirtualKeyW`` returns scancode 0, so the key is not on
#:   this keyboard at all
#:
#: The residual cost, stated because it was not testable from here: releasing the
#: Windows key normally opens Start, and Windows suppresses that when another
#: modifier was held with it. If Start does open on release, ``--key menu`` and
#: ``--key f8`` are inert single-key alternatives and the manual QA names them.
DEFAULT_HOLD_KEY = "ctrl+win"


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
        """True while every part of *key* is held at the same time.

        A combination is read as several independent questions and AND-ed, which
        is all ``GetAsyncKeyState`` can do -- it reports one key per call and
        knows nothing about chords. A single key is the one-part case, so
        nothing about the previous behaviour changes: ``is_down("f9")`` still
        makes exactly one call with exactly the same test on the result.
        """
        try:
            parts = parse_hold_key(key)
        except ValueError:
            return False
        for part in parts:
            code = KEY_CODES[part]
            # The low bit means "pressed since last call" and is not wanted; the
            # high bit (0x8000) means "down now", which is the question.
            if not self._user32.GetAsyncKeyState(code) & 0x8000:
                return False
        return True


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
    "COMBO_SEPARATOR",
    "DEFAULT_HOLD_KEY",
    "KEY_CODES",
    "MAXIMUM_HOLD_SECONDS",
    "HoldResult",
    "KeyProbe",
    "PushToTalkSession",
    "WindowsKeyProbe",
    "describe_hold_key",
    "hold_to_talk_vad_config",
    "parse_hold_key",
]
