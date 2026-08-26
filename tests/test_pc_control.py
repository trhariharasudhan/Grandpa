from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from grandpa import pc_control
from grandpa.desktop_context import DesktopContextResult
from grandpa.pc_control import run_local_action
from grandpa.windows_app_resolver import AppResolution
from grandpa.windows_window_control import WindowControlResult


@pytest.fixture(autouse=True)
def _isolated_pc_control(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "GRANDPA_LOCAL_ACTION_LOG", str(tmp_path / "local_actions.jsonl")
    )
    monkeypatch.setenv(
        "GRANDPA_PC_CONTROL_DB", str(tmp_path / "pc_control_approvals.db")
    )
    monkeypatch.setenv(
        "GRANDPA_PC_CONTROL_RETENTION_CONFIG", str(tmp_path / "retention.json")
    )
    monkeypatch.setenv(
        "GRANDPA_CLIPBOARD_HISTORY_DB", str(tmp_path / "clipboard_history.db")
    )
    pc_control.reset_emergency_stop()
    yield
    pc_control.reset_emergency_stop()


def _found_app(app_id: str = "notepad") -> AppResolution:
    return AppResolution(
        app_id,
        app_id.title(),
        "found",
        "command",
        f"{app_id}.exe",
        "test",
        "Found app.",
    )


def test_app_open_command_dry_run():
    result = run_local_action(
        {"action_type": "open_app", "target": "notepad", "dry_run": True}
    )

    assert result.ok is True
    assert result.status == "dry_run"
    assert result.risk_level == "LOW"


def test_installed_app_detection(monkeypatch):
    monkeypatch.setattr(
        "grandpa.windows_app_resolver.resolve_app", lambda _app: _found_app("chrome")
    )

    result = run_local_action({"action_type": "detect_app", "target": "chrome"})

    assert result.ok is True
    assert result.evidence["app_id"] == "chrome"


def test_vscode_opens_with_project_path_argument(monkeypatch, tmp_path: Path):
    project = tmp_path / "Grandpa"
    project.mkdir()
    launch_calls = []
    monkeypatch.setattr(
        "grandpa.windows_app_resolver.resolve_app", lambda _app: _found_app("vscode")
    )

    def fake_launch_app(name, *, args=None):
        launch_calls.append((name, args))
        return _found_app("vscode")

    monkeypatch.setattr("grandpa.windows_app_resolver.launch_app", fake_launch_app)

    result = run_local_action(
        {
            "action_type": "open_app",
            "target": "vscode",
            "args": {"project_path": str(project)},
        }
    )

    assert result.ok is True
    assert launch_calls == [("vscode", [str(project.resolve(strict=False))])]


def test_vscode_invalid_project_path_is_rejected(monkeypatch, tmp_path: Path):
    missing = tmp_path / "missing"
    monkeypatch.setattr(
        "grandpa.windows_app_resolver.resolve_app", lambda _app: _found_app("vscode")
    )
    monkeypatch.setattr(
        "grandpa.windows_app_resolver.launch_app",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("should not launch")
        ),
    )

    result = run_local_action(
        {
            "action_type": "open_app",
            "target": "vscode",
            "args": {"project_path": str(missing)},
        }
    )

    assert result.ok is False
    assert result.status == "blocked"
    assert result.error == "invalid_project_path"


def test_vscode_protected_project_path_is_blocked(monkeypatch, tmp_path: Path):
    project = tmp_path / "Grandpa"
    project.mkdir()
    monkeypatch.setattr(
        "grandpa.windows_app_resolver.resolve_app", lambda _app: _found_app("vscode")
    )
    monkeypatch.setattr("grandpa.pc_control._is_protected_path", lambda _path: True)

    result = run_local_action(
        {
            "action_type": "open_app",
            "target": "vscode",
            "args": {"project_path": str(project)},
        }
    )

    assert result.ok is False
    assert result.status == "blocked"
    assert result.error == "protected_project_path"


def test_grandpa_project_path_is_not_protected():
    assert pc_control._is_protected_path(Path(r"D:\Grandpa")) is False


