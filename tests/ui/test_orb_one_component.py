"""The orb and the panel are one component with two native windows.

There is no shared parent to move: the panel is the ``Tk()`` root and the orb
is a ``Toplevel`` whose pixels Win32 blits, so each is positioned by its own
mechanism. What keeps them together is that neither positions *itself* --
both drag handlers report a delta to the controller, which holds one anchor and
one offset and places both windows from them.

The failure this rules out is two positions that agree until they do not: a
panel that was moved while the orb stayed, or an orb that was dragged while the
panel snapped back to its side.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from grandpa.ui.bubble import BubbleController
from grandpa.ui.orb_image import (
    HIT_RADIUS,
    ORB_SIZE,
    RING_RADIUS,
    is_on_orb,
    responsive_fraction,
)
from grandpa.ui.orb_view import anchor_panel_to_orb

pytestmark = pytest.mark.core

AREA = (0, 0, 1920, 1080)
PANEL = (400, 324)


class FakePanel:
    def __init__(self) -> None:
        self.at = (0, 0)
        self.hidden = False
        self.moves: list[tuple[int, int]] = []
        self.reply = ""

    def show(self, *, position, topmost):
        self.at = tuple(position)

    def set_state(self, state, label):
        pass

    def set_status_line(self, text):
        pass

    def set_reply(self, text):
        self.reply = text

    def set_transcript(self, text):
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
        self.moves.append(self.at)
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
        self.moves: list[tuple[int, int]] = []
        self.redraws = 0

    def show(self, *, position, topmost):
        self.at = tuple(position)

    def set_state(self, state, *, unread):
        pass

    def set_level(self, level):
        pass

    def set_levels(self, levels):
        pass

    def move_window(self, x, y):
        self.at = (int(x), int(y))
        self.moves.append(self.at)

    def redraw(self):
        self.redraws += 1
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
        speak_replies=False,
    )
    controller.start(position_path=tmp_path / "p.json")
    if expanded:
        controller.expand()
    return controller, panel, orb


# --- 1. one anchor ------------------------------------------------------------


def test_the_anchor_is_the_orb_and_the_panel_is_derived(tmp_path: Path) -> None:
    controller, panel, orb = a_component(tmp_path)

    assert controller.panel_offset is not None
    assert controller.position == (
        controller.orb_position[0] + controller.panel_offset[0],
        controller.orb_position[1] + controller.panel_offset[1],
    )
    assert panel.at == controller.position


def test_dragging_the_orb_moves_both(tmp_path: Path) -> None:
    controller, panel, orb = a_component(tmp_path)
    orb_before, panel_before = controller.orb_position, controller.position

    controller.move_component(60, -25)

    assert controller.orb_position == (orb_before[0] + 60, orb_before[1] - 25)
    assert controller.position == (panel_before[0] + 60, panel_before[1] - 25)
    assert orb.at == controller.orb_position
    assert panel.at == controller.position


def test_dragging_the_panel_moves_both(tmp_path: Path) -> None:
    """Same entry point. There is one way to move the component and both drag
    handlers use it, which is why they cannot disagree."""
    controller, panel, orb = a_component(tmp_path)
    orb_before = controller.orb_position

    controller.move_component(-40, 90)

    assert orb.at == (orb_before[0] - 40, orb_before[1] + 90)
    assert panel.at == controller.position


def test_the_offset_never_changes_however_far_it_is_dragged(tmp_path: Path) -> None:
    controller, _panel, _orb = a_component(tmp_path)
    offset = controller.panel_offset

    for dx, dy in ((10, 10), (-300, 40), (120, -200), (5, 5)):
        controller.move_component(dx, dy)

        assert controller.panel_offset == offset, "the panel drifted"


def test_the_offset_survives_a_collapse_and_an_expand(tmp_path: Path) -> None:
    controller, panel, orb = a_component(tmp_path)
    controller.move_component(70, 70)
    offset = controller.panel_offset
    orb_at, panel_at = controller.orb_position, controller.position

    controller.collapse()
    controller.expand()

    assert controller.panel_offset == offset
    assert controller.orb_position == orb_at
    assert controller.position == panel_at
    assert panel.at == panel_at


def test_a_panel_dragged_somewhere_comes_back_there(tmp_path: Path) -> None:
    """The offset is adopted once and then preserved, so expanding does not
    snap the panel back to the orb's side."""
    controller, panel, _orb = a_component(tmp_path)
    controller.panel_offset = (-500, 200)
    controller._place_windows()
    moved_to = controller.position

    controller.collapse()
    controller.expand()

    assert controller.position == moved_to
    assert panel.at == moved_to


def test_moving_while_collapsed_does_not_touch_the_hidden_panel(
    tmp_path: Path,
) -> None:
    """It is withdrawn; moving it would be work nobody can see. Its position
    still follows the anchor, so it reappears in the right place."""
    controller, panel, orb = a_component(tmp_path, expanded=False)
    panel.moves.clear()

    controller.move_component(50, 50)

    assert panel.moves == []
    assert orb.at == controller.orb_position
    assert controller.position == (
        controller.orb_position[0] + controller.panel_offset[0],
        controller.orb_position[1] + controller.panel_offset[1],
    )


def test_the_orb_is_repainted_where_it_moved_to(tmp_path: Path) -> None:
    """The layered blit sets the window position, so a move that does not
    repaint leaves the orb behind."""
    controller, _panel, orb = a_component(tmp_path)
    before = orb.redraws

    controller.move_component(12, 0)

    assert orb.redraws > before


