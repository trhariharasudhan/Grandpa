"""The hold key must not reach the text box, and must not fail silently.

Reported: holding SPACE put a space in the bubble's own entry and recorded
nothing -- no indicator, no error. Two independent faults behind one symptom.

**1. The key reached the entry.** ``GetAsyncKeyState`` is global, which is why
hold-to-talk works over another window; but when the bubble itself has focus the
same keystroke is also delivered to its entry. Measured on a mapped window,
because the binding level decides whether it can be stopped:

    control: no "break", bound on the entry      entry 'ab '   not suppressed
    instance binding on the entry + "break"      entry 'ab'    SUPPRESSED
    binding on the toplevel + "break"            entry 'ab '   not suppressed

Tk resolves bindings in bindtags order -- ``('.!entry', 'Entry', '.', 'all')`` --
and the Entry's insertion *is* its class binding, so an instance binding runs
first and ``"break"`` stops it. A toplevel binding runs third, too late. And
swallowing cannot eat the global key: a KeyPress only reaches the focused
window, so with the bubble unfocused the binding never fires at all.

**2. The poller screened the press and returned quietly.** ``_hold_poller``
checked ``can_record()`` before calling ``on_hold()``, so while the model was
loading the explanation never ran. Silence is indistinguishable from a dead key.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from grandpa.cli.bubble_cmd import _hold_poller
from grandpa.ui.bubble import DEFAULT_HOLD_KEY, BubbleController, BubbleState
from grandpa.ui.tk_view import KEY_SYMS, TkBubbleView
from grandpa.voice.push_to_talk import KEY_CODES

pytestmark = pytest.mark.core


# --- a recorder standing in for tkinter -------------------------------------------


class RecordingWidget:
    def __init__(self, calls: list[tuple[str, tuple, dict]], name: str):
        self._calls = calls
        self._name = name

    def __getattr__(self, attribute: str):
        if attribute.startswith("_"):
            raise AttributeError(attribute)

        def record(*args, **kwargs):
            self._calls.append((f"{self._name}.{attribute}", args, kwargs))
            if attribute in {"winfo_x", "winfo_y"}:
                return 7
            if attribute == "get":
                return "typed"
            return RecordingWidget(self._calls, f"{self._name}.{attribute}")

        return record


class RecordingTk:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []
        self.entry_bindings: dict[str, Any] = {}

    def Tk(self, *args, **kwargs):  # noqa: N802 - mirrors tkinter
        self.calls.append(("Tk", args, kwargs))
        return RecordingWidget(self.calls, "root")

    def Entry(self, *args, **kwargs):  # noqa: N802 - mirrors tkinter
        self.calls.append(("Entry", args, kwargs))
        tk = self

        class Entry(RecordingWidget):
            def bind(self, sequence, handler=None, add=None):
                tk.calls.append(("entry.bind", (sequence,), {}))
                tk.entry_bindings[sequence] = handler
                return ""

        return Entry(self.calls, "entry")

    def __getattr__(self, attribute: str):
        def factory(*args, **kwargs):
            self.calls.append((attribute, args, kwargs))
            return RecordingWidget(self.calls, attribute.lower())

        return factory


def _shown(key: str = DEFAULT_HOLD_KEY) -> tuple[RecordingTk, TkBubbleView, list]:
    tk = RecordingTk()
    seen: list[int] = []
    view = TkBubbleView(
        tkinter_module=tk, hold_key=key, on_hold_key=lambda: seen.append(1)
    )
    view.show(position=(10, 10), topmost=True)
    return tk, view, seen


# --- 1. the key is bound on the entry, and swallowed -------------------------------


def test_the_hold_key_is_bound_on_the_entry_not_the_toplevel() -> None:
    """A toplevel binding fires after the insert, so it cannot suppress."""
    tk, _view, _seen = _shown("f9")

    assert "<KeyPress-F9>" in tk.entry_bindings
    toplevel = [
        args[0] for name, args, _ in tk.calls if name == "root.bind" and args
    ]
    assert "<KeyPress-F9>" not in toplevel


def test_the_handler_returns_break_so_the_character_is_suppressed() -> None:
    """"break" is what stops the Entry's class binding from inserting."""
    tk, _view, _seen = _shown("f9")

    handler = tk.entry_bindings["<KeyPress-F9>"]

    assert handler(object()) == "break"


def test_the_release_is_swallowed_too() -> None:
    """But only the release of a press that was itself swallowed."""
    tk, _view, _seen = _shown("f9")

    tk.entry_bindings["<KeyPress-F9>"](object())

    assert tk.entry_bindings["<KeyRelease-F9>"](object()) == "break"


