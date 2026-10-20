"""The orb cannot leave the work area, and the panel stays reachable with it.

Reported: dragging toward a corner takes the orb partly or completely off
screen, and once it is gone there is nothing left to grab. There was no clamp
at all -- ``work_area`` and ``clamp`` appeared zero times in the controller.

Two decisions this file pins, because they pull against each other:

* **the clamp applies to the orb, not to the component's bounding box.** The
  panel is 400 pixels wide and anchored beside the orb, so clamping the pair
  would cost 400 pixels of travel and stop the orb reaching the right-hand
  corner at all -- which is the thing being asked for.
* **the panel flips instead.** ``anchor_panel_to_orb`` already flips to the
  orb's other side at a work-area edge, so when the stored offset would put the
  panel off screen the anchor decides instead. An orb that is reachable whose
  panel opens off screen is the same bug one layer along, so the offset yields
  rather than the reachability.

And the clamp is about the *visible ring*, not the window. Most of the window is
transparent padding; clamping the window would leave a permanent gap at the
screen edge and the orb would look as though it refused to reach the corner.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from grandpa.ui.bubble import BubbleController
from grandpa.ui.orb_image import HIT_RADIUS, ORB_SIZE, visible_inset
from grandpa.ui.orb_view import (
    anchor_panel_to_orb,
    clamp_orb_position,
    work_area_for,
)
from grandpa.ui.tk_view import HEIGHT as PANEL_HEIGHT
from grandpa.ui.tk_view import WIDTH as PANEL_WIDTH

pytestmark = pytest.mark.core

AREA = (0, 0, 1536, 864)

#: The panel the command actually opens, not a literal that happened to match
#: it once. This was ``(400, 324)`` and the panel became 520x480 in the
#: redesign, so every flip test below was flipping a window that no longer
#: existed -- and all of them still passed.
PANEL = (PANEL_WIDTH, PANEL_HEIGHT)


# --- 1. the clamp, as arithmetic ---------------------------------------------


def test_the_window_may_overhang_by_exactly_its_padding() -> None:
    """So the ring sits flush with the screen edge rather than short of it."""
    inset = visible_inset(ORB_SIZE)

    assert inset == pytest.approx(ORB_SIZE * (0.5 - HIT_RADIUS))
    assert 0 < inset < ORB_SIZE / 2
    # ceil, not round: the overhang is the whole-pixel amount that still keeps
    # the ring inside. Nine pixels does; ten would put it over by a third of a
    # pixel, which is invisible and still makes the bound untrue.
    import math

    assert clamp_orb_position(-1000, 400, size=ORB_SIZE, area=AREA)[0] == math.ceil(
        -inset
    )


@pytest.mark.parametrize(
    "corner",
    [(-5000, -5000), (5000, -5000), (-5000, 5000), (5000, 5000)],
)
def test_every_corner_keeps_the_whole_ring_on_screen(corner) -> None:
    """All four, because a sign error shows up in exactly one of them."""
    x, y = clamp_orb_position(*corner, size=ORB_SIZE, area=AREA)
    left, top, right, bottom = AREA
    inset = visible_inset(ORB_SIZE)

    assert x + inset >= left - 0.5, "the ring went off the left edge"
    assert y + inset >= top - 0.5, "the ring went off the top edge"
    assert x + ORB_SIZE - inset <= right + 0.5, "the ring went off the right edge"
    assert y + ORB_SIZE - inset <= bottom + 0.5, "the ring went off the bottom"


def test_a_position_well_inside_is_left_alone() -> None:
    """A clamp that moves something already fine is a clamp that fights the
    drag."""
    assert clamp_orb_position(700, 400, size=ORB_SIZE, area=AREA) == (700, 400)


def test_a_work_area_that_does_not_start_at_zero_is_honoured() -> None:
    """A taskbar on the left, or a second monitor at a negative offset."""
    area = (-1920, 100, 0, 1180)

    x, y = clamp_orb_position(5000, 5000, size=ORB_SIZE, area=area)

    assert x < 0, f"clamped to {x}, which is on the other monitor"
    assert y >= 100 - visible_inset(ORB_SIZE)


def test_a_work_area_smaller_than_the_orb_centres_rather_than_inverting() -> None:
    """Degenerate, but an inverted min/max returns nonsense silently."""
    area = (0, 0, 20, 20)

    x, y = clamp_orb_position(5000, 5000, size=ORB_SIZE, area=area)

    assert x == y == round((0 + 20 - ORB_SIZE) / 2)


def test_the_clamp_scales_with_the_orb() -> None:
    for size in (32, 48, 64, 96):
        x, _y = clamp_orb_position(5000, 400, size=size, area=AREA)

        assert x + size - visible_inset(size) <= AREA[2] + 0.5


# --- 2. the monitor it is actually on ----------------------------------------


def test_the_work_area_comes_from_the_monitor_under_the_point() -> None:
    """SPI_GETWORKAREA answers for the primary display only, which would clamp
    the orb back onto the main screen the moment it was dragged to a second
    one -- stranded rather than reachable."""
    left, top, right, bottom = work_area_for((100, 100))

    assert right > left and bottom > top


def test_a_point_on_no_monitor_still_resolves(monkeypatch) -> None:
    """DEFAULTTONEAREST, so an orb that somehow got out comes back rather than
    failing to be placed at all."""
    far_away = work_area_for((-99999, -99999))

    assert far_away[2] > far_away[0]
    assert far_away[3] > far_away[1]


def test_an_unusable_monitor_api_falls_back(monkeypatch) -> None:
    class Broken:
        def MonitorFromPoint(self, *_args):  # noqa: N802 - mirrors Win32
            raise OSError("no multi-monitor support here")

        def SystemParametersInfoW(self, *_args):  # noqa: N802
            return 0

    from grandpa.ui.orb_view import DEFAULT_WORK_AREA

    assert work_area_for((0, 0), Broken()) == DEFAULT_WORK_AREA


# --- 3. the controller clamps every motion event -----------------------------


class FakePanel:
    def __init__(self) -> None:
        self.at = (0, 0)
        self.hidden = False

    def show(self, *, position, topmost):
        self.at = tuple(position)

    def set_state(self, state, label):
        pass

    def set_status_line(self, text):
        pass

    def set_reply(self, text):
        pass

    def set_transcript(self, text):
        pass

    def set_earlier(self, rows):
        pass

    def clear_entry(self):
        pass

    def set_entry_text(self, text):
        pass

    def set_levels(self, levels):
        pass

    def position(self):
        return self.at

    def move_to(self, x, y):
        self.at = (int(x), int(y))
        return True

    def hide(self):
        self.hidden = True
        return True

    def unhide(self):
        self.hidden = False
        return True

    def close(self):
        pass


class FakeOrb:
    def __init__(self) -> None:
        self.at = (0, 0)

    def show(self, *, position, topmost):
        self.at = tuple(position)

    def set_state(self, state, *, unread):
        pass

    def set_level(self, level):
        pass

    def set_levels(self, levels):
        pass

    def set_mic_live(self, live):
        pass

    def move_window(self, x, y):
        self.at = (int(x), int(y))

    def redraw(self):
        return True

    def position(self):
        return self.at

    def close(self):
        pass


class Reply:
    text = "ok"
    failed = False
    status = "ok"
    kind = None


class Bridge:
    speech_ready = True

    def send(self, text):
        return Reply()


def a_component(tmp_path: Path, *, expanded: bool = True):
    panel, orb = FakePanel(), FakeOrb()
    controller = BubbleController(
        view=panel,
        bridge=Bridge(),
        orb=orb,
        anchor=lambda at: anchor_panel_to_orb(at, PANEL, area=AREA),
        clamp=lambda x, y: clamp_orb_position(x, y, size=ORB_SIZE, area=AREA),
        work_area=lambda _at: AREA,
        panel_size=PANEL,
        speak_replies=False,
    )
    controller.start(position_path=tmp_path / "p.json")
    if expanded:
        controller.expand()
    return controller, panel, orb


@pytest.mark.parametrize(
    "push", [(-9000, 0), (9000, 0), (0, -9000), (0, 9000), (9000, 9000)]
)
def test_dragging_hard_at_an_edge_stops_at_it(tmp_path: Path, push) -> None:
    controller, _panel, orb = a_component(tmp_path)

    controller.move_component(*push)

    x, y = controller.orb_position
    inset = visible_inset(ORB_SIZE)

    assert x + inset >= AREA[0] - 0.5
    assert y + inset >= AREA[1] - 0.5
    assert x + ORB_SIZE - inset <= AREA[2] + 0.5
    assert y + ORB_SIZE - inset <= AREA[3] + 0.5
    assert orb.at == controller.orb_position, "the window did not follow the clamp"


def test_the_clamp_runs_on_every_motion_not_at_the_end(tmp_path: Path) -> None:
    """Otherwise the orb travels off screen and is yanked back when the button
    comes up, which is both ugly and -- if the drag is interrupted -- a lost
    orb."""
    controller, _panel, orb = a_component(tmp_path)
    seen = []

    for _ in range(20):
        controller.move_component(400, 0)
        seen.append(controller.orb_position[0])

    assert max(seen) + ORB_SIZE - visible_inset(ORB_SIZE) <= AREA[2] + 0.5


def test_a_remembered_position_off_the_screen_is_clamped_on_startup(
    tmp_path: Path,
) -> None:
    """A position saved on a larger screen, or on a monitor since unplugged,
    would otherwise start the orb somewhere unreachable."""
    import json

    store = tmp_path / "p.json"
    store.write_text(
        json.dumps({"x": 10, "y": 10, "orb_x": 99999, "orb_y": 99999}),
        encoding="utf-8",
    )
    panel, orb = FakePanel(), FakeOrb()
    controller = BubbleController(
        view=panel,
        bridge=Bridge(),
        orb=orb,
        clamp=lambda x, y: clamp_orb_position(x, y, size=ORB_SIZE, area=AREA),
        speak_replies=False,
    )

    controller.start(position_path=store)

    x = controller.orb_position[0]

    assert x + ORB_SIZE - visible_inset(ORB_SIZE) <= AREA[2]


def test_a_controller_with_no_clamp_still_moves(tmp_path: Path) -> None:
    """The clamp is injected, so a caller without one must not be broken."""
    panel, orb = FakePanel(), FakeOrb()
    controller = BubbleController(
        view=panel, bridge=Bridge(), orb=orb, speak_replies=False
    )
    controller.start(position_path=tmp_path / "p.json")

    controller.move_component(50, 50)

    assert orb.at == controller.orb_position


def test_a_clamp_that_raises_does_not_freeze_the_orb(tmp_path: Path) -> None:
    panel, orb = FakePanel(), FakeOrb()

    def broken(_x, _y):
        raise RuntimeError("no monitors")

    controller = BubbleController(
        view=panel, bridge=Bridge(), orb=orb, clamp=broken, speak_replies=False
    )
    controller.start(position_path=tmp_path / "p.json")
    before = controller.orb_position

    controller.move_component(30, 30)

    assert controller.orb_position == (before[0] + 30, before[1] + 30)


# --- 4. and the panel stays reachable ----------------------------------------


def test_the_panel_flips_rather_than_going_off_the_right_edge(
    tmp_path: Path,
) -> None:
    """The decision, as a behaviour: the orb keeps its corner and the panel
    moves to the orb's other side."""
    controller, panel, _orb = a_component(tmp_path)

    controller.move_component(9000, 0)

    assert controller.position[0] + PANEL[0] <= AREA[2], (
        f"the panel runs to {controller.position[0] + PANEL[0]} of {AREA[2]}"
    )
    assert panel.at == controller.position
    # And it is to the orb's left now, which is what flipping means.
    assert controller.position[0] < controller.orb_position[0]


