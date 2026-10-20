"""The redesigned chat panel: bubbles, the empty state, and four buttons.

The panel stopped being two captioned panes and became a conversation: a
header, bubbles on alternating sides, an empty state when nothing has been
said, a thinking pill, and an action row under the reply.

Most of it is drawing, and drawing is tested here the only way a recorded
toolkit allows -- by what the window asks tkinter to make. The parts that are
*not* drawing get their own tests, because they are the parts that can be
wrong in a way a screenshot would not show:

* ``rounded_points`` is pure geometry, so it is asserted on numbers.
* copy, read and stop are behaviour, so each is driven through its binding.
* "stop" must not be queued behind the speech it stops, which is a property of
  the wiring and is asserted on the wiring.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from grandpa.ui.tk_view import (
    ACTION_COPY,
    USER_BUBBLE,
    ACTION_HEIGHT,
    ACTION_READ,
    ACTION_STOP,
    ACTION_WIDTH,
    BORDER,
    BUBBLE_GRANDPA,
    BUBBLE_RADIUS,
    BUBBLE_USER,
    CLOSE_GLYPH,
    DRAG_HANDLE_WIDGETS,
    EMPTY_TITLE,
    HEIGHT,
    PANEL_RADIUS,
    PLACEHOLDER_ENTRY,
    PRODUCT_NAME,
    PRODUCT_TAGLINE,
    THINKING_TEXT,
    WIDTH,
    TkBubbleView,
)

pytestmark = pytest.mark.core


# --- a recorder that remembers which widget did what -------------------------
#
# The existing fakes record a call name and its arguments, which is enough to
# ask "was anything created with an empty string". It is not enough to ask "is
# the empty state packed and the bubble row not", because every Frame records
# under the name "frame". This one keeps the widget object.


class Widget:
    def __init__(self, owner: Tk, kind: str) -> None:
        self._owner = owner
        self.kind = kind
        self.options: dict[str, Any] = {}
        self.items: list[tuple[str, tuple, dict]] = []

    def bind(self, sequence, handler=None, add=None):
        self._owner.bound.append((self, sequence, handler))
        return ""

    def __getattr__(self, attribute: str):
        if attribute.startswith("_"):
            raise AttributeError(attribute)

        def record(*args, **kwargs):
            self._owner.history.append((self, attribute, args, kwargs))
            if attribute.startswith("create_"):
                self.items.append((attribute, args, kwargs))
                # tkinter hands back an integer item id, and the window keeps
                # one of them to recolour the logo ring by.
                return len(self.items)
            if attribute == "configure":
                self.options.update(kwargs)
            if attribute in {"winfo_x", "winfo_y"}:
                return 7
            if attribute == "get":
                return self._owner.entry_text[0]
            return Widget(self._owner, f"{self.kind}.{attribute}")

        return record


@dataclass
class Tk:
    history: list = field(default_factory=list)
    bound: list = field(default_factory=list)
    made: list = field(default_factory=list)
    entry_text: list = field(default_factory=lambda: [""])

    def Entry(self, *args, **kwargs):  # noqa: N802 - mirrors tkinter
        owner = self
        widget = Widget(self, "Entry")
        widget.options.update(kwargs)

        def insert(index, text):
            owner.history.append((widget, "insert", (index, text), {}))
            owner.entry_text[0] = str(text)

        def delete(first, last=None):
            owner.history.append((widget, "delete", (first, last), {}))
            owner.entry_text[0] = ""

        widget.insert = insert  # type: ignore[method-assign]
        widget.delete = delete  # type: ignore[method-assign]
        self.made.append(widget)
        return widget

    def __getattr__(self, attribute: str):
        def factory(*args, **kwargs):
            widget = Widget(self, attribute)
            widget.options.update(kwargs)
            self.made.append(widget)
            return widget

        return factory

    # --- questions the tests ask ------------------------------------------
    def polygons(self) -> list[dict]:
        return [
            kwargs
            for widget, method, _args, kwargs in self.history
            if method == "create_polygon"
        ]

    def polygon_points(self) -> list[tuple]:
        return [
            args
            for _widget, method, args, _kwargs in self.history
            if method == "create_polygon"
        ]

    def texts(self) -> list[str]:
        return [
            widget.options["text"]
            for widget in self.made
            if isinstance(widget.options.get("text"), str) and widget.options["text"]
        ]

    def packing(self, widget: Widget) -> list[str]:
        """Every pack/pack_forget this widget received, in order."""
        return [
            method
            for recorded, method, _args, _kwargs in self.history
            if recorded is widget and method in {"pack", "pack_forget"}
        ]

    def pack_side(self, widget: Widget) -> str | None:
        for recorded, method, _args, kwargs in self.history:
            if recorded is widget and method == "pack":
                return kwargs.get("side")
        return None

    def handler_for(self, widget: Widget, sequence: str):
        for bound, bound_sequence, handler in reversed(self.bound):
            if bound is widget and bound_sequence == sequence:
                return handler
        raise KeyError(f"that widget never bound {sequence}")

    def click(self, widget: Widget) -> Any:
        return self.handler_for(widget, "<Button-1>")(object())


def _shown(**kwargs) -> tuple[Tk, TkBubbleView]:
    tk = Tk()
    view = TkBubbleView(tkinter_module=tk, **kwargs)
    view.show(position=(10, 10), topmost=True)
    return tk, view


# --- 1. the rounded geometry, as numbers -------------------------------------


def test_the_rounded_rectangle_is_a_closed_twelve_point_polygon() -> None:
    """Three points per corner, which is what the spline rounds."""
    points = TkBubbleView.rounded_points(0, 0, 100, 50, 10)

    assert len(points) == 24
    assert len(points) % 2 == 0


def test_no_rounded_point_falls_outside_its_box() -> None:
    points = TkBubbleView.rounded_points(5, 7, 105, 57, 12)
    xs, ys = points[0::2], points[1::2]

    assert min(xs) == 5 and max(xs) == 105
    assert min(ys) == 7 and max(ys) == 57


def test_every_corner_of_the_box_is_a_vertex() -> None:
    """Without the corner itself the spline cuts across rather than turning."""
    points = TkBubbleView.rounded_points(0, 0, 40, 20, 6)
    vertices = set(zip(points[0::2], points[1::2]))

    for corner in ((0, 0), (40, 0), (40, 20), (0, 20)):
        assert corner in vertices, f"{corner} is not a vertex of {sorted(vertices)}"


def test_an_oversized_radius_is_clamped_to_the_box() -> None:
    """A radius larger than the box would invert the shape.

    The action buttons ask for ``ACTION_HEIGHT / 2`` on a box that is wider
    than it is tall, so this is a path the window really takes.
    """
    points = TkBubbleView.rounded_points(0, 0, 10, 10, 999)
    xs, ys = points[0::2], points[1::2]

    assert min(xs) >= 0 and max(xs) <= 10
    assert min(ys) >= 0 and max(ys) <= 10
    # Clamped to half the smaller side: every x is 0, 5 or 10.
    assert set(xs) <= {0.0, 5.0, 10.0}


def test_a_zero_radius_is_the_plain_rectangle() -> None:
    points = TkBubbleView.rounded_points(0, 0, 10, 20, 0)

    assert set(zip(points[0::2], points[1::2])) == {
        (0, 0), (10, 0), (10, 20), (0, 20)
    }


def test_the_radius_is_never_negative() -> None:
    points = TkBubbleView.rounded_points(0, 0, 10, 10, -5)

    assert set(zip(points[0::2], points[1::2])) == {
        (0, 0), (10, 0), (10, 10), (0, 10)
    }


def test_the_drawing_helper_survives_a_canvas_that_refuses() -> None:
    """A closed window must not turn a repaint into a traceback."""

    class Dead:
        def create_polygon(self, *args, **kwargs):
            raise RuntimeError("that canvas is gone")

    view = TkBubbleView(tkinter_module=Tk())

    assert view._rounded(Dead(), 0, 0, 10, 10, 2, fill="#fff", outline="") is None


# --- 2. the panel's own border -----------------------------------------------


def test_the_panel_draws_itself_a_rounded_inner_border() -> None:
    """The window's corners are square -- measured -- so this is the only
    rounding there is. Whether it *reads* as rounded is a separate question
    and is answered in the manual QA notes, not here."""
    tk, _view = _shown()

    wanted = tuple(
        TkBubbleView.rounded_points(1, 1, WIDTH - 2, HEIGHT - 2, PANEL_RADIUS)
    )

    assert wanted in {tuple(points) for points in tk.polygon_points()}


def test_every_rounded_shape_is_drawn_smooth() -> None:
    """``create_polygon`` without ``smooth=True`` is a twelve-sided box."""
    tk, _view = _shown()

    assert tk.polygons(), "nothing rounded was drawn at all"
    for options in tk.polygons():
        assert options.get("smooth") is True


# --- 3. the bubbles ----------------------------------------------------------


def test_the_two_speakers_are_different_colours() -> None:
    assert BUBBLE_USER != BUBBLE_GRANDPA


def test_both_bubbles_are_drawn_in_their_own_colour() -> None:
    tk, _view = _shown()
    fills = {options.get("fill") for options in tk.polygons()}

    assert BUBBLE_USER in fills
    assert BUBBLE_GRANDPA in fills


def test_the_bubbles_use_the_bubble_radius_and_not_the_panel_one() -> None:
    tk, view = _shown()
    bubble = tk.polygon_points()
    wanted = tuple(
        TkBubbleView.rounded_points(
            0, 0, USER_BUBBLE[0] - 1, USER_BUBBLE[1] - 1, BUBBLE_RADIUS
        )
    )

    assert wanted in {tuple(points) for points in bubble}
    assert BUBBLE_RADIUS != PANEL_RADIUS, "the test would prove nothing"
    assert view._widgets["user_bubble"] is not None


def test_the_speakers_sit_on_opposite_sides() -> None:
    """Which is the whole point of bubbles over two stacked panes."""
    tk, view = _shown()

    assert tk.pack_side(view._widgets["user_bubble"]) == "right"
    assert tk.pack_side(view._widgets["grandpa_bubble"]) == "left"


# --- 4. the empty state ------------------------------------------------------


def test_a_window_with_no_exchange_shows_the_empty_state() -> None:
    tk, view = _shown()

    assert tk.packing(view._widgets["empty"])[-1] == "pack"
    assert EMPTY_TITLE in tk.texts()


def test_the_bubbles_are_not_packed_before_there_is_anything_in_them() -> None:
    tk, view = _shown()

    for name in ("user_row", "grandpa_row", "actions"):
        assert tk.packing(view._widgets[name])[-1] == "pack_forget", name


def test_a_reply_replaces_the_empty_state_with_the_conversation() -> None:
    tk, view = _shown()

    view.set_reply("It is just past four.")

    assert tk.packing(view._widgets["empty"])[-1] == "pack_forget"
    for name in ("user_row", "grandpa_row", "actions"):
        assert tk.packing(view._widgets[name])[-1] == "pack", name


def test_a_transcript_alone_is_enough_to_show_the_conversation() -> None:
    """The user's message appears before the reply exists, not after it."""
    tk, view = _shown()

    view.set_transcript("what time is it")

    assert tk.packing(view._widgets["empty"])[-1] == "pack_forget"
    assert tk.packing(view._widgets["user_row"])[-1] == "pack"


