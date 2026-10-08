"""The bubble's behaviour, with no toolkit import anywhere in it.

Separated from the view for the reason ``HighlightOverlay`` is separated from
``_render_tk_overlay``: the behaviour is worth testing and a window is not
testable. Everything here is driven by an injected :class:`BubbleView`, so the
suite exercises the whole controller while opening nothing.

The states are the ones a user needs to tell apart, and ``LOADING`` is one of
them on purpose. A surface that looks ready while the speech model is still
loading is the bug that made two accuracy runs unusable -- 145 MB arriving
during the first prompt -- at the UI layer instead of the CLI's.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

# Re-exported below, not defined here: the hold key lives beside
# ``KEY_CODES`` in push_to_talk because three commands read one and two of
# them are not the bubble. A constant in the UI package could only ever be
# one source for the UI. The module it comes from is pure standard library,
# so this does not give bubble.py a heavy import -- and it is not a toolkit
# import, which is the rule this module actually obeys.
from grandpa.voice.push_to_talk import DEFAULT_HOLD_KEY, describe_hold_key


class BubbleState(StrEnum):
    """What the bubble is doing. Shown, not inferred."""

    LOADING = "loading"
    IDLE = "idle"
    RECORDING = "recording"
    TRANSCRIBING = "transcribing"
    THINKING = "thinking"
    SPEAKING = "speaking"
    ERROR = "error"


#: What each state says, so the view does not invent wording.
STATE_LABELS: dict[BubbleState, str] = {
    BubbleState.LOADING: "Loading model...",
    BubbleState.IDLE: "Ready",
    BubbleState.RECORDING: "Recording",
    BubbleState.TRANSCRIBING: "Transcribing...",
    BubbleState.THINKING: "Thinking...",
    BubbleState.SPEAKING: "Speaking...",
    BubbleState.ERROR: "Error",
}

#: The states in which a hold must not start a recording.
STATES_THAT_REFUSE_A_HOLD = frozenset(
    {BubbleState.LOADING, BubbleState.RECORDING, BubbleState.TRANSCRIBING,
     BubbleState.THINKING}
)

DEFAULT_POSITION = (40, 40)

#: How many bars the level meter holds. One capture chunk is 0.1s, so this is
#: about three seconds of history -- long enough to see a sentence, short enough
#: that the view redraws a fixed, small number of rectangles.
METER_BARS = 32

#: The meter's floor and ceiling in PCM16 RMS, from this project's own
#: measurements rather than a guess:
#:
#:     ~90     noise floor logged beside live captures
#:     200     the VAD's default minimum_rms -- below this it is not speech
#:     289     the average speech chunk in the recording that read as rms 176
#:     640-2994 max_rms across the live recordings logged in voice/vad.py
#:
#: So the floor sits just above the noise floor and the ceiling just under the
#: loudest measured peak. The mapping is logarithmic because loudness is
#: perceived that way: on a linear scale an ordinary 289 would sit in the bottom
#: ninth of the meter and look like silence.
METER_FLOOR_RMS = 100.0
METER_CEILING_RMS = 2500.0


def normalise_level(rms: float) -> float:
    """One chunk's RMS as a 0..1 meter height. Never raises, never exceeds 1."""
    try:
        value = float(rms)
    except (TypeError, ValueError):
        return 0.0
    if value <= METER_FLOOR_RMS:
        return 0.0
    span = math.log(METER_CEILING_RMS) - math.log(METER_FLOOR_RMS)
    scaled = (math.log(value) - math.log(METER_FLOOR_RMS)) / span
    return min(1.0, max(0.0, scaled))


class BubbleView(Protocol):
    """Everything the controller may ask of a window.

    Small on purpose. A wider protocol is a wider thing to fake, and the fake is
    what the tests run against.
    """

    def show(self, *, position: tuple[int, int], topmost: bool) -> None:
        """Create and display the window at *position*."""

    def set_state(self, state: str, label: str) -> None:
        """Reflect the current state."""

    def set_status_line(self, text: str) -> None:
        """Model, speech readiness, last error."""

    def set_reply(self, text: str) -> None:
        """Show a reply. Must be selectable."""

    def set_transcript(self, text: str) -> None:
        """Show what was heard, before the reply arrives."""

    def clear_entry(self) -> None:
        """Empty the text box after submitting it."""

    def set_levels(self, levels: tuple[float, ...]) -> None:
        """Draw the capture level meter. Empty means "not recording".

        Values are already normalised to 0..1 by the controller, so a
        view never sees an RMS and never reads the microphone itself.
        """

    def position(self) -> tuple[int, int]:
        """Where the window is now, for remembering it."""

    def close(self) -> None:
        """Destroy the window."""


