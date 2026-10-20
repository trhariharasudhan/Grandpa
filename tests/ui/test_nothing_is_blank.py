"""No surface of the bubble may be blank or unexplained on the first frame.

Reported: "The text box is an empty dark strip above the status line. I had to
ask what it was for." Auditing every element for the same fault found three
more, and the audit is the interesting part -- the reported one was not the
worst:

    Entry       no placeholder, highlightthickness=0 and bd=0, so it did not
                read as an input at all
    Text        the reply pane -- six lines of SURFACE-coloured nothing with
                expand=True, the largest thing in the window
    Label       the transcript -- text="" is zero-height, so the layout jumped
                the first time something was heard
    Label       the status -- blank at construction, non-blank only because
                controller.start() happens to refresh it immediately

The meter had the same fault and was fixed a round earlier, which is what
suggested looking for the pattern rather than the instance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from grandpa.ui.tk_view import (
    ACCENT,
    CAPTION_HEARD,
    CAPTION_REPLY,
    EMPTY_HEARD,
    FOCUS_STEALING_CALLS,
    METER_BARS,
    PLACEHOLDER_ENTRY,
    TkBubbleView,
)

pytestmark = pytest.mark.core


# --- a recorder standing in for tkinter -------------------------------------------


class RecordingWidget:
    def __init__(self, calls: list, name: str, owner: RecordingTk) -> None:
        self._calls = calls
        self._name = name
        self._owner = owner

    def bind(self, sequence, handler=None, add=None):
        """Kept per widget: <Button-1> is bound by the header for dragging and
        by the heard row for correcting, and they are different handlers."""
        self._calls.append((f"{self._name}.bind", (sequence,), {}))
        self._owner.bound.append((self, self._name, sequence, handler))
        return ""

    def __getattr__(self, attribute: str):
        if attribute.startswith("_"):
            raise AttributeError(attribute)

        def record(*args, **kwargs):
            self._calls.append((f"{self._name}.{attribute}", args, kwargs))
            if attribute in {"winfo_x", "winfo_y"}:
                return 7
            if attribute == "get":
                return self._owner.entry_text[0]
            return RecordingWidget(
                self._calls, f"{self._name}.{attribute}", self._owner
            )

        return record


@dataclass
class RecordingTk:
    calls: list = field(default_factory=list)
    #: (widget, name, sequence, handler) for every bind, in order. The widget
    #: itself, because every Label records under the name "label" and the
    #: header binds <Button-1> for dragging just as the heard row does for
    #: correcting.
    bound: list = field(default_factory=list)
    #: What ``entry.get()`` returns, so placeholder logic can be driven.
    entry_text: list = field(default_factory=lambda: [""])

    @property
    def bindings(self) -> dict:
        """Entry bindings by sequence, which is what most tests want."""
        return {
            sequence: handler
            for _widget, name, sequence, handler in self.bound
            if name == "entry"
        }

    def handler_for(self, widget: Any, sequence: str):
        """The handler *widget* bound for *sequence*, by identity."""
        for bound, _name, bound_sequence, handler in reversed(self.bound):
            if bound is widget and bound_sequence == sequence:
                return handler
        raise KeyError(f"that widget never bound {sequence}")

    def Entry(self, *args, **kwargs):  # noqa: N802 - mirrors tkinter
        self.calls.append(("Entry", args, kwargs))
        tk = self

        class Entry(RecordingWidget):
            def insert(self, index, text):
                tk.calls.append(("entry.insert", (index, text), {}))
                tk.entry_text[0] = str(text)

            def delete(self, first, last=None):
                tk.calls.append(("entry.delete", (first, last), {}))
                tk.entry_text[0] = ""

        return Entry(self.calls, "entry", self)

    def __getattr__(self, attribute: str):
        def factory(*args, **kwargs):
            self.calls.append((attribute, args, kwargs))
            return RecordingWidget(self.calls, attribute.lower(), self)

        return factory


def _shown(**kwargs) -> tuple[RecordingTk, TkBubbleView]:
    tk = RecordingTk()
    view = TkBubbleView(tkinter_module=tk, **kwargs)
    view.show(position=(10, 10), topmost=True)
    return tk, view


def _text_kwargs(tk: RecordingTk) -> list[str]:
    return [k.get("text") for _n, _a, k in tk.calls if isinstance(k.get("text"), str)]


def _inserted(tk: RecordingTk) -> list[str]:
    return [
        str(args[-1])
        for name, args, _k in tk.calls
        if name.endswith(".insert") and args
    ]


# --- 1. the audit, as a test ------------------------------------------------------


def test_no_widget_is_constructed_with_an_empty_string() -> None:
    """The general form of the fault, so the next element cannot ship with it.

    A widget built with ``text=""`` is invisible until something fills it, and
    a Label built that way has no height either, so the layout moves when it
    does.
    """
    tk, _view = _shown()

    blanks = [value for value in _text_kwargs(tk) if value == ""]

    assert blanks == [], f"{len(blanks)} widget(s) start blank"


def test_every_pane_has_content_by_the_time_show_returns() -> None:
    """Nothing on screen says nothing.

    The reply pane used to be checked here, as a Text with a placeholder in
    it. There is no reply pane any more: a reply is a row built when one
    arrives, and a row that does not exist cannot be blank -- which is the
    stronger form of the same property. What is left to check here is the
    box, and the empty state that stands in for a conversation before there
    is one.
    """
    tk, _view = _shown()
    inserted = " ".join(_inserted(tk))
    texts = [str(value) for value in _text_kwargs(tk)]

    assert PLACEHOLDER_ENTRY in inserted, "the text box has no placeholder"
    assert any("No messages yet" in value for value in texts), (
        "the empty conversation says nothing"
    )


def test_the_meter_is_drawn_at_rest_rather_than_left_blank() -> None:
    """Fixed a round earlier; pinned here with the rest of the pattern."""
    tk, _view = _shown()

    moved = [name for name, _a, _k in tk.calls if name.endswith(".coords")]

    assert len(moved) >= METER_BARS


def test_no_status_line_is_built_at_all_until_there_is_a_fault() -> None:
    """The always-present status line is gone, and nothing replaces it empty.

    It carried the model, the speech state, the microphone and the painter on
    every frame -- four facts wide, permanently there, and therefore read once
    and never again. What took its place appears only when something is
    wrong, and it is built at that moment, with its text. So there is never a
    widget present while saying nothing.

    That is the rule the test above enforces, applied to the one element it
    would have been most tempting to exempt from it.
    """
    tk, view = _shown()

    assert view._widgets.get("fault") is None
    assert "starting..." not in _text_kwargs(tk)


def test_a_fault_builds_the_line_and_shows_it() -> None:
    tk, view = _shown()

    view.set_status_line("orb falling back to a flat disc")

    assert view._widgets.get("fault") is not None
    assert "orb falling back to a flat disc" in _text_kwargs(tk)


def test_an_empty_fault_before_any_fault_builds_nothing() -> None:
    """The ordinary case: every status refresh, for the whole of a good run."""
    tk, view = _shown()

    view.set_status_line("")

    assert view._widgets.get("fault") is None


# --- 2. the text box reads as a text box -----------------------------------------


def test_the_box_says_what_it_is_for() -> None:
    """The reported fault. "I had to ask what it was for".

    The answer is split across two elements now -- the placeholder names what
    the box is, the line beneath it says how to send -- so the test checks
    both rather than requiring one string to carry everything. What it must
    not become is a box that says neither.
    """
    tk, _view = _shown()

    assert PLACEHOLDER_ENTRY in _inserted(tk)
    assert PLACEHOLDER_ENTRY.strip(), "the placeholder is empty"
    assert any(
        "Enter to send" in text for text in _text_kwargs(tk)
    ), "nothing tells the user how to send"


def test_the_box_has_a_visible_edge() -> None:
    """A borderless box the colour of the pane above it is not an input.

    The edge moved rather than went. The entry carried a one-pixel highlight
    ring in the accent colour, which is the thing that read as dated; it sits
    inside a rounded pill drawn on the canvas behind it now, and that pill's
    outline is the edge.
    """
    from grandpa.ui.tk_view import BORDER, SURFACE

    tk, view = _shown()
    kwargs = next(k for n, _a, k in tk.calls if n == "Entry")

    assert kwargs["highlightthickness"] == 0, "the old ring is still there"
    assert kwargs["bg"] == SURFACE, "the box is the colour of the pane"

    # The pill is drawn when the field is first laid out, which the recorder
    # does not do on its own -- so ask for it the way a <Configure> would.
    view._on_field_resized(type("E", (), {"width": 300})())
    outlines = {
        kwargs.get("outline")
        for name, _args, kwargs in tk.calls
        if name.endswith("create_polygon")
    }

    assert BORDER in outlines, "nothing draws the box an edge"


def test_the_placeholder_is_removed_when_the_box_is_clicked_into() -> None:
    tk, view = _shown()
    assert view._placeholder_active is True

    tk.bindings["<FocusIn>"](object())

    assert view._placeholder_active is False
    assert tk.entry_text[0] == ""


def test_the_placeholder_comes_back_when_the_box_is_left_empty() -> None:
    tk, view = _shown()
    tk.bindings["<FocusIn>"](object())

    tk.bindings["<FocusOut>"](object())

    assert view._placeholder_active is True
    assert tk.entry_text[0] == PLACEHOLDER_ENTRY


def test_the_placeholder_does_not_come_back_over_real_text() -> None:
    tk, view = _shown()
    tk.bindings["<FocusIn>"](object())
    tk.entry_text[0] = "what is the time"

    tk.bindings["<FocusOut>"](object())

    assert view._placeholder_active is False
    assert tk.entry_text[0] == "what is the time"


def test_the_placeholder_is_never_submitted() -> None:
    """Otherwise pressing Enter asks the assistant to answer our own prompt."""
    submitted: list[str] = []
    tk, view = _shown(on_submit=submitted.append)
    assert view._placeholder_active is True

    tk.bindings["<Return>"](object())

    assert submitted == []


def test_real_text_is_submitted() -> None:
    submitted: list[str] = []
    tk, _view = _shown(on_submit=submitted.append)
    tk.bindings["<FocusIn>"](object())
    tk.entry_text[0] = "what is the time"

    tk.bindings["<Return>"](object())

    assert submitted == ["what is the time"]


def test_clearing_the_box_restores_the_placeholder() -> None:
    """After a submit the box is emptied, and an empty box explains itself."""
    tk, view = _shown()
    tk.bindings["<FocusIn>"](object())
    tk.entry_text[0] = "something"

    view.clear_entry()

    assert view._placeholder_active is True
    assert tk.entry_text[0] == PLACEHOLDER_ENTRY


# --- 3. heard is visibly not the reply -------------------------------------------


def _last_row_label(view):
    """The Label inside the newest bubble, whatever row it ended up in."""
    return view._widgets.get("reply")


def test_both_speakers_are_labelled() -> None:
    """The reported need: telling "misheard me" from "misunderstood me".

    Two unlabelled blocks of text cannot be told apart, and the two need
    different fixes from the user -- speak differently, or rephrase. The
    labels are per-message meta lines now rather than two fixed captions, so
    they arrive with their messages.
    """
    tk, view = _shown()

    view.set_transcript("hello grandpa")
    view.set_reply("good morning")

    texts = [str(value) for value in _text_kwargs(tk)]

    assert any(CAPTION_HEARD in value for value in texts), texts
    assert any(CAPTION_REPLY in value for value in texts), texts


def test_an_empty_conversation_says_so() -> None:
    """What replaced "nothing heard yet" on a permanent row: an empty state
    for the whole conversation, which goes away the moment there is one."""
    tk, view = _shown()

    assert any(
        "No messages yet" in str(value) for value in _text_kwargs(tk)
    )


def test_the_user_bubble_is_drawn_in_the_user_colour() -> None:
    """What the accent edge was for.

    A three-pixel bar beside a permanent row said "this row is live". There
    is no permanent row: a message either exists as a bubble or it does not,
    and the bubble's own colour says whose it is.
    """
    from grandpa.ui.tk_view import BUBBLE_GRANDPA, BUBBLE_USER

    tk, view = _shown()

    view.set_transcript("hello grandpa good morning")
    view.set_reply("good morning to you")

    fills = {
        kwargs.get("fill")
        for name, _args, kwargs in tk.calls
        if name.endswith("create_polygon")
    }

    assert BUBBLE_USER in fills, "the user's message has no bubble"
    assert BUBBLE_GRANDPA in fills, "the reply has no bubble"
    assert BUBBLE_USER != BUBBLE_GRANDPA


def test_an_empty_transcript_creates_no_row_at_all() -> None:
    """Stronger than blanking one: there is nothing there to be blank.

    This used to assert that an empty transcript restored a placeholder on a
    reusable Label, because a zero-height label made the layout jump. A row
    that is never built cannot jump.
    """
    tk, view = _shown()

    view.set_transcript("")

    assert view.rows() == ()
    assert view._open_row is None


def test_the_transcript_is_quoted_so_it_reads_as_speech() -> None:
    tk, view = _shown()

    view.set_transcript("hello grandpa")

    quoted = [str(value) for value in _text_kwargs(tk)]

    assert any(
        "hello grandpa" in value and "\u201c" in value for value in quoted
    ), quoted


def test_an_empty_reply_adds_nothing() -> None:
    tk, view = _shown()
    view.set_transcript("a question")

    view.set_reply("")

    assert view.rows() == (), "an empty reply completed the exchange"


# --- 4. correcting a mis-heard transcript ----------------------------------------


def _click_transcript(tk, view):
    """Click whatever carries the newest transcript.

    By the handler rather than by a widget name: the transcript is a Label in
    a row now, and which widget it is is exactly the sort of thing this test
    should not care about.
    """
    for widget, _name, sequence, handler in reversed(tk.bound):
        if sequence == "<Button-1>" and handler == view._edit_transcript:
            return handler(object())
    raise AssertionError("nothing is bound to correct the transcript")


def test_clicking_the_heard_row_loads_it_into_the_box() -> None:
    """One wrong word should not cost the whole sentence again.

    Reported: "An event by Good Morning." for "hello grandpa good morning" --
    the reply was right and the transcript was wrong, and the only remedy was
    saying all of it again.
    """
    tk, view = _shown()
    view.set_transcript("An event by Good Morning.")

    _click_transcript(tk, view)

    assert tk.entry_text[0] == "An event by Good Morning."
    assert view._placeholder_active is False


def test_clicking_with_nothing_heard_does_nothing() -> None:
    """There is no row to click before anything is heard, so the handler is
    called directly: it must still refuse."""
    tk, view = _shown()

    view._edit_transcript(object())

    assert tk.entry_text[0] == PLACEHOLDER_ENTRY


def test_a_loaded_transcript_can_be_submitted_as_a_correction() -> None:
    sent: list[str] = []
    tk, view = _shown()
    view.on_submit = sent.append
    view.set_transcript("An event by Good Morning.")

    _click_transcript(tk, view)
    tk.entry_text[0] = "hello grandpa good morning"
    view._submit(object())

    assert sent == ["hello grandpa good morning"]


def test_the_meta_line_says_the_row_can_be_corrected() -> None:
    tk, view = _shown()

    view.set_transcript("something it got wrong")

    assert any(
        "correct" in str(value) for value in _text_kwargs(tk)
    ), "nothing tells the user the row can be fixed"


def test_an_injected_handler_takes_precedence_over_the_default() -> None:
    seen: list[str] = []
    tk, view = _shown()
    view.on_edit_transcript = seen.append
    view.set_transcript("wrong words")

    _click_transcript(tk, view)

    assert seen == ["wrong words"]


def test_a_handler_that_raises_falls_back_to_loading_the_box() -> None:
    def boom(_text: str) -> None:
        raise RuntimeError("the handler is broken")

    tk, view = _shown()
    view.on_edit_transcript = boom
    view.set_transcript("wrong words")

    _click_transcript(tk, view)

    assert tk.entry_text[0] == "wrong words"


def test_nothing_added_this_round_steals_focus() -> None:
    """Including set_entry_text, which is the obvious place to be tempted.

    Loading a correction into the box must not grab the caret: the window is
    on top of whatever the user is working in.
    """
    tk, view = _shown()
    view.set_transcript("misheard")
    _click_transcript(tk, view)
    view.set_entry_text("a correction")

    offenders = [
        name
        for name, _a, _k in tk.calls
        if any(name.endswith("." + bad) for bad in FOCUS_STEALING_CALLS)
    ]

    assert offenders == []


def test_the_entry_is_still_out_of_the_tab_order() -> None:
    tk, _view = _shown()
    kwargs = next(k for n, _a, k in tk.calls if n == "Entry")

    assert kwargs["takefocus"] is False


def test_the_hold_key_is_still_swallowed_in_the_box() -> None:
    """The new bindings must not have displaced the old ones."""
    tk, _view = _shown(hold_key="ctrl+win", combo_is_down=lambda: True)

    assert tk.bindings["<KeyPress-Control_L>"](object()) == "break"