def test_an_empty_reply_returns_to_the_empty_state_of_the_reply_bubble() -> None:
    """set_reply("") is the documented way to clear it, and it must not crash."""
    tk, view = _shown()
    view.set_reply("something")

    view.set_reply("")

    assert view._last_reply == ""


# --- 5. the header -----------------------------------------------------------


def test_the_header_says_what_the_product_is() -> None:
    tk, _view = _shown()
    texts = tk.texts()

    assert PRODUCT_NAME in texts
    assert PRODUCT_TAGLINE in texts


def test_the_drag_handle_is_the_same_three_widgets_as_before() -> None:
    """The redesign rebuilt the header. It must not have moved the handle.

    A panel that can only be dragged by a strip the user cannot identify is
    the fault this tuple exists to prevent.
    """
    assert DRAG_HANDLE_WIDGETS == ("header", "state", "dot")

    tk, view = _shown()
    for name in DRAG_HANDLE_WIDGETS:
        widget = view._widgets[name]
        assert tk.handler_for(widget, "<Button-1>") is not None, name
        assert tk.handler_for(widget, "<B1-Motion>") is not None, name


def test_the_close_button_calls_the_same_handler_escape_does() -> None:
    """New affordance, no new behaviour: Escape already did exactly this."""
    tk, view = _shown()
    seen: list[str] = []
    view.on_close = lambda: seen.append("closed")

    tk.click(view._widgets["close"])

    assert seen == ["closed"]
    assert CLOSE_GLYPH in tk.texts()