@pytest.mark.parametrize(
    "push", [(-9000, -9000), (9000, -9000), (-9000, 9000), (9000, 9000)]
)
def test_the_panel_is_wholly_on_screen_at_every_corner(
    tmp_path: Path, push
) -> None:
    controller, _panel, _orb = a_component(tmp_path)

    controller.move_component(*push)

    x, y = controller.position

    assert x >= AREA[0]
    assert y >= AREA[1]
    assert x + PANEL[0] <= AREA[2]
    assert y + PANEL[1] <= AREA[3]


def test_the_offset_is_kept_while_the_panel_still_fits(tmp_path: Path) -> None:
    """The offset exists so a panel dragged somewhere stays there. It only
    yields when keeping it would put the panel off screen."""
    controller, _panel, _orb = a_component(tmp_path)
    offset = controller.panel_offset

    controller.move_component(60, 40)

    assert controller.panel_offset == offset
    assert controller.position == (
        controller.orb_position[0] + offset[0],
        controller.orb_position[1] + offset[1],
    )


def test_the_offset_itself_is_not_rewritten_by_a_flip(tmp_path: Path) -> None:
    """So dragging back from the edge restores the panel where it was, rather
    than leaving it flipped for good."""
    controller, _panel, _orb = a_component(tmp_path)
    offset = controller.panel_offset

    controller.move_component(9000, 0)
    flipped = controller.position
    controller.move_component(-700, 0)

    assert controller.panel_offset == offset
    assert controller.position != flipped
    assert controller.position == (
        controller.orb_position[0] + offset[0],
        controller.orb_position[1] + offset[1],
    )


