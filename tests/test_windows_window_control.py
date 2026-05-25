from __future__ import annotations

import pytest

from grandpa import local_actions, windows_window_control
from grandpa.local_action_approvals import LocalActionApprovalStore
from grandpa.local_actions import handle_local_action
from grandpa.windows_window_control import WindowInfo, control_window


@pytest.fixture(autouse=True)
def _approval_store_fixture(tmp_path, monkeypatch):
    store = LocalActionApprovalStore(tmp_path / "approvals.db")
    monkeypatch.setattr(local_actions, "LocalActionApprovalStore", lambda: store)
    return store


def test_window_focus_command_is_allowed_without_execution():
    result = handle_local_action("focus notepad", execute=False)

    assert result.status == "handled"
    assert result.kind == "window"
    assert result.target == "focus|notepad"
    assert result.permission == "allowed"


def test_window_minimize_command_is_allowed_without_execution():
    result = handle_local_action("minimize chrome", execute=False)

    assert result.status == "handled"
    assert result.kind == "window"
    assert result.target == "minimize|chrome"
    assert result.permission == "allowed"


def test_window_close_command_requires_confirmation():
    result = handle_local_action("close notepad", execute=False)

    assert result.status == "requires_confirmation"
    assert result.kind == "window"
    assert result.target == "close|notepad"
    assert result.permission == "requires_confirmation"
    assert result.pending_action


def test_window_close_system_app_command_is_blocked():
    result = handle_local_action("close task manager", execute=False)

    assert result.status == "blocked"
    assert result.permission == "blocked"


def test_window_control_is_unsupported_off_windows(monkeypatch):
    monkeypatch.setattr(windows_window_control.sys, "platform", "linux")

    result = control_window("focus", "notepad")

    assert result.status == "unsupported"
    assert "only supported on Windows" in result.message


def test_window_control_reports_multiple_matches(monkeypatch):
    monkeypatch.setattr(windows_window_control.sys, "platform", "win32")
    monkeypatch.setattr(
        windows_window_control,
        "_list_windows",
        lambda: [
            WindowInfo(100, "notes - Notepad"),
            WindowInfo(101, "todo - Notepad"),
        ],
    )

    result = control_window("focus", "notepad")

    assert result.status == "multiple_matches"
    assert "multiple Notepad windows" in result.message


def test_window_control_blocks_closing_system_critical_window(monkeypatch):
    monkeypatch.setattr(windows_window_control.sys, "platform", "win32")
    monkeypatch.setattr(windows_window_control, "_get_foreground_window", lambda: 100)
    monkeypatch.setattr(
        windows_window_control,
        "_get_window_title",
        lambda _hwnd: "Task Manager",
    )

    result = control_window("close", "active")

    assert result.status == "blocked"
    assert "blocked" in result.message.lower()


def test_window_control_uses_graceful_window_operation(monkeypatch):
    calls: list[tuple[str, int]] = []
    monkeypatch.setattr(windows_window_control.sys, "platform", "win32")
    monkeypatch.setattr(
        windows_window_control,
        "_list_windows",
        lambda: [WindowInfo(100, "Untitled - Notepad")],
    )
    monkeypatch.setattr(
        windows_window_control,
        "_apply_action",
        lambda action, handle: calls.append((action, handle)),
    )

    result = control_window("minimize", "notepad")

    assert result.status == "handled"
    assert result.message == "Minimized Notepad."
    assert calls == [("minimize", 100)]