@pytest.mark.parametrize(
    "path",
    [
        Path(r"C:\Windows"),
        Path(r"C:\Windows\System32"),
        Path(r"C:\Program Files"),
        Path(r"C:\Program Files (x86)\Common Files"),
        Path.home() / ".ssh",
        Path.home() / "AppData" / "Local" / "Google" / "Chrome" / "User Data",
        Path(r"C:\$Recycle.Bin"),
        Path(r"C:\System Volume Information"),
    ],
)
def test_true_windows_protected_paths_are_blocked(path: Path):
    assert pc_control._is_protected_path(path) is True


def test_normal_vscode_open_still_uses_no_project_argument(monkeypatch):
    launch_calls = []
    monkeypatch.setattr(
        "grandpa.windows_app_resolver.resolve_app", lambda _app: _found_app("vscode")
    )

    def fake_launch_app(name, *, args=None):
        launch_calls.append((name, args))
        return _found_app("vscode")

    monkeypatch.setattr("grandpa.windows_app_resolver.launch_app", fake_launch_app)

    result = run_local_action({"action_type": "open_app", "target": "vscode"})

    assert result.ok is True
    assert launch_calls == [("vscode", [])]


def test_blocked_unknown_app():
    result = run_local_action({"action_type": "open_app", "target": "unknown browser"})

    assert result.ok is False
    assert result.status == "blocked"


def test_close_app_dry_run():
    result = run_local_action(
        {"action_type": "close_app", "target": "notepad", "dry_run": True}
    )

    assert result.ok is True
    assert result.risk_level == "MEDIUM"


def test_window_action_no_window_found(monkeypatch):
    monkeypatch.setattr(
        "grandpa.windows_window_control.control_window",
        lambda _action, _target: WindowControlResult(
            "not_found", "focus", "notepad", "I could not find an open Notepad window."
        ),
    )

    result = run_local_action({"action_type": "focus_window", "target": "notepad"})

    assert result.ok is False
    assert result.status == "failed"
    assert result.error == "not_found"


