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


# --- asking exactly when pc_control would --------------------------------------


def test_scrolling_does_not_ask(monkeypatch: pytest.MonkeyPatch) -> None:
    """pc_control excludes scrolling from approval: it cannot activate anything.

    Asking anyway looked stricter, and taught a user to answer yes without
    reading -- which is the opposite of what a prompt is for.
    """
    import grandpa.desktop.control.automation as automation

    class _Ok:
        ok = True
        message = "Scrolled."

    monkeypatch.setattr(
        automation.AutomationControlService,
        "execute",
        lambda self, request, action, platform: _Ok(),
    )
    asked: list[str] = []

    result = execute_spec("scroll|down", confirm_callback=lambda s, _t: asked.append(s))

    assert result.status == "handled"
    assert asked == []


def test_typing_still_asks_and_refuses_without_anyone_to_ask() -> None:
    assert execute_spec("type|hello").status == "blocked"


# --- the three specs Phase 1.6 broke -------------------------------------------
#
# Deleting grandpa.desktop_automation, the report said local_actions never built
# a chained spec. It does -- "type hello in notepad" becomes
# focus|notepad||type|hello -- and the claim came from searching for ";" rather
# than "||". click_center and move_center had no entry and answered "not
# supported" where they had worked.


@pytest.fixture
def recorded(monkeypatch: pytest.MonkeyPatch):
    import grandpa.desktop.control.automation as automation
    import grandpa.desktop.control.windows as windows

    calls: list[tuple[str, object]] = []

    class _Ok:
        ok = True
        message = "done"
        status = "completed"

    monkeypatch.setattr(
        automation.AutomationControlService,
        "execute",
        lambda self, request, action, platform: (
            calls.append((action, dict(request.args))) or _Ok()
        ),
    )
    monkeypatch.setattr(
        windows.WindowControlService,
        "execute",
        lambda self, request, action: calls.append((action, request.target)) or _Ok(),
    )
    return calls


def test_a_chain_runs_each_step_in_order(recorded) -> None:
    result = execute_spec("focus|notepad||type|hello", confirm_callback=lambda *_: True)

    assert result.status == "handled"
    assert recorded == [
        ("focus_window", "notepad"),
        ("keyboard_type", {"text": "hello"}),
    ]


def test_each_step_of_a_chain_is_confirmed_on_its_own(recorded) -> None:
    """Approving the focus is not approving the typing."""
    asked: list[str] = []

    result = execute_spec(
        "focus|notepad||type|hello",
        confirm_callback=lambda spec, _t: asked.append(spec) or False,
    )

    assert result.status == "cancelled"
    assert asked == ["type|hello"]
    assert ("keyboard_type", {"text": "hello"}) not in recorded


def test_click_center_clicks_the_middle_of_the_screen(recorded) -> None:
    result = execute_spec("click_center", confirm_callback=lambda *_: True)

    assert result.status == "handled"
    action, args = recorded[0]
    assert action == "mouse_click"
    assert set(args) == {"x", "y"}


def test_move_center_does_not_ask(recorded) -> None:
    asked: list[str] = []

    result = execute_spec("move_center", confirm_callback=lambda s, _t: asked.append(s))

    assert result.status == "handled"
    assert asked == []
    assert recorded[0][0] == "mouse_move"


def test_focus_brings_a_window_forward_instead_of_being_refused(recorded) -> None:
    result = execute_spec("focus|chrome")

    assert result.status == "handled"
    assert recorded == [("focus_window", "chrome")]


def test_click_highlighted_is_still_an_honest_refusal(recorded) -> None:
    result = execute_spec("click_highlighted", confirm_callback=lambda *_: True)

    assert result.status == "unsupported"
    assert "visual target detection" in result.message
    assert recorded == []
