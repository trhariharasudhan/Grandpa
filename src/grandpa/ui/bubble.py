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
    #: An automation is running right now. Set from the action layer's own
    #: announcement around the single site where a catalogued action is
    #: performed, never guessed at from the text of a request.
    EXECUTING = "executing"
    SPEAKING = "speaking"
    #: An operation completed. A resting state, not a flash: it persists until
    #: the next thing happens, exactly as ERROR does. The symmetry is the
    #: argument -- a failure you can still see a minute later is useful, and so
    #: is a success.
    SUCCESS = "success"
    ERROR = "error"


#: What each state says, so the view does not invent wording.
STATE_LABELS: dict[BubbleState, str] = {
    BubbleState.LOADING: "Loading model...",
    # "Standby", not "Ready": green now means an operation completed, and a
    # neutral-white ring labelled "Ready" would have contradicted it.
    BubbleState.IDLE: "Standby",
    BubbleState.RECORDING: "Recording",
    BubbleState.TRANSCRIBING: "Transcribing...",
    BubbleState.THINKING: "Thinking...",
    BubbleState.EXECUTING: "Working...",
    BubbleState.SPEAKING: "Speaking...",
    BubbleState.SUCCESS: "Done",
    BubbleState.ERROR: "Error",
}


def done_kinds() -> frozenset[str]:
    """The action kinds that mean something on this machine actually changed.

    Derived from the action layer's own ``ActionKind`` literal rather than
    listed here, so a kind added there cannot be silently missed. Three are
    excluded, and each exclusion is a claim:

    * ``agent_plan`` -- a plan was produced, not performed.
    * ``blocked`` -- it was refused. Nothing ran.
    * ``app_lookup`` -- a question was answered. Nothing changed.

    A kind not in ``ActionKind`` at all is not an action: the conversational
    paths report ``voice``, ``assistant`` and -- for the "who are you" reply --
    ``local``, which is why the test is membership in this set and never
    ``kind != "voice"``.
    """
    from typing import get_args

    from grandpa.local_action_result import ActionKind

    return frozenset(get_args(ActionKind)) - {"agent_plan", "blocked", "app_lookup"}


#: Kinds excluded from :func:`done_kinds`, named so a test can assert each one
#: is a real ``ActionKind``. A typo here would exclude nothing and go unnoticed.
NOT_DONE_KINDS = frozenset({"agent_plan", "blocked", "app_lookup"})


def completed_an_operation(reply: Any) -> bool:
    """Whether this reply means an operation finished, rather than arrived.

    Both halves are required. ``status == "handled"`` is the action layer's own
    word for "performed" -- it is one of a closed set that also contains
    ``requires_confirmation``, ``blocked``, ``unsupported``, ``no_match``,
    ``error`` and ``cancelled``, none of which ran anything. And the kind has
    to be an action, or every chat answer would turn the ring green and green
    would mean "a reply arrived", which the resting state already means.
    """
    status = str(getattr(reply, "status", "") or "")
    kind = str(getattr(reply, "kind", "") or "")
    return status == "handled" and kind in done_kinds()

#: The states in which a hold must not start a recording.
STATES_THAT_REFUSE_A_HOLD = frozenset(
    {BubbleState.LOADING, BubbleState.RECORDING, BubbleState.TRANSCRIBING,
     BubbleState.THINKING, BubbleState.EXECUTING}
)

DEFAULT_POSITION = (40, 40)

#: Where the orb sits on a first run: just clear of the panel's own default
#: rectangle, so the two do not start on top of each other.
DEFAULT_ORB_POSITION = (460, 40)

