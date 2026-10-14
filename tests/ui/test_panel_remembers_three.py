"""Collapsed is voice-only, so the panel has to remember more than one thing.

Three questions before opening the panel is an ordinary thing to do when the
orb is the whole interface, and with one slot the first two were simply gone --
``set_transcript`` and ``set_reply`` overwrite their labels. The conversation
survived in memory; the panel could not show it.

Three, not a scrolling log: the orb is the identity and a short exchange suits
it. The current exchange keeps its two prominent panes and the earlier ones are
one compact line each, above.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from grandpa.ui.bubble import EXCHANGE_MEMORY, BubbleController
from grandpa.ui.tk_view import EARLIER_JOIN, EARLIER_LIMIT, EARLIER_ROWS

pytestmark = pytest.mark.core


class FakePanel:
    def __init__(self) -> None:
        self.reply = ""
        self.transcript = ""
        self.earlier: tuple = ()

    def show(self, *, position, topmost):
        pass

    def set_state(self, state, label):
        pass

    def set_status_line(self, text):
        pass

    def set_reply(self, text):
        self.reply = text

    def set_transcript(self, text):
        self.transcript = text

    def set_earlier(self, rows):
        self.earlier = tuple(rows)

    def clear_entry(self):
        pass

    def set_entry_text(self, text):
        pass

    def set_levels(self, levels):
        pass

    def position(self):
        return (0, 0)

    def move_to(self, x, y):
        return True

    def hide(self):
        return True

    def unhide(self):
        return True

    def close(self):
        pass


class Reply:
    failed = False
    status = "ok"
    kind = None

    def __init__(self, text: str) -> None:
        self.text = text


class Bridge:
    speech_ready = True

    def __init__(self) -> None:
        self.count = 0

    def send(self, text):
        self.count += 1
        return Reply(f"answer {self.count}")


def a_controller(tmp_path: Path):
    panel = FakePanel()
    controller = BubbleController(
        view=panel, bridge=Bridge(), speak_replies=False
    )
    controller.start(position_path=tmp_path / "p.json")
    return controller, panel


# --- 1. three are kept --------------------------------------------------------


def test_three_exchanges_are_remembered(tmp_path: Path) -> None:
    controller, _panel = a_controller(tmp_path)

    for question in ("first", "second", "third"):
        controller.submit(question)

    assert controller.exchanges() == (
        ("first", "answer 1"),
        ("second", "answer 2"),
        ("third", "answer 3"),
    )


def test_the_fourth_pushes_the_first_out(tmp_path: Path) -> None:
    """Bounded, so a long session cannot grow it."""
    controller, _panel = a_controller(tmp_path)

    for question in ("one", "two", "three", "four"):
        controller.submit(question)

    assert len(controller.exchanges()) == EXCHANGE_MEMORY
    assert controller.exchanges()[0][0] == "two"
    assert controller.exchanges()[-1][0] == "four"


def test_the_memory_bound_is_three(tmp_path: Path) -> None:
    assert EXCHANGE_MEMORY == 3
    assert EARLIER_ROWS == EXCHANGE_MEMORY - 1


# --- 2. the panel is told about the earlier ones, newest first ---------------


def test_the_panel_is_given_the_earlier_exchanges_newest_first(
    tmp_path: Path,
) -> None:
    controller, panel = a_controller(tmp_path)

    controller.submit("first")
    controller.submit("second")
    controller.submit("third")

    assert panel.earlier == (("second", "answer 2"), ("first", "answer 1"))


def test_the_current_exchange_is_not_repeated_in_the_strip(
    tmp_path: Path,
) -> None:
    """It already has the two prominent panes; repeating it would read as
    having been asked twice."""
    controller, panel = a_controller(tmp_path)

    controller.submit("only")

    assert panel.earlier == ()
    assert panel.reply == "answer 1"


def test_the_first_exchange_shows_no_strip_at_all(tmp_path: Path) -> None:
    controller, panel = a_controller(tmp_path)

    controller.submit("hello")

    assert panel.earlier == ()


# --- 3. a spoken exchange records what was heard, not what was typed ---------


def test_a_spoken_exchange_remembers_the_transcript(tmp_path: Path) -> None:
    """The point of keeping them: what you said, beside what came back."""
    controller, panel = a_controller(tmp_path)
    controller._pending_heard = "open notepad please"

    controller.submit("open notepad please")

    assert controller.exchanges()[-1][0] == "open notepad please"


def test_a_typed_exchange_remembers_what_was_typed(tmp_path: Path) -> None:
    controller, _panel = a_controller(tmp_path)

    controller.submit("  what is the time  ")

    assert controller.exchanges()[-1] == ("what is the time", "answer 1")


def test_a_reply_with_no_text_is_still_remembered(tmp_path: Path) -> None:
    """Otherwise the strip would show a question with nothing after it."""

    class Empty:
        failed = False
        status = "ok"
        kind = None
        text = ""

    class EmptyBridge:
        speech_ready = True

        def send(self, text):
            return Empty()

    panel = FakePanel()
    controller = BubbleController(
        view=panel, bridge=EmptyBridge(), speak_replies=False
    )
    controller.start(position_path=tmp_path / "p.json")

    controller.submit("anything")

    assert controller.exchanges()[-1] == ("anything", "(no reply)")


def test_an_empty_submission_records_nothing(tmp_path: Path) -> None:
    controller, _panel = a_controller(tmp_path)

    controller.submit("   ")

    assert controller.exchanges() == ()


def test_a_panel_without_the_method_does_not_break_the_controller(
    tmp_path: Path,
) -> None:
    """The protocol gained a method; an older view must still work."""

    class Older(FakePanel):
        set_earlier = None

    panel = Older()
    controller = BubbleController(view=panel, bridge=Bridge(), speak_replies=False)
    controller.start(position_path=tmp_path / "p.json")

    controller.submit("hello")

    assert controller.exchanges()[-1][0] == "hello"


# --- 4. how a line reads ------------------------------------------------------


def test_an_exchange_becomes_one_line() -> None:
    from grandpa.ui.tk_view import TkBubbleView

    line = TkBubbleView.earlier_line("what is the time", "It is four o'clock.")

    assert EARLIER_JOIN.strip() in line
    assert "\n" not in line


def test_a_long_exchange_is_cut_rather_than_wrapped() -> None:
    """A compact reminder, not a second copy of the exchange."""
    from grandpa.ui.tk_view import TkBubbleView

    line = TkBubbleView.earlier_line("a" * 80, "b" * 80)

    assert len(line) <= EARLIER_LIMIT
    assert line.endswith("…")


def test_newlines_in_a_reply_do_not_become_a_tall_row() -> None:
    from grandpa.ui.tk_view import TkBubbleView

    line = TkBubbleView.earlier_line("ask", "one\ntwo\nthree")

    assert "\n" not in line


# --- 5. the panel builds no blank rows ---------------------------------------


def test_the_strip_is_absent_until_there_is_something_in_it() -> None:
    """The window's standing rule: nothing is present while saying nothing.
    The rows are built on first use, with their text."""
    from tests.ui.test_bubble_never_takes_focus import RecordingTk
    from grandpa.ui.tk_view import TkBubbleView

    tk = RecordingTk()
    view = TkBubbleView(tkinter_module=tk)
    view.show(position=(0, 0), topmost=True)

    assert view._earlier_rows == [], "rows were built before there was content"

    labels_before = sum(1 for name, _a, _k in tk.calls if name == "Label")
    view.set_earlier((("asked", "answered"),))
    labels_after = sum(1 for name, _a, _k in tk.calls if name == "Label")

    assert labels_after == labels_before + 1
    assert len(view._earlier_rows) == 1


def test_no_earlier_row_is_ever_created_blank() -> None:
    from tests.ui.test_bubble_never_takes_focus import RecordingTk
    from grandpa.ui.tk_view import TkBubbleView

    tk = RecordingTk()
    view = TkBubbleView(tkinter_module=tk)
    view.show(position=(0, 0), topmost=True)
    view.set_earlier((("a", "b"), ("c", "d")))

    blanks = [
        kwargs
        for name, _args, kwargs in tk.calls
        if name == "Label" and kwargs.get("text") == ""
    ]

    assert blanks == []


def test_showing_fewer_rows_hides_the_extras_rather_than_blanking_them() -> None:
    from tests.ui.test_bubble_never_takes_focus import RecordingTk
    from grandpa.ui.tk_view import TkBubbleView

    tk = RecordingTk()
    view = TkBubbleView(tkinter_module=tk)
    view.show(position=(0, 0), topmost=True)
    view.set_earlier((("a", "b"), ("c", "d")))

    view.set_earlier((("e", "f"),))

    forgotten = [name for name, _a, _k in tk.calls if name.endswith(".pack_forget")]

    assert forgotten, "the second row was left showing stale text"


def test_more_rows_than_there_is_room_for_are_dropped() -> None:
    from tests.ui.test_bubble_never_takes_focus import RecordingTk
    from grandpa.ui.tk_view import TkBubbleView

    tk = RecordingTk()
    view = TkBubbleView(tkinter_module=tk)
    view.show(position=(0, 0), topmost=True)

    view.set_earlier(tuple((f"q{i}", f"a{i}") for i in range(10)))

    assert len(view._earlier_rows) == EARLIER_ROWS