def test_there_is_no_minimise_or_maximise() -> None:
    """Collapsing to the orb is already the gesture, and the panel is a
    WS_EX_TOOLWINDOW with no taskbar button to minimise to."""
    tk, _view = _shown()

    assert "–" not in tk.texts()
    assert "—" not in tk.texts()
    assert "□" not in tk.texts()


# --- 6. copy -----------------------------------------------------------------


def _clipboard(tk: Tk) -> list[str]:
    return [
        str(args[0])
        for _widget, method, args, _kwargs in tk.history
        if method == "clipboard_append" and args
    ]


def test_copy_puts_the_reply_on_the_clipboard() -> None:
    tk, view = _shown()
    view.set_reply("It is just past four.")

    tk.click(view._widgets["action_copy"])

    assert _clipboard(tk) == ["It is just past four."]


def test_copy_clears_the_clipboard_before_appending_to_it() -> None:
    """Otherwise the second copy appends to the first."""
    tk, view = _shown()
    view.set_reply("one")
    view.set_reply("two")

    tk.click(view._widgets["action_copy"])

    methods = [
        method
        for _widget, method, _args, _kwargs in tk.history
        if method.startswith("clipboard_")
    ]
    assert methods == ["clipboard_clear", "clipboard_append"]
    assert _clipboard(tk) == ["two"]


