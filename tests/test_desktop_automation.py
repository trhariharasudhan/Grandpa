"""Synthetic input, and the guards that now apply to every route to it.

This file used to test ``grandpa.desktop_automation``, a second implementation
of synthetic input reached by chat through ``local_actions``. It was deleted
when the two were given one owner, and the claims that still hold were moved
here to test the owner instead.

The claim that changed is the important one. The deleted module rated Win+R as
merely *confirm_required*: on a yes it opened the Run dialog. The surviving
service blocks it outright, because approving "press Win+R" is approving shell
access, which ``BLOCKED_ACTIONS`` exists to deny. Both directions are pinned
below.
"""

from __future__ import annotations

import pytest

from grandpa.desktop.control.automation import (
    AutomationControlService,
    execute_spec,
    is_blocked_hotkey,
    is_blocked_text,
)


class _Request:
    def __init__(self, target: str = "", **args: object) -> None:
        self.target = target
        self.args = dict(args)


@pytest.fixture(autouse=True)
def _no_cooldown(monkeypatch: pytest.MonkeyPatch) -> None:
    """The cooldown is real, and it is not what these tests are about."""
    monkeypatch.setattr(
        "grandpa.desktop.control.automation._cooldown_remaining", lambda: 0.0
    )


@pytest.fixture(autouse=True)
def _ordinary_window(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "grandpa.desktop_context.active_window_is_protected", lambda: False
    )


# --- the hotkeys the deleted module would have pressed -------------------------


@pytest.mark.parametrize(
    "keys", ["win+r", "win+x", "ctrl+shift+esc", "ctrl+alt+delete", "Windows+R"]
)
def test_command_execution_hotkeys_are_blocked_not_confirmed(keys: str) -> None:
    """The regression this merge exists to prevent.

    grandpa.desktop_automation classified these as confirm_required, so chat
    would press them on a yes. Approving a launcher is approving what it can
    launch.
    """
    assert is_blocked_hotkey(keys)

    result = execute_spec(f"hotkey|{keys}", confirm_callback=lambda *_: True)

    assert result.status == "blocked"
    assert "command-execution" in result.message


def test_an_ordinary_hotkey_is_not_blocked() -> None:
    assert not is_blocked_hotkey("ctrl+c")


# --- the text the surviving service did not used to check ----------------------


@pytest.mark.parametrize(
    "text",
    ["powershell", "cmd.exe", "format c:", "rm -rf /", "delete the system32 folder"],
)
def test_text_naming_a_shell_is_blocked(text: str) -> None:
    """Carried over from the deleted module, which had this and no hotkey list."""
    assert is_blocked_text(text)

    result = execute_spec(f"type|{text}", confirm_callback=lambda *_: True)

    assert result.status == "blocked"


def test_ordinary_text_is_not_blocked() -> None:
    assert not is_blocked_text("hello world")


# --- confirmation, unchanged ---------------------------------------------------


def test_typing_asks_first() -> None:
    asked: list[str] = []

    execute_spec("type|hello", confirm_callback=lambda spec, _tier: asked.append(spec))

    assert asked == ["type|hello"]


def test_declining_cancels_and_runs_nothing() -> None:
    result = execute_spec("type|hello", confirm_callback=lambda *_: False)

    assert result.status == "cancelled"


def test_no_one_to_ask_means_no() -> None:
    result = execute_spec("type|hello")

    assert result.status == "blocked"
    assert "Confirmation required" in result.message


def test_an_unknown_spec_is_refused_rather_than_guessed() -> None:
    result = execute_spec("teleport|home", confirm_callback=lambda *_: True)

    assert result.status == "unsupported"


# --- the protected window check, which the deleted module never had ------------


def test_a_sensitive_window_refuses_input(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "grandpa.desktop_context.active_window_is_protected", lambda: True
    )

    response = AutomationControlService().execute(
        _Request("hello", text="hello"), "keyboard_type", platform="win32"
    )

    assert response.ok is False
    assert response.error == "protected_window"


def test_input_is_unsupported_off_windows() -> None:
    response = AutomationControlService().execute(
        _Request("hello", text="hello"), "keyboard_type", platform="linux"
    )

    assert response.ok is False
    assert response.status == "unsupported"


# --- the cooldown --------------------------------------------------------------


def test_a_refusal_does_not_start_the_cooldown(monkeypatch: pytest.MonkeyPatch) -> None:
    """Otherwise one blocked hotkey makes the next honest request fail too."""
    marked: list[bool] = []
    monkeypatch.setattr(
        "grandpa.desktop.control.automation._mark_action",
        lambda: marked.append(True),
    )

    execute_spec("hotkey|win+r", confirm_callback=lambda *_: True)

    assert marked == []
