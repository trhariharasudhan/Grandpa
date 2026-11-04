"""The launcher menu, driven by real key bytes.

The reported defect was that pressing 1 exited instead of entering chat. The
audit that cleared it drove the launcher by feeding ACTION NAMES to a stubbed
run_interactive_menu, so keyboard dispatch was never under test -- it measured
the thing next to the thing that was reported.

These press bytes into prompt_toolkit's own input pipe, so the key bindings,
the key processor and the handler all run as they do under a real terminal.
Nothing in run_interactive_menu is stubbed. The only substitutions are
prompt_toolkit's input (a pipe instead of a tty) and its output (a dummy
instead of a screen), which is how prompt_toolkit tests itself.
"""

from __future__ import annotations

import io

import pytest
from prompt_toolkit.application import create_app_session
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput
from rich.console import Console

from grandpa.cli.launcher import run_interactive_menu

MENU = [
    ("1", "c", "Chat Assistant", "chat"),
    ("2", "v", "Voice Assistant", "voice"),
    ("3", "d", "Doctor / Health Check", "doctor"),
    ("4", "p", "Profile", "profile"),
    ("5", "s", "Settings", "settings"),
    ("6", "q", "Exit", "exit"),
]

DIGITS = [("1", "chat"), ("2", "voice"), ("3", "doctor"), ("4", "profile"),
          ("5", "settings"), ("6", "exit")]
LETTERS = [("c", "chat"), ("v", "voice"), ("d", "doctor"), ("p", "profile"),
           ("s", "settings"), ("q", "exit")]
ARROWS = [
    ("\r", "chat", "Enter on the first row"),
    ("\x1b[B\r", "voice", "Down then Enter"),
    ("\x1b[A\r", "exit", "Up from the top wraps to the last row"),
]


def press(keys: str) -> object:
    """Run the real picker with *keys* already queued."""
    # StringIO, not os.devnull: the suite's write guard refuses a real device,
    # and the menu's drawing is not what is under test here anyway.
    console = Console(file=io.StringIO(), width=100)
    with create_pipe_input() as pipe:
        pipe.send_text(keys)
        with create_app_session(input=pipe, output=DummyOutput()):
            return run_interactive_menu(console, "Choose a mode", MENU, "Tester", None)


@pytest.mark.parametrize(("key", "expected"), DIGITS)
def test_digit_selects_its_row(key: str, expected: str) -> None:
    assert press(key) == expected


@pytest.mark.parametrize(("key", "expected"), LETTERS)
def test_hotkey_letter_selects_its_row(key: str, expected: str) -> None:
    assert press(key) == expected


@pytest.mark.parametrize(("keys", "expected", "label"), ARROWS)
def test_arrow_navigation_and_enter(keys: str, expected: str, label: str) -> None:
    assert press(keys) == expected, label


def test_pressing_one_enters_chat_and_does_not_exit() -> None:
    """The reported defect, as its own named case.

    Covered by the parametrised digits too, but this is the sentence the bug
    report was written in, and it should fail by name if it ever comes back.
    """
    assert press("1") == "chat"
    assert press("1") != "exit"


def test_an_unrecognised_key_does_not_exit_or_swallow_the_next_one() -> None:
    """z is not one of the fifteen bound keys.

    The honest check is not "z returns None" -- it is that z leaves the menu
    standing, so the 1 that follows still selects chat. A menu that exited, or
    that consumed the next keystroke, fails this.
    """
    assert press("z1") == "chat"