def test_copy_with_nothing_said_yet_copies_nothing() -> None:
    """Not an empty string on the clipboard -- the clipboard is left alone."""
    tk, view = _shown()

    tk.click(view._widgets["action_copy"])

    assert _clipboard(tk) == []


def test_clicking_the_word_copy_counts_as_clicking_the_button() -> None:
    """The caption covers the middle of the canvas it sits on."""
    tk, view = _shown()
    view.set_reply("the answer")

    tk.click(view._widgets["action_copy_label"])

    assert _clipboard(tk) == ["the answer"]


def test_a_clipboard_that_refuses_does_not_kill_the_window() -> None:
    tk, view = _shown()
    view.set_reply("the answer")

    def refuse(*_args, **_kwargs):
        raise RuntimeError("the clipboard is owned by something else")

    view.root.clipboard_clear = refuse

    tk.click(view._widgets["action_copy"])  # must not raise


def test_the_copy_button_explains_why_it_is_not_gated() -> None:
    """The action layer's clipboard actions are behind consent. This one is
    not, and the reason has to be written down where the next reader of this
    file will find it, not in a commit message.
    """
    import inspect

    from grandpa.ui.tk_view import TkBubbleView as View

    doc = inspect.getdoc(View._copy_reply) or ""

    assert "consent" in doc.lower() or "gate" in doc.lower()
    assert "Ctrl+C" in doc, "the precedent is that this is already possible"


# --- 7. read and stop --------------------------------------------------------


def test_read_asks_the_controller_to_speak_again() -> None:
    tk, view = _shown()
    seen: list[str] = []
    view.on_read = lambda: seen.append("read")

    tk.click(view._widgets["action_read"])

    assert seen == ["read"]
    assert ACTION_READ in tk.texts()


def test_stop_asks_the_controller_to_stop_speaking() -> None:
    tk, view = _shown()
    seen: list[str] = []
    view.on_stop_speaking = lambda: seen.append("stopped")

    tk.click(view._widgets["action_stop"])

    assert seen == ["stopped"]
    assert ACTION_STOP in tk.texts()
    assert ACTION_COPY in tk.texts()


@pytest.mark.parametrize("name", ["action_read", "action_stop"])
def test_an_unwired_action_button_does_nothing_rather_than_raising(name) -> None:
    """The view is usable without a controller -- every test here proves it."""
    tk, view = _shown()

    assert tk.click(view._widgets[name]) is None


@pytest.mark.parametrize(
    ("name", "callback"), [("action_read", "on_read"), ("action_stop", "on_stop_speaking")]
)
def test_a_handler_that_raises_does_not_reach_tk(name, callback) -> None:
    tk, view = _shown()

    def boom() -> None:
        raise RuntimeError("the speech engine is gone")

    setattr(view, callback, boom)

    tk.click(view._widgets[name])  # must not raise


