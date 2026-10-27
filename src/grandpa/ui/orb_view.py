"""The orb's window: it owns the rectangle and the mouse, not the pixels.

tk cannot paint a glow -- measured in the survey -- so this holds a borderless
always-on-top window and hands its handle to a painter. What tk still does well
is windows and events, which is all that is asked of it here.

Two measurements shaped this file rather than reasoning about it:

* **The orb is a Toplevel of the panel's root, not a second ``Tk()``.** Creating
  a root window *does* take the foreground -- measured: the foreground window
  became the new window's own handle -- while creating a ``Toplevel`` does not.
  So the orb adds no new focus theft to the one the panel already performs at
  startup, and both windows are built once at startup rather than per toggle.
* **The panel's root can be withdrawn while this stays up**, and this window's
  ``after`` tick keeps firing with the root withdrawn. That is what makes
  collapsed mode possible without destroying and rebuilding the panel, which
  would lose the last exchange and take the foreground again.

Everything the panel promised holds here too. Nothing in this file calls
``focus_force``, ``focus_set``, ``grab_set``, ``lift`` or ``tkraise``, and the
label is out of the tab order: the orb floats over whatever is being worked in
and must never take the caret.

The animation tick **cancels** rather than re-arms. That is the opposite of the
panel's ``pump`` and it is deliberate: the survey measured a 20fps pulse at 0.6%
of a core, which is nothing for a moment and absurd forever for a thing nobody
is looking at. A still orb is blitted once and composited by Windows with no
further work from this process.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from grandpa.ui.orb_image import (
    HIT_RADIUS,
    LEVEL_BUCKETS,
    ORB_SIZE,
    fps_for,
    is_on_orb,
    visible_inset,
    frames_for,
    is_animated,
    is_live,
    is_oneshot,
    orb_image,
    orb_on_disc,
)

#: Frames in one cycle when a state does not say otherwise. Each state does
#: say otherwise -- see ``orb_image.ORB_STYLES`` -- because a breathe that runs
#: forever and an arc somebody is waiting on do not want the same rate.
PULSE_FRAMES = 24

#: The default tick, 20fps. Measured at 0.56% of one core for a pre-generated
#: frame at 0.28ms a blit. Per-state rates come from ``fps_for``: idle breathes
#: at 5fps for 0.14%, and the waveform runs at 10fps because that is the rate
#: its data arrives -- 20fps would redraw the same level history twice.
TICK_MS = 50

#: Fallbacks for the Windows metrics, used only when they cannot be read. The
#: real values come from the system because they are the user's own
#: accessibility settings -- someone with a tremor may have raised them.
DEFAULT_DOUBLE_CLICK_MS = 500
DEFAULT_DRAG_SLOP = 4

#: SM_CXDRAG / SM_CYDRAG: how far the mouse may move before Windows itself
#: calls it a drag rather than a click.
SM_CXDRAG = 68
SM_CYDRAG = 69

#: What shows if every painter fails outright. Matches the panel.
ORB_WINDOW_BACKGROUND = "#17181b"


def system_input_thresholds(user32: Any = None) -> tuple[int, int]:
    """``(double_click_ms, drag_slop_px)`` from Windows, or the defaults."""
    try:
        if user32 is None:
            import ctypes

            user32 = ctypes.windll.user32
        double_click = int(user32.GetDoubleClickTime())
        slop = max(
            int(user32.GetSystemMetrics(SM_CXDRAG)),
            int(user32.GetSystemMetrics(SM_CYDRAG)),
        )
        return (
            double_click if double_click > 0 else DEFAULT_DOUBLE_CLICK_MS,
            slop if slop > 0 else DEFAULT_DRAG_SLOP,
        )
    except Exception:  # noqa: BLE001 - not Windows, or no user32
        return DEFAULT_DOUBLE_CLICK_MS, DEFAULT_DRAG_SLOP


#: SPI_GETWORKAREA: the screen minus the taskbar. The panel is placed against
#: this, not against the full screen, or it opens under the taskbar.
SPI_GETWORKAREA = 0x0030

#: Gap between the orb and the panel when the panel opens beside it.
ANCHOR_GAP = 12

#: Used only when the work area cannot be read. 1920x1080 is this machine's.
DEFAULT_WORK_AREA = (0, 0, 1920, 1080)


def work_area(user32: Any = None) -> tuple[int, int, int, int]:
    """``(left, top, right, bottom)`` of the usable desktop."""
    try:
        import ctypes
        import ctypes.wintypes as wt

        if user32 is None:
            user32 = ctypes.windll.user32
        rect = wt.RECT()
        ok = user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rect), 0)
        if not ok:
            return DEFAULT_WORK_AREA
        return int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)
    except Exception:  # noqa: BLE001 - not Windows
        return DEFAULT_WORK_AREA


#: MonitorFromPoint's "nearest monitor" flag, and the size of MONITORINFO.
MONITOR_DEFAULTTONEAREST = 0x00000002


def work_area_for(
    point: tuple[int, int], user32: Any = None
) -> tuple[int, int, int, int]:
    """The work area of the monitor containing *point*, or the primary one.

    SPI_GETWORKAREA answers for the primary display only, which on a
    multi-monitor desktop would clamp the orb back onto the main screen the
    moment it was dragged to a second one -- stranded rather than reachable.
    MonitorFromPoint answers for the display it is actually on, and
    DEFAULTTONEAREST means a point already off every screen resolves to the
    closest monitor rather than failing, which is how an orb that somehow got
    out comes back.
    """
    try:
        import ctypes
        import ctypes.wintypes as wt

        if user32 is None:
            user32 = ctypes.windll.user32

        class MONITORINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", wt.DWORD),
                ("rcMonitor", wt.RECT),
                ("rcWork", wt.RECT),
                ("dwFlags", wt.DWORD),
            ]

        class POINT(ctypes.Structure):
            _fields_ = [("x", wt.LONG), ("y", wt.LONG)]

        user32.MonitorFromPoint.argtypes = [POINT, wt.DWORD]
        user32.MonitorFromPoint.restype = wt.HANDLE
        monitor = user32.MonitorFromPoint(
            POINT(int(point[0]), int(point[1])), MONITOR_DEFAULTTONEAREST
        )
        if not monitor:
            return work_area(user32)
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            return work_area(user32)
        rect = info.rcWork
        if rect.right <= rect.left or rect.bottom <= rect.top:
            return work_area(user32)
        return int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)
    except Exception:  # noqa: BLE001 - not Windows, or no multi-monitor API
        return work_area(user32)


def clamp_orb_position(
    x: int,
    y: int,
    *,
    size: int = ORB_SIZE,
    area: tuple[int, int, int, int] | None = None,
) -> tuple[int, int]:
    """Keep the orb's visible ring inside the work area.

    The window may overhang by its own transparent padding -- see
    ``visible_inset`` -- so the ring can sit snugly in a corner rather than
    stopping short of it. A pure function of four numbers, so every edge and
    every corner can be asserted without a screen.
    """
    left, top, right, bottom = (
        area if area is not None else work_area_for((int(x), int(y)))
    )
    import math

    inset = visible_inset(size)
    # Rounded outward to whole pixels BEFORE clamping, not after. Rounding the
    # result instead let it land half a pixel past the edge, which is invisible
    # and still makes the bound a lie -- and a test asserting the bound then
    # needs a tolerance, which is a test that has stopped checking the thing.
    lowest_x = math.ceil(left - inset)
    highest_x = math.floor(right - size + inset)
    lowest_y = math.ceil(top - inset)
    highest_y = math.floor(bottom - size + inset)
    # A work area narrower than the visible ring would invert the bounds; centre
    # it rather than returning something arbitrary.
    if highest_x < lowest_x:
        lowest_x = highest_x = round((left + right - size) / 2.0)
    if highest_y < lowest_y:
        lowest_y = highest_y = round((top + bottom - size) / 2.0)
    return (
        int(min(max(int(x), lowest_x), highest_x)),
        int(min(max(int(y), lowest_y), highest_y)),
    )


def anchor_panel_to_orb(
    orb_position: tuple[int, int],
    panel_size: tuple[int, int],
    *,
    orb_size: int = ORB_SIZE,
    area: tuple[int, int, int, int] | None = None,
    gap: int = ANCHOR_GAP,
) -> tuple[int, int]:
    """Where the panel goes when it expands beside the orb.

    A pure function of four rectangles, so the placement can be asserted at
    every corner without a screen. Preference is right of the orb and
    top-aligned with it; each axis **flips** to the other side of the orb if the
    preferred side would leave the work area, and only clamps if neither side
    fits -- which, measured at 1920x1080, never happens.
    """
    left, top, right, bottom = area if area is not None else work_area()
    width, height = int(panel_size[0]), int(panel_size[1])
    orb_x, orb_y = int(orb_position[0]), int(orb_position[1])

    x = orb_x + orb_size + gap
    if x + width > right:
        x = orb_x - gap - width  # flip to the orb's left
    x = max(left, min(x, right - width))

    y = orb_y
    if y + height > bottom:
        y = orb_y + orb_size - height  # flip to hang upward from the orb
    y = max(top, min(y, bottom - height))
    return int(x), int(y)


@dataclass
class TapTracker:
    """Tells a tap from a drag, and a double-tap from two separate taps.

    The rule, and why each half of it:

    * a press that never moves beyond the drag slop is a **tap**; one that does
      is a **drag**, and the orb has already moved by then.
    * the *maximum* distance from the press point is what counts, not the final
      one. Moving six pixels and coming back is still a drag -- it moved the orb,
      and a gesture that moved the orb must never also toggle the panel.
    * a drag discards any pending first tap, so drag-then-tap is not a double.
    """

    double_click_ms: int = DEFAULT_DOUBLE_CLICK_MS
    drag_slop: int = DEFAULT_DRAG_SLOP
    clock: Any = None

    _press: tuple[int, int] | None = field(default=None, init=False)
    _max_distance: float = field(default=0.0, init=False)
    #: None, not 0.0: a monotonic clock that happens to start at zero would
    #: make the first tap look like no tap at all, and the second tap then
    #: starts the pair instead of completing it. Real time.monotonic() is
    #: never 0, which is exactly why this would have survived to a test with
    #: an injected clock and no further.
    _last_tap_at: float | None = field(default=None, init=False)
    dragging: bool = field(default=False, init=False)

    def _now(self) -> float:
        if self.clock is not None:
            return float(self.clock())
        import time

        return time.monotonic()

    def press(self, x: int, y: int) -> None:
        self._press = (int(x), int(y))
        self._max_distance = 0.0
        self.dragging = False

    def motion(self, x: int, y: int) -> bool:
        """True once this has become a drag."""
        if self._press is None:
            return False
        dx = int(x) - self._press[0]
        dy = int(y) - self._press[1]
        self._max_distance = max(self._max_distance, max(abs(dx), abs(dy)))
        if self._max_distance > self.drag_slop:
            self.dragging = True
        return self.dragging

    def release(self) -> str:
        """``"drag"``, ``"tap"`` or ``"double"``."""
        was_dragging = self.dragging
        self._press = None
        self.dragging = False
        if was_dragging:
            self._last_tap_at = None
            return "drag"
        now = self._now()
        if (
            self._last_tap_at is not None
            and (now - self._last_tap_at) * 1000.0 <= self.double_click_ms
        ):
            self._last_tap_at = None
            return "double"
        self._last_tap_at = now
        return "tap"


@dataclass
class OrbView:
    """A borderless always-on-top window showing the orb.

    ``tkinter_module`` is the injection point, as in the panel: tests pass a
    recorder and nothing opens. ``master`` is the panel's root -- given one,
    this is a ``Toplevel`` of it, which is what keeps it from taking the
    foreground when it appears.
    """

    tkinter_module: Any = None
    #: The panel's root, or a callable returning it. A callable because the
    #: panel's window does not exist until it is shown, and the orb is built
    #: before that so the controller can hold both.
    master: Any = None
    size: int = ORB_SIZE
    #: Called with no arguments when the orb is clicked once, on release, and
    #: only when the press landed on the orb itself rather than on the
    #: transparent part of its window.
    on_toggle: Any = None
    #: Called with ``(dx, dy)`` as the orb is dragged. A delta rather than a
    #: position, because the controller owns where things are: the orb and the
    #: panel are one component and a drag moves the pair.
    on_drag: Any = None
    #: Called with ``(x, y)`` as the orb is dragged, for a caller that wants the
    #: position rather than the delta. Both fire; neither is required.
    on_move: Any = None
    #: Called when Escape is pressed with the orb focused -- the same way the
    #: panel closes. It only arrives if the orb was clicked first, because the
    #: window never takes focus on its own.
    on_close: Any = None
    #: Builds the painter for this view. Injected so a test can supply one that
    #: refuses, and watch the fallback engage.
    painter_factory: Any = None
    #: Reads the input thresholds. Injected for the same reason.
    thresholds: Any = None

    root: Any = field(default=None, init=False)
    painter: Any = field(default=None, init=False)
    tracker: Any = field(default=None, init=False)
    orb_position: tuple[int, int] = field(default=(40, 40), init=False)
    state: str = field(default="loading", init=False)
    unread: bool = field(default=False, init=False)
    level: float = field(default=0.0, init=False)
    #: The level history, oldest first, as the waveform needs it. One number
    #: cannot describe a shape around a circle.
    levels: tuple[float, ...] = field(
        default_factory=lambda: (0.0,) * LEVEL_BUCKETS, init=False
    )
    #: Images the fallback produced, newest last. Carried so a test can prove
    #: the fallback yields a usable orb rather than merely not raising.
    shown_images: list[Any] = field(default_factory=list, init=False)

    _label: Any = field(default=None, init=False)
    _photo: Any = field(default=None, init=False)
    _frame_index: int = field(default=0, init=False)
    _tick_id: Any = field(default=None, init=False)
    _grab_offset: tuple[int, int] = field(default=(0, 0), init=False)
    #: Frames already built for the current look, by index. Built on demand so
    #: entering a state does not stall for a whole cycle, and cleared when the
    #: look changes so only one state's frames are ever held.
    _frames: dict[int, Any] = field(default_factory=dict, init=False)
    _frames_key: Any = field(default=None, init=False)
    #: True once a one-shot animation has played, so its last frame holds.
    _finished: bool = field(default=False, init=False)
    #: Whether the press that is in progress began on the orb. A press that
    #: started in a transparent corner may still drag -- the whole window is
    #: the handle -- but it may not count as a click.
    _pressed_on_orb: bool = field(default=False, init=False)
    #: Where the pointer was at the last motion, so a drag can report a delta.
    _last_pointer: tuple[int, int] = field(default=(0, 0), init=False)

    def _tk(self) -> Any:
        if self.tkinter_module is None:
            import tkinter

            self.tkinter_module = tkinter
        return self.tkinter_module

    # --- lifecycle -----------------------------------------------------------

    def show(self, *, position: tuple[int, int], topmost: bool = True) -> None:
        tk = self._tk()
        master = self.master() if callable(self.master) else self.master
        # A Toplevel when there is a panel to hang off, which is the measured
        # difference between appearing quietly and taking the foreground.
        root = tk.Toplevel(master=master) if master is not None else tk.Tk()
        self.root = root
        self.orb_position = (int(position[0]), int(position[1]))
        root.overrideredirect(True)
        if topmost:
            root.attributes("-topmost", True)
        root.geometry(
            f"{self.size}x{self.size}+{self.orb_position[0]}+{self.orb_position[1]}"
        )
        root.configure(bg=ORB_WINDOW_BACKGROUND)

        # The fallback painter needs somewhere to put an image; the layered
        # painter replaces the whole window surface and ignores this.
        self._label = tk.Label(
            root, bd=0, highlightthickness=0, bg=ORB_WINDOW_BACKGROUND,
            takefocus=False,
        )
        self._label.pack(fill="both", expand=True)

        double_click_ms, slop = (
            self.thresholds() if callable(self.thresholds) else system_input_thresholds()
        )
        self.tracker = TapTracker(double_click_ms=double_click_ms, drag_slop=slop)

        # Realise the window before anything asks for its handle, so the one
        # that gets the layered style is the one that will be on screen.
        try:
            root.update_idletasks()
        except Exception:  # noqa: BLE001 - a recorder has no event loop
            pass

        for widget in (root, self._label):
            widget.bind("<ButtonPress-1>", self._on_press)
            widget.bind("<B1-Motion>", self._on_motion)
            widget.bind("<ButtonRelease-1>", self._on_release)
        root.bind("<Escape>", self._on_escape)

        self.painter = self._build_painter()
        self.redraw()

    def _build_painter(self) -> Any:
        """The painter, with its fallback already in hand -- not after it fails."""
        from grandpa.ui.layered import DiscPainter, LayeredPainter, PainterChoice

        if callable(self.painter_factory):
            return self.painter_factory(self)

        # The handle is passed as a callable, not a number: tk re-creates a
        # borderless toplevel's window when it maps it, and a handle captured
        # here is stale before the first frame -- while the blit to it still
        # reports success. Measured, not guessed.
        layered = LayeredPainter(hwnd=self.window_handle)
        return PainterChoice(primary=layered, fallback=DiscPainter(show=self.show_image))

    def window_handle(self) -> int:
        """The toplevel handle. ``winfo_id`` gives tk's child window."""
        try:
            import ctypes

            child = self.root.winfo_id()
            user32 = ctypes.windll.user32
            user32.GetParent.argtypes = [ctypes.c_void_p]
            user32.GetParent.restype = ctypes.c_void_p
            return int(user32.GetParent(child) or child)
        except Exception:  # noqa: BLE001 - not Windows
            try:
                return int(self.root.winfo_id())
            except Exception:  # noqa: BLE001
                return 0

    def show_image(self, image: Any, x: int, y: int) -> None:
        """The fallback's output: an ordinary tk image in a Label.

        Kept public and recorded in ``shown_images`` because this is the
        fallback's only visible effect, and a fallback whose output nobody can
        inspect is indistinguishable from one that silently shows nothing.
        """
        self.shown_images.append(image)
        self.move_window(int(x), int(y))
        photo = self._photo_for(image)
        if photo is None:
            return
        self._photo = photo  # held, or tk discards it
        if self._label is not None:
            self._label.configure(image=photo)

    def _photo_for(self, image: Any) -> Any:
        """An image tk will display. PIL's own bridge if it is there."""
        try:
            from PIL import ImageTk

            return ImageTk.PhotoImage(image.convert("RGB"), master=self.root)
        except Exception:  # noqa: BLE001 - no ImageTk, or no display
            return self._photo_by_rows(image)

    def _photo_by_rows(self, image: Any) -> Any:
        """The ImageTk-free path: build the bitmap a row at a time."""
        try:
            tk = self._tk()
            flat = image.convert("RGB")
            width, height = flat.size
            pixels = flat.load()
            photo = tk.PhotoImage(master=self.root, width=width, height=height)
            for y in range(height):
                row = " ".join("#%02x%02x%02x" % pixels[x, y] for x in range(width))
                photo.put("{" + row + "}", to=(0, y))
            return photo
        except Exception:  # noqa: BLE001
            return None

    def close(self) -> None:
        self.stop_animation()
        if self.root is not None:
            try:
                self.root.destroy()
            except Exception:  # noqa: BLE001
                pass
            self.root = None

    # --- drawing -------------------------------------------------------------

    def set_state(self, state: str, *, unread: bool = False) -> None:
        """What the ring shows. Starts or stops the tick to match.

        Re-entering the same state does not restart its animation -- a
        one-shot would otherwise flash again every time the status line
        refreshed.
        """
        if str(state) == self.state and bool(unread) == self.unread:
            self.redraw()
            return
        self.state = str(state)
        self.unread = bool(unread)
        self._frame_index = 0
        self._finished = False
        # Cancel first, always. Each state ticks at its own rate now, so
        # leaving the previous timer armed would run the new state at the old
        # state's rate -- an idle breathe at the speaking rate, four times the
        # cost it was measured at -- and start_animation() returns early while
        # a timer exists, so it would never have corrected itself.
        self.stop_animation()
        self.redraw()
        if is_animated(self.state, unread=self.unread):
            self.start_animation()

    def set_level(self, level: float) -> None:
        """The live microphone level, 0..1 -- the same number the panel's meter
        consumes, so the orb answers "is it hearing me" with no panel to look at."""
        self.level = min(1.0, max(0.0, float(level)))
        if self.state == "recording":
            self.redraw()

    def set_levels(self, levels: Any) -> None:
        """The level history the waveform is drawn from, oldest first.

        Stored rather than drawn immediately: the tick is what decides when a
        frame is painted, and the history arrives faster than that in bursts.
        """
        try:
            values = tuple(
                min(1.0, max(0.0, float(value))) for value in levels
            )
        except Exception:  # noqa: BLE001 - a bad reading must not kill the UI
            return
        if values:
            self.levels = values

    def _build(self, phase: float) -> Any:
        """The orb for one phase, in the form the active painter can use.

        The fallback needs an opaque disc; the layered painter needs the alpha.
        Asking the painter which it is keeps that decision in one place.
        """
        builder = orb_on_disc if self.painter_mode() == "disc" else orb_image
        return builder(
            self.state, phase, self.level, size=self.size, unread=self.unread,
            levels=self.levels,
        )

    def _image_for(self, index: int) -> Any:
        """The frame at *index*, from the cache where there is a cycle to cache.

        The waveform has no cycle: its frames depend on a level history that
        changes as new chunks arrive, so there is nothing to pre-build and it
        is drawn live. Measured at 0.466ms a frame, which is why it runs at
        10fps rather than 20 -- and 10fps is also the rate the levels arrive,
        so a faster tick would redraw the same data.
        """
        frames = frames_for(self.state, unread=self.unread)
        phase = (index % frames) / frames
        if is_live(self.state, unread=self.unread):
            return self._build(phase)

        key = (self.state, self.unread, self.painter_mode(), self.size)
        if key != self._frames_key:
            self._frames_key = key
            self._frames = {}
        slot = index % frames
        image = self._frames.get(slot)
        if image is None:
            image = self._build(phase)
            self._frames[slot] = image
        return image

    def redraw(self) -> bool:
        """Paint the current frame. False if no painter could."""
        if self.painter is None:
            return False
        image = self._image_for(self._frame_index)
        return bool(
            self.painter.paint(image, self.orb_position[0], self.orb_position[1])
        )

    def painter_mode(self) -> str:
        return str(getattr(self.painter, "mode", "none"))

    def painter_description(self) -> str:
        """What the status line says, so a machine on the fallback is visible."""
        describe = getattr(self.painter, "describe", None)
        return describe() if callable(describe) else ""

    # --- the tick, which cancels rather than re-arms -------------------------

    def start_animation(self) -> None:
        if self.root is None or self._tick_id is not None or self._finished:
            return
        self._schedule()

    def tick_ms(self) -> int:
        """The interval for the current state, from its own frame rate."""
        fps = fps_for(self.state, unread=self.unread)
        return max(1, int(round(1000.0 / fps))) if fps > 0 else TICK_MS

    def _schedule(self) -> None:
        try:
            self._tick_id = self.root.after(self.tick_ms(), self._tick)
        except Exception:  # noqa: BLE001 - a closed window has no loop
            self._tick_id = None

    def _tick(self) -> None:
        self._tick_id = None
        frames = frames_for(self.state, unread=self.unread)
        last = self._frame_index + 1 >= frames
        if last and is_oneshot(self.state, unread=self.unread):
            # One ripple, two flashes: play the cycle once and hold the final
            # frame. Holding it is what makes success and error resting states
            # rather than loops, and it is why the tick can still cancel.
            self._frame_index = frames - 1
            self._finished = True
            self.redraw()
            return
        self._frame_index = (self._frame_index + 1) % frames
        self.redraw()
        # Re-armed only while the state still wants it. This is what keeps an
        # animation from running forever for a thing nobody is looking at.
        if is_animated(self.state, unread=self.unread) and not self._finished:
            self._schedule()

    def stop_animation(self) -> None:
        tick_id, self._tick_id = self._tick_id, None
        if tick_id is None or self.root is None:
            return
        try:
            self.root.after_cancel(tick_id)
        except Exception:  # noqa: BLE001
            pass

    @property
    def animating(self) -> bool:
        return self._tick_id is not None

    # --- the mouse -----------------------------------------------------------

    def _on_press(self, event: Any) -> None:
        self._grab_offset = (int(getattr(event, "x", 0)), int(getattr(event, "y", 0)))
        self._pressed_on_orb = is_on_orb(
            getattr(event, "x", 0), getattr(event, "y", 0), size=self.size
        )
        pointer = (
            int(getattr(event, "x_root", 0)), int(getattr(event, "y_root", 0))
        )
        self._last_pointer = pointer
        if self.tracker is not None:
            self.tracker.press(*pointer)

    def _on_motion(self, event: Any) -> None:
        if self.tracker is None:
            return
        pointer = (
            int(getattr(event, "x_root", 0)), int(getattr(event, "y_root", 0))
        )
        if not self.tracker.motion(*pointer):
            return
        delta = (
            pointer[0] - self._last_pointer[0], pointer[1] - self._last_pointer[1]
        )
        self._last_pointer = pointer
        if callable(self.on_drag):
            # The controller moves both windows. Reporting the delta rather
            # than moving ourselves is what stops the orb and the panel
            # drifting apart: there is one place that knows where they are.
            try:
                self.on_drag(delta[0], delta[1])
                return
            except Exception:  # noqa: BLE001 - a drag must not kill the UI
                pass
        self.move_to(
            pointer[0] - self._grab_offset[0], pointer[1] - self._grab_offset[1]
        )

    def _on_release(self, _event: Any = None) -> None:
        """One click expands, and the decision is made here.

        On release, because by release a drag is already known: the tracker
        watches the *maximum* distance from the press, so a press that reached
        the fifth pixel is a drag before the button comes up and never reports
        a tap. There is nothing to undo, which is what makes a single click
        reliable here where it would not be if it fired on press.
        """
        if self.tracker is None:
            return
        outcome = self.tracker.release()
        if outcome != "tap" or not self._pressed_on_orb:
            return
        if callable(self.on_toggle):
            try:
                self.on_toggle()
            except Exception:  # noqa: BLE001 - a click must not kill the UI
                pass

    def _on_escape(self, _event: Any = None) -> None:
        if callable(self.on_close):
            try:
                self.on_close()
            except Exception:  # noqa: BLE001
                pass

    def move_window(self, x: int, y: int) -> None:
        """Move the window only. The layered painter moves it as part of the
        blit, so this is for the fallback, which cannot."""
        self.orb_position = (int(x), int(y))
        if self.root is None:
            return
        try:
            self.root.geometry(f"+{self.orb_position[0]}+{self.orb_position[1]}")
        except Exception:  # noqa: BLE001
            pass

    def move_to(self, x: int, y: int) -> None:
        """Move the orb and repaint it there."""
        self.move_window(x, y)
        self.redraw()
        if callable(self.on_move):
            try:
                self.on_move(self.orb_position[0], self.orb_position[1])
            except Exception:  # noqa: BLE001
                pass

    def position(self) -> tuple[int, int]:
        return self.orb_position


__all__ = [
    "ANCHOR_GAP",
    "HIT_RADIUS",
    "MONITOR_DEFAULTTONEAREST",
    "PULSE_FRAMES",
    "DEFAULT_DOUBLE_CLICK_MS",
    "DEFAULT_DRAG_SLOP",
    "DEFAULT_WORK_AREA",
    "ORB_WINDOW_BACKGROUND",
    "TICK_MS",
    "OrbView",
    "TapTracker",
    "anchor_panel_to_orb",
    "clamp_orb_position",
    "system_input_thresholds",
    "work_area",
    "work_area_for",
]
