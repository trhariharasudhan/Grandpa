"""The coupled movement, asserted on windows rather than on the model.

``test_orb_one_component.py`` drives a FakePanel and a FakeOrb whose ``at``
attributes are written by the controller's own calls. Those tests prove the
controller computes the right numbers. They prove nothing about whether a
window moves, which is the only thing a person can see -- and that gap was
named from the outside before it was noticed from the inside.

So this file closes it at two levels:

* the links the fakes skipped, asserted without a window: that ``move_to`` and
  ``move_window`` really reach ``geometry``, and that the layered painter is
  handed the anchor as its blit destination -- the orb's position is set by the
  blit, so an anchor the painter never sees would move nothing.
* a real-window test, marked ``environment`` because it opens two toplevels and
  reads Win32 geometry. Measured rather than modelled: drag the orb, drag the
  panel, and read both windows' real rectangles back out.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.core


class RecordingWidget:
    def __init__(self, calls: list, name: str):
        self._calls, self._name = calls, name

    def bind(self, sequence, handler):
        self._calls.append((f"{self._name}.bind", (sequence,), {}))

    def winfo_id(self):
        return 4242

    def winfo_x(self):
        return 111

    def winfo_y(self):
        return 222

    def __getattr__(self, attribute: str):
        if attribute.startswith("_"):
            raise AttributeError(attribute)

        def record(*args, **kwargs):
            self._calls.append((f"{self._name}.{attribute}", args, kwargs))
            return RecordingWidget(self._calls, f"{self._name}.{attribute}")

        return record


class RecordingTk:
    def __init__(self) -> None:
        self.calls: list = []

    def Tk(self, *args, **kwargs):  # noqa: N802 - mirrors tkinter
        self.calls.append(("Tk", args, kwargs))
        return RecordingWidget(self.calls, "root")

    def Toplevel(self, *args, **kwargs):  # noqa: N802 - mirrors tkinter
        self.calls.append(("Toplevel", args, kwargs))
        return RecordingWidget(self.calls, "toplevel")

    def __getattr__(self, attribute: str):
        def factory(*args, **kwargs):
            self.calls.append((attribute, args, kwargs))
            return RecordingWidget(self.calls, attribute.lower())

        return factory

    def geometries(self) -> list[str]:
        return [
            args[0]
            for name, args, _kwargs in self.calls
            if name.endswith(".geometry") and args
        ]


# --- 1. the links the fakes skipped -----------------------------------------


def test_the_panel_really_reaches_geometry() -> None:
    """A FakePanel's move_to sets an attribute. The real one has to call tk."""
    from grandpa.ui.tk_view import TkBubbleView

    tk = RecordingTk()
    view = TkBubbleView(tkinter_module=tk)
    view.show(position=(40, 40), topmost=True)

    assert view.move_to(321, 654) is True
    assert "+321+654" in tk.geometries()


def test_the_orb_really_reaches_geometry() -> None:
    from grandpa.ui.orb_view import OrbView

    tk = RecordingTk()
    view = OrbView(tkinter_module=tk, painter_factory=lambda _v: _NullPainter())
    view.show(position=(10, 10), topmost=True)

    view.move_window(777, 888)

    assert "+777+888" in tk.geometries()


class _NullPainter:
    name = "layered"
    last_error = ""

    def __init__(self) -> None:
        self.destinations: list[tuple[int, int]] = []

    @property
    def mode(self) -> str:
        return self.name

    def paint(self, image, x, y) -> bool:
        self.destinations.append((x, y))
        return True

    def describe(self) -> str:
        return "orb: glow"


def test_the_painter_is_handed_the_anchor_as_its_destination() -> None:
    """**The link most likely to have been wrong.** The orb's window position
    is set by ``UpdateLayeredWindow``'s destination point, so an anchor the
    painter never sees would move the window and then have it blitted straight
    back. If this ever regresses, the orb would appear to snap back on every
    repaint."""
    from grandpa.ui.orb_view import OrbView

    painter = _NullPainter()
    view = OrbView(
        tkinter_module=RecordingTk(), painter_factory=lambda _v: painter
    )
    view.show(position=(100, 100), topmost=True)

    view.move_to(410, 260)

    assert painter.destinations[-1] == (410, 260)