def test_volume_action_mocked(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(pc_control.sys, "platform", "win32")
    monkeypatch.setitem(
        __import__("sys").modules,
        "pyautogui",
        SimpleNamespace(press=lambda key: calls.append(key)),
    )

    result = run_local_action({"action_type": "volume_up"})

    assert result.ok is True
    assert calls == ["volumeup"]


def test_volume_set_missing_backend_is_graceful(monkeypatch):
    monkeypatch.setattr(pc_control.sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "comtypes", None)
    monkeypatch.setitem(sys.modules, "pycaw", None)

    result = run_local_action(
        {"action_type": "volume_set", "target": "50", "args": {"level": 50}}
    )

    assert result.ok is False
    assert result.status == "unsupported"
    assert result.error == "missing_volume_backend"


def test_brightness_unsupported_path():
    result = run_local_action({"action_type": "brightness_get"})

    assert result.ok is False
    assert result.status == "unsupported"


def test_brightness_set_is_allowed_but_truthful_when_unsupported():
    result = run_local_action({"action_type": "brightness_set", "target": "50"})

    assert result.status in {"completed", "unsupported"}
    assert result.risk_level == "LOW"


def test_multi_monitor_detection(monkeypatch):
    monkeypatch.setattr(
        "grandpa.desktop_context.list_monitors",
        lambda: DesktopContextResult(
            True,
            "Detected 2 monitors.",
            {
                "count": 2,
                "monitors": [
                    {
                        "id": "monitor-1",
                        "left": 0,
                        "top": 0,
                        "width": 1920,
                        "height": 1080,
                        "primary": True,
                    },
                    {
                        "id": "monitor-2",
                        "left": 1920,
                        "top": 0,
                        "width": 1280,
                        "height": 1024,
                        "primary": False,
                    },
                ],
            },
        ),
        raising=False,
    )

    result = run_local_action({"action_type": "list_monitors"})

    assert result.ok is True
    assert result.evidence["count"] == 2


def test_active_process_awareness(monkeypatch):
    monkeypatch.setattr(
        "grandpa.desktop_context.get_active_process",
        lambda: DesktopContextResult(
            True,
            "Active process: notepad.exe.",
            {
                "process": {
                    "pid": 123,
                    "name": "notepad.exe",
                    "title": "Untitled - Notepad",
                    "executable": "notepad.exe",
                }
            },
        ),
        raising=False,
    )

    result = run_local_action({"action_type": "active_process"})

    assert result.ok is True
    assert result.evidence["process"]["name"] == "notepad.exe"


def test_clipboard_read_write_mocked(monkeypatch):
    clipboard = {"value": ""}
    monkeypatch.setitem(
        __import__("sys").modules,
        "pyperclip",
        SimpleNamespace(
            copy=lambda text: clipboard.update(value=text),
            paste=lambda: clipboard["value"],
        ),
    )

    write = run_local_action(
        {"action_type": "clipboard_write", "target": "secret text"}
    )
    read = run_local_action({"action_type": "clipboard_read"})

    assert write.ok is True
    assert read.evidence["clipboard_text"] == "secret text"
    log_text = Path(pc_control.get_audit_log_path()).read_text(encoding="utf-8")
    assert "secret text" not in log_text
    assert "[redacted]" in log_text


def test_clipboard_inspect_and_history_are_metadata_only(monkeypatch):
    clipboard = {"value": "https://example.com/private-token"}
    monkeypatch.setitem(
        __import__("sys").modules,
        "pyperclip",
        SimpleNamespace(
            copy=lambda text: clipboard.update(value=text),
            paste=lambda: clipboard["value"],
        ),
    )

    inspect_result = run_local_action({"action_type": "clipboard_inspect"})
    history = run_local_action({"action_type": "clipboard_history"})

    assert inspect_result.ok is True
    assert inspect_result.evidence["content_type"] == "url"
    assert history.ok is True
    assert history.evidence["metadata_only"] is True
    assert "private-token" not in json.dumps(history.evidence)


def test_safe_file_create_rename_move_copy(tmp_path):
    source = tmp_path / "note.txt"
    renamed = tmp_path / "renamed.txt"
    moved = tmp_path / "folder" / "moved.txt"
    copied = tmp_path / "copy.txt"

    assert run_local_action(
        {
            "action_type": "file_create",
            "target": str(source),
            "args": {"content": "hello"},
        }
    ).ok
    assert run_local_action(
        {
            "action_type": "file_rename",
            "target": str(source),
            "args": {"destination": str(renamed)},
        }
    ).ok
    assert run_local_action(
        {
            "action_type": "file_move",
            "target": str(renamed),
            "args": {"destination": str(moved)},
        }
    ).ok
    assert run_local_action(
        {
            "action_type": "file_copy",
            "target": str(moved),
            "args": {"destination": str(copied)},
        }
    ).ok
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
    result = run_local_action(
        {"action_type": "file_create", "target": "C:\\Windows\\grandpa-test.txt"}
    )

    assert result.status == "blocked"
    assert result.error == "protected_path"


def test_keyboard_mouse_dry_run():
    key = run_local_action(
        {"action_type": "keyboard_type", "target": "hello", "dry_run": True}
    )
    mouse = run_local_action(
        {"action_type": "mouse_click", "args": {"x": 10, "y": 20}, "dry_run": True}
    )

    assert key.ok is True
    assert mouse.ok is True
    assert key.risk_level == "MEDIUM"


def test_mouse_drag_dry_run():
    result = run_local_action(
        {
            "action_type": "mouse_drag",
            "args": {"start_x": 1, "start_y": 2, "end_x": 30, "end_y": 40},
            "dry_run": True,
        }
    )

    assert result.ok is True
    assert result.risk_level == "MEDIUM"


def test_protected_active_window_blocks_automation(monkeypatch):
    monkeypatch.setattr(pc_control.sys, "platform", "win32")
    monkeypatch.setattr(
        "grandpa.desktop_context.active_window_is_protected", lambda: True
    )

    result = run_local_action({"action_type": "keyboard_type", "target": "hello"})

    assert result.status == "blocked"
    assert result.error == "protected_window"


def test_desktop_session_summary(monkeypatch):
    monkeypatch.setattr(
        "grandpa.desktop_context.desktop_session_summary",
        lambda: DesktopContextResult(
            True,
            "Detected 1 monitor. Active process: chrome.exe.",
            {
                "monitors": {"count": 1},
                "active_process": {"name": "chrome.exe"},
                "process_count": 10,
            },
        ),
    )

    result = run_local_action({"action_type": "desktop_summary"})

    assert result.ok is True
    assert result.evidence["active_process"]["name"] == "chrome.exe"


def test_pc_control_diagnostics_contains_richer_sections(monkeypatch):
    monkeypatch.setattr(
        "grandpa.desktop_context.pc_control_diagnostics",
        lambda: {
            "monitors": {"supported": True, "count": 1},
            "active_process": {"supported": True},
            "automation": {"pyautogui": True},
            "clipboard": {"metadata_only": True},
        },
    )

    result = run_local_action({"action_type": "pc_diagnostics"})

    assert result.ok is True
    assert result.evidence["clipboard"]["metadata_only"] is True


def test_high_risk_power_command_requires_approval():
    result = run_local_action({"action_type": "system_shutdown"})

    assert result.status == "approval_required"
    assert result.risk_level == "HIGH"


def test_lock_pc_is_low_risk_dry_run():
    result = run_local_action({"action_type": "system_lock", "dry_run": True})

    assert result.ok is True
    assert result.risk_level == "LOW"


def test_empty_recycle_bin_requires_approval():
    result = run_local_action({"action_type": "empty_recycle_bin"})

    assert result.status == "approval_required"
    assert result.risk_level == "HIGH"


def _approval_code(action_id: str) -> str:
    """Read the out-of-band approval code a pending action was staged with.

    Production callers read this off the operator console; the HTTP API never
    returns it.
    """
    record = pc_control._load_pending_record(action_id)
    assert record is not None
    assert record.approval_token
    return record.approval_token


def test_approval_approve_reject_flow(tmp_path):
    target = tmp_path / "delete-me.txt"
    target.write_text("x", encoding="utf-8")
    pending = run_local_action({"action_type": "file_delete", "target": str(target)})

    rejected = pc_control.reject_local_action(pending.action_id or "")
    assert rejected.status == "rejected"
    assert target.exists()

    pending2 = run_local_action({"action_type": "file_delete", "target": str(target)})
    action_id = pending2.action_id or ""
    approved = pc_control.approve_local_action(action_id, _approval_code(action_id))
    assert approved.ok is True
    assert not target.exists()


def test_approval_requires_out_of_band_code(tmp_path):
    """An action_id alone must not authorise execution."""
    target = tmp_path / "delete-me.txt"
    target.write_text("x", encoding="utf-8")
    pending = run_local_action({"action_type": "file_delete", "target": str(target)})
    action_id = pending.action_id or ""
    code = _approval_code(action_id)

    no_code = pc_control.approve_local_action(action_id)
    assert no_code.ok is False
    assert no_code.error == "invalid_approval_token"
    assert target.exists()

    wrong_code = pc_control.approve_local_action(action_id, "DEADBEEF")
    assert wrong_code.ok is False
    assert wrong_code.error == "invalid_approval_token"
    assert target.exists()

    # A rejected attempt must not consume the pending action.
    approved = pc_control.approve_local_action(action_id, code)
    assert approved.ok is True
    assert not target.exists()


def test_pending_listing_does_not_leak_approval_code(tmp_path):
    target = tmp_path / "delete-me.txt"
    target.write_text("x", encoding="utf-8")
    pending = run_local_action({"action_type": "file_delete", "target": str(target)})
    code = _approval_code(pending.action_id or "")

    serialised = json.dumps(
        {
            "pending": pc_control.list_pending_actions(),
            "records": pc_control.list_approval_records(),
            "response": pending.to_dict(),
        },
        default=str,
    )
    assert code not in serialised
    assert "approval_token" not in serialised


def test_duplicate_approval_does_not_execute_twice(tmp_path):
    target = tmp_path / "delete-me.txt"
    target.write_text("x", encoding="utf-8")
    pending = run_local_action({"action_type": "file_delete", "target": str(target)})
    action_id = pending.action_id or ""
    code = _approval_code(action_id)

    first = pc_control.approve_local_action(action_id, code)
    second = pc_control.approve_local_action(action_id, code)
    rejected = pc_control.reject_local_action(action_id)

    assert first.ok is True
    assert second.ok is False
    assert second.error == "already_completed"
    assert rejected.ok is False
    assert rejected.error == "already_completed"


@pytest.mark.parametrize(
    "action_type",
    [
        "keyboard_type",
        "keyboard_hotkey",
        "mouse_click",
        "mouse_drag",
        "browser_form_fill",
        "browser_download",
    ],
)
def test_synthetic_input_actions_require_approval(action_type):
    """Synthetic input reaches arbitrary code execution, so it cannot run unattended."""
    result = run_local_action({"action_type": action_type, "target": "x"})

    assert result.status == "approval_required"
    assert result.approval_required is True
    assert result.action_id


@pytest.mark.parametrize(
    "keys",
    ["win+r", "Windows + R", "WIN+X", "ctrl+shift+esc", "ctrl+alt+delete"],
)
def test_command_surface_hotkeys_are_blocked_before_approval(keys):
    """A denied shortcut fails immediately rather than queuing for approval."""
    result = run_local_action({"action_type": "keyboard_hotkey", "target": keys})

    assert result.status == "blocked"
    assert result.error == "blocked_by_policy"
    assert result.action_id is None


def test_blocked_hotkey_cannot_be_smuggled_via_empty_keys():
    """An empty ``keys`` entry must not suppress the denylist check on ``target``."""
    result = run_local_action(
        {"action_type": "keyboard_hotkey", "target": "win+r", "args": {"keys": ""}}
    )

    assert result.status == "blocked"
    assert result.error == "blocked_by_policy"
    assert result.action_id is None


@pytest.mark.parametrize("keys", ["ctrl+c", "alt+tab", "win+d"])
def test_ordinary_hotkeys_still_reach_the_approval_gate(keys):
    result = run_local_action({"action_type": "keyboard_hotkey", "target": keys})

    assert result.status == "approval_required"


@pytest.mark.parametrize("action_type", ["mouse_move", "mouse_scroll"])
def test_pointer_only_actions_do_not_require_approval(action_type):
    """Moving or scrolling cannot commit an action, so it stays unattended."""
    result = run_local_action(
        {"action_type": action_type, "target": "0", "dry_run": True}
    )

    assert result.status == "dry_run"
    assert result.approval_required is False


def test_expired_approval_cannot_execute(tmp_path):
    target = tmp_path / "delete-me.txt"
    target.write_text("x", encoding="utf-8")
    pending = run_local_action({"action_type": "file_delete", "target": str(target)})
    with sqlite3.connect(pc_control.get_approval_db_path()) as conn:
        conn.execute(
            "UPDATE pc_control_approvals SET expires_at = ? WHERE action_id = ?",
            (time.time() - 1, pending.action_id),
        )

    approved = pc_control.approve_local_action(pending.action_id or "")

    assert approved.status == "expired"
    assert approved.error == "already_expired"
    assert target.exists()


def test_persistent_approval_reload(tmp_path):
    target = tmp_path / "delete-me.txt"
    target.write_text("x", encoding="utf-8")
    pending = run_local_action({"action_type": "file_delete", "target": str(target)})

    pending_after_reload = pc_control.list_pending_actions()

    assert pending_after_reload[0]["action_id"] == pending.action_id
    assert pending_after_reload[0]["status"] == "pending"
    assert Path(pc_control.get_approval_db_path()).exists()


def test_emergency_stop_cancels_pending_actions(tmp_path):
    target = tmp_path / "delete-me.txt"
    target.write_text("x", encoding="utf-8")
    pending = run_local_action({"action_type": "file_delete", "target": str(target)})

    stopped = pc_control.emergency_stop()
    approved = pc_control.approve_local_action(pending.action_id or "")
    records = pc_control.list_approval_records()

    assert stopped.evidence["cancelled_pending_actions"] == 1
    assert approved.ok is False
    assert records[0]["status"] == "cancelled"
    assert target.exists()


def test_audit_log_schema_redacts_clipboard(monkeypatch):
    monkeypatch.setitem(
        __import__("sys").modules,
        "pyperclip",
        SimpleNamespace(copy=lambda _text: None, paste=lambda: "sensitive clipboard"),
    )
    run_local_action(
        {"action_type": "clipboard_write", "target": "sensitive clipboard"}
    )

    line = (
        Path(pc_control.get_audit_log_path())
        .read_text(encoding="utf-8")
        .splitlines()[-1]
    )
    record = json.loads(line)
    assert record["target"] == "[redacted]"
    assert "sensitive clipboard" not in line


def test_recent_audit_entries_are_redacted(monkeypatch):
    monkeypatch.setitem(
        __import__("sys").modules,
        "pyperclip",
        SimpleNamespace(copy=lambda _text: None, paste=lambda: "sensitive clipboard"),
    )
    run_local_action(
        {"action_type": "clipboard_write", "target": "sensitive clipboard"}
    )

    entries = pc_control.read_recent_audit_entries()

    assert entries[-1]["target"] == "[redacted]"
    assert "sensitive clipboard" not in json.dumps(entries)


def test_retention_cleanup_removes_old_decided_records_but_keeps_pending(tmp_path):
    old_target = tmp_path / "old.txt"
    old_target.write_text("x", encoding="utf-8")
    old = run_local_action({"action_type": "file_delete", "target": str(old_target)})
    pc_control.reject_local_action(old.action_id or "")
    pending_target = tmp_path / "pending.txt"
    pending_target.write_text("x", encoding="utf-8")
    pending = run_local_action(
        {"action_type": "file_delete", "target": str(pending_target)}
    )
    old_time = time.time() - 40 * 86400
    with sqlite3.connect(pc_control.get_approval_db_path()) as conn:
        conn.execute(
            "UPDATE pc_control_approvals SET decision_timestamp = ?, created_at = ? WHERE action_id = ?",
            (old_time, old_time, old.action_id),
        )

    summary = pc_control.run_pc_control_maintenance()
    records = pc_control.list_approval_records()

    assert summary["deleted_approval_records"] == 1
    assert [record["action_id"] for record in records] == [pending.action_id]
    assert records[0]["status"] == "pending"


def test_expired_approval_preserved_until_retention_window(tmp_path):
    target = tmp_path / "delete-me.txt"
    target.write_text("x", encoding="utf-8")
    pending = run_local_action({"action_type": "file_delete", "target": str(target)})
    with sqlite3.connect(pc_control.get_approval_db_path()) as conn:
        conn.execute(
            "UPDATE pc_control_approvals SET expires_at = ? WHERE action_id = ?",
            (time.time() - 1, pending.action_id),
        )

    summary = pc_control.run_pc_control_maintenance()
    records = pc_control.list_approval_records()

    assert summary["expired_approvals"] == 1
    assert records[0]["status"] == "expired"
    assert target.exists()


def test_audit_log_rotation_keeps_newest_entries(monkeypatch, tmp_path):
    policy_path = Path(pc_control.get_retention_config_path())
    policy_path.write_text(
        json.dumps(
            {
                "approval_retention_days": 30,
                "audit_max_bytes": 100,
                "audit_keep_recent_lines": 2,
            }
        ),
        encoding="utf-8",
    )
    audit_path = Path(pc_control.get_audit_log_path())
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(
        "\n".join(
            json.dumps(
                {
                    "timestamp": i,
                    "action_type": "open_app",
                    "target": f"app-{i}",
                    "risk_level": "LOW",
                    "status": "completed",
                }
            )
            for i in range(5)
        )
        + "\n",
        encoding="utf-8",
    )

    summary = pc_control.run_pc_control_maintenance()
    entries = pc_control.read_recent_audit_entries(10)

    assert summary["audit_rotated"] is True
    assert summary["audit_kept_lines"] == 2
    assert [entry["target"] for entry in entries] == ["app-3", "app-4"]
    assert list(audit_path.parent.glob("local_actions.jsonl.*.gz"))


def test_corrupted_audit_entry_recovery():
    audit_path = Path(pc_control.get_audit_log_path())
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(
        "{not-json}\n"
        + json.dumps(
            {
                "timestamp": 1,
                "action_type": "open_app",
                "target": "notepad",
                "risk_level": "LOW",
                "status": "completed",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    entries = pc_control.read_recent_audit_entries()

    assert len(entries) == 1
    assert entries[0]["target"] == "notepad"