def test_the_clamp_is_not_applied_to_the_components_bounding_box(
    tmp_path: Path,
) -> None:
    """**The decision, stated as what it is not.** Clamping the pair would cost
    400 pixels of travel and stop the orb reaching the right-hand corner --
    which is exactly the thing being asked for."""
    controller, _panel, _orb = a_component(tmp_path)

    controller.move_component(9000, 0)

    rightmost = AREA[2] - ORB_SIZE + visible_inset(ORB_SIZE)

    assert controller.orb_position[0] == pytest.approx(rightmost, abs=1), (
        "the orb stopped short of the corner, so the panel is being clamped too"
    )


def test_a_missing_measurement_leaves_the_panel_where_it_was(
    tmp_path: Path,
) -> None:
    """No panel size and no work area means nothing to check against, and a
    missing measurement must not move a window that was fine."""
    panel, orb = FakePanel(), FakeOrb()
    controller = BubbleController(
        view=panel,
        bridge=Bridge(),
        orb=orb,
        anchor=lambda at: anchor_panel_to_orb(at, PANEL, area=AREA),
        clamp=lambda x, y: clamp_orb_position(x, y, size=ORB_SIZE, area=AREA),
        speak_replies=False,
    )
    controller.start(position_path=tmp_path / "p.json")
    controller.expand()
    offset = controller.panel_offset

    controller.move_component(9000, 0)

    assert controller.panel_offset == offset
    assert controller.position == (
        controller.orb_position[0] + offset[0],
        controller.orb_position[1] + offset[1],
    )


