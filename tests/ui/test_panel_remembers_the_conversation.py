"""Collapsed is voice-only, so the panel has to remember more than one thing.

**This file argued for a decision that has been reversed, and is rewritten
rather than patched.** It used to open:

    Three, not a scrolling log: the orb is the identity and a short exchange
    suits it. The current exchange keeps its two prominent panes and the
    earlier ones are one compact line each, above.

That was wrong in use. A new message pushed the old one away, the one-line
summary was not enough to recover it, and there was no way back. The panel
scrolls now and keeps up to ``EXCHANGE_MEMORY`` exchanges.

What survives from the old file is every property that was about *memory*
rather than about the strip:

* more than one exchange is remembered;
* questions asked while collapsed are all there when the panel is opened;
* what was said is kept beside what came back;
* a reply with no text is still an exchange;
* an empty submission records nothing;
* the bound is real, and the oldest goes first.

What is gone is everything about the one-line strip -- its row count, its
joining, its 58-character cut -- because there is no strip. Those tests were
not deleted for being inconvenient; the thing they described does not exist.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from grandpa.ui.bubble import EXCHANGE_MEMORY, BubbleController

pytestmark = pytest.mark.core


class FakePanel:
    """A panel that records, with no toolkit behind it.

    It has no ``set_earlier``: the view accumulates rows as transcripts and
    replies arrive, so there is nothing for the controller to push.
    """

    def __init__(self) -> None:
        self.reply = ""
        self.transcript = ""
        self.replies: list[str] = []
        self.transcripts: list[str] = []

    def show(self, *, position, topmost):
        pass

    def set_state(self, state, label):
        pass

    def set_status_line(self, text):
        pass

    def set_reply(self, text):
        self.reply = text
        self.replies.append(text)

    def set_transcript(self, text):
        self.transcript = text
        self.transcripts.append(text)

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


# --- 1. more than one is kept, and far more than three ------------------------


def test_several_exchanges_are_remembered(tmp_path: Path) -> None:
    """The original complaint, in its original form: ask three things while
    collapsed and all three are there when the panel opens."""
    controller, _panel = a_controller(tmp_path)

    for text in ("one", "two", "three"):
        controller.submit(text)

    assert controller.exchanges() == (
        ("one", "answer 1"), ("two", "answer 2"), ("three", "answer 3"),
    )


def test_the_fourth_no_longer_pushes_the_first_out(tmp_path: Path) -> None:
    """The reversal, as a test. With a memory of three this was
    ``test_the_fourth_pushes_the_first_out`` and it asserted the opposite."""
    controller, _panel = a_controller(tmp_path)

    for text in ("one", "two", "three", "four"):
        controller.submit(text)

    kept = [heard for heard, _reply in controller.exchanges()]

    assert kept == ["one", "two", "three", "four"]


def test_the_memory_is_bounded_even_so(tmp_path: Path) -> None:
    """Bounded, not unbounded. Each exchange is eight widgets on screen and
    nothing releases them on its own, so a long day must not grow forever."""
    assert EXCHANGE_MEMORY >= 50, "too short to be a scrollback"
    assert EXCHANGE_MEMORY <= 1000, "unbounded in all but name"

    controller, _panel = a_controller(tmp_path)
    for index in range(EXCHANGE_MEMORY + 5):
        controller.submit(f"q{index}")

    assert len(controller.exchanges()) == EXCHANGE_MEMORY


def test_the_oldest_is_what_goes_when_the_bound_is_reached(
    tmp_path: Path,
) -> None:
    controller, _panel = a_controller(tmp_path)

    for index in range(EXCHANGE_MEMORY + 3):
        controller.submit(f"q{index}")

    kept = [heard for heard, _reply in controller.exchanges()]

    assert kept[0] == "q3", "something other than the oldest was dropped"
    assert kept[-1] == f"q{EXCHANGE_MEMORY + 2}"


# --- 2. what is kept is both halves -------------------------------------------


def test_a_spoken_exchange_remembers_the_transcript(tmp_path: Path) -> None:
    """The point of keeping them: what you said, beside what came back."""
    controller, _panel = a_controller(tmp_path)
    controller._pending_heard = "what time is it"

    controller.submit("what time is it")

    assert controller.exchanges()[-1] == ("what time is it", "answer 1")


def test_a_typed_exchange_remembers_what_was_typed(tmp_path: Path) -> None:
    controller, _panel = a_controller(tmp_path)

    controller.submit("typed question")

    assert controller.exchanges()[-1][0] == "typed question"


def test_a_reply_with_no_text_is_still_an_exchange(tmp_path: Path) -> None:
    """Otherwise the scrollback would show a question with nothing after it."""

    class Empty:
        speech_ready = True

        def send(self, text):
            return Reply("")

    panel = FakePanel()
    controller = BubbleController(
        view=panel, bridge=Empty(), speak_replies=False
    )
    controller.start(position_path=tmp_path / "p.json")

    controller.submit("hello")

    assert len(controller.exchanges()) == 1
    assert controller.exchanges()[-1][1] == "(no reply)"


def test_an_empty_submission_records_nothing(tmp_path: Path) -> None:
    controller, _panel = a_controller(tmp_path)

    controller.submit("   ")

    assert controller.exchanges() == ()


# --- 3. and the panel is shown each one as it happens --------------------------


def test_every_exchange_reaches_the_panel_as_it_arrives(
    tmp_path: Path,
) -> None:
    """The view builds its rows from these calls and appends; it is never
    handed the whole history, because rebuilding 200 rows measured 6.8
    seconds against 44ms to append one."""
    controller, panel = a_controller(tmp_path)

    for text in ("one", "two", "three"):
        controller.submit(text)

    assert panel.replies == ["answer 1", "answer 2", "answer 3"]


def test_the_controller_does_not_push_a_history_list_at_all(
    tmp_path: Path,
) -> None:
    """The mechanical form of the same claim.

    ``set_earlier`` is gone. If it came back, so would the full-rebuild cost
    it implied, and this test is cheaper than measuring that again.
    """
    controller, panel = a_controller(tmp_path)

    controller.submit("hello")

    assert not hasattr(panel, "set_earlier")
    assert not hasattr(controller.view, "set_earlier")


def test_a_panel_missing_a_method_does_not_break_the_controller(
    tmp_path: Path,
) -> None:
    """An older view must still work: the controller probes before calling."""

    class Minimal:
        def show(self, *, position, topmost):
            pass

        def set_state(self, state, label):
            pass

        def set_status_line(self, text):
            pass

        def set_reply(self, text):
            pass

        def set_transcript(self, text):
            pass

        def clear_entry(self):
            pass

        def position(self):
            return (0, 0)

        def move_to(self, x, y):
            return True

        def close(self):
            pass

    controller = BubbleController(
        view=Minimal(), bridge=Bridge(), speak_replies=False
    )
    controller.start(position_path=tmp_path / "p.json")

    controller.submit("hello")  # must not raise

    assert len(controller.exchanges()) == 1