def test_the_action_buttons_are_the_size_the_tokens_say() -> None:
    """``width=5`` on a Label is five characters, not forty pixels."""
    tk, view = _shown()

    for name in ("copy", "read", "stop"):
        button = view._widgets[f"action_{name}"]
        assert button.options.get("width") == ACTION_WIDTH, name
        assert button.options.get("height") == ACTION_HEIGHT, name


def test_the_action_buttons_have_a_visible_edge() -> None:
    tk, _view = _shown()
    outlines = {options.get("outline") for options in tk.polygons()}

    assert BORDER in outlines


# --- 8. the thinking pill ----------------------------------------------------


@pytest.mark.parametrize("state", ["thinking", "transcribing"])
def test_the_pill_appears_while_the_user_is_waiting(state) -> None:
    tk, view = _shown()
    view.set_transcript("what time is it")

    view.set_state(state, state)

    assert tk.packing(view._widgets["thinking"])[-1] == "pack"
    assert THINKING_TEXT in tk.texts()


@pytest.mark.parametrize("state", ["idle", "recording", "speaking", "error"])
def test_the_pill_is_gone_the_rest_of_the_time(state) -> None:
    tk, view = _shown()
    view.set_transcript("what time is it")
    view.set_state("thinking", "thinking")

    view.set_state(state, state)

    assert tk.packing(view._widgets["thinking"])[-1] == "pack_forget"


def test_no_pill_over_an_empty_conversation() -> None:
    """There is nothing to think about before anything was asked, and the
    empty state is not a place to stack a pill on."""
    tk, view = _shown()

    view.set_state("thinking", "thinking")

    assert tk.packing(view._widgets["thinking"])[-1] == "pack_forget"


def test_the_pill_takes_the_action_row_s_slot() -> None:
    """Measured: the conversation's six rows fill all but a dozen pixels of
    it, so a seventh row was mapped one pixel tall -- invisible exactly when
    the user is waiting. Both the pill and the action row are 22 tall, so
    sharing the slot shifts nothing."""
    tk, view = _shown()
    view.set_transcript("what time is it")

    view.set_state("thinking", "thinking")

    assert tk.packing(view._widgets["thinking"])[-1] == "pack"
    assert tk.packing(view._widgets["actions"])[-1] == "pack_forget"


def test_the_buttons_come_back_when_the_thinking_stops() -> None:
    tk, view = _shown()
    view.set_transcript("what time is it")
    view.set_state("thinking", "thinking")

    view.set_reply("It is just past four.")
    view.set_state("idle", "Standby")

    assert tk.packing(view._widgets["actions"])[-1] == "pack"
    assert tk.packing(view._widgets["thinking"])[-1] == "pack_forget"


def test_a_reply_arriving_mid_thought_does_not_leave_both() -> None:
    """set_reply re-packs every row, including the one the pill is using."""
    tk, view = _shown()
    view.set_transcript("what time is it")
    view.set_state("thinking", "thinking")

    view.set_reply("It is just past four.")

    packed = {
        name: tk.packing(view._widgets[name])[-1]
        for name in ("actions", "thinking")
    }
    assert sorted(packed.values()) == ["pack", "pack_forget"], packed


def test_the_header_ring_follows_the_state_too() -> None:
    """So the panel reads as the same object as the orb beside it."""
    from grandpa.ui.palette import RING_COLOURS

    tk, view = _shown()

    view.set_state("error", "error")

    recoloured = [
        (args, kwargs.get("outline"))
        for widget, method, args, kwargs in tk.history
        if widget is view._widgets["logo"] and method == "itemconfigure"
    ]
    assert ((view._logo_ring,), RING_COLOURS["error"]) in recoloured
    assert view._logo_ring is not None, "the ring's id was never kept"


# --- 9. the hint says only what is true --------------------------------------


def test_nothing_promises_a_shift_enter_that_does_not_work() -> None:
    """The design asked for "Shift + Enter for new line". The entry is a
    single-line Entry, so painting that line would be painting a lie."""
    tk, _view = _shown()

    for text in tk.texts():
        assert "Shift" not in text, text


def test_the_hint_says_how_to_send_and_how_to_talk() -> None:
    tk, view = _shown()
    hint = view.input_hint_text()

    assert hint in tk.texts()
    assert "Enter to send" in hint
    assert view.hold_hint_text() in hint