# --- 5. and on real windows, at all four corners -----------------------------


@pytest.mark.environment(
    "drags two real toplevels into all four corners and reads their Win32 "
    "geometry; the only test that can see whether the ring is actually on "
    "screen"
)
def test_the_real_window_ring_stays_inside_the_work_area(tmp_path) -> None:
    """Measured, not modelled.

    Deselected by default because it opens windows and briefly takes the
    foreground. Run it with ``-m environment`` when the clamp is in question:
    it is the only thing in the suite that would catch a clamp computed in the
    wrong coordinate space.
    """
    import ctypes
    import ctypes.wintypes as wt
    import tkinter

    from grandpa.ui.orb_view import OrbView
    from grandpa.ui.tk_view import HEIGHT, WIDTH, TkBubbleView

    user32 = ctypes.windll.user32
    user32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(wt.RECT)]
    user32.GetParent.argtypes = [ctypes.c_void_p]
    user32.GetParent.restype = ctypes.c_void_p

    def rect_of(widget) -> tuple[int, int, int, int]:
        child = widget.winfo_id()
        hwnd = user32.GetParent(child) or child
        rect = wt.RECT()
        user32.GetWindowRect(ctypes.c_void_p(hwnd), ctypes.byref(rect))
        return rect.left, rect.top, rect.right, rect.bottom

    panel = TkBubbleView(tkinter_module=tkinter)
    orb = OrbView(tkinter_module=tkinter, master=lambda: panel.root)
    controller = BubbleController(
        view=panel,
        bridge=Bridge(),
        orb=orb,
        anchor=lambda at: anchor_panel_to_orb(at, (WIDTH, HEIGHT)),
        clamp=lambda x, y: clamp_orb_position(x, y),
        work_area=work_area_for,
        panel_size=(WIDTH, HEIGHT),
        speak_replies=False,
    )
    orb.on_drag = controller.move_component
    panel.on_drag = controller.move_component

    def pump(times: int = 20) -> None:
        for _ in range(times):
            panel.root.update()
            orb.root.update()

    try:
        controller.start(position_path=tmp_path / "pos.json")
        controller.expand()
        pump(30)

        area = work_area_for(controller.orb_position)
        left, top, right, bottom = area
        inset = visible_inset(ORB_SIZE)
        failures: list[str] = []

        for name, push in (
            ("top-left", (-9000, -9000)),
            ("top-right", (9000, -9000)),
            ("bottom-left", (-9000, 9000)),
            ("bottom-right", (9000, 9000)),
        ):
            controller.move_component(*push)
            pump(25)
            orb_rect = rect_of(orb.root)
            panel_rect = rect_of(panel.root)

            # The visible ring, which is what the clamp is actually about.
            ring = (
                orb_rect[0] + inset,
                orb_rect[1] + inset,
                orb_rect[2] - inset,
                orb_rect[3] - inset,
            )
            if ring[0] < left - 1 or ring[1] < top - 1:
                failures.append(f"{name}: ring at {ring} past the top-left of {area}")
            if ring[2] > right + 1 or ring[3] > bottom + 1:
                failures.append(
                    f"{name}: ring at {ring} past the bottom-right of {area}"
                )
            if (
                panel_rect[0] < left - 1
                or panel_rect[1] < top - 1
                or panel_rect[2] > right + 1
                or panel_rect[3] > bottom + 1
            ):
                failures.append(f"{name}: panel at {panel_rect} outside {area}")

        assert failures == [], "; ".join(failures)
    finally:
        controller.stop()