def test_a_repaint_does_not_move_the_orb_back() -> None:
    """The same hazard from the other side: redrawing after a move must blit to
    where it moved to, not to where it started."""
    from grandpa.ui.orb_view import OrbView

    painter = _NullPainter()
    view = OrbView(
        tkinter_module=RecordingTk(), painter_factory=lambda _v: painter
    )
    view.show(position=(100, 100), topmost=True)
    view.move_window(500, 300)

    view.redraw()
    view.redraw()

    assert painter.destinations[-1] == (500, 300)


def test_the_controller_moves_both_windows_through_their_real_methods() -> None:
    """Driven through the recorders, so both windows' geometry calls are
    visible: the fakes made this unobservable."""
    from grandpa.ui.bubble import BubbleController
    from grandpa.ui.orb_view import OrbView, anchor_panel_to_orb
    from grandpa.ui.tk_view import HEIGHT, WIDTH, TkBubbleView

    panel_tk, orb_tk = RecordingTk(), RecordingTk()
    painter = _NullPainter()
    panel = TkBubbleView(tkinter_module=panel_tk)
    orb = OrbView(tkinter_module=orb_tk, painter_factory=lambda _v: painter)
    controller = BubbleController(
        view=panel,
        bridge=_Bridge(),
        orb=orb,
        anchor=lambda at: anchor_panel_to_orb(at, (WIDTH, HEIGHT)),
        speak_replies=False,
    )
    controller.start(position_path=None)
    controller.expand()
    before_panel = len(panel_tk.geometries())
    before_orb = len(orb_tk.geometries())

    controller.move_component(37, -19)

    assert len(panel_tk.geometries()) > before_panel, "the panel window stayed put"
    assert len(orb_tk.geometries()) > before_orb, "the orb window stayed put"
    assert f"+{controller.orb_position[0]}+{controller.orb_position[1]}" in (
        orb_tk.geometries()
    )
    assert f"+{controller.position[0]}+{controller.position[1]}" in (
        panel_tk.geometries()
    )
    assert painter.destinations[-1] == controller.orb_position


class _Reply:
    text = "ok"
    failed = False
    status = "ok"
    kind = None


class _Bridge:
    speech_ready = True

    def send(self, text):
        return _Reply()


def test_both_drag_handlers_report_a_delta_and_move_nothing_themselves() -> None:
    """If either moved its own window as well, the anchor would be overwritten
    and the two would drift -- which was the first hypothesis for why this did
    not work."""
    from grandpa.ui.orb_view import OrbView
    from grandpa.ui.tk_view import TkBubbleView

    deltas: list[tuple[int, int]] = []

    orb_tk = RecordingTk()
    orb = OrbView(
        tkinter_module=orb_tk,
        painter_factory=lambda _v: _NullPainter(),
        on_drag=lambda dx, dy: deltas.append(("orb", dx, dy)),
    )
    orb.show(position=(0, 0), topmost=True)
    orb.tracker.clock = lambda: 1.0
    before = len(orb_tk.geometries())
    orb._on_press(_Event(x=8, y=8, x_root=200, y_root=200))
    orb._on_motion(_Event(x=8, y=8, x_root=230, y_root=210))

    assert deltas and deltas[-1] == ("orb", 30, 10)
    assert len(orb_tk.geometries()) == before, "the orb moved itself as well"

    panel_tk = RecordingTk()
    panel = TkBubbleView(
        tkinter_module=panel_tk,
        on_drag=lambda dx, dy: deltas.append(("panel", dx, dy)),
    )
    panel.show(position=(40, 40), topmost=True)
    before = len(panel_tk.geometries())
    panel._drag_start(_Event(x=5, y=5))
    panel._drag_move(_Event(x_root=300, y_root=400))

    assert deltas[-1][0] == "panel"
    assert len(panel_tk.geometries()) == before, "the panel moved itself as well"