def test_the_hint_is_composed_from_the_one_producer_of_the_key_phrase() -> None:
    """Two places writing "hold F9" is how the window came to say SPACE for a
    whole release after the default changed."""
    view = TkBubbleView(tkinter_module=Tk(), hold_key="f8")

    assert "F8" in view.input_hint_text()
    assert view.hold_hint_text() == "hold F8"


def test_the_placeholder_names_the_box_rather_than_its_keyboard() -> None:
    assert PLACEHOLDER_ENTRY.strip()
    assert "Enter" not in PLACEHOLDER_ENTRY, "that moved to the hint line"


# --- 10. the timestamps are data, and say so ---------------------------------


def test_the_user_line_carries_the_time_and_that_it_was_sent() -> None:
    _tk, view = _shown()

    line = view.user_meta_text("what time is it", when="16:04")

    assert "16:04" in line
    assert "sent" in line
    assert "correct" in line, "the row is still clickable and must still say so"


def test_the_user_line_says_nothing_before_anything_was_heard() -> None:
    """No timestamp on a message that does not exist."""
    _tk, view = _shown()

    line = view.user_meta_text("")

    assert ":" not in line


def test_the_reply_line_names_the_speaker_and_the_time() -> None:
    _tk, view = _shown()

    line = view.reply_meta_text(when="16:05")

    assert "Grandpa" in line
    assert "16:05" in line


def test_the_clock_is_its_own_method_so_it_can_be_replaced() -> None:
    _tk, view = _shown()

    assert callable(view._now)
    assert ":" in view._now()


# --- 11. the wiring: stop must not queue behind the speech it stops ----------


def _assignments(path: str) -> dict[str, ast.AST]:
    """``view.on_read = ...`` -> {"on_read": the value expression}."""
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    found: dict[str, ast.AST] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "view"
            ):
                found[target.attr] = node.value
    return found


CLI = "src/grandpa/cli/bubble_cmd.py"


def test_read_is_wired_to_the_controller_off_the_tk_thread() -> None:
    """Speaking blocks for the length of the reply. On the tk thread that is a
    frozen window, which is why submit already goes to a worker."""
    value = _assignments(CLI).get("on_read")

    assert value is not None, "nothing wires the read button up"
    source = ast.dump(value)
    assert "_run_off_thread" in source
    assert "speak_again" in source


def test_stop_is_wired_straight_through_and_not_onto_the_worker() -> None:
    """The measured reason, not a preference.

    While a reply is being spoken the worker thread is inside
    ``speaker.speak``. ``_run_off_thread`` refuses a second job while one is
    running, so a stop sent that way would be dropped outright -- and even
    without the flag it would arrive only once the speech had finished. A stop
    that cannot stop anything is worse than no button.
    """
    value = _assignments(CLI).get("on_stop_speaking")

    assert value is not None, "nothing wires the stop button up"
    source = ast.dump(value)
    assert "interrupt_speech" in source
    assert "_run_off_thread" not in source


def test_the_width_the_command_passes_is_the_width_the_panel_draws() -> None:
    """The anchor, the clamp and the flip all take the size as a parameter.
    If the command passed the old 400 the panel would overlap the orb."""
    text = Path(CLI).read_text(encoding="utf-8")

    assert "tk_view.WIDTH" in text or "WIDTH" in text


# --- 12. the radius asked for is the radius drawn -----------------------------


def test_the_nominal_radius_is_corrected_before_it_is_drawn() -> None:
    """tk's spline cuts the corner far tighter than its control points say.

    Measured at four radii: 8, 14, 20 and 28 nominal produced 3.2, 5.6, 8.0
    and 10.4 visible logical pixels. So the control offset has to be larger
    than the radius a person is meant to see.
    """
    from grandpa.ui.tk_view import SPLINE_RADIUS_FACTOR

    assert SPLINE_RADIUS_FACTOR > 1.0

    points = TkBubbleView.rounded_points(0, 0, 400, 400, 10)
    xs = sorted(set(points[0::2]))

    assert xs == [0.0, 10 * SPLINE_RADIUS_FACTOR, 400 - 10 * SPLINE_RADIUS_FACTOR, 400]