def test_a_release_without_a_swallowed_press_is_let_through() -> None:
    """The combination case, from the other end.

    Binding Control_L for ``ctrl+win`` means this view sees the key-up of every
    ordinary Ctrl+C. Swallowing that unconditionally -- which is what the
    previous single-key code did -- would eat it.
    """
    tk, _view, _seen = _shown("f9")

    assert tk.entry_bindings["<KeyRelease-F9>"](object()) is None


def test_pressing_the_key_in_the_entry_reports_that_it_was_seen() -> None:
    """The half that stops silence: a swallowed key must still be announced."""
    tk, _view, seen = _shown("f9")

    tk.entry_bindings["<KeyPress-F9>"](object())

    assert seen == [1]


def test_a_callback_that_raises_does_not_break_the_keypress() -> None:
    tk = RecordingTk()
    view = TkBubbleView(
        tkinter_module=tk,
        hold_key="f9",
        on_hold_key=lambda: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    view.show(position=(0, 0), topmost=True)

    assert tk.entry_bindings["<KeyPress-F9>"](object()) == "break"


@pytest.mark.parametrize("key", sorted(KEY_CODES))
def test_every_offered_key_is_swallowed(key: str) -> None:
    """Including space, so the reported default is fixed and not merely avoided."""
    tk, _view, _seen = _shown(key)

    bound = [
        sequence
        for sequence in tk.entry_bindings
        if sequence.startswith("<KeyPress-")
    ]

    assert bound, f"{key} is not swallowed in the entry"
    for keysym in KEY_SYMS[key]:
        assert f"<KeyPress-{keysym}>" in tk.entry_bindings


def test_every_offered_key_has_a_keysym() -> None:
    """Otherwise a key could be selectable and unswallowable."""
    assert set(KEY_SYMS) == set(KEY_CODES)


def test_the_enter_binding_survives() -> None:
    """Swallowing must not have displaced submitting."""
    tk, _view, _seen = _shown("f9")

    assert "<Return>" in tk.entry_bindings


# --- 2. the default ----------------------------------------------------------------


def test_the_default_is_not_a_printable_key() -> None:
    """space typed into whatever had focus, including the bubble's own box.

    The default is a combination now, so the property is about every part of
    it: ``ctrl+space`` would be just as bad as ``space``.
    """
    from grandpa.voice.push_to_talk import parse_hold_key

    assert DEFAULT_HOLD_KEY == "ctrl+win"
    assert "space" not in parse_hold_key(DEFAULT_HOLD_KEY)


def test_the_default_is_not_a_lone_shortcut_modifier() -> None:
    """A global read means a lone ctrl fires on every Ctrl+C performed.

    Restated for combinations: a modifier may be *part* of the default, because
    the test is "all of these at once" and Ctrl+C never satisfies ctrl+win. What
    is still forbidden is a default that is one bare modifier.
    """
    from grandpa.voice.push_to_talk import parse_hold_key

    parts = parse_hold_key(DEFAULT_HOLD_KEY)

    assert parts != ("ctrl",)
    assert parts != ("shift",)
    assert parts != ("alt",)
    assert len(parts) > 1 or parts[0] not in {"ctrl", "shift", "alt"}


def test_the_default_is_not_f10() -> None:
    """F10 activates the menu bar in Win32 apps, the way Alt does."""
    assert DEFAULT_HOLD_KEY != "f10"


def test_the_controller_and_the_cli_agree_on_the_default() -> None:
    """Three places used to be able to disagree; now they read one constant."""
    import inspect

    from grandpa.cli import bubble_cmd

    assert BubbleController(view=None, bridge=None).key == DEFAULT_HOLD_KEY
    source = inspect.getsource(bubble_cmd.bubble.callback)
    assert "DEFAULT_HOLD_KEY" in source


def test_the_docs_name_the_same_default() -> None:
    """The README and both manual QA docs cannot drift from the code.

    This test passed throughout the release in which the bubble's own header
    read "hold SPACE": it reads files, and the window is not a file. The
    rendered-string tests in section 4 are the part that was missing, and the
    push-to-talk QA doc is here because all three commands now share the
    default rather than two of them defaulting to space.
    """
    from pathlib import Path

    import grandpa

    root = Path(grandpa.__file__).parents[2]
    docs = (
        ("README.md", "README"),
        ("docs/testing/desktop-ui-manual-qa.md", "bubble manual QA"),
        ("docs/testing/push-to-talk-manual-qa.md", "push-to-talk manual QA"),
    )

    from grandpa.voice.push_to_talk import describe_hold_key

    # Case-insensitively: prose writes "Ctrl+Win" and a UI chip writes
    # "CTRL+WIN", and both name the default. The earlier upper-case-only check
    # failed the README for capitalising a word normally.
    named = describe_hold_key(DEFAULT_HOLD_KEY).lower()

    for relative, label in docs:
        text = (root / relative).read_text(encoding="utf-8")
        assert named in text.lower(), f"{label} does not name the default"
        assert "hold SPACE anywhere" not in text, (
            f"{label} still tells the user to hold SPACE"
        )
        assert "hold F9 anywhere" not in text, (
            f"{label} still tells the user to hold F9"
        )


# --- 3. the poller hands the press over instead of screening it -------------------


@dataclass
class Probe:
    down: bool = True
    asked: int = 0

    def is_down(self, key: str) -> bool:
        self.asked += 1
        return self.down


@dataclass
class Recorder:
    calls: list[str] = field(default_factory=list)
    key: str = "f9"
    probe: Any = None
    state: BubbleState = BubbleState.LOADING

    def on_hold(self) -> str:
        self.calls.append("on_hold")
        return ""

    def can_record(self) -> bool:
        self.calls.append("can_record")
        return False


def test_the_poller_calls_on_hold_even_when_recording_is_refused() -> None:
    """The bug: it screened with can_record() and returned without a word.

    The refusals live in on_hold and each says why, so they only reach the user
    if on_hold is actually called.
    """
    controller = Recorder(probe=Probe(down=True))

    _hold_poller(controller)()

    assert "on_hold" in controller.calls


def test_the_poller_does_nothing_when_the_key_is_up() -> None:
    controller = Recorder(probe=Probe(down=False))

    _hold_poller(controller)()

    assert controller.calls == []


def test_the_poller_survives_a_probe_that_raises() -> None:
    class Exploding:
        def is_down(self, key: str) -> bool:
            raise OSError("user32 went away")

    controller = Recorder(probe=Exploding())

    _hold_poller(controller)()  # must not raise


def test_the_poller_without_a_probe_is_quiet() -> None:
    controller = Recorder(probe=None)

    _hold_poller(controller)()

    assert controller.calls == []


# --- 4. the window names the key it is actually using -----------------------------
#
# The gap this round closed. ``test_the_docs_name_the_same_default`` passed
# through the whole of the previous change while the header read "hold SPACE",
# because the view did not read the constant and the test did not read the view.


def _rendered_texts(tk: RecordingTk) -> list[str]:
    """Every string the window puts on screen, from the recorded widget calls."""
    return [
        kwargs["text"]
        for _name, _args, kwargs in tk.calls
        if isinstance(kwargs.get("text"), str) and kwargs["text"]
    ]


def test_the_header_names_the_default_key() -> None:
    """The reported bug, at the layer the user actually reads."""
    tk, _view, _seen = _shown()

    assert f"hold {DEFAULT_HOLD_KEY.upper()}" in _rendered_texts(tk)


@pytest.mark.parametrize("key", sorted(KEY_CODES))
def test_the_header_names_whichever_key_was_chosen(key: str) -> None:
    tk, _view, _seen = _shown(key)

    assert f"hold {key.upper()}" in _rendered_texts(tk)


@pytest.mark.parametrize("key", sorted(KEY_CODES))
def test_no_rendered_text_names_a_key_the_bubble_is_not_using(key: str) -> None:
    """The general form, so the next change of default cannot ship this bug.

    Any key name on screen must be the key in use. A hardcoded label fails here
    whichever key it names.
    """
    import re

    tk, _view, _seen = _shown(key)
    pattern = re.compile(
        r"\b(" + "|".join(sorted(KEY_CODES)) + r")\b", re.IGNORECASE
    )
    for text in _rendered_texts(tk):
        for found in pattern.findall(text):
            assert found.lower() == key, (
                f"the window shows {text!r} while the hold key is {key!r}"
            )


def test_the_view_has_no_second_copy_of_the_default() -> None:
    """``hold_key: str = "f9"`` was a second copy that happened to agree."""
    assert TkBubbleView().hold_key == DEFAULT_HOLD_KEY

    import inspect

    import grandpa.ui.tk_view as module

    source = inspect.getsource(module)
    assert "hold_key: str = DEFAULT_HOLD_KEY" in source


def test_the_view_names_no_key_in_a_string_literal() -> None:
    """Outside the keysym table, which is what the table is for.

    Comments and docstrings are excluded deliberately: the explanation of this
    bug necessarily contains the word SPACE, and a test that forbids explaining
    a decision is a test against documenting decisions.
    """
    import ast
    import re
    from pathlib import Path

    import grandpa.ui.tk_view as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    docstrings = {
        id(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
    }
    pattern = re.compile(
        r"\b(" + "|".join(sorted(KEY_CODES)) + r")\b", re.IGNORECASE
    )

    offenders: list[str] = []
    for node in tree.body:
        # The keysym table is allowed to name every key; that is its job.
        targets = []
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets = [node.target.id]
        elif isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if "KEY_SYMS" in targets:
            continue
        for sub in ast.walk(node):
            if (
                isinstance(sub, ast.Constant)
                and isinstance(sub.value, str)
                and id(sub) not in docstrings
                and pattern.search(sub.value)
            ):
                offenders.append(sub.value)

    assert not offenders, f"the view hardcodes a key name: {offenders}"


def test_the_command_help_names_the_default_key() -> None:
    """``--help`` is the first place a user looks, and it said SPACE.

    The docs test read the README and the manual QA. It did not read this.
    """
    from click.testing import CliRunner

    from grandpa.cli.bubble_cmd import bubble

    output = CliRunner().invoke(bubble, ["--help"]).output

    assert f"Hold {DEFAULT_HOLD_KEY.upper()} anywhere" in output
    assert f"[default: ({DEFAULT_HOLD_KEY})]" in output
    for other in KEY_CODES:
        if other != DEFAULT_HOLD_KEY:
            assert f"Hold {other.upper()} anywhere" not in output


def test_one_constant_feeds_every_command_that_takes_a_hold_key() -> None:
    """Three commands read a hold key and two of them defaulted to space.

    The constant lived in the UI package, so "one source" was one source for one
    command. It now lives beside ``KEY_CODES`` and the UI re-exports it.
    """
    from grandpa.cli.voice_cmd import voice
    from grandpa.voice.push_to_talk import DEFAULT_HOLD_KEY as from_voice

    assert from_voice is DEFAULT_HOLD_KEY, "the UI must re-export, not redefine"

    for name in ("push-to-talk", "accuracy-test"):
        command = voice.get_command(None, name)
        option = next(p for p in command.params if p.name == "key")
        assert option.default == DEFAULT_HOLD_KEY, (
            f"voice {name} --key defaults to {option.default!r}"
        )


# --- 5. a combination is swallowed, and only when it is the whole chord -----------
#
# Binding Control_L for ``ctrl+win`` means the entry sees the keystroke of every
# ordinary Ctrl+C. The predicate is what tells the two apart, and without it the
# fix for one bug would have created another.


def _shown_with(key: str, engaged: bool):
    tk = RecordingTk()
    seen: list[int] = []
    view = TkBubbleView(
        tkinter_module=tk,
        hold_key=key,
        on_hold_key=lambda: seen.append(1),
        combo_is_down=lambda: engaged,
    )
    view.show(position=(10, 10), topmost=True)
    return tk, view, seen


def test_every_part_of_a_combination_is_bound_on_the_entry() -> None:
    tk, _view, _seen = _shown("ctrl+win")

    for sequence in ("<KeyPress-Control_L>", "<KeyPress-Win_L>"):
        assert sequence in tk.entry_bindings, f"{sequence} was not bound"


def test_the_whole_combination_is_swallowed() -> None:
    tk, _view, seen = _shown_with("ctrl+win", engaged=True)

    assert tk.entry_bindings["<KeyPress-Control_L>"](object()) == "break"
    assert seen == [1], "a swallowed key must still be announced"


def test_one_part_of_a_combination_is_let_through() -> None:
    """Ctrl pressed on its own is an ordinary shortcut, not a hold."""
    tk, _view, seen = _shown_with("ctrl+win", engaged=False)

    assert tk.entry_bindings["<KeyPress-Control_L>"](object()) is None
    assert seen == [], "a key that was not ours must not be reported as seen"


def test_ctrl_still_copies_in_the_text_box() -> None:
    """The regression the predicate exists to prevent, stated as its own case."""
    tk, _view, _seen = _shown_with("ctrl+win", engaged=False)

    press = tk.entry_bindings["<KeyPress-Control_L>"](object())
    release = tk.entry_bindings["<KeyRelease-Control_L>"](object())

    assert press is None and release is None


def test_a_printable_part_of_a_combination_is_still_swallowed() -> None:
    """``--key ctrl+space`` must not put a space in the box."""
    tk, _view, _seen = _shown_with("ctrl+space", engaged=True)

    assert tk.entry_bindings["<KeyPress-space>"](object()) == "break"


def test_a_predicate_that_raises_does_not_swallow() -> None:
    """Failing open: a broken predicate must not eat the user's typing."""
    tk = RecordingTk()
    view = TkBubbleView(
        tkinter_module=tk,
        hold_key="ctrl+win",
        combo_is_down=lambda: (_ for _ in ()).throw(RuntimeError("probe died")),
    )
    view.show(position=(0, 0), topmost=True)

    assert tk.entry_bindings["<KeyPress-Control_L>"](object()) is None


def test_the_header_names_the_combination() -> None:
    tk, _view, _seen = _shown("ctrl+win")

    assert "hold CTRL+WIN" in _rendered_texts(tk)


def test_an_unusable_spec_binds_nothing_rather_than_crashing() -> None:
    tk = RecordingTk()
    view = TkBubbleView(tkinter_module=tk, hold_key="banana")
    view.show(position=(0, 0), topmost=True)

    assert not [k for k in tk.entry_bindings if "KeyPress" in k and "Return" not in k]