class _Event:
    def __init__(self, x=0, y=0, x_root=0, y_root=0):
        self.x, self.y = x, y
        self.x_root, self.y_root = x_root, y_root


# --- 2. and on real windows --------------------------------------------------


@pytest.mark.environment(
    "opens two real toplevels and reads their Win32 geometry; the only test "
    "here that can see what a person sees"
)
def test_real_windows_keep_their_offset_through_both_drags(tmp_path) -> None:
    """Measured, not modelled.

    Deselected by default because it opens windows and briefly takes the
    foreground. Run it with ``-m environment`` when the coupled movement is
    what is in question -- it is the only thing in the suite that would have
    caught a drag that moved the model and not the window.
    """
    import ctypes
    import ctypes.wintypes as wt
    import tkinter

    from grandpa.ui.bubble import BubbleController
    from grandpa.ui.orb_view import OrbView, anchor_panel_to_orb
    from grandpa.ui.tk_view import HEIGHT, WIDTH, TkBubbleView

    user32 = ctypes.windll.user32
    user32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(wt.RECT)]
    user32.GetParent.argtypes = [ctypes.c_void_p]
    user32.GetParent.restype = ctypes.c_void_p

    def top_left(widget) -> tuple[int, int]:
        child = widget.winfo_id()
        hwnd = user32.GetParent(child) or child
        rect = wt.RECT()
        user32.GetWindowRect(ctypes.c_void_p(hwnd), ctypes.byref(rect))
        return rect.left, rect.top

    panel = TkBubbleView(tkinter_module=tkinter)
    orb = OrbView(tkinter_module=tkinter, master=lambda: panel.root)
    controller = BubbleController(
        view=panel,
        bridge=_Bridge(),
        orb=orb,
        anchor=lambda at: anchor_panel_to_orb(at, (WIDTH, HEIGHT)),
        speak_replies=False,
    )
    orb.on_drag = controller.move_component
    panel.on_drag = controller.move_component

    try:
        controller.start(position_path=tmp_path / "pos.json")
        controller.expand()
        for _ in range(20):
            panel.root.update()
            orb.root.update()

        baseline = (
            top_left(panel.root)[0] - top_left(orb.root)[0],
            top_left(panel.root)[1] - top_left(orb.root)[1],
        )
        orb_before = top_left(orb.root)

        orb._on_press(_Event(x=8, y=8, x_root=500, y_root=400))
        for step in range(1, 5):
            orb._on_motion(
                _Event(x=8, y=8, x_root=500 + step * 20, y_root=400 + step * 10)
            )
            for _ in range(5):
                panel.root.update()
                orb.root.update()
        orb._on_release(_Event(x=8, y=8, x_root=580, y_root=440))
        for _ in range(20):
            panel.root.update()
            orb.root.update()

        after_orb_drag = (
            top_left(panel.root)[0] - top_left(orb.root)[0],
            top_left(panel.root)[1] - top_left(orb.root)[1],
        )

        assert top_left(orb.root) != orb_before, "the orb window did not move"
        assert after_orb_drag == baseline, (
            f"the offset changed: {baseline} -> {after_orb_drag}"
        )

        orb_mid = top_left(orb.root)
        panel._drag_start(_Event(x=10, y=6))
        for step in range(1, 5):
            panel._drag_move(_Event(x_root=700 + step * 15, y_root=300 + step * 15))
            for _ in range(5):
                panel.root.update()
                orb.root.update()
        for _ in range(20):
            panel.root.update()
            orb.root.update()

        after_panel_drag = (
            top_left(panel.root)[0] - top_left(orb.root)[0],
            top_left(panel.root)[1] - top_left(orb.root)[1],
        )

        assert top_left(orb.root) != orb_mid, "the orb did not follow the panel"
        assert after_panel_drag == baseline, (
            f"the offset changed: {baseline} -> {after_panel_drag}"
        )
        # And the windows are where the model says, not merely consistent with
        # each other.
        assert top_left(orb.root) == tuple(controller.orb_position)
        assert top_left(panel.root) == tuple(controller.position)
    finally:
        controller.stop()