#: How many exchanges the panel keeps. Three, because collapsed is voice-only
#: and three questions before expanding is an ordinary thing to do -- with one
#: slot the first two were simply gone. A bounded deque and two compact lines,
#: not the scrolling log that was considered and rejected: the orb is the
#: identity and a short exchange suits it.
EXCHANGE_MEMORY = 3

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

    def set_earlier(self, rows: tuple[tuple[str, str], ...]) -> None:
        """Show the exchanges before the current one, newest first."""

    def set_transcript(self, text: str) -> None:
        """Show what was heard, before the reply arrives."""

    def clear_entry(self) -> None:
        """Empty the text box after submitting it."""

    def set_entry_text(self, text: str) -> None:
        """Put text in the box, ready to be edited and sent.

        Used to correct a mis-heard transcript. Presentational: the corrected
        text goes out through the ordinary submit path, so the controller needs
        to know nothing about it.
        """

    def set_levels(self, levels: tuple[float, ...]) -> None:
        """Draw the capture level meter. Empty means "not recording".

        Values are already normalised to 0..1 by the controller, so a
        view never sees an RMS and never reads the microphone itself.
        """

    def position(self) -> tuple[int, int]:
        """Where the window is now, for remembering it."""

    def close(self) -> None:
        """Destroy the window."""


class OrbSurface(Protocol):
    """Everything the controller may ask of the orb.

    Smaller than BubbleView because the orb shows one thing: a state. It has no
    text, which is the point of it -- collapsed is voice-only.
    """

    def show(self, *, position: tuple[int, int], topmost: bool) -> None:
        """Put it on screen."""

    def set_state(self, state: str, *, unread: bool) -> None:
        """What the ring shows."""

    def set_level(self, level: float) -> None:
        """The live microphone level, 0..1."""

    def position(self) -> tuple[int, int]:
        """Where it is now."""

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


def load_orb_position(path: Path | None = None) -> tuple[int, int]:
    """Where the orb was left, or its default. Never raises."""
    return _read_state(path).get("orb", DEFAULT_ORB_POSITION)


def load_collapsed(path: Path | None = None) -> bool:
    """Whether the bubble was last left collapsed to the orb.

    Absent means collapsed: a first run opens as the orb. See
    docs/development/orb-survey.md for why that is the chosen default rather
    than merely the remembered one.
    """
    return bool(_read_state(path).get("collapsed", True))


def _read_state(path: Path | None = None) -> dict[str, Any]:
    """The whole remembered window state, normalised. Never raises."""
    import json

    target = path or position_file()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    state: dict[str, Any] = {}
    try:
        state["panel"] = (int(data["x"]), int(data["y"]))
    except Exception:
        pass
    try:
        state["orb"] = (int(data["orb_x"]), int(data["orb_y"]))
    except Exception:
        pass
    if "collapsed" in data:
        state["collapsed"] = bool(data["collapsed"])
    return state


