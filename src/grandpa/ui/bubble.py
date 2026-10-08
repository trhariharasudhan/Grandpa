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
from grandpa.voice.push_to_talk import DEFAULT_HOLD_KEY


class BubbleState(StrEnum):
    """What the bubble is doing. Shown, not inferred."""

    LOADING = "loading"
    IDLE = "idle"
    RECORDING = "recording"
    TRANSCRIBING = "transcribing"
    THINKING = "thinking"
    ERROR = "error"


#: What each state says, so the view does not invent wording.
STATE_LABELS: dict[BubbleState, str] = {
    BubbleState.LOADING: "Loading model...",
    BubbleState.IDLE: "Ready",
    BubbleState.RECORDING: "Recording",
    BubbleState.TRANSCRIBING: "Transcribing...",
    BubbleState.THINKING: "Thinking...",
    BubbleState.ERROR: "Error",
}

#: The states in which a hold must not start a recording.
STATES_THAT_REFUSE_A_HOLD = frozenset(
    {BubbleState.LOADING, BubbleState.RECORDING, BubbleState.TRANSCRIBING,
     BubbleState.THINKING}
)

DEFAULT_POSITION = (40, 40)


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
    #: f9, not space. A global read means the key also reaches whatever has
    #: focus, so a printable key types into that window -- including the
    #: bubble's own text box, which is how this default was reported. Modifiers
    #: type nothing but fire on every shortcut the user performs (Ctrl+C,
    #: Shift+click, Alt+Tab), and Alt alone opens the Windows menu bar. F9 is
    #: neither printable nor a shortcut modifier. See DEFAULT_HOLD_KEY.
    key: str = DEFAULT_HOLD_KEY
    #: Shortest hold that counts, borrowed from push-to-talk's own value so the
    #: two paths agree about what a tap is.
    minimum_hold_seconds: float = 0.2
    #: Injected so tests neither sleep nor wait on a real clock. The hold's
    #: watcher thread belongs to PushToTalkSession, which this delegates to.
    sleep: Any = None
    clock: Any = None

    state: BubbleState = field(default=BubbleState.LOADING, init=False)
    last_error: str = field(default="", init=False)
    #: How many times the view reported the hold key while focused. Carried so a
    #: test can prove the key was noticed rather than silently dropped.
    key_seen_count: int = field(default=0, init=False)
    model_name: str = field(default="", init=False)
    position: tuple[int, int] = field(default=DEFAULT_POSITION, init=False)
    _position_path: Path | None = field(default=None, init=False)

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
                f"Saw {self.key.upper()} -- still loading the model, so the "
                f"hold was ignored."
            )
        elif self.state in STATES_THAT_REFUSE_A_HOLD:
            self.last_error = (
                f"Saw {self.key.upper()} -- busy ({self.state}), so the hold "
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
        if self.state is BubbleState.LOADING:
            self.last_error = (
                f"Saw {self.key.upper()} -- still loading the model, so "
                f"nothing was recorded."
            )
            self._refresh_status()
            return ""
        if self.state in STATES_THAT_REFUSE_A_HOLD:
            self.last_error = (
                f"Saw {self.key.upper()} -- already {self.state}, so the hold "
                f"was ignored."
            )
            self._refresh_status()
            return ""
        if self.probe is None or self.capture is None:
            self.last_error = (
                f"Saw {self.key.upper()} -- no microphone capture is wired up."
            )
            self._enter(BubbleState.ERROR)
            self._refresh_status()
            return ""

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
                f"That was a {held:.2f}s tap -- hold {self.key.upper()} down "
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
            self.view.set_transcript("")
            self.last_error = f"Heard nothing usable -- {explanation}."
            self._enter(BubbleState.IDLE)
            self._refresh_status()
            return ""

        self.view.set_transcript(transcript)
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
        self.view.clear_entry()
        reply_text = (getattr(reply, "text", "") or "").strip()
        if getattr(reply, "failed", False):
            self.last_error = reply_text or "That did not work."
            self.view.set_reply(reply_text or self.last_error)
            self._enter(BubbleState.ERROR)
        else:
            self.last_error = ""
            self.view.set_reply(reply_text or "(no reply)")
            self._enter(BubbleState.IDLE)
        self._refresh_status()
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

    def _refresh_status(self) -> None:
        self.view.set_status_line(self.status_line())

    def _enter(self, state: BubbleState) -> None:
        self.state = state
        self.view.set_state(str(state), STATE_LABELS[state])

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
    "STATES_THAT_REFUSE_A_HOLD",
    "STATE_LABELS",
    "BubbleController",
    "BubbleState",
    "BubbleView",
    "load_position",
    "position_file",
    "save_position",
]
