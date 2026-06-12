from __future__ import annotations

import pytest

import grandpa.desktop_automation as desktop_automation

pytestmark = pytest.mark.core


class FakePyAutoGUI:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def write(self, text: str, interval: float = 0.0) -> None:
        self.calls.append(("write", text, interval))

    def press(self, key: str) -> None:
        self.calls.append(("press", key))

    def hotkey(self, *keys: str) -> None:
        self.calls.append(("hotkey", keys))

    def size(self) -> tuple[int, int]:
        self.calls.append(("size", None))
        return (100, 80)


def test_automation_unsupported_off_windows(monkeypatch):
    monkeypatch.setattr(desktop_automation.sys, "platform", "linux")

    result = desktop_automation.execute_automation("type|hello")

    assert result.status == "unsupported"
    assert "not supported" in result.message


def test_sensitive_typing_is_blocked():
    spec = "type|my password is secret"

    assert not desktop_automation.requires_confirmation(spec)
    assert desktop_automation.classify_automation_permission(spec) == "blocked"


def test_plain_typing_requires_confirmation():
    assert desktop_automation.requires_confirmation("type|hello")


def test_emergency_stop_placeholder_exists():
    text = desktop_automation.emergency_stop_placeholder()

    assert "Emergency stop" in text
    assert "failsafe" in text


def test_chained_pyautogui_actions_execute_in_order():
    fake = FakePyAutoGUI()

    result = desktop_automation._execute_with_pyautogui(
        fake,
        "type|hello||press|enter",
        confirmed=True,
    )

    assert result.status == "handled"
    assert result.action == "type|hello||press|enter"
    assert result.message == 'Typed "hello". Pressed enter.'
    assert result.tts_text == "Done."
    assert fake.calls == [
        ("write", "hello", 0.01),
        ("press", "enter"),
    ]


def test_chained_pyautogui_actions_stop_on_unsupported_action():
    fake = FakePyAutoGUI()

    result = desktop_automation._execute_with_pyautogui(
        fake,
        "type|hello||dance|now||press|enter",
        confirmed=True,
    )

    assert result.status == "unsupported"
    assert result.action == "dance|now"
    assert result.message == "That desktop automation action is not supported."
    assert fake.calls == [("write", "hello", 0.01)]


def test_safe_action_executes_without_confirmation():
    fake = FakePyAutoGUI()

    result = desktop_automation._execute_with_pyautogui(fake, "focus|chrome")

    assert result.status == "handled"
    assert result.message == "Tried to switch focus toward Chrome."
    assert fake.calls == [("hotkey", ("alt", "tab"))]


@pytest.mark.parametrize(
    "spec",
    [
        "type|hello",
        "click_center",
        "press|enter",
        "hotkey|ctrl+c",
    ],
)
def test_risky_actions_require_confirmation(spec):
    fake = FakePyAutoGUI()

    result = desktop_automation._execute_with_pyautogui(fake, spec)

    assert result.status == "cancelled"
    assert result.action == spec
    assert "Confirmation required" in result.message
    assert fake.calls == []


def test_confirmed_risky_action_executes():
    fake = FakePyAutoGUI()

    result = desktop_automation._execute_with_pyautogui(
        fake,
        "type|hello",
        confirm_callback=lambda spec, permission: permission == "confirm_required",
    )

    assert result.status == "handled"
    assert fake.calls == [("write", "hello", 0.01)]


def test_denied_confirmation_returns_cancelled_result():
    fake = FakePyAutoGUI()

    result = desktop_automation._execute_with_pyautogui(
        fake,
        "click_center",
        confirm_callback=lambda spec, permission: False,
    )

    assert result.status == "cancelled"
    assert fake.calls == []


def test_chained_commands_stop_if_one_action_is_denied():
    fake = FakePyAutoGUI()

    def confirm(spec: str, permission: str) -> bool:
        return spec != "press|enter"

    result = desktop_automation._execute_with_pyautogui(
        fake,
        "type|hello||press|enter||type|world",
        confirm_callback=confirm,
    )

    assert result.status == "cancelled"
    assert result.action == "press|enter"
    assert fake.calls == [("write", "hello", 0.01)]


@pytest.mark.parametrize(
    ("spec", "permission"),
    [
        ("shell|dir", "dangerous"),
        ("delete|system32", "blocked"),
        ("run_command|format d:", "blocked"),
    ],
)
def test_unknown_or_dangerous_command_does_not_execute_silently(spec, permission):
    fake = FakePyAutoGUI()

    result = desktop_automation._execute_with_pyautogui(fake, spec)

    assert desktop_automation.classify_automation_permission(spec) == permission
    assert result.status in {"blocked", "cancelled"}
    assert fake.calls == []
