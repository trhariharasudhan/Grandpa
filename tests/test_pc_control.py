from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from grandpa import pc_control
from grandpa.pc_control import run_local_action
from grandpa.windows_app_resolver import AppResolution
from grandpa.windows_window_control import WindowControlResult


@pytest.fixture(autouse=True)
def _isolated_pc_control(tmp_path, monkeypatch):
    monkeypatch.setenv("GRANDPA_LOCAL_ACTION_LOG", str(tmp_path / "local_actions.jsonl"))
    pc_control._PENDING_ACTIONS.clear()
    pc_control.reset_emergency_stop()
    yield
    pc_control._PENDING_ACTIONS.clear()
    pc_control.reset_emergency_stop()


def _found_app(app_id: str = "notepad") -> AppResolution:
    return AppResolution(app_id, app_id.title(), "found", "command", f"{app_id}.exe", "test", "Found app.")


def test_app_open_command_dry_run():
    result = run_local_action({"action_type": "open_app", "target": "notepad", "dry_run": True})

    assert result.ok is True
    assert result.status == "dry_run"
    assert result.risk_level == "LOW"


def test_installed_app_detection(monkeypatch):
    monkeypatch.setattr("grandpa.windows_app_resolver.resolve_app", lambda _app: _found_app("chrome"))

    result = run_local_action({"action_type": "detect_app", "target": "chrome"})

    assert result.ok is True
    assert result.evidence["app_id"] == "chrome"


def test_blocked_unknown_app():
    result = run_local_action({"action_type": "open_app", "target": "unknown browser"})

    assert result.ok is False
    assert result.status == "blocked"


def test_close_app_dry_run():
    result = run_local_action({"action_type": "close_app", "target": "notepad", "dry_run": True})

    assert result.ok is True
    assert result.risk_level == "MEDIUM"


def test_window_action_no_window_found(monkeypatch):
    monkeypatch.setattr(
        "grandpa.windows_window_control.control_window",
        lambda _action, _target: WindowControlResult("not_found", "focus", "notepad", "I could not find an open Notepad window."),
    )

    result = run_local_action({"action_type": "focus_window", "target": "notepad"})

    assert result.ok is False
    assert result.status == "failed"
    assert result.error == "not_found"


