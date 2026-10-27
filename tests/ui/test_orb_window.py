"""The orb's window: the mouse, the tick, and the constraints that already held.

A recorder stands in for tkinter, so this is a statement about the code rather
than about a window someone looked at. No test here opens a window.

The three things most worth pinning:

* **a drag never toggles.** Moving the orb and opening the panel are different
  gestures and they share a button. The thresholds come from Windows itself,
  because they are the user's own accessibility settings.
* **the tick cancels rather than re-arms.** The panel's ``pump`` re-arms
  unconditionally, which is right for polling a key and wrong for an animation:
  idle has to cost nothing, not 0.6% of a core forever.
* **focus.** Every constraint that has held for the panel holds for the orb.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from grandpa.ui.orb_view import (
    ANCHOR_GAP,
    DEFAULT_DOUBLE_CLICK_MS,
    DEFAULT_DRAG_SLOP,
    TICK_MS,
    OrbView,
    TapTracker,
    anchor_panel_to_orb,
    system_input_thresholds,
    work_area,
)
from grandpa.ui.tk_view import FOCUS_STEALING_CALLS, REMAP_CALLS

pytestmark = pytest.mark.core

AREA = (0, 0, 1920, 1080)
PANEL = (400, 324)
ORB = 48


class Event:
    def __init__(self, x: int = 10, y: int = 10, x_root: int = 0, y_root: int = 0):
        self.x, self.y = x, y
        self.x_root, self.y_root = x_root, y_root


class RecordingWidget:
    def __init__(self, calls: list, name: str, handlers: dict, scheduled: dict):
        self._calls, self._name = calls, name
        self._handlers, self._scheduled = handlers, scheduled

    def bind(self, sequence, handler):
        self._calls.append((f"{self._name}.bind", (sequence,), {}))
        self._handlers[sequence] = handler

    def after(self, delay, callback):
        self._calls.append((f"{self._name}.after", (delay,), {}))
        token = f"timer{len(self._scheduled) + 1}"
        self._scheduled[token] = (delay, callback)
        return token

    def after_cancel(self, token):
        self._calls.append((f"{self._name}.after_cancel", (token,), {}))
        self._scheduled.pop(token, None)

    def winfo_id(self):
        return 4242

    def __getattr__(self, attribute: str):
        if attribute.startswith("_"):
            raise AttributeError(attribute)

        def record(*args, **kwargs):
            self._calls.append((f"{self._name}.{attribute}", args, kwargs))
            return RecordingWidget(
                self._calls, f"{self._name}.{attribute}", self._handlers,
                self._scheduled,
            )

        return record


class RecordingTk:
    """A stand-in tkinter module. Opens nothing."""

    def __init__(self) -> None:
        self.calls: list = []
        self.handlers: dict = {}
        self.scheduled: dict = {}

    def _widget(self, name: str):
        return RecordingWidget(self.calls, name, self.handlers, self.scheduled)

    def Tk(self, *args, **kwargs):  # noqa: N802 - mirrors tkinter
        self.calls.append(("Tk", args, kwargs))
        return self._widget("root")

    def Toplevel(self, *args, **kwargs):  # noqa: N802 - mirrors tkinter
        self.calls.append(("Toplevel", args, kwargs))
        return self._widget("toplevel")

    def __getattr__(self, attribute: str):
        def factory(*args, **kwargs):
            self.calls.append((attribute, args, kwargs))
            return self._widget(attribute.lower())

        return factory

    def run_due(self) -> int:
        """Fire every scheduled callback once, as a tk loop would."""
        due = list(self.scheduled.items())
        for token, (_delay, callback) in due:
            self.scheduled.pop(token, None)
            callback()
        return len(due)


class Painted:
    """A painter that records images instead of blitting them."""

    name = "layered"
    last_error = ""

    def __init__(self) -> None:
        self.frames: list = []

    @property
    def mode(self) -> str:
        return self.name

    def paint(self, image, x, y) -> bool:
        self.frames.append((image, x, y))
        return True

    def describe(self) -> str:
        return "orb: glow"


def a_view(**kwargs) -> tuple[RecordingTk, OrbView, Painted]:
    tk = RecordingTk()
    painter = Painted()
    view = OrbView(
        tkinter_module=tk,
        master=kwargs.pop("master", None),
        painter_factory=lambda _view: painter,
        thresholds=lambda: (DEFAULT_DOUBLE_CLICK_MS, DEFAULT_DRAG_SLOP),
        **kwargs,
    )
    view.show(position=kwargs.pop("position", (300, 300)), topmost=True)
    return tk, view, painter


def names(tk: RecordingTk) -> list[str]:
    return [name for name, _args, _kwargs in tk.calls]


# --- 1. the window it opens --------------------------------------------------


def test_it_is_a_toplevel_of_the_panel_when_there_is_one() -> None:
    """Measured: creating a root window takes the foreground, creating a
    Toplevel does not. So the orb must never be the second root."""
    tk, _view, _painter = a_view(master=object())

    assert "Toplevel" in names(tk)
    assert "Tk" not in names(tk)


def test_the_master_may_be_a_callable_because_the_panel_has_no_window_yet() -> None:
    """The orb is built before the panel is shown, so the controller can hold
    both. A plain reference would capture None."""
    panel_root = object()
    tk = RecordingTk()
    view = OrbView(
        tkinter_module=tk,
        master=lambda: panel_root,
        painter_factory=lambda _v: Painted(),
        thresholds=lambda: (500, 4),
    )
    view.show(position=(0, 0), topmost=True)

    toplevel = next(kwargs for name, _a, kwargs in tk.calls if name == "Toplevel")
    assert toplevel["master"] is panel_root


def test_it_is_borderless_and_on_top() -> None:
    tk, _view, _painter = a_view()
    called = names(tk)

    assert "toplevel.overrideredirect" in called or "root.overrideredirect" in called
    assert any(
        args == ("-topmost", True)
        for name, args, _k in tk.calls
        if name.endswith(".attributes")
    )


@pytest.mark.parametrize("forbidden", FOCUS_STEALING_CALLS)
def test_the_orb_never_takes_focus(forbidden: str) -> None:
    """Every constraint that has held for the panel holds for the orb. Checked
    per call so a failure names which one appeared."""
    tk, view, _painter = a_view()
    view.set_state("recording")
    view.set_level(0.8)
    view.move_to(500, 400)
    tk.run_due()

    offenders = [name for name in names(tk) if name.endswith(f".{forbidden}")]

    assert offenders == [], f"{forbidden} would move focus to the orb; {offenders}"


def test_the_orb_is_out_of_the_tab_order() -> None:
    """Otherwise it can acquire focus by being tabbed into."""
    tk, _view, _painter = a_view()

    labels = [kwargs for name, _a, kwargs in tk.calls if name == "Label"]

    assert labels, "no Label was created"
    assert labels[0].get("takefocus") is False


def test_it_paints_as_soon_as_it_is_shown() -> None:
    """Nothing blank: a window that appears and then waits for a state change
    is an empty rectangle for however long that takes."""
    _tk, _view, painter = a_view()

    assert len(painter.frames) == 1


def test_the_painter_is_given_a_handle_it_can_re_read() -> None:
    """A regression guard with a measured cause: the window tk hands back
    during setup is not the one it ends up showing, and a captured handle
    silently paints into nothing while reporting success."""
    from grandpa.ui.layered import LayeredPainter

    tk = RecordingTk()
    view = OrbView(tkinter_module=tk, thresholds=lambda: (500, 4))
    view.show(position=(0, 0), topmost=True)
    primary = view.painter.primary

    assert isinstance(primary, LayeredPainter)
    assert callable(primary.hwnd), "the handle was captured rather than resolvable"


def test_the_window_is_realised_before_its_handle_is_asked_for() -> None:
    """update_idletasks is what makes the handle the real one."""
    tk, _view, _painter = a_view()

    called = names(tk)
    assert any(name.endswith(".update_idletasks") for name in called)


# --- 2. the mouse ------------------------------------------------------------


def a_clickable_view(**kwargs):
    """A view whose press lands on the orb unless the test says otherwise."""
    tk = RecordingTk()
    view = OrbView(
        tkinter_module=tk,
        painter_factory=lambda _v: Painted(),
        thresholds=lambda: (500, 4),
        **kwargs,
    )
    view.show(position=(0, 0), topmost=True)
    view.tracker.clock = lambda: 1.0
    return tk, view


def on_the_orb(**kwargs) -> Event:
    """An event at the centre of the window, which is inside the ring."""
    from grandpa.ui.orb_image import ORB_SIZE

    middle = (ORB_SIZE - 1) // 2
    return Event(x=middle, y=middle, **kwargs)


def test_a_single_click_toggles() -> None:
    """One click, not two. The decision is on release, where a drag is already
    known, so there is nothing to undo."""
    toggled: list[int] = []
    tk, view = a_clickable_view(on_toggle=lambda: toggled.append(1))

    tk.handlers["<ButtonPress-1>"](on_the_orb(x_root=100, y_root=100))
    tk.handlers["<ButtonRelease-1>"](on_the_orb(x_root=100, y_root=100))

    assert toggled == [1]


def test_a_click_on_the_transparent_corner_is_ignored() -> None:
    """The cost of moving from a double-tap to a single click, and the fix.
    Most of the window is see-through; a stray click there must not expand the
    panel."""
    toggled: list[int] = []
    tk, view = a_clickable_view(on_toggle=lambda: toggled.append(1))

    tk.handlers["<ButtonPress-1>"](Event(x=0, y=0, x_root=100, y_root=100))
    tk.handlers["<ButtonRelease-1>"](Event(x=0, y=0, x_root=100, y_root=100))

    assert toggled == []


def test_a_press_that_moves_on_the_fifth_pixel_never_counts_as_a_click() -> None:
    """The case worth naming: slop is 4px, so five pixels is a drag, and the
    tracker knows it before the button comes up."""
    toggled: list[int] = []
    moved: list[tuple[int, int]] = []
    tk, view = a_clickable_view(
        on_toggle=lambda: toggled.append(1),
        on_drag=lambda dx, dy: moved.append((dx, dy)),
    )

    tk.handlers["<ButtonPress-1>"](on_the_orb(x_root=200, y_root=200))
    tk.handlers["<B1-Motion>"](on_the_orb(x_root=205, y_root=200))
    tk.handlers["<ButtonRelease-1>"](on_the_orb(x_root=205, y_root=200))

    assert toggled == []
    assert moved == [(5, 0)]


def test_a_press_that_wanders_within_the_slop_is_still_a_click() -> None:
    toggled: list[int] = []
    moved: list[tuple[int, int]] = []
    tk, view = a_clickable_view(
        on_toggle=lambda: toggled.append(1),
        on_drag=lambda dx, dy: moved.append((dx, dy)),
    )

    tk.handlers["<ButtonPress-1>"](on_the_orb(x_root=200, y_root=200))
    tk.handlers["<B1-Motion>"](on_the_orb(x_root=203, y_root=202))
    tk.handlers["<ButtonRelease-1>"](on_the_orb(x_root=203, y_root=202))

    assert toggled == [1]
    assert moved == []


def test_a_drag_never_toggles() -> None:
    """The gesture that moved the orb must not also open the panel."""
    clock = [0.0]
    toggled: list[int] = []
    moved: list[tuple[int, int]] = []
    tk = RecordingTk()
    view = OrbView(
        tkinter_module=tk,
        painter_factory=lambda _v: Painted(),
        thresholds=lambda: (500, 4),
        on_toggle=lambda: toggled.append(1),
        on_move=lambda x, y: moved.append((x, y)),
    )
    view.show(position=(0, 0), topmost=True)
    view.tracker.clock = lambda: clock[0]

    press = tk.handlers["<ButtonPress-1>"]
    motion = tk.handlers["<B1-Motion>"]
    release = tk.handlers["<ButtonRelease-1>"]
    for index in range(2):
        clock[0] = index * 0.2
        press(Event(x=5, y=5, x_root=200, y_root=200))
        motion(Event(x=5, y=5, x_root=240, y_root=230))
        release(Event(x=5, y=5, x_root=240, y_root=230))

    assert toggled == []
    assert moved, "the drag did not move the orb"
    assert moved[-1] == (235, 225)


def test_a_tap_that_wandered_and_came_back_is_still_a_drag() -> None:
    """The maximum distance counts, not the final one: it moved the orb."""
    tracker = TapTracker(double_click_ms=500, drag_slop=4, clock=lambda: 1.0)
    tracker.press(100, 100)
    tracker.motion(112, 100)
    tracker.motion(100, 100)

    assert tracker.release() == "drag"


def test_a_press_inside_the_slop_is_a_tap_not_a_drag() -> None:
    """Otherwise a jittery hand can never tap at all, and every tap nudges the
    orb a pixel."""
    moved: list = []
    tk = RecordingTk()
    view = OrbView(
        tkinter_module=tk,
        painter_factory=lambda _v: Painted(),
        thresholds=lambda: (500, 4),
        on_move=lambda x, y: moved.append((x, y)),
    )
    view.show(position=(50, 50), topmost=True)

    tk.handlers["<ButtonPress-1>"](Event(x_root=200, y_root=200))
    tk.handlers["<B1-Motion>"](Event(x_root=203, y_root=202))

    assert moved == []
    assert view.position() == (50, 50)


def test_two_slow_taps_are_two_taps() -> None:
    clock = [0.0]
    tracker = TapTracker(double_click_ms=500, drag_slop=4, clock=lambda: clock[0])
    tracker.press(10, 10)
    assert tracker.release() == "tap"
    clock[0] = 2.0
    tracker.press(10, 10)

    assert tracker.release() == "tap"


def test_a_clock_that_starts_at_zero_does_not_swallow_the_first_tap() -> None:
    """A 0.0 sentinel made the first tap look like no tap, so the second
    started the pair instead of completing it. Real monotonic time is never 0,
    which is exactly how this would have survived."""
    clock = [0.0]
    tracker = TapTracker(double_click_ms=500, drag_slop=4, clock=lambda: clock[0])
    tracker.press(0, 0)
    tracker.release()
    clock[0] = 0.1
    tracker.press(0, 0)

    assert tracker.release() == "double"


def test_a_toggle_that_raises_does_not_kill_the_window() -> None:
    tk = RecordingTk()
    view = OrbView(
        tkinter_module=tk,
        painter_factory=lambda _v: Painted(),
        thresholds=lambda: (500, 4),
        on_toggle=lambda: 1 / 0,
    )
    view.show(position=(0, 0), topmost=True)
    view.tracker.clock = lambda: 1.0

    tk.handlers["<ButtonPress-1>"](Event())
    tk.handlers["<ButtonRelease-1>"](Event())
    tk.handlers["<ButtonPress-1>"](Event())
    tk.handlers["<ButtonRelease-1>"](Event())

    assert view.root is not None


def test_the_thresholds_come_from_windows_not_from_a_constant() -> None:
    """They are the user's own accessibility settings. Someone with a tremor
    may have raised them deliberately."""

    class Fake:
        def GetDoubleClickTime(self):  # noqa: N802 - mirrors Win32
            return 900

        def GetSystemMetrics(self, index):  # noqa: N802 - mirrors Win32
            return 11 if index == 68 else 7

    assert system_input_thresholds(Fake()) == (900, 11)


def test_unreadable_thresholds_fall_back_rather_than_raise() -> None:
    class Broken:
        def GetDoubleClickTime(self):  # noqa: N802
            raise OSError("no user32")

        def GetSystemMetrics(self, index):  # noqa: N802
            return 0

    assert system_input_thresholds(Broken()) == (
        DEFAULT_DOUBLE_CLICK_MS, DEFAULT_DRAG_SLOP,
    )


def test_zero_thresholds_are_treated_as_unavailable() -> None:
    """Zero slop would make every tap a drag."""

    class Zeros:
        def GetDoubleClickTime(self):  # noqa: N802
            return 0

        def GetSystemMetrics(self, index):  # noqa: N802
            return 0

    assert system_input_thresholds(Zeros()) == (
        DEFAULT_DOUBLE_CLICK_MS, DEFAULT_DRAG_SLOP,
    )


# --- 3. the tick -------------------------------------------------------------


def test_an_animated_state_schedules_a_tick() -> None:
    tk, view, _painter = a_view()

    view.set_state("thinking")

    assert view.animating is True
    assert any(name.endswith(".after") for name in names(tk))


@pytest.mark.parametrize("state", ["success", "error"])
def test_a_one_shot_state_stops_ticking_once_it_has_played(state: str) -> None:
    """**The property the user asked to have pinned.** Idle breathes now, so
    "a still state cancels its tick" could have quietly stopped being true of
    anything. It is still true of these two: success ripples once and error
    flashes twice, and then each holds its final frame with no tick armed.

    This is the mechanism that stops an animation running forever for
    something nobody is looking at, and it needs at least one state to keep
    exercising it."""
    from grandpa.ui.orb_image import frames_for

    tk, view, _painter = a_view()
    view.set_state(state)

    assert view.animating is True, f"{state} should play once"

    for _ in range(frames_for(state) + 4):
        tk.run_due()

    assert view.animating is False, f"{state} is still ticking"
    assert tk.scheduled == {}
    assert view._finished is True


@pytest.mark.parametrize("state", ["success", "error"])
def test_a_played_out_one_shot_does_not_restart_itself(state: str) -> None:
    """Re-entering the state it is already in must not flash again -- the
    status line refreshes often enough that it would strobe."""
    from grandpa.ui.orb_image import frames_for

    tk, view, _painter = a_view()
    view.set_state(state)
    for _ in range(frames_for(state) + 4):
        tk.run_due()

    view.set_state(state)
    view.start_animation()

    assert view.animating is False
    assert tk.scheduled == {}


def test_the_tick_is_cancelled_rather_than_left_to_re_arm() -> None:
    """The opposite of the panel's pump, deliberately. A tick that re-arms
    unconditionally is a tick that never stops."""
    from grandpa.ui.orb_image import frames_for

    tk, view, _painter = a_view()
    view.set_state("speaking")
    assert view.animating is True

    view.set_state("success")
    for _ in range(frames_for("success") + 4):
        tk.run_due()

    assert view.animating is False
    assert tk.scheduled == {}
    assert any(name.endswith(".after_cancel") for name in names(tk))


def test_a_tick_that_fires_into_a_finished_state_does_not_re_arm_itself() -> None:
    """The other half: the state can change between the schedule and the fire,
    and the fired tick must notice rather than keep the cycle alive."""
    tk, view, _painter = a_view()
    view.set_state("thinking")
    # Finished without going through set_state, as a race would leave it.
    view._finished = True

    tk.run_due()

    assert view.animating is False
    assert tk.scheduled == {}


def test_each_tick_advances_the_cycle_and_repaints() -> None:
    tk, view, painter = a_view()
    view.set_state("speaking")
    before = len(painter.frames)

    tk.run_due()
    tk.run_due()

    assert len(painter.frames) >= before + 2


def test_the_cycle_wraps_rather_than_counting_forever() -> None:
    from grandpa.ui.orb_image import frames_for

    tk, view, _painter = a_view()
    view.set_state("speaking")
    frames = frames_for("speaking")
    for _ in range(frames + 3):
        tk.run_due()

    assert 0 <= view._frame_index < frames


def test_starting_the_animation_twice_does_not_stack_two_timers() -> None:
    tk, view, _painter = a_view()
    view.set_state("speaking")

    view.start_animation()
    view.start_animation()

    assert len(tk.scheduled) == 1


def test_the_unread_ring_animates_even_though_idle_does_not() -> None:
    tk, view, _painter = a_view()

    view.set_state("idle", unread=True)

    assert view.animating is True
    assert len(tk.scheduled) == 1


def test_closing_cancels_the_tick() -> None:
    tk, view, _painter = a_view()
    view.set_state("speaking")

    view.close()

    assert view.animating is False
    assert tk.scheduled == {}


def test_the_tick_rate_is_the_measured_one() -> None:
    """20fps by default, against 0.28ms to blit a pre-rendered frame."""
    assert TICK_MS == 50


def test_each_state_ticks_at_its_own_measured_rate() -> None:
    """Not one rate for everything. Idle breathes at 5fps because it runs
    forever -- 0.14% of a core against 0.56% at 20 -- and the waveform runs at
    10fps because that is the rate its level history arrives, so a faster tick
    would redraw the same data."""
    tk, view, _painter = a_view()

    rates: dict[str, int] = {}
    for state in ("idle", "recording", "thinking", "speaking"):
        view.set_state(state)
        rates[state] = view.tick_ms()

    assert rates["idle"] == 200
    assert rates["recording"] == 100
    assert rates["thinking"] == 50
    assert rates["speaking"] == 50


# --- 4. the level ------------------------------------------------------------


def test_a_new_level_repaints_while_recording() -> None:
    _tk, view, painter = a_view()
    view.set_state("recording")
    before = len(painter.frames)

    view.set_level(0.7)

    assert len(painter.frames) == before + 1


def test_a_level_arriving_in_another_state_does_not_repaint() -> None:
    """The meter tick runs 16 times a second whatever the state is."""
    _tk, view, painter = a_view()
    view.set_state("idle")
    before = len(painter.frames)

    view.set_level(0.7)

    assert len(painter.frames) == before


def test_the_level_is_clamped_at_the_window_too() -> None:
    _tk, view, _painter = a_view()

    view.set_level(5.0)
    assert view.level == 1.0

    view.set_level(-1.0)
    assert view.level == 0.0


# --- 5. the fallback, through the window ------------------------------------


def test_the_fallback_gets_a_disc_and_the_glow_painter_gets_alpha() -> None:
    """Which image is built depends on which painter is live, and that
    decision lives in one place."""

    class Disc(Painted):
        name = "disc"

    _tk, view, _painter = a_view()
    view.painter = Disc()
    view.redraw()
    disc_image = view.painter.frames[-1][0]

    _tk2, view2, layered = a_view()
    view2.redraw()
    glow_image = layered.frames[-1][0]

    from grandpa.ui.orb_image import ORB_SIZE

    middle = ORB_SIZE // 2
    assert disc_image.getpixel((middle, middle))[3] == 255
    assert glow_image.getpixel((0, 0))[3] == 0


def test_the_fallback_output_is_inspectable() -> None:
    """A fallback whose output nobody can see is indistinguishable from one
    that silently shows nothing."""
    from grandpa.ui.layered import DiscPainter, LayeredPainter, PainterChoice

    tk = RecordingTk()
    view = OrbView(tkinter_module=tk, thresholds=lambda: (500, 4))
    view.painter_factory = lambda v: PainterChoice(
        primary=LayeredPainter(hwnd=1, update_layered_window=lambda *_a: 0),
        fallback=DiscPainter(show=v.show_image),
    )
    view.show(position=(70, 80), topmost=True)

    assert view.painter_mode() == "disc"
    assert view.shown_images, "the fallback produced nothing"
    assert view.shown_images[-1].size == (view.size, view.size)
    assert view.position() == (70, 80)
    assert "flat disc" in view.painter_description()


# --- 6. placing the panel beside the orb ------------------------------------


def test_the_panel_opens_to_the_right_of_the_orb_with_room_to_spare() -> None:
    assert anchor_panel_to_orb((100, 100), PANEL, area=AREA) == (
        100 + ORB + ANCHOR_GAP, 100,
    )


@pytest.mark.parametrize(
    "orb_at",
    [(0, 0), (1824, 0), (0, 984), (1824, 984), (912, 492), (40, 40), (1800, 980)],
)
def test_the_panel_always_lands_inside_the_work_area(orb_at) -> None:
    """Checked at every corner. Each axis flips to the other side of the orb
    rather than hanging off the screen."""
    x, y = anchor_panel_to_orb(orb_at, PANEL, area=AREA)

    assert AREA[0] <= x
    assert x + PANEL[0] <= AREA[2]
    assert AREA[1] <= y
    assert y + PANEL[1] <= AREA[3]


def test_the_panel_flips_to_the_left_at_the_right_edge() -> None:
    orb_at = (1800, 100)

    x, _y = anchor_panel_to_orb(orb_at, PANEL, area=AREA)

    assert x + PANEL[0] + ANCHOR_GAP <= orb_at[0] + 1, "it did not flip"


def test_the_panel_flips_upward_at_the_bottom_edge() -> None:
    _x, y = anchor_panel_to_orb((100, 1000), PANEL, area=AREA)

    assert y < 1000
    assert y + PANEL[1] <= AREA[3]


def test_a_panel_too_big_for_the_work_area_is_clamped_not_lost() -> None:
    """Clamping never fired at 1920x1080, but a 1024x768 screen with a huge
    panel must still put it somewhere on screen."""
    x, y = anchor_panel_to_orb((500, 500), (2000, 2000), area=AREA)

    assert (x, y) == (0, 0)


def test_the_work_area_is_the_screen_minus_the_taskbar() -> None:
    """Against the full screen the panel opens under the taskbar."""
    left, top, right, bottom = work_area()

    assert right > left
    assert bottom > top


def test_an_unreadable_work_area_falls_back_rather_than_raising() -> None:
    class Broken:
        def SystemParametersInfoW(self, *_args):  # noqa: N802 - mirrors Win32
            return 0

    from grandpa.ui.orb_view import DEFAULT_WORK_AREA

    assert work_area(Broken()) == DEFAULT_WORK_AREA


# --- 7. the panel's own half of collapsing ----------------------------------


def test_the_panel_hides_by_withdrawing_not_by_destroying() -> None:
    """Destroying it would lose the last exchange and rebuilding it would take
    the foreground again."""
    from tests.ui.test_bubble_never_takes_focus import RecordingTk as PanelTk

    from grandpa.ui.tk_view import TkBubbleView

    tk = PanelTk()
    view = TkBubbleView(tkinter_module=tk)
    view.show(position=(40, 40), topmost=True)
    view.set_reply("the answer")

    assert view.hide() is True
    assert view.hidden is True

    called = [name for name, _a, _k in tk.calls]
    assert "root.withdraw" in called
    assert "root.destroy" not in called


def test_the_panel_comes_back_with_deiconify_and_nothing_stronger() -> None:
    from tests.ui.test_bubble_never_takes_focus import RecordingTk as PanelTk

    from grandpa.ui.tk_view import TkBubbleView

    tk = PanelTk()
    view = TkBubbleView(tkinter_module=tk)
    view.show(position=(40, 40), topmost=True)
    view.hide()

    assert view.unhide() is True
    assert view.hidden is False

    called = [name for name, _a, _k in tk.calls]
    assert "root.deiconify" in called
    for forbidden in FOCUS_STEALING_CALLS:
        assert f"root.{forbidden}" not in called


def test_remapping_a_window_is_confined_to_the_method_that_undoes_a_hide() -> None:
    """``deiconify`` is only safe as the undo of a withdraw -- measured. Used to
    raise an already-visible window it is ``lift`` by another name, so it is
    pinned to one method here.

    Inspected as a syntax tree rather than as text, because a test that
    forbids a word its own explanation uses forbids itself.
    """
    source = Path("src/grandpa/ui/tk_view.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    allowed = {"withdraw": "hide", "deiconify": "unhide"}
    found: dict[str, set[str]] = {call: set() for call in REMAP_CALLS}
    for function in ast.walk(tree):
        if not isinstance(function, ast.FunctionDef):
            continue
        for node in ast.walk(function):
            if isinstance(node, ast.Attribute) and node.attr in found:
                found[node.attr].add(function.name)

    for call, holders in found.items():
        assert holders == {allowed[call]}, f"{call} is used in {holders}"


def test_the_panel_survives_being_asked_to_hide_before_it_exists() -> None:
    from grandpa.ui.tk_view import TkBubbleView

    view = TkBubbleView(tkinter_module=RecordingTk())

    assert view.hide() is False
    assert view.unhide() is False


def test_creating_a_window_taking_the_foreground_is_recorded_not_hidden() -> None:
    """The one hole in the promise, and the recorded-call tests cannot see it.
    Stated in the module so the next person reads it rather than measuring it
    again."""
    from grandpa.ui.tk_view import CREATION_TAKES_FOREGROUND

    assert CREATION_TAKES_FOREGROUND is True
