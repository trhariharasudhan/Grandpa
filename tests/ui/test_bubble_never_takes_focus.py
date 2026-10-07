"""The bubble must never take focus, and that is asserted, not assumed.

A floating always-on-top window that grabs keystrokes is worse than no window:
the normal case is typing into something else while the bubble is visible. The
held key is read globally through ``GetAsyncKeyState``, so the bubble never needs
focus to hear a hold -- which is why the hotkey rather than the button is the
primitive, and why taking focus would be a pure cost.

The toolkit is injected, as ``grandpa.tray.start_tray`` takes ``pystray_module``.
A recorder stands in for tkinter and every call is inspected, so this is a
statement about the code rather than about a window someone looked at. No test
opens a window.
"""

from __future__ import annotations

import pytest

from grandpa.ui.tk_view import FOCUS_STEALING_CALLS, TkBubbleView

pytestmark = pytest.mark.core


class RecordingWidget:
    """Records every method call and attribute access made on it."""

    def __init__(self, calls: list[tuple[str, tuple, dict]], name: str = "widget"):
        self._calls = calls
        self._name = name

    def __getattr__(self, attribute: str):
        if attribute.startswith("_"):
            raise AttributeError(attribute)

        def record(*args, **kwargs):
            self._calls.append((f"{self._name}.{attribute}", args, kwargs))
            # Geometry readers have to return numbers.
            if attribute in {"winfo_x", "winfo_y"}:
                return 123
            if attribute == "get":
                return "typed text"
            return RecordingWidget(self._calls, f"{self._name}.{attribute}")

        return record


class RecordingTk:
    """A stand-in tkinter module. Opens nothing."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []

    def Tk(self, *args, **kwargs):  # noqa: N802 - mirrors tkinter's name
        self.calls.append(("Tk", args, kwargs))
        return RecordingWidget(self.calls, "root")

    def __getattr__(self, attribute: str):
        def factory(*args, **kwargs):
            self.calls.append((f"{attribute}", args, kwargs))
            return RecordingWidget(self.calls, attribute.lower())

        return factory


def _shown() -> RecordingTk:
    tk = RecordingTk()
    view = TkBubbleView(tkinter_module=tk)
    view.show(position=(40, 40), topmost=True)
    view.set_state("idle", "Ready")
    view.set_status_line("base.en  |  speech ready")
    view.set_transcript("open notepad")
    view.set_reply("Opening Notepad.")
    view.clear_entry()
    view.position()
    return tk


def _names(tk: RecordingTk) -> list[str]:
    return [name for name, _args, _kwargs in tk.calls]


# --- the guarantee -----------------------------------------------------------------


@pytest.mark.parametrize("forbidden", FOCUS_STEALING_CALLS)
def test_no_call_moves_focus_to_the_bubble(forbidden: str) -> None:
    """Checked per call so a failure names which one appeared."""
    names = _names(_shown())

    offenders = [name for name in names if name.endswith(f".{forbidden}")]

    assert offenders == [], (
        f"{forbidden} would move focus to the bubble; found {offenders}"
    )


def test_the_entry_is_out_of_the_tab_order() -> None:
    """Otherwise the window can acquire focus by being tabbed into."""
    tk = _shown()
    entries = [
        kwargs for name, _args, kwargs in tk.calls if name == "Entry"
    ]

    assert entries, "no Entry was created"
    assert entries[0].get("takefocus") is False


def test_the_forbidden_list_is_not_empty() -> None:
    """A parametrised test over an empty list passes without asserting anything."""
    assert len(FOCUS_STEALING_CALLS) >= 5
    assert "focus_force" in FOCUS_STEALING_CALLS
    assert "grab_set" in FOCUS_STEALING_CALLS


# --- and the window is what it claims to be ---------------------------------------


def test_it_is_borderless_and_always_on_top() -> None:
    tk = _shown()

    assert ("root.overrideredirect", (True,), {}) in tk.calls
    assert ("root.attributes", ("-topmost", True), {}) in tk.calls


def test_topmost_is_not_forced_when_the_caller_says_no() -> None:
    """The flag is a parameter, so a caller can opt out."""
    tk = RecordingTk()
    TkBubbleView(tkinter_module=tk).show(position=(0, 0), topmost=False)

    assert not any(
        name == "root.attributes" and args[:1] == ("-topmost",)
        for name, args, _kwargs in tk.calls
    )


def test_it_opens_at_the_position_it_was_given() -> None:
    tk = RecordingTk()
    TkBubbleView(tkinter_module=tk).show(position=(815, 442), topmost=True)

    geometry = [
        args[0] for name, args, _ in tk.calls if name == "root.geometry" and args
    ]

    assert any("+815+442" in str(value) for value in geometry), geometry


def test_the_header_is_draggable_because_there_is_no_title_bar() -> None:
    """overrideredirect removes the bar, so dragging has to be bound."""
    tk = _shown()
    bindings = [
        args[0] for name, args, _ in tk.calls if name.endswith(".bind") and args
    ]

    assert "<Button-1>" in bindings
    assert "<B1-Motion>" in bindings


def test_the_reply_pane_is_selectable_text_not_a_label() -> None:
    """A reply has to be copyable, and a disabled Text blocks selection."""
    tk = _shown()
    names = _names(tk)

    assert "Text" in names, "the reply pane must be a Text widget"
    text_kwargs = [kwargs for name, _args, kwargs in tk.calls if name == "Text"]
    assert text_kwargs[0].get("state") != "disabled", (
        "disabled would stop the user selecting the reply"
    )


def test_escape_closes_it() -> None:
    tk = _shown()
    bindings = [
        args[0] for name, args, _ in tk.calls if name == "root.bind" and args
    ]

    assert "<Escape>" in bindings


def test_nothing_is_imported_from_tkinter_when_a_module_is_injected() -> None:
    """The point of the injection: a test must not need a display.

    ``tk_view`` must not import tkinter at module scope, or importing the test
    file would already have done it.
    """
    import inspect

    from grandpa.ui import tk_view

    source = inspect.getsource(tk_view)
    header = source.split("@dataclass")[0]

    assert "import tkinter" not in header, (
        "tkinter is imported at module scope; it must be imported lazily"
    )
