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
    """Including the two that cannot carry a text= kwarg at all."""
    tk, _view = _shown()
    inserted = " ".join(_inserted(tk))

    assert "Replies appear here" in inserted, "the reply pane is an empty box"
    assert PLACEHOLDER_ENTRY in inserted, "the text box has no placeholder"


def test_the_meter_is_drawn_at_rest_rather_than_left_blank() -> None:
    """Fixed a round earlier; pinned here with the rest of the pattern."""
    tk, _view = _shown()

    moved = [name for name, _a, _k in tk.calls if name.endswith(".coords")]

    assert len(moved) >= METER_BARS


def test_the_status_line_is_not_blank_at_construction() -> None:
    """It was non-blank only because the controller refreshes it immediately.

    That is the controller's good manners, not this widget's correctness.
    """
    tk, _view = _shown()

    assert "starting..." in _text_kwargs(tk)


# --- 2. the text box reads as a text box -----------------------------------------


def test_the_box_says_what_it_is_for() -> None:
    """The reported fault. "I had to ask what it was for"."""
    tk, _view = _shown()

    assert PLACEHOLDER_ENTRY in _inserted(tk)
    assert "press Enter" in PLACEHOLDER_ENTRY, "it should say how to send"


def test_the_box_has_a_visible_edge() -> None:
    """A borderless box the colour of the pane above it is not an input."""
    tk, _view = _shown()
    kwargs = next(k for n, _a, k in tk.calls if n == "Entry")

    assert kwargs["highlightthickness"] == 1
    assert kwargs["highlightbackground"]
    assert kwargs["highlightcolor"] == ACCENT, "and a focus colour"


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


def test_both_rows_are_captioned() -> None:
    """The reported need: telling "misheard me" from "misunderstood me".

    Two unlabelled blocks of text in one pane cannot be told apart, and the two
    need different fixes from the user -- speak differently, or rephrase.
    """
    tk, _view = _shown()
    texts = _text_kwargs(tk)

    assert CAPTION_HEARD in texts
    assert CAPTION_REPLY in texts


def test_the_heard_row_says_so_when_nothing_has_been_heard() -> None:
    tk, _view = _shown()

    assert EMPTY_HEARD in _text_kwargs(tk)


def test_a_transcript_lights_the_accent_edge() -> None:
    """So the row reads as live rather than as decoration."""
    tk, view = _shown()
    before = [k.get("bg") for _n, _a, k in tk.calls if k.get("bg") == ACCENT]

    view.set_transcript("hello grandpa good morning")

    lit = [
        k.get("bg")
        for n, _a, k in tk.calls
        if n.endswith(".configure") and k.get("bg") == ACCENT
    ]
    assert not before
    assert lit, "the accent edge did not light up"


def test_an_empty_transcript_restores_the_empty_state(tmp_path) -> None:
    """Rather than blanking the row, which made the layout jump."""
    tk, view = _shown()
    view.set_transcript("something")

    view.set_transcript("")

    configured = [
        k.get("text")
        for n, _a, k in tk.calls
        if n.endswith(".configure") and isinstance(k.get("text"), str)
    ]
    assert EMPTY_HEARD in configured
    assert configured[-1] in {EMPTY_HEARD, CAPTION_HEARD}


def test_the_transcript_is_quoted_so_it_reads_as_speech() -> None:
    tk, view = _shown()

    view.set_transcript("hello grandpa")

    quoted = [
        k.get("text")
        for n, _a, k in tk.calls
        if n.endswith(".configure") and isinstance(k.get("text"), str)
    ]
    assert any("hello grandpa" in value and "“" in value for value in quoted)


def test_an_empty_reply_restores_the_empty_state() -> None:
    tk, view = _shown()
    view.set_reply("an answer")

    view.set_reply("")

    assert any("Replies appear here" in value for value in _inserted(tk)[1:])


# --- 4. correcting a mis-heard transcript ----------------------------------------


def test_clicking_the_heard_row_loads_it_into_the_box() -> None:
    """One wrong word should not cost the whole sentence again.

    Reported: "An event by Good Morning." for "hello grandpa good morning" --
    the reply was right and the transcript was wrong, and the only remedy was
    saying all of it again.
    """
    tk, view = _shown()
    view.set_transcript("An event by Good Morning.")

    tk.handler_for(view._widgets["transcript"], "<Button-1>")(object())

    assert tk.entry_text[0] == "An event by Good Morning."
    assert view._placeholder_active is False


def test_clicking_with_nothing_heard_does_nothing() -> None:
    tk, view = _shown()

    tk.handler_for(view._widgets["transcript"], "<Button-1>")(object())

    assert tk.entry_text[0] == PLACEHOLDER_ENTRY


def test_a_loaded_transcript_can_be_submitted_as_a_correction() -> None:
    """It goes out through the ordinary submit path, so nothing new routes."""
    submitted: list[str] = []
    tk, view = _shown(on_submit=submitted.append)
    view.set_transcript("An event by Good Morning.")
    tk.handler_for(view._widgets["transcript"], "<Button-1>")(object())

    tk.entry_text[0] = "hello grandpa good morning"
    tk.bindings["<Return>"](object())

    assert submitted == ["hello grandpa good morning"]


def test_the_caption_says_the_row_can_be_corrected() -> None:
    """Discoverability: a clickable thing that does not say so is not clicked."""
    tk, view = _shown()

    view.set_transcript("something wrong")

    captions = [
        k.get("text")
        for n, _a, k in tk.calls
        if n.endswith(".configure") and isinstance(k.get("text"), str)
    ]
    assert any("click to correct" in value for value in captions)


def test_an_injected_handler_takes_precedence_over_the_default() -> None:
    received: list[str] = []
    tk, view = _shown(on_edit_transcript=received.append)
    view.set_transcript("misheard")

    tk.handler_for(view._widgets["transcript"], "<Button-1>")(object())

    assert received == ["misheard"]


def test_a_handler_that_raises_falls_back_to_loading_the_box() -> None:
    def explode(_text: str) -> None:
        raise RuntimeError("handler is broken")

    tk, view = _shown(on_edit_transcript=explode)
    view.set_transcript("misheard")

    tk.handler_for(view._widgets["transcript"], "<Button-1>")(object())

    assert tk.entry_text[0] == "misheard"


# --- 5. the constraints that have held all along ---------------------------------


def test_nothing_added_this_round_steals_focus() -> None:
    """Including set_entry_text, which is the obvious place to be tempted.

    Loading a correction into the box must not grab the caret: the window is
    on top of whatever the user is working in.
    """
    tk, view = _shown()
    view.set_transcript("misheard")
    tk.handler_for(view._widgets["transcript"], "<Button-1>")(object())
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