def position_file() -> Path:
    """Where the remembered position lives.

    Resolved at call time, not import time. A module-level default computed from
    ``GRANDPA_HOME`` is evaluated before anything has had a chance to set it,
    which is how a store once wrote into a real home directory from a test.
    """
    import os

    root = Path(os.environ.get("GRANDPA_HOME", Path.home() / ".grandpa")).expanduser()
    return root / "ui" / "bubble-position.json"


def load_position(path: Path | None = None) -> tuple[int, int]:
    """The remembered position, or the default. Never raises."""
    import json

    target = path or position_file()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        return int(data["x"]), int(data["y"])
    except Exception:
        return DEFAULT_POSITION


def save_position(position: tuple[int, int], path: Path | None = None) -> bool:
    """Remember the position. Returns whether it was written.

    A UI that cannot write its own position file should still run, so a failure
    is reported rather than raised.
    """
    import json

    target = path or position_file()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps({"x": int(position[0]), "y": int(position[1])}),
            encoding="utf-8",
        )
        return True
    except Exception:
        return False


@dataclass
class BubbleController:
    """The bubble, minus the window.

    ``probe`` and ``capture`` are the same objects ``grandpa voice
    push-to-talk`` uses, unchanged. The hold is read with
    :class:`WindowsKeyProbe`, which reads ``GetAsyncKeyState`` globally -- which
    is why a held key works while another window has focus, and why the hotkey
    rather than the button is the primitive here.
    """

    view: BubbleView
    bridge: Any
    probe: Any = None
    capture: Any = None
    #: A combination, ``ctrl+win``, not a single key. A global read means the
    #: key also reaches whatever has focus, so a printable key types into that
    #: window and a lone modifier fires on every shortcut the user performs. A
    #: chord satisfies neither: Ctrl+C never satisfies ctrl+win. See
    #: DEFAULT_HOLD_KEY for what was rejected and why.
    key: str = DEFAULT_HOLD_KEY
    #: Shortest hold that counts, borrowed from push-to-talk's own value so the
    #: two paths agree about what a tap is.
    minimum_hold_seconds: float = 0.2
    #: Injected so tests neither sleep nor wait on a real clock. The hold's
    #: watcher thread belongs to PushToTalkSession, which this delegates to.
    sleep: Any = None
    clock: Any = None
    #: Speak replies as well as showing them. Text is never replaced by speech.
    speak_replies: bool = True
    #: The text-to-speech seam: anything with ``speak(text)`` and ``stop()``.
    #: ``None`` means replies stay silent, which is what every test uses -- the
    #: audio guard denies opening a speaker.
    speaker: Any = None
    #: How a view update reaches the view. ``None`` applies it immediately on
    #: the calling thread, which is what tests and any single-threaded driver
    #: want. The bubble command sets this to a queue put that the tkinter tick
    #: drains, because a hold and a spoken reply both block and so must run off
    #: the view's thread -- and tkinter may only be touched from its own.
    dispatch: Any = None

    state: BubbleState = field(default=BubbleState.LOADING, init=False)
    last_error: str = field(default="", init=False)
    #: How many times the view reported the hold key while focused. Carried so a
    #: test can prove the key was noticed rather than silently dropped.
    key_seen_count: int = field(default=0, init=False)
    model_name: str = field(default="", init=False)
    position: tuple[int, int] = field(default=DEFAULT_POSITION, init=False)
    _position_path: Path | None = field(default=None, init=False)
    #: Recent capture levels, already normalised, newest last. A bounded deque
    #: appended from the capture thread and read from the view's thread;
    #: ``append`` on a bounded deque is atomic in CPython, and a meter that
    #: misses one frame of three-second history does not need a lock for it.
    _levels: deque[float] = field(
        default_factory=lambda: deque(maxlen=METER_BARS), init=False
    )

    def __post_init__(self) -> None:
        import time

        if self.sleep is None:
            self.sleep = time.sleep
        if self.clock is None:
            self.clock = time.monotonic

    # --- lifecycle -----------------------------------------------------------

    def start(self, *, position_path: Path | None = None) -> None:
        """Show the window, then load the model.

        In that order, so the user sees something immediately -- but in the
        LOADING state, which says the speech path is not usable yet. Showing
        "Ready" first and loading afterwards is the bug this is written to
        avoid.
        """
        self._position_path = position_path
        self.position = load_position(position_path)
        self.view.show(position=self.position, topmost=True)
        self._enter(BubbleState.LOADING)
        self._refresh_status()

    def warm(self) -> bool:
        """Load the speech model and move out of LOADING."""
        warmer = getattr(self.bridge, "warm", None)
        if not callable(warmer):
            self.model_name = ""
            self._enter(BubbleState.IDLE)
            self._refresh_status()
            return True
        ready, detail = warmer()
        self.model_name = self._current_model()
        if not ready:
            self.last_error = detail
            self._enter(BubbleState.ERROR)
        else:
            self._enter(BubbleState.IDLE)
        self._refresh_status()
        return bool(ready)

    def stop(self) -> None:
        """Remember where the window is, then close it."""
        try:
            self.position = tuple(self.view.position())  # type: ignore[assignment]
        except Exception:
            pass
        save_position(self.position, self._position_path)
        self.view.close()

    # --- the hold ------------------------------------------------------------

    @property
    def speech_ready(self) -> bool:
        return bool(getattr(self.bridge, "speech_ready", False))

    def can_record(self) -> bool:
        return (
            self.state not in STATES_THAT_REFUSE_A_HOLD
            and self.probe is not None
            and self.capture is not None
        )

    def note_key_seen(self) -> None:
        """The hold key was pressed while the bubble had focus.

        Called by the view, which has already stopped the character reaching the
        text box. The point of this is that the key was *seen*: a held key that
        produced no indicator, no error and no recording is what the bubble
        reported before, and silence is indistinguishable from a dead key.
        """
        self.key_seen_count += 1
        if self.state is BubbleState.LOADING:
            self.last_error = (
                f"Saw {describe_hold_key(self.key)} -- still loading the model, so the "
                f"hold was ignored."
            )
        elif self.state in STATES_THAT_REFUSE_A_HOLD:
            self.last_error = (
                f"Saw {describe_hold_key(self.key)} -- busy ({self.state}), so the hold "
                f"was ignored."
            )
        else:
            self.last_error = ""
        self._refresh_status()

    def on_hold(self) -> str:
        """One press-and-hold: record, transcribe, route.

        Returns the transcript, empty if nothing came back. Every refusal below
        says why. The caller must not pre-screen with ``can_record()`` and
        return quietly -- that is exactly what made a held key produce nothing
        at all, because the explanations here never ran.
        """
        # Holding the key during a spoken reply cuts it off and starts a
        # new utterance. That is why SPEAKING is not in
        # STATES_THAT_REFUSE_A_HOLD: interrupting is the point.
        if self.state is BubbleState.SPEAKING:
            self.interrupt_speech()
        if self.state is BubbleState.LOADING:
            self.last_error = (
                f"Saw {describe_hold_key(self.key)} -- still loading the model, so "
                f"nothing was recorded."
            )
            self._refresh_status()
            return ""
        if self.state in STATES_THAT_REFUSE_A_HOLD:
            self.last_error = (
                f"Saw {describe_hold_key(self.key)} -- already {self.state}, so the hold "
                f"was ignored."
            )
            self._refresh_status()
            return ""
        if self.probe is None or self.capture is None:
            self.last_error = (
                f"Saw {describe_hold_key(self.key)} -- no microphone capture is wired up."
            )
            self._enter(BubbleState.ERROR)
            self._refresh_status()
            return ""

        self._levels.clear()
        self._enter(BubbleState.RECORDING)
        try:
            audio, held = self._record_while_held()
        except Exception as exc:  # noqa: BLE001 - a UI must not die of a capture
            self.last_error = f"{type(exc).__name__}: {exc}"
            self._enter(BubbleState.ERROR)
            self._refresh_status()
            return ""

        # A tap is not an utterance. Checked here rather than left to the
        # transcriber because the whole point of this round is that a key press
        # must produce a visible answer, and "that was a 0.08s tap" is one.
        if held < self.minimum_hold_seconds:
            self.last_error = (
                f"That was a {held:.2f}s tap -- hold {describe_hold_key(self.key)} down "
                f"while you speak."
            )
            self._enter(BubbleState.IDLE)
            self._refresh_status()
            return ""

        self._enter(BubbleState.TRANSCRIBING)
        outcome = self.bridge.transcribe(audio)
        transcript = (getattr(outcome, "text", "") or "").strip()
        if not transcript:
            explanation = getattr(outcome, "explanation", "") or "nothing recognisable"
            self._to_view(lambda: self.view.set_transcript(""))
            self.last_error = f"Heard nothing usable -- {explanation}."
            self._enter(BubbleState.IDLE)
            self._refresh_status()
            return ""

        self._to_view(lambda: self.view.set_transcript(transcript))
        self.submit(transcript)
        return transcript

    def _record_while_held(self) -> tuple[Any, float]:
        """Delegate to ``PushToTalkSession.record_while_held``, unchanged.

        That method is the hold: it spawns the key watcher, hands the capture a
        stop event, and enforces ``MAXIMUM_HOLD_SECONDS`` so a stuck key cannot
        record forever. An earlier version of this file reimplemented it and
        silently dropped the stuck-key cap, which is the argument for delegating
        rather than copying.

        ``run_once`` is deliberately not used. It owns a blocking loop that
        waits for the press, transcribes and routes, and prints its own
        progress -- so the view could not be updated between the states, which
        is the bubble's whole job. The session is built here only to borrow the
        one method, and its transcriber is never touched by it.
        """
        session = self._hold_session()
        audio, held, _reason = session.record_while_held()
        return audio, held

    def _hold_session(self) -> Any:
        """A PushToTalkSession wired to this controller's collaborators."""
        from grandpa.voice.push_to_talk import PushToTalkSession

        return PushToTalkSession(
            capture=self.capture,
            # record_while_held never consults it; the bubble transcribes
            # through the bridge so the seam stays the only route out.
            transcriber=None,
            probe=self.probe,
            key=self.key,
            echo=lambda _message: None,
            sleep=self.sleep,
            clock=self.clock,
        )

    # --- the text box --------------------------------------------------------

    def submit(self, text: str) -> str:
        """Route typed or spoken text and show the reply."""
        cleaned = (text or "").strip()
        if not cleaned:
            return ""
        self._enter(BubbleState.THINKING)
        reply = self.bridge.send(cleaned)
        self._to_view(self.view.clear_entry)
        reply_text = (getattr(reply, "text", "") or "").strip()
        if getattr(reply, "failed", False):
            self.last_error = reply_text or "That did not work."
            failed_text = reply_text or self.last_error
            self._to_view(lambda: self.view.set_reply(failed_text))
            self._enter(BubbleState.ERROR)
        else:
            self.last_error = ""
            shown = reply_text or "(no reply)"
            self._to_view(lambda: self.view.set_reply(shown))
            self._enter(BubbleState.IDLE)
        self._refresh_status()
        # After the text is on screen, never instead of it.
        if not getattr(reply, "failed", False):
            self._speak(reply_text)
        return reply_text

    # --- status --------------------------------------------------------------

    def status_line(self) -> str:
        """Model, speech readiness, last error. In that order."""
        model = self.model_name or "model unknown"
        if self.state is BubbleState.LOADING:
            speech = "loading"
        elif self.speech_ready:
            speech = "speech ready"
        else:
            speech = "speech not ready"
        parts = [model, speech]
        if self.last_error:
            parts.append(self.last_error)
        return "  |  ".join(parts)

    def _to_view(self, update: Any) -> None:
        """Apply a view update, here or wherever the dispatcher says.

        Every call that touches the view goes through this. With no dispatcher
        it is a direct call and nothing has changed; with one, the update is
        handed to the thread that owns the widgets.
        """
        if self.dispatch is None:
            update()
            return
        try:
            self.dispatch(update)
        except Exception:  # noqa: BLE001 - a closed window must not raise here
            pass

    def _refresh_status(self) -> None:
        line = self.status_line()
        self._to_view(lambda: self.view.set_status_line(line))

    def _enter(self, state: BubbleState) -> None:
        # The state changes now, on this thread, because the refusal checks and
        # can_record() read it; only the drawing of it is dispatched.
        self.state = state
        label = STATE_LABELS[state]
        self._to_view(lambda: self.view.set_state(str(state), label))

    # --- the level meter -----------------------------------------------------

    def note_level(self, rms: float) -> None:
        """One capture chunk's loudness, from the thread reading the device.

        Deliberately does not touch the view: this runs on whichever thread is
        inside ``capture()``. It only appends. ``refresh_meter`` moves it to the
        view, on the view's own thread, once per tick rather than once per
        chunk -- which is what keeps a meter that updates ten times a second
        from becoming thirty widget writes.
        """
        self._levels.append(normalise_level(rms))

    def meter_levels(self) -> tuple[float, ...]:
        """The meter as the view should draw it: oldest first, padded to width."""
        values = tuple(self._levels)
        if len(values) >= METER_BARS:
            return values[-METER_BARS:]
        return (0.0,) * (METER_BARS - len(values)) + values

    def refresh_meter(self) -> None:
        """Push the meter to the view. Called from the view's own thread."""
        levels = self.meter_levels() if self.state is BubbleState.RECORDING else ()
        self._to_view(lambda: self.view.set_levels(levels))

    # --- speech --------------------------------------------------------------

    def toggle_speech(self) -> bool:
        """Turn spoken replies on or off, and stop anything in progress."""
        self.speak_replies = not self.speak_replies
        if not self.speak_replies:
            self.interrupt_speech()
        self._refresh_status()
        return self.speak_replies

    def interrupt_speech(self) -> bool:
        """Cut a reply off mid-sentence. True if there was an engine to ask."""
        if self.speaker is None:
            return False
        stop = getattr(self.speaker, "stop", None)
        if not callable(stop):
            return False
        try:
            stop()
        except Exception:  # noqa: BLE001 - interrupting must not raise
            return False
        if self.state is BubbleState.SPEAKING:
            self._enter(BubbleState.IDLE)
            self._refresh_status()
        return True

    def _speak(self, text: str) -> None:
        """Say the reply. The text is already on screen before this runs.

        A failure here changes the status line and nothing else: the reply
        arrived and is readable, so losing the audio is not losing the answer.
        """
        if not text or not self.speak_replies or self.speaker is None:
            return
        self._enter(BubbleState.SPEAKING)
        self._refresh_status()
        try:
            result = self.speaker.speak(text)
        except Exception as exc:  # noqa: BLE001 - the text already arrived
            self.last_error = f"Could not speak the reply ({type(exc).__name__})."
        else:
            # The engine reports rather than raises; "fallback" means it printed
            # instead of speaking, which is worth saying once.
            status = str(getattr(result, "status", "") or "")
            self.last_error = (
                "The reply was not spoken: no working speech engine."
                if status == "fallback"
                else ""
            )
        if self.state is BubbleState.SPEAKING:
            self._enter(BubbleState.IDLE)
        self._refresh_status()

    def _current_model(self) -> str:
        transcriber = getattr(self.bridge, "transcriber", None)
        for attribute in ("model", "_model_size", "stt_model"):
            value = getattr(transcriber, attribute, "")
            if value:
                return str(value)
        engine = getattr(transcriber, "_engine", None)
        value = getattr(engine, "model", "")
        return str(value or "")


__all__ = [
    "DEFAULT_HOLD_KEY",
    "DEFAULT_POSITION",
    "METER_BARS",
    "METER_CEILING_RMS",
    "METER_FLOOR_RMS",
    "STATES_THAT_REFUSE_A_HOLD",
    "STATE_LABELS",
    "normalise_level",
    "BubbleController",
    "BubbleState",
    "BubbleView",
    "load_position",
    "position_file",
    "save_position",
]