def save_position(
    position: tuple[int, int],
    path: Path | None = None,
    *,
    collapsed: bool | None = None,
    orb_position: tuple[int, int] | None = None,
) -> bool:
    """Remember the position. Returns whether it was written.

    Keys not passed are **merged from whatever is already on disk** rather than
    dropped. A caller that only knows about the panel's position must not be
    able to silently erase the collapsed flag: that is how a window forgets
    which state it was in because an unrelated code path saved.

    A UI that cannot write its own position file should still run, so a failure
    is reported rather than raised.
    """
    import json

    target = path or position_file()
    existing: dict[str, Any] = {}
    try:
        loaded = json.loads(target.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            existing = loaded
    except Exception:
        existing = {}
    existing["x"] = int(position[0])
    existing["y"] = int(position[1])
    if orb_position is not None:
        existing["orb_x"] = int(orb_position[0])
        existing["orb_y"] = int(orb_position[1])
    if collapsed is not None:
        existing["collapsed"] = bool(collapsed)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(existing), encoding="utf-8")
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
    #: The orb, or None. Optional because the controller predates it and every
    #: path through it must still work with the panel alone.
    orb: Any = None
    #: Places the panel beside the orb on expand. Injected so the work area is
    #: not read from a real screen in a test. Called with the orb's position.
    anchor: Any = None
    #: Keeps the orb's visible ring inside the work area. Called with ``(x, y)``
    #: and returning a possibly-adjusted ``(x, y)``. Injected for the same
    #: reason as *anchor*: a test must not depend on this machine's monitors.
    clamp: Any = None
    #: The panel's size, so the controller can tell whether the panel still
    #: fits where the stored offset puts it. Set by the command from the view's
    #: own constants; bubble.py imports no toolkit and must not read them.
    panel_size: tuple[int, int] | None = None
    #: The work area, for the fit check above. Injected, same reasoning.
    work_area: Any = None
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
    #: Where the panel is. DERIVED from the anchor and the offset below --
            # written by _place_windows and by nothing else.
    position: tuple[int, int] = field(default=DEFAULT_POSITION, init=False)
    #: **The anchor.** The orb's top-left, and the single thing a drag moves.
    #: The orb and the panel are two native windows -- the panel is the Tk
    #: root, the orb is a Toplevel whose pixels Win32 blits -- so there is no
    #: shared parent to move. One number that both windows are placed from is
    #: the whole of what keeps them together; the alternative is two positions
    #: that agree until they do not.
    orb_position: tuple[int, int] = field(default=DEFAULT_ORB_POSITION, init=False)
    #: The panel's offset from the anchor. Set once when the panel is first
    #: placed beside the orb and preserved through every collapse, expand and
    #: drag, which is what "the panel never detaches" means in practice.
    panel_offset: tuple[int, int] | None = field(default=None, init=False)
    #: Collapsed to the orb: voice only, no panel. Set from the remembered
    #: state by start(), not by the constructor.
    collapsed: bool = field(default=False, init=False)
    #: Whether the microphone stream is held open. Pushed to the orb, which
    #: marks it on whatever state is showing. False is the open-on-demand
    #: behaviour, with the measured deaf window.
    mic_live: bool = field(default=False, init=False)
    #: A reply arrived that was never heard and never read. Shown as an amber
    #: ring on the orb, cleared by expanding, and it never times out -- a
    #: notification that disappears on its own is a notification that can be
    #: missed entirely.
    unread: bool = field(default=False, init=False)
    _position_path: Path | None = field(default=None, init=False)
    #: The event bus, once subscribed. None means not watching.
    _action_watch: Any = field(default=None, init=False)
    #: The last few exchanges, oldest first, as ``(heard, reply)``. Bounded, so
    #: a long session cannot grow it.
    _exchanges: deque[tuple[str, str]] = field(
        default_factory=lambda: deque(maxlen=EXCHANGE_MEMORY), init=False
    )
    #: What was heard for the exchange being answered now.
    _pending_heard: str = field(default="", init=False)
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
        # Clamped on the way in as well as during a drag: a remembered position
        # from a larger screen, or from a monitor that is no longer attached,
        # would otherwise put the orb somewhere it cannot be reached.
        self.orb_position = self._clamped(*load_orb_position(position_path))
        self.collapsed = load_collapsed(position_path)
        # Both windows are created now, whichever state is wanted, because
        # creating a window takes the foreground -- measured -- and a window
        # built on first expand would take it then instead, every time.
        self.view.show(position=self.position, topmost=True)
        if self.orb is not None:
            self.orb.show(position=self.orb_position, topmost=True)
        if self.collapsed:
            self._hide_panel()
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
        """Remember where the windows are and which state they were in, then
        close them."""
        try:
            self.position = tuple(self.view.position())  # type: ignore[assignment]
        except Exception:
            pass
        if self.orb is not None:
            try:
                self.orb_position = tuple(self.orb.position())  # type: ignore[assignment]
            except Exception:
                pass
        self._remember()
        self.unwatch_actions()
        if self.orb is not None:
            try:
                self.orb.close()
            except Exception:  # noqa: BLE001 - closing one must not strand the other
                pass
        self.view.close()

    def _remember(self) -> bool:
        return save_position(
            self.position,
            self._position_path,
            collapsed=self.collapsed,
            orb_position=self.orb_position,
        )

    # --- collapsed and expanded ----------------------------------------------

    def toggle_collapsed(self) -> bool:
        """One click on the orb. Returns the new collapsed state."""
        return self.collapse() if not self.collapsed else self.expand()

    # --- one component, two windows ------------------------------------------

    def move_component(self, dx: int, dy: int) -> tuple[int, int]:
        """Move the whole thing by a delta. Returns the new anchor.

        Called by *both* drag handlers -- the orb's and the panel header's --
        because there is one component and dragging any part of it moves the
        part. The panel's offset is untouched, so the two cannot drift.

        The anchor is clamped on every motion event rather than at the end of
        the drag, so the orb stops at the edge instead of going over it and
        being pulled back. Clamping the anchor rather than each window is what
        keeps the clamp and the coupling from fighting: there is one position,
        so there is one thing to constrain.
        """
        self.orb_position = self._clamped(
            int(self.orb_position[0] + dx), int(self.orb_position[1] + dy)
        )
        self._place_windows()
        return self.orb_position

    def _clamped(self, x: int, y: int) -> tuple[int, int]:
        """The anchor, kept where the orb's ring stays on screen."""
        if not callable(self.clamp):
            return (int(x), int(y))
        try:
            clamped = self.clamp(int(x), int(y))
            return (int(clamped[0]), int(clamped[1]))
        except Exception:  # noqa: BLE001 - a bad clamp must not freeze the orb
            return (int(x), int(y))

    def _panel_position(self) -> tuple[int, int]:
        """Where the panel goes for the current anchor.

        The stored offset is honoured **while the panel still fits**. Once the
        orb is close enough to an edge that the offset would put the panel off
        screen, the anchor function decides instead -- and that already flips
        the panel to the orb's other side and clamps as a last resort.

        This is the answer to a real tension. The offset exists so a panel
        dragged somewhere stays there; the flip exists so a panel is reachable
        at an edge. Clamping the component's whole bounding box would satisfy
        neither: it would cost 400 pixels of travel and stop the orb reaching
        the corner at all, which is the thing being asked for. An orb that is
        reachable whose panel opens off screen is the same bug one layer along,
        so the offset yields rather than the reachability.
        """
        anchored: tuple[int, int] | None = None
        if callable(self.anchor):
            try:
                anchored = tuple(self.anchor(self.orb_position))  # type: ignore[assignment]
            except Exception:  # noqa: BLE001 - a bad anchor must not trap the panel
                anchored = None
        if self.panel_offset is not None:
            offset_place = (
                int(self.orb_position[0] + self.panel_offset[0]),
                int(self.orb_position[1] + self.panel_offset[1]),
            )
            if self._panel_fits(offset_place) or anchored is None:
                return offset_place
            return anchored
        if anchored is not None:
            return anchored
        return self.position

    def _panel_fits(self, at: tuple[int, int]) -> bool:
        """Whether the panel is wholly inside the work area at *at*.

        True when there is nothing to check against -- no size, no work area --
        because a missing measurement must not move a window that was fine.
        """
        if self.panel_size is None or not callable(self.work_area):
            return True
        try:
            left, top, right, bottom = self.work_area(at)
            width, height = int(self.panel_size[0]), int(self.panel_size[1])
        except Exception:  # noqa: BLE001
            return True
        return (
            at[0] >= left
            and at[1] >= top
            and at[0] + width <= right
            and at[1] + height <= bottom
        )

    def _adopt_offset(self) -> None:
        """Fix the panel's offset from wherever the anchor function puts it.

        Done once, on the first placement, so that afterwards the offset is the
        thing preserved rather than recomputed -- recomputing on every drag
        would snap the panel back to the orb's side the moment it was moved.
        """
        if self.panel_offset is not None:
            return
        placed = self._panel_position()
        self.panel_offset = (
            int(placed[0] - self.orb_position[0]),
            int(placed[1] - self.orb_position[1]),
        )

    def _place_windows(self) -> None:
        """Put both windows where the anchor says. The only writer of position."""
        self._adopt_offset()
        self.position = self._panel_position()
        orb_at = self.orb_position
        panel_at = self.position
        move_orb = getattr(self.orb, "move_window", None)
        if callable(move_orb):
            self._to_orb(lambda: self.orb.move_window(orb_at[0], orb_at[1]))
            self._to_orb(self.orb.redraw)
        move_panel = getattr(self.view, "move_to", None)
        if callable(move_panel) and not self.collapsed:
            self._to_view(lambda: self.view.move_to(panel_at[0], panel_at[1]))

    def collapse(self) -> bool:
        """Voice only: the panel goes away, the orb stays."""
        self.collapsed = True
        self._hide_panel()
        self._remember()
        self._refresh_orb()
        return self.collapsed

    def expand(self) -> bool:
        """The panel comes back, beside the orb, with the last exchange still
        in it -- and the unread ring clears, because it has now been read.

        Its place comes from the anchor and the stored offset, so a panel that
        was dragged somewhere comes back where it was left rather than snapping
        to the orb's side.
        """
        self.collapsed = False
        self.unread = False
        self._adopt_offset()
        self.position = self._panel_position()
        placed = self.position
        self._to_view(lambda: self._unhide_panel(placed))
        self._remember()
        self._refresh_orb()
        return self.collapsed

    def _hide_panel(self) -> None:
        hide = getattr(self.view, "hide", None)
        if callable(hide):
            self._to_view(hide)

    def _unhide_panel(self, position: tuple[int, int]) -> None:
        """Put the panel back where the anchor said, then re-map it.

        In that order: moving a withdrawn window and then showing it means the
        user never sees it at the old place first.
        """
        move = getattr(self.view, "move_to", None)
        if callable(move):
            try:
                move(position[0], position[1])
            except Exception:  # noqa: BLE001
                pass
        unhide = getattr(self.view, "unhide", None)
        if callable(unhide):
            unhide()

    def _mark_unread(self) -> None:
        """A reply nobody heard and nobody has read."""
        self.unread = True
        self._refresh_orb()

    # --- what the action layer says it is doing -------------------------------

    def watch_actions(self) -> bool:
        """Follow the action layer's running/finished announcements.

        Subscribed rather than polled, and to the events the action layer
        already publishes -- there is no second state machine here. The
        callbacks arrive on the announcement thread, so they go through the
        same dispatcher every other view update uses.
        """
        if self._action_watch is not None:
            return True
        try:
            from grandpa.core.events import EventType, get_event_bus

            bus = get_event_bus()
            bus.subscribe(EventType.TOOL_CALL_START, self._on_action_started)
            bus.subscribe(EventType.TOOL_CALL_END, self._on_action_finished)
        except Exception:  # noqa: BLE001 - no bus is not a broken bubble
            return False
        self._action_watch = bus
        return True

    def unwatch_actions(self) -> None:
        bus, self._action_watch = self._action_watch, None
        if bus is None:
            return
        try:
            from grandpa.core.events import EventType

            bus.unsubscribe(EventType.TOOL_CALL_START, self._on_action_started)
            bus.unsubscribe(EventType.TOOL_CALL_END, self._on_action_finished)
        except Exception:  # noqa: BLE001 - leaving a subscription is not fatal
            pass

    def _on_action_started(self, _event: Any = None) -> None:
        """An automation began. Only meaningful while a request is in flight.

        Screened on the current state rather than trusted: this fires for any
        catalogued action performed anywhere in the process, and the orb should
        only speak for the one the user just asked for.
        """
        if self.state not in {BubbleState.THINKING, BubbleState.EXECUTING}:
            return
        self._enter(BubbleState.EXECUTING)
        self._refresh_status()

    def _on_action_finished(self, _event: Any = None) -> None:
        """It returned. Back to thinking, because the reply is still coming."""
        if self.state is not BubbleState.EXECUTING:
            return
        self._enter(BubbleState.THINKING)
        self._refresh_status()

    def note_mic_live(self, live: bool) -> None:
        """The microphone stream opened, or went away. Marked on the orb."""
        self.mic_live = bool(live)
        push = getattr(self.orb, "set_mic_live", None)
        if callable(push):
            flag = self.mic_live
            self._to_orb(lambda: self.orb.set_mic_live(flag))
        self._refresh_status()

    def _refresh_orb(self) -> None:
        state = str(self.state)
        unread = self.unread
        self._to_orb(lambda: self.orb.set_state(state, unread=unread))

    def _to_orb(self, update: Any) -> None:
        if self.orb is None:
            return
        self._to_view(update)

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
        # The numbers `grandpa oops` reports for "voice did not hear
        # me". Recorded whether or not anything was transcribed,
        # because an empty transcript is the case that needs them.
        try:
            from grandpa.diagnostics.oops import record_capture

            record_capture(
                audio,
                held_seconds=held,
                reason=str(getattr(outcome, "reason", "") or ""),
                model=self.model_name,
                transcript_len=len(transcript),
            )
        except Exception:  # noqa: BLE001 - a breadcrumb cannot break a hold
            pass
        if not transcript:
            explanation = getattr(outcome, "explanation", "") or "nothing recognisable"
            self._to_view(lambda: self.view.set_transcript(""))
            self.last_error = f"Heard nothing usable -- {explanation}."
            self._enter(BubbleState.IDLE)
            self._refresh_status()
            return ""

        self._pending_heard = transcript
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

    def exchanges(self) -> tuple[tuple[str, str], ...]:
        """The remembered exchanges, oldest first."""
        return tuple(self._exchanges)

    def _remember_exchange(self, heard: str, reply: str) -> None:
        """Keep this exchange and push the earlier ones to the panel.

        Earlier rather than all: the current exchange already has the two
        prominent panes, and repeating it in the strip above would read as
        having been asked twice.
        """
        self._exchanges.append((heard, reply))
        earlier = tuple(reversed(tuple(self._exchanges)[:-1]))
        push = getattr(self.view, "set_earlier", None)
        if callable(push):
            self._to_view(lambda: self.view.set_earlier(earlier))

    def submit(self, text: str) -> str:
        """Route typed or spoken text and show the reply."""
        cleaned = (text or "").strip()
        if not cleaned:
            return ""
        if not self._pending_heard:
            # Typed, not spoken: what was "heard" is what was typed.
            self._pending_heard = cleaned
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
        self._remember_exchange(self._pending_heard, reply_text or "(no reply)")
        self._pending_heard = ""
        self._refresh_status()
        # After the text is on screen, never instead of it.
        if not getattr(reply, "failed", False):
            spoken = self._speak(reply_text)
            # After speaking, not before: _speak returns the state to IDLE when
            # it finishes, which would have thrown the green away.
            if completed_an_operation(reply):
                self._enter(BubbleState.SUCCESS)
                self._refresh_status()
            # Collapsed and unspoken means the reply exists and nobody has
            # encountered it. A failure is left alone deliberately: the orb is
            # already red for that, and amber would replace the louder signal
            # with a quieter one.
            if self.collapsed and not spoken and reply_text:
                self._mark_unread()
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
        if self.mic_live:
            parts.append("mic held open")
        # Which orb painter is running, so a machine quietly on the flat-disc
        # fallback is visible rather than merely worse-looking.
        painter = ""
        describe = getattr(self.orb, "painter_description", None)
        if callable(describe):
            try:
                painter = str(describe() or "")
            except Exception:  # noqa: BLE001
                painter = ""
        if painter:
            parts.append(painter)
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
        self._refresh_orb()

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
        """Push the meter to the view. Called from the view's own thread.

        The orb gets the same numbers: the newest level, which is what makes the
        ring thicken while the key is held. note_level() cannot do this itself
        because it runs on the capture thread and tkinter may only be touched
        from its own.
        """
        recording = self.state is BubbleState.RECORDING
        levels = self.meter_levels() if recording else ()
        self._to_view(lambda: self.view.set_levels(levels))
        level = levels[-1] if recording and levels else 0.0
        self._to_orb(lambda: self.orb.set_level(level))
        # The whole history, not just the newest number: the waveform is a
        # shape around the circle and one reading cannot describe it.
        history = self.meter_levels() if recording else (0.0,) * METER_BARS
        push_levels = getattr(self.orb, "set_levels", None)
        if callable(push_levels):
            self._to_orb(lambda: self.orb.set_levels(history))

    # --- speech --------------------------------------------------------------

    def toggle_speech(self) -> bool:
        """Turn spoken replies on or off, and stop anything in progress."""
        self.speak_replies = not self.speak_replies
        if not self.speak_replies:
            self.interrupt_speech()
        self._refresh_status()
        return self.speak_replies

    def interrupt_speech(self) -> bool:
        """Cut a reply off mid-sentence. True if there was an engine to ask.

        Deliberately cheap, and deliberately *not* queued onto the worker:
        while a reply is being spoken the worker is inside ``speaker.speak``,
        so a stop queued behind it would arrive only once the thing it stops
        had finished.

        This is what the panel's "stop" button does, and it stops *speaking*.
        It does not stop generating: ``bridge.send`` is one blocking call with
        no cancellation, which is a separate piece of work.
        """
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

    def last_reply(self) -> str:
        """The most recent reply, or empty if there has not been one yet."""
        return self._exchanges[-1][1] if self._exchanges else ""

    def speak_again(self) -> bool:
        """Say the last reply again, because the user asked for it.

        Bypasses :attr:`speak_replies`, which says whether replies are spoken
        *automatically*. A click on "read" is not automatic, and refusing it
        because the automatic setting is off would be the window ignoring a
        direct instruction.

        Blocks for as long as the speech does, so the caller runs it off the tk
        thread. "stop" does not -- see :meth:`interrupt_speech`.
        """
        return self._speak(self.last_reply(), because_asked=True)

    def _speak(self, text: str, *, because_asked: bool = False) -> bool:
        """Say the reply. The text is already on screen before this runs.

        Returns whether it was actually spoken, which is what decides the orb's
        unread ring while collapsed. A failure here changes the status line and
        nothing else: the reply arrived and is readable, so losing the audio is
        not losing the answer.
        """
        if not text or self.speaker is None:
            return False
        if not self.speak_replies and not because_asked:
            return False
        spoken = True
        self._enter(BubbleState.SPEAKING)
        self._refresh_status()
        try:
            result = self.speaker.speak(text)
        except Exception as exc:  # noqa: BLE001 - the text already arrived
            self.last_error = f"Could not speak the reply ({type(exc).__name__})."
            spoken = False
        else:
            # The engine reports rather than raises; "fallback" means it printed
            # instead of speaking, which is worth saying once.
            status = str(getattr(result, "status", "") or "")
            if status == "fallback":
                self.last_error = "The reply was not spoken: no working speech engine."
                spoken = False
            else:
                self.last_error = ""
        if self.state is BubbleState.SPEAKING:
            self._enter(BubbleState.IDLE)
        self._refresh_status()
        return spoken

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
    "EXCHANGE_MEMORY",
    "NOT_DONE_KINDS",
    "DEFAULT_ORB_POSITION",
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
    "OrbSurface",
    "completed_an_operation",
    "done_kinds",
    "load_collapsed",
    "load_orb_position",
    "load_position",
    "position_file",
    "save_position",
]