def test_without_the_correction_the_corner_would_be_smaller() -> None:
    """The mutation, so the constant cannot be quietly set back to one."""
    corrected = TkBubbleView.rounded_points(0, 0, 400, 400, 10)
    raw = TkBubbleView.rounded_points(0, 0, 400, 400, 10, factor=1.0)

    assert corrected != raw
    assert sorted(set(corrected[0::2]))[1] > sorted(set(raw[0::2]))[1]


def test_the_correction_cannot_invert_a_small_shape() -> None:
    """The action pill asks for half its own height, which over-corrects well
    past the box. Clamping after the correction is what keeps it a pill."""
    points = TkBubbleView.rounded_points(
        0, 0, ACTION_WIDTH - 1, ACTION_HEIGHT - 1, ACTION_HEIGHT / 2
    )
    xs, ys = points[0::2], points[1::2]

    assert min(xs) >= 0 and max(xs) <= ACTION_WIDTH - 1
    assert min(ys) >= 0 and max(ys) <= ACTION_HEIGHT - 1
    # Fully round in the short direction, which is what a pill is.
    assert set(ys) == {0.0, (ACTION_HEIGHT - 1) / 2, float(ACTION_HEIGHT - 1)}


# --- 13. and on a real packer, everything has to fit -------------------------


@pytest.mark.environment(
    "opens a real tk window and asks the packer where every row landed; the "
    "only test that can see a row pushed off the bottom edge"
)
def test_a_full_panel_fits_the_window_it_is_drawn_in() -> None:
    """Measured, not modelled.

    The recorded-call tests see ``pack()`` being asked for. They cannot see
    what the packer did with it, and the packer is what decides. Two faults
    passed every other test in this file:

    * with everything packed from the top, one long reply pushed the status
      line off the bottom of the window and the action row was never mapped;
    * the thinking pill, packed as a seventh row, was mapped one pixel tall --
      present, invisible, and invisible exactly while the user is waiting for
      the thing it reports.

    **One window for both checks, deliberately.** Measured on this machine,
    creating and tearing down several Tk interpreters in one pytest process
    fails to bootstrap Tcl about two runs in five, and the failure lands on
    whichever test goes second. That flake predates this file -- the two
    environment tests that were already here fail at the same rate on their
    own -- but there is no reason to double it.
    """
    import time
    import tkinter

    from grandpa.ui.tk_view import HEIGHT

    def settle() -> None:
        # update() alone is not enough once the rows have no slack left: the
        # window manager needs real time to propagate geometry, and a tight
        # loop of forty updates measured the layout mid-flight. Without the
        # sleep this reads the pill at 7px on a panel where it is 23.
        for _ in range(40):
            view.root.update()
            time.sleep(0.004)

    rows = (
        "header", "meter", "convo", "user_row", "user_meta", "grandpa_row",
        "grandpa_meta", "input_row", "hold_hint", "status",
    )
    view = TkBubbleView(tkinter_module=tkinter, hold_key="ctrl+win")
    try:
        view.show(position=(300, 150), topmost=True)
        view.set_state("idle", "Standby")
        view.set_status_line("base.en  -  speech ready  -  orb: glow")
        view.set_transcript("what time is it in Chennai")
        view.set_reply(
            "It is 4:07 in the afternoon in Chennai. That is nine and a half "
            "hours ahead of London, so if you are calling someone there this "
            "evening they will already be well into tomorrow morning."
        )
        view.set_earlier((("remind me at six", "Set for six o'clock."),))
        settle()

        top = view.root.winfo_rooty()
        faults: list[str] = []

        def check(name: str) -> None:
            widget = view._widgets[name]
            if not widget.winfo_ismapped():
                faults.append(f"{name} is not mapped at all")
                return
            y = widget.winfo_rooty() - top
            height = widget.winfo_height()
            if y + height > HEIGHT:
                faults.append(f"{name} ends at {y + height} of {HEIGHT}")
            if height <= 2:
                faults.append(f"{name} was squashed to {height}px")

        for name in (*rows, "actions"):
            check(name)

        # And the same window again with the pill up, which takes the action
        # row's slot rather than adding one.
        view.set_state("thinking", "Thinking")
        settle()
        for name in (*rows, "thinking"):
            check(name)
        pill = view._widgets["thinking"]
        if pill.winfo_ismapped() and pill.winfo_height() <= 10:
            faults.append(f"the pill is {pill.winfo_height()}px tall")

        assert faults == [], "; ".join(faults)
    finally:
        view.close()