def test_a_controller_with_no_orb_still_moves_its_panel(tmp_path: Path) -> None:
    panel = FakePanel()
    controller = BubbleController(
        view=panel,
        bridge=Bridge(),
        anchor=lambda at: anchor_panel_to_orb(at, PANEL, area=AREA),
        speak_replies=False,
    )
    controller.start(position_path=tmp_path / "p.json")
    controller.expand()

    controller.move_component(30, 30)

    assert panel.at == controller.position


def test_the_remembered_state_is_the_anchor_and_the_offset(tmp_path: Path) -> None:
    from grandpa.ui.bubble import load_orb_position

    store = tmp_path / "p.json"  # the path a_component() hands the controller
    controller, _panel, orb = a_component(tmp_path)
    controller.move_component(100, 50)
    anchor = controller.orb_position
    orb.at = anchor
    controller.stop()

    assert load_orb_position(store) == anchor


# --- 2. the hit test ----------------------------------------------------------


def test_the_hit_region_is_the_ring_and_its_inside() -> None:
    centre = (ORB_SIZE - 1) // 2

    assert is_on_orb(centre, centre)
    assert is_on_orb(centre, centre - int(RING_RADIUS * ORB_SIZE) + 1)
    assert not is_on_orb(0, 0)
    assert not is_on_orb(ORB_SIZE - 1, ORB_SIZE - 1)
    assert not is_on_orb(ORB_SIZE - 1, 0)


def test_the_hit_region_is_the_same_in_every_state() -> None:
    """**Why it is geometric and not alpha.** Measured at 64 pixels, pixels
    above alpha 40 cover 8.0% of the window while loading, 22.7% at standby and
    62.4% while recording -- so an alpha rule would make the same click hit or
    miss depending on what the orb happened to be doing. A button does not do
    that."""
    assert responsive_fraction() == pytest.approx(0.274, abs=0.02)


def test_the_responsive_share_is_the_orb_and_not_the_rectangle() -> None:
    """61-73% of the window is merely non-transparent. The ring's outer edge is
    just over a quarter of it."""
    import numpy as np

    from grandpa.ui.orb_image import orb_image

    alpha = np.asarray(orb_image("idle"))[:, :, 3]
    non_transparent = float((alpha > 0).mean())

    assert responsive_fraction() < non_transparent / 2
    assert 0.2 < responsive_fraction() < 0.35


def test_the_hit_region_scales_with_the_orb() -> None:
    for size in (48, 64, 96):
        centre = (size - 1) // 2

        assert is_on_orb(centre, centre, size=size)
        assert not is_on_orb(0, 0, size=size)
        assert responsive_fraction(size=size) == pytest.approx(0.274, abs=0.03)


def test_the_hit_radius_is_the_rings_outer_edge() -> None:
    from grandpa.ui.orb_image import RING_WIDTH

    assert HIT_RADIUS == pytest.approx(RING_RADIUS + RING_WIDTH)


# --- 3. where a drag may begin -----------------------------------------------


def test_only_the_header_and_its_two_labels_can_start_a_drag() -> None:
    """Pinned as a list and as code. A drag that could start from the entry
    would fight a text selection; from the heard row it would fight the click
    that loads a transcript for correcting."""
    import ast

    from grandpa.ui.tk_view import DRAG_HANDLE_WIDGETS

    assert DRAG_HANDLE_WIDGETS == ("header", "state", "dot")

    source = Path("src/grandpa/ui/tk_view.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    bound: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.For):
            continue
        body = ast.unparse(ast.Module(body=node.body, type_ignores=[]))
        if "_drag_start" not in body:
            continue
        bound.append(ast.unparse(node.iter))

    assert len(bound) == 1, f"drag is bound in {len(bound)} places"
    for name in DRAG_HANDLE_WIDGETS:
        assert name in bound[0], f"{name} is no longer a drag handle"
    for forbidden in ("entry", "speak", "transcript", "status", "meter", "reply"):
        assert forbidden not in bound[0], f"a drag can now start from {forbidden}"


def test_the_panel_reports_a_delta_rather_than_moving_itself() -> None:
    """Given an on_drag it must not call move_to: the controller moves both."""
    from tests.ui.test_bubble_never_takes_focus import RecordingTk
    from grandpa.ui.tk_view import TkBubbleView

    deltas: list[tuple[int, int]] = []
    tk = RecordingTk()
    view = TkBubbleView(tkinter_module=tk, on_drag=lambda dx, dy: deltas.append((dx, dy)))
    view.show(position=(40, 40), topmost=True)

    view._drag_start(type("E", (), {"x": 5, "y": 5})())
    view._drag_move(type("E", (), {"x_root": 200, "y_root": 150})())

    assert deltas, "the panel moved itself instead of reporting"
    moved = [name for name, _a, _k in tk.calls if name == "root.geometry"]

    # One geometry call from show(), none from the drag.
    assert len(moved) == 1, f"the panel moved itself: {len(moved)} geometry calls"


def test_without_a_handler_the_panel_still_moves_itself() -> None:
    """So the panel is usable on its own, as it was before the two were joined."""
    from tests.ui.test_bubble_never_takes_focus import RecordingTk
    from grandpa.ui.tk_view import TkBubbleView

    tk = RecordingTk()
    view = TkBubbleView(tkinter_module=tk)
    view.show(position=(40, 40), topmost=True)

    view._drag_start(type("E", (), {"x": 5, "y": 5})())
    view._drag_move(type("E", (), {"x_root": 200, "y_root": 150})())

    moved = [name for name, _a, _k in tk.calls if name == "root.geometry"]

    assert len(moved) == 2
