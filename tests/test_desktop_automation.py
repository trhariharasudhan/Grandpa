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


def test_automation_unsupported_off_windows(monkeypatch):
    monkeypatch.setattr(desktop_automation.sys, "platform", "linux")

    result = desktop_automation.execute_automation("type|hello")

    assert result.status == "unsupported"
    assert "not supported" in result.message


def test_sensitive_typing_requires_confirmation():
    assert desktop_automation.requires_confirmation("type|my password is secret")


def test_plain_typing_does_not_require_confirmation():
    assert not desktop_automation.requires_confirmation("type|hello")


def test_emergency_stop_placeholder_exists():
    text = desktop_automation.emergency_stop_placeholder()

    assert "Emergency stop" in text
    assert "failsafe" in text


def test_chained_pyautogui_actions_execute_in_order():
    fake = FakePyAutoGUI()

    result = desktop_automation._execute_with_pyautogui(
        fake,
        "type|hello||press|enter",
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
    )

    assert result.status == "unsupported"
    assert result.action == "dance|now"
    assert result.message == "That desktop automation action is not supported."
    assert fake.calls == [("write", "hello", 0.01)]