def test_volume_action_mocked(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(pc_control.sys, "platform", "win32")
    monkeypatch.setitem(__import__("sys").modules, "pyautogui", SimpleNamespace(press=lambda key: calls.append(key)))

    result = run_local_action({"action_type": "volume_up"})

    assert result.ok is True
    assert calls == ["volumeup"]


def test_brightness_unsupported_path():
    result = run_local_action({"action_type": "brightness_get"})

    assert result.ok is False
    assert result.status == "unsupported"


def test_brightness_set_is_allowed_but_truthful_when_unsupported():
    result = run_local_action({"action_type": "brightness_set", "target": "50"})

    assert result.status in {"completed", "unsupported"}
    assert result.risk_level == "LOW"


def test_clipboard_read_write_mocked(monkeypatch):
    clipboard = {"value": ""}
    monkeypatch.setitem(
        __import__("sys").modules,
        "pyperclip",
        SimpleNamespace(copy=lambda text: clipboard.update(value=text), paste=lambda: clipboard["value"]),
    )

    write = run_local_action({"action_type": "clipboard_write", "target": "secret text"})
    read = run_local_action({"action_type": "clipboard_read"})

    assert write.ok is True
    assert read.evidence["clipboard_text"] == "secret text"
    log_text = Path(pc_control.get_audit_log_path()).read_text(encoding="utf-8")
    assert "secret text" not in log_text
    assert "[redacted]" in log_text


def test_safe_file_create_rename_move_copy(tmp_path):
    source = tmp_path / "note.txt"
    renamed = tmp_path / "renamed.txt"
    moved = tmp_path / "folder" / "moved.txt"
    copied = tmp_path / "copy.txt"

    assert run_local_action({"action_type": "file_create", "target": str(source), "args": {"content": "hello"}}).ok
    assert run_local_action({"action_type": "file_rename", "target": str(source), "args": {"destination": str(renamed)}}).ok
    assert run_local_action({"action_type": "file_move", "target": str(renamed), "args": {"destination": str(moved)}}).ok
    assert run_local_action({"action_type": "file_copy", "target": str(moved), "args": {"destination": str(copied)}}).ok
    assert copied.read_text(encoding="utf-8") == "hello"


def test_delete_requires_approval(tmp_path):
    target = tmp_path / "delete-me.txt"
    target.write_text("x", encoding="utf-8")

    result = run_local_action({"action_type": "file_delete", "target": str(target)})

    assert result.status == "approval_required"
    assert result.approval_required is True
    assert target.exists()
    pending = pc_control.list_pending_actions()
    assert pending[0]["action_type"] == "file_delete"
    assert pending[0]["target"] == str(target)
    assert pending[0]["decision"] == "pending"


def test_protected_path_blocked():
    result = run_local_action({"action_type": "file_create", "target": "C:\\Windows\\grandpa-test.txt"})

    assert result.status == "blocked"
    assert result.error == "protected_path"


def test_keyboard_mouse_dry_run():
    key = run_local_action({"action_type": "keyboard_type", "target": "hello", "dry_run": True})
    mouse = run_local_action({"action_type": "mouse_click", "args": {"x": 10, "y": 20}, "dry_run": True})

    assert key.ok is True
    assert mouse.ok is True
    assert key.risk_level == "MEDIUM"


def test_high_risk_power_command_requires_approval():
    result = run_local_action({"action_type": "system_shutdown"})

    assert result.status == "approval_required"
    assert result.risk_level == "HIGH"


def test_approval_approve_reject_flow(tmp_path):
    target = tmp_path / "delete-me.txt"
    target.write_text("x", encoding="utf-8")
    pending = run_local_action({"action_type": "file_delete", "target": str(target)})

    rejected = pc_control.reject_local_action(pending.action_id or "")
    assert rejected.status == "rejected"
    assert target.exists()

    pending2 = run_local_action({"action_type": "file_delete", "target": str(target)})
    approved = pc_control.approve_local_action(pending2.action_id or "")
    assert approved.ok is True
    assert not target.exists()


def test_emergency_stop_cancels_pending_actions(tmp_path):
    target = tmp_path / "delete-me.txt"
    target.write_text("x", encoding="utf-8")
    pending = run_local_action({"action_type": "file_delete", "target": str(target)})

    stopped = pc_control.emergency_stop()
    approved = pc_control.approve_local_action(pending.action_id or "")

    assert stopped.evidence["cancelled_pending_actions"] == 1
    assert approved.ok is False
    assert target.exists()


def test_audit_log_schema_redacts_clipboard(monkeypatch):
    monkeypatch.setitem(
        __import__("sys").modules,
        "pyperclip",
        SimpleNamespace(copy=lambda _text: None, paste=lambda: "sensitive clipboard"),
    )
    run_local_action({"action_type": "clipboard_write", "target": "sensitive clipboard"})

    line = Path(pc_control.get_audit_log_path()).read_text(encoding="utf-8").splitlines()[-1]
    record = json.loads(line)
    assert record["target"] == "[redacted]"
    assert "sensitive clipboard" not in line


def test_recent_audit_entries_are_redacted(monkeypatch):
    monkeypatch.setitem(
        __import__("sys").modules,
        "pyperclip",
        SimpleNamespace(copy=lambda _text: None, paste=lambda: "sensitive clipboard"),
    )
    run_local_action({"action_type": "clipboard_write", "target": "sensitive clipboard"})

    entries = pc_control.read_recent_audit_entries()

    assert entries[-1]["target"] == "[redacted]"
    assert "sensitive clipboard" not in json.dumps(entries)
