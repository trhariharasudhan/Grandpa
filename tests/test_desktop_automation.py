from __future__ import annotations

import grandpa.desktop_automation as desktop_automation


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
