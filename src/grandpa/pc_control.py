"""Unified safe PC control layer for Grandpa.

The public entry points in this module separate action planning, risk
classification, approval, execution, and audit logging. Tests use dry-run and
mocked OS calls so dangerous operations never run during validation.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
import threading
import time
import uuid
import gzip
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from grandpa.core.config import DEFAULT_CONFIG_DIR

RiskLevel = Literal["LOW", "MEDIUM", "HIGH", "BLOCKED"]
ActionStatus = Literal[
    "completed",
    "dry_run",
    "approval_required",
    "rejected",
    "blocked",
    "unsupported",
    "failed",
    "expired",
]

RUNTIME_DIR = Path("runtime")
AUDIT_LOG_PATH = RUNTIME_DIR / "logs" / "local_actions.jsonl"
PENDING_TTL_SECONDS = 300
DEFAULT_APPROVAL_DB = DEFAULT_CONFIG_DIR / "pc_control_approvals.db"
DEFAULT_RETENTION_CONFIG = DEFAULT_CONFIG_DIR / "pc_control_retention.json"
DEFAULT_RETENTION_DAYS = 30
DEFAULT_AUDIT_MAX_BYTES = 5 * 1024 * 1024
DEFAULT_AUDIT_KEEP_RECENT_LINES = 1000

_EMERGENCY_STOP_ACTIVE = False
_STORE_LOCK = threading.RLock()
_LAST_MAINTENANCE_SUMMARY: dict[str, Any] | None = None

LOW_RISK_ACTIONS = {
    "open_app",
    "detect_app",
    "list_windows",
    "volume_up",
    "volume_down",
    "volume_mute",
    "volume_unmute",
    "brightness_get",
    "brightness_set",
    "clipboard_read",
    "clipboard_write",
    "clipboard_clear",
    "file_create",
    "browser_context",
    "browser_tabs",
    "browser_summary",
    "browser_headings",
    "browser_links",
    "browser_buttons",
    "browser_open",
    "browser_search",
    "browser_new_tab",
}
MEDIUM_RISK_ACTIONS = {
    "close_app",
    "focus_window",
    "minimize_window",
    "maximize_window",
    "restore_window",
    "close_window",
    "file_rename",
    "file_move",
    "file_copy",
    "keyboard_type",
    "keyboard_hotkey",
    "mouse_move",
    "mouse_click",
    "mouse_scroll",
    "browser_click",
    "browser_focus",
    "browser_back",
    "browser_forward",
    "browser_reload",
}
HIGH_RISK_ACTIONS = {
    "file_delete",
    "system_sleep",
    "system_restart",
    "system_shutdown",
    "system_lock",
}
BLOCKED_ACTIONS = {
    "file_permanent_delete",
    "script_run",
    "shell_run",
    "browser_submit_form",
    "browser_extract_password",
    "browser_purchase",
}

SAFE_APP_ALIASES = {
    "notepad": "notepad",
    "calculator": "calculator",
    "calc": "calculator",
    "chrome": "chrome",
    "edge": "edge",
    "vscode": "vscode",
    "vs code": "vscode",
    "visual studio code": "vscode",
    "file explorer": "explorer",
    "explorer": "explorer",
    "terminal": "terminal",
    "windows terminal": "terminal",
    "task manager": "task_manager",
}
PROTECTED_PATH_PARTS = {
    "windows",
    "program files",
    "program files (x86)",
    "$recycle.bin",
    "system volume information",
}
SECRET_KEYS = {"content", "text", "value", "clipboard", "password", "secret", "token"}


DEFAULT_RETENTION_POLICY = {
    "approval_retention_days": DEFAULT_RETENTION_DAYS,
    "audit_max_bytes": DEFAULT_AUDIT_MAX_BYTES,
    "audit_keep_recent_lines": DEFAULT_AUDIT_KEEP_RECENT_LINES,
}


@dataclass(frozen=True)
class LocalActionRequest:
    action_type: str
    target: str = ""
    args: dict[str, Any] = field(default_factory=dict)
    require_approval: bool = False
    dry_run: bool = False


@dataclass(frozen=True)
class PendingLocalAction:
    action_id: str
    request: LocalActionRequest
    risk_level: RiskLevel
    created_at: float
    expires_at: float
    status: str = "pending"
    decision: str = "pending"
    decision_timestamp: float | None = None


@dataclass
class LocalActionResponse:
    ok: bool
    action_id: str | None
    status: ActionStatus
    message: str
    approval_required: bool
    risk_level: RiskLevel
    evidence: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "action_id": self.action_id,
            "status": self.status,
            "message": self.message,
            "approval_required": self.approval_required,
            "risk_level": self.risk_level,
            "evidence": self.evidence,
            "error": self.error,
        }


def run_local_action(payload: dict[str, Any] | LocalActionRequest) -> LocalActionResponse:
    request = _coerce_request(payload)
    risk = classify_risk(request)
    if risk == "BLOCKED":
        response = LocalActionResponse(
            ok=False,
            action_id=None,
            status="blocked",
            message="I blocked this action for safety.",
            approval_required=False,
            risk_level=risk,
            error="blocked_by_policy",
        )
        _audit(request, response, approval_status="blocked")
        return response

    guard = _preflight_guard(request, risk)
    if guard is not None:
        _audit(request, guard, approval_status="blocked" if guard.status == "blocked" else "none")
        return guard

    if request.dry_run:
        response = LocalActionResponse(
            ok=True,
            action_id=None,
            status="dry_run",
            message=_dry_run_message(request, risk),
            approval_required=False,
            risk_level=risk,
            evidence={"would_execute": True, "action_type": request.action_type, "target": request.target},
        )
        _audit(request, response, approval_status="dry_run")
        return response

    if request.require_approval or risk == "HIGH":
        action_id = _create_pending(request)
        response = LocalActionResponse(
            ok=False,
            action_id=action_id,
            status="approval_required",
            message=_approval_message(request),
            approval_required=True,
            risk_level=risk,
            evidence={"pending": True, "expires_at": time.time() + PENDING_TTL_SECONDS},
        )
        _audit(request, response, approval_status="pending")
        return response

    if _EMERGENCY_STOP_ACTIVE and risk in {"MEDIUM", "HIGH"}:
        response = LocalActionResponse(
            ok=False,
            action_id=None,
            status="blocked",
            message="Emergency stop is active. Medium and high risk local actions are paused.",
            approval_required=False,
            risk_level=risk,
            error="emergency_stop_active",
        )
        _audit(request, response, approval_status="blocked")
        return response

    response = _execute(request, risk)
    _audit(request, response, approval_status="none")
    return response


def approve_local_action(action_id: str) -> LocalActionResponse:
    with _STORE_LOCK:
        _expire_pending()
        pending = _load_pending_record(action_id)
        if pending is None:
            return _missing_or_decided_action(action_id)
        request = pending.request
        risk = classify_risk(request)
        if pending.expires_at <= time.time():
            _mark_pending_decision(action_id, status="expired", decision="expired")
            response = LocalActionResponse(
                ok=False,
                action_id=action_id,
                status="expired",
                message="That local action approval has expired and was not run.",
                approval_required=False,
                risk_level=risk,
                error="approval_expired",
            )
            _audit(request, response, approval_status="expired")
            return response
        if _EMERGENCY_STOP_ACTIVE and risk in {"MEDIUM", "HIGH"}:
            _mark_pending_decision(action_id, status="cancelled", decision="emergency_stop")
            response = LocalActionResponse(
                ok=False,
                action_id=action_id,
                status="blocked",
                message="Emergency stop is active. This pending action was not run.",
                approval_required=False,
                risk_level=risk,
                error="emergency_stop_active",
            )
            _audit(request, response, approval_status="approved_blocked")
            return response
        _mark_pending_decision(action_id, status="approved", decision="approved")

    if _EMERGENCY_STOP_ACTIVE and risk in {"MEDIUM", "HIGH"}:
        response = LocalActionResponse(
            ok=False,
            action_id=action_id,
            status="blocked",
            message="Emergency stop is active. This pending action was not run.",
            approval_required=False,
            risk_level=risk,
            error="emergency_stop_active",
        )
        _audit(request, response, approval_status="approved_blocked")
        return response
    response = _execute(request, risk)
    response.action_id = action_id
    if response.ok:
        _set_approval_status(action_id, status="completed", decision="approved")
    else:
        _set_approval_status(action_id, status=response.status, decision="approved")
    _audit(request, response, approval_status="approved")
    return response


def reject_local_action(action_id: str) -> LocalActionResponse:
    with _STORE_LOCK:
        _expire_pending()
        pending = _load_pending_record(action_id)
        if pending is None:
            return _missing_or_decided_action(action_id)
        request = pending.request
        _mark_pending_decision(action_id, status="rejected", decision="rejected")
    response = LocalActionResponse(
        ok=True,
        action_id=action_id,
        status="rejected",
        message="Rejected the pending local action.",
        approval_required=False,
        risk_level=classify_risk(request),
        evidence={"rejected": True},
    )
    _audit(request, response, approval_status="rejected")
    return response


def emergency_stop() -> LocalActionResponse:
    global _EMERGENCY_STOP_ACTIVE
    _expire_pending()
    count = _mark_all_pending_cancelled()
    _EMERGENCY_STOP_ACTIVE = True
    request = LocalActionRequest("emergency_stop", "local_actions")
    response = LocalActionResponse(
        ok=True,
        action_id=None,
        status="completed",
        message=f"Emergency stop activated. Cancelled {count} pending local action(s).",
        approval_required=False,
        risk_level="HIGH",
        evidence={"cancelled_pending_actions": count},
    )
    _audit(request, response, approval_status="emergency_stop")
    return response


def reset_emergency_stop() -> None:
    global _EMERGENCY_STOP_ACTIVE
    _EMERGENCY_STOP_ACTIVE = False


def pending_action_count() -> int:
    _expire_pending()
    return len(list_pending_actions())


def initialize_pc_control_store() -> dict[str, Any]:
    return run_pc_control_maintenance()


def run_pc_control_maintenance() -> dict[str, Any]:
    global _LAST_MAINTENANCE_SUMMARY
    started_at = time.time()
    summary: dict[str, Any] = {
        "started_at": started_at,
        "completed_at": None,
        "storage_healthy": False,
        "cleanup_completed": False,
        "errors": [],
        "expired_approvals": 0,
        "deleted_approval_records": 0,
        "audit_rotated": False,
        "audit_archived_path": None,
        "audit_kept_lines": 0,
        "retention": load_retention_policy(),
        "counts": {},
        "storage": {
            "backend": "sqlite",
            "path": str(get_approval_db_path()),
            "persistent": True,
            "local_only": True,
        },
    }
    with _STORE_LOCK:
        try:
            summary["expired_approvals"] = _expire_pending()
        except Exception as exc:
            summary["errors"].append(f"expire_pending:{exc.__class__.__name__}")
        try:
            summary["deleted_approval_records"] = _cleanup_old_approval_records(summary["retention"])
        except Exception as exc:
            summary["errors"].append(f"approval_cleanup:{exc.__class__.__name__}")
        try:
            rotation = _rotate_audit_log_if_needed(summary["retention"])
            summary.update(rotation)
        except Exception as exc:
            summary["errors"].append(f"audit_rotation:{exc.__class__.__name__}")
        try:
            summary["counts"] = _approval_counts_by_status()
            summary["storage_healthy"] = _approval_db_is_healthy()
        except Exception as exc:
            summary["errors"].append(f"health:{exc.__class__.__name__}")
    summary["cleanup_completed"] = not summary["errors"]
    summary["completed_at"] = time.time()
    _LAST_MAINTENANCE_SUMMARY = summary
    return summary


def get_pc_control_runtime_health() -> dict[str, Any]:
    summary = _LAST_MAINTENANCE_SUMMARY or run_pc_control_maintenance()
    return {
        "storage": summary.get("storage", {}),
        "retention": summary.get("retention", load_retention_policy()),
        "maintenance": summary,
        "counts": _approval_counts_by_status(),
    }


def list_pending_actions() -> list[dict[str, Any]]:
    _expire_pending()
    return list_approval_records(statuses=("pending",))


def list_approval_records(
    *,
    statuses: tuple[str, ...] = ("pending", "approved", "completed", "rejected", "expired", "cancelled", "blocked", "failed"),
    limit: int = 100,
) -> list[dict[str, Any]]:
    _expire_pending()
    safe_limit = max(1, min(int(limit or 100), 500))
    placeholders = ",".join("?" for _ in statuses)
    with _connect_approval_db() as conn:
        rows = conn.execute(
            f"""
            SELECT * FROM pc_control_approvals
            WHERE status IN ({placeholders})
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (*statuses, safe_limit),
        ).fetchall()
    return [_approval_row_to_dict(row) for row in rows]


def read_recent_audit_entries(limit: int = 100) -> list[dict[str, Any]]:
    path = get_audit_log_path()
    if not path.exists():
        return []
    safe_limit = max(1, min(int(limit or 100), 500))
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-safe_limit:]
    except OSError:
        return []
    entries: list[dict[str, Any]] = []
    for line in lines:
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        action_type = str(raw.get("action_type", ""))
        entries.append(
            {
                "timestamp": float(raw.get("timestamp") or 0),
                "action_type": action_type,
                "target": _redact_target(action_type, str(raw.get("target", ""))),
                "risk_level": str(raw.get("risk_level", "LOW")),
                "status": str(raw.get("status", "")),
                "decision": str(raw.get("approval_status", raw.get("decision", ""))),
                "dry_run": bool(raw.get("dry_run", False)),
                "ok": bool(raw.get("ok", False)),
                "action_id": raw.get("action_id"),
            }
        )
    return entries


def classify_risk(request: LocalActionRequest) -> RiskLevel:
    action = _normalise_action_type(request.action_type)
    if action in BLOCKED_ACTIONS:
        return "BLOCKED"
    if action in HIGH_RISK_ACTIONS:
        return "HIGH"
    if action in MEDIUM_RISK_ACTIONS:
        return "MEDIUM"
    if action in LOW_RISK_ACTIONS:
        return "LOW"
    return "BLOCKED"


def _execute(request: LocalActionRequest, risk: RiskLevel) -> LocalActionResponse:
    try:
        action = _normalise_action_type(request.action_type)
        if action in {"open_app", "detect_app"}:
            return _execute_app(request, action)
        if action == "close_app":
            return _execute_window_alias(request, "close")
        if action in {"list_windows", "focus_window", "minimize_window", "maximize_window", "restore_window", "close_window"}:
            return _execute_window(request, action)
        if action.startswith("volume_"):
            return _execute_volume(action)
        if action.startswith("brightness_"):
            return _execute_brightness(request, action)
        if action.startswith("clipboard_"):
            return _execute_clipboard(request, action)
        if action.startswith("file_"):
            return _execute_file(request, action)
        if action.startswith("keyboard_") or action.startswith("mouse_"):
            return _execute_input(request, action)
        if action.startswith("system_"):
            return _execute_system(request, action)
        if action.startswith("browser_"):
            return _execute_browser(request, action)
    except Exception as exc:
        return LocalActionResponse(
            ok=False,
            action_id=None,
            status="failed",
            message="I could not complete that local action.",
            approval_required=False,
            risk_level=risk,
            error=exc.__class__.__name__,
        )
    return LocalActionResponse(
        ok=False,
        action_id=None,
        status="blocked",
        message="I blocked this action for safety.",
        approval_required=False,
        risk_level="BLOCKED",
        error="unknown_action_type",
    )


def _execute_app(request: LocalActionRequest, action: str) -> LocalActionResponse:
    app_id = _app_id(request.target)
    if not app_id:
        return _blocked("Unknown app is not in Grandpa's safe app allowlist.")
    from grandpa.windows_app_resolver import launch_app, resolve_app

    resolution = resolve_app(app_id)
    evidence = {"app_id": app_id, "resolution": resolution.to_dict()}
    if resolution.status not in {"found", "available"}:
        return LocalActionResponse(
            ok=False,
            action_id=None,
            status="unsupported" if resolution.status == "unsupported" else "failed",
            message=resolution.message,
            approval_required=False,
            risk_level="LOW",
            evidence=evidence,
            error=resolution.status,
        )
    if action == "detect_app":
        return LocalActionResponse(True, None, "completed", resolution.message, False, "LOW", evidence)
    launch = launch_app(app_id)
    evidence["launch"] = launch.to_dict()
    ok = launch.status == "found"
    return LocalActionResponse(
        ok=ok,
        action_id=None,
        status="completed" if ok else "failed",
        message=launch.message,
        approval_required=False,
        risk_level="LOW",
        evidence=evidence,
        error=None if ok else launch.status,
    )


def _execute_window_alias(request: LocalActionRequest, action: str) -> LocalActionResponse:
    return _execute_window(LocalActionRequest(f"{action}_window", request.target, request.args), f"{action}_window")


def _execute_window(request: LocalActionRequest, action: str) -> LocalActionResponse:
    from grandpa.windows_window_control import control_window, list_open_windows

    if action == "list_windows":
        result = list_open_windows()
    else:
        verb = action.removesuffix("_window")
        result = control_window(verb, request.target or "active")
    ok = result.status == "handled"
    status: ActionStatus = "completed" if ok else "failed"
    if result.status == "unsupported":
        status = "unsupported"
    if result.status == "blocked":
        status = "blocked"
    return LocalActionResponse(
        ok=ok,
        action_id=None,
        status=status,
        message=result.message,
        approval_required=False,
        risk_level="LOW" if action == "list_windows" else "MEDIUM",
        evidence={"window_status": result.status, "windows": [w.title for w in getattr(result, "windows", ())]},
        error=None if ok else result.status,
    )


def _execute_volume(action: str) -> LocalActionResponse:
    if sys.platform != "win32":
        return _unsupported("Volume control is only supported on Windows desktop.", "LOW")
    key = {
        "volume_up": "volumeup",
        "volume_down": "volumedown",
        "volume_mute": "volumemute",
        "volume_unmute": "volumemute",
    }[action]
    import pyautogui  # type: ignore

    pyautogui.press(key)
    label = action.replace("volume_", "volume ").replace("_", " ")
    return LocalActionResponse(True, None, "completed", f"Adjusted {label}.", False, "LOW", {"key": key})


def _execute_brightness(request: LocalActionRequest, action: str) -> LocalActionResponse:
    try:
        import screen_brightness_control as sbc  # type: ignore
    except Exception:
        return _unsupported("Brightness control is not supported on this system.", "LOW")
    if action == "brightness_get":
        value = sbc.get_brightness()
        return LocalActionResponse(True, None, "completed", "Brightness read.", False, "LOW", {"brightness": value})
    value = int(request.args.get("level", request.target or 0))
    sbc.set_brightness(max(0, min(100, value)))
    return LocalActionResponse(True, None, "completed", f"Brightness set to {value}%.", False, "LOW", {"brightness": value})


def _execute_clipboard(request: LocalActionRequest, action: str) -> LocalActionResponse:
    import pyperclip

    if action == "clipboard_read":
        text = pyperclip.paste()
        return LocalActionResponse(
            True,
            None,
            "completed",
            "Clipboard read.",
            False,
            "LOW",
            {"clipboard_text": text, "characters": len(text)},
        )
    if action == "clipboard_write":
        text = str(request.args.get("content", request.target))
        pyperclip.copy(text)
        return LocalActionResponse(True, None, "completed", "Clipboard updated.", False, "LOW", {"characters": len(text)})
    pyperclip.copy("")
    return LocalActionResponse(True, None, "completed", "Clipboard cleared.", False, "LOW", {"cleared": True})


def _execute_file(request: LocalActionRequest, action: str) -> LocalActionResponse:
    target = _resolve_path(request.target)
    destination = _resolve_path(str(request.args.get("destination", ""))) if request.args.get("destination") else None
    if action == "file_create":
        kind = request.args.get("kind", "file")
        if kind == "folder":
            target.mkdir(parents=True, exist_ok=False)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(str(request.args.get("content", "")), encoding="utf-8")
        return LocalActionResponse(True, None, "completed", f"Created {kind}.", False, "LOW", {"path": str(target), "kind": kind})
    if action == "file_rename":
        if destination is None:
            destination = target.with_name(str(request.args["new_name"]))
        destination.parent.mkdir(parents=True, exist_ok=True)
        target.rename(destination)
        return LocalActionResponse(True, None, "completed", "Renamed item.", False, "MEDIUM", {"from": str(target), "to": str(destination)})
    if action == "file_move":
        if destination is None:
            raise ValueError("destination is required")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(target), str(destination))
        return LocalActionResponse(True, None, "completed", "Moved item.", False, "MEDIUM", {"from": str(target), "to": str(destination)})
    if action == "file_copy":
        if destination is None:
            raise ValueError("destination is required")
        if target.is_dir():
            shutil.copytree(target, destination)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, destination)
        return LocalActionResponse(True, None, "completed", "Copied item.", False, "MEDIUM", {"from": str(target), "to": str(destination)})
    if action == "file_delete":
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
        return LocalActionResponse(True, None, "completed", "Deleted item.", False, "HIGH", {"path": str(target)})
    return _blocked("I blocked this file action for safety.")


def _execute_input(request: LocalActionRequest, action: str) -> LocalActionResponse:
    if sys.platform != "win32":
        return _unsupported("Keyboard and mouse control is only supported on Windows desktop.", "MEDIUM")
    import pyautogui  # type: ignore

    pyautogui.FAILSAFE = True
    if action == "keyboard_type":
        text = str(request.args.get("text", request.target))
        pyautogui.write(text, interval=0.01)
        return LocalActionResponse(True, None, "completed", "Typed text.", False, "MEDIUM", {"characters": len(text)})
    if action == "keyboard_hotkey":
        keys = request.args.get("keys", request.target)
        if isinstance(keys, str):
            keys = [part.strip() for part in keys.split("+") if part.strip()]
        pyautogui.hotkey(*keys)
        return LocalActionResponse(True, None, "completed", "Pressed hotkey.", False, "MEDIUM", {"keys": keys})
    if action == "mouse_move":
        pyautogui.moveTo(int(request.args.get("x", 0)), int(request.args.get("y", 0)))
        return LocalActionResponse(True, None, "completed", "Moved mouse.", False, "MEDIUM", {"x": request.args.get("x"), "y": request.args.get("y")})
    if action == "mouse_click":
        pyautogui.click(int(request.args.get("x", 0)), int(request.args.get("y", 0)))
        return LocalActionResponse(True, None, "completed", "Clicked mouse.", False, "MEDIUM", {"x": request.args.get("x"), "y": request.args.get("y")})
    if action == "mouse_scroll":
        pyautogui.scroll(int(request.args.get("amount", request.target or 0)))
        return LocalActionResponse(True, None, "completed", "Scrolled mouse.", False, "MEDIUM", {"amount": request.args.get("amount", request.target)})
    return _blocked("I blocked this automation action for safety.")


def _execute_system(request: LocalActionRequest, action: str) -> LocalActionResponse:
    if sys.platform != "win32":
        return _unsupported("Power control is only supported on Windows desktop.", "HIGH")
    if action == "system_lock":
        import ctypes

        ctypes.windll.user32.LockWorkStation()
        return LocalActionResponse(True, None, "completed", "Locked the screen.", False, "HIGH", {"system_action": "lock"})
    command = {
        "system_sleep": ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"],
        "system_restart": ["shutdown", "/r", "/t", "0"],
        "system_shutdown": ["shutdown", "/s", "/t", "0"],
    }[action]
    import subprocess

    subprocess.Popen(command)
    return LocalActionResponse(True, None, "completed", "Started the requested power action.", False, "HIGH", {"system_action": action})


def _execute_browser(request: LocalActionRequest, action: str) -> LocalActionResponse:
    from grandpa.browser_control import execute_browser_action

    mapping = {
        "browser_context": ("context", "active"),
        "browser_tabs": ("tabs", "recent"),
        "browser_summary": ("summary", "visible"),
        "browser_headings": ("headings", "visible"),
        "browser_links": ("links", "visible"),
        "browser_buttons": ("buttons", "visible"),
        "browser_open": ("open", request.target),
        "browser_search": ("search", request.target),
        "browser_new_tab": ("new_tab", request.target or "about:blank"),
        "browser_click": ("click", request.target),
        "browser_focus": ("focus_search", request.target or "visible"),
        "browser_back": ("back", "visible"),
        "browser_forward": ("forward", "visible"),
        "browser_reload": ("reload", "visible"),
    }
    browser_action = mapping.get(action)
    if browser_action is None:
        return _blocked("I blocked this browser action for safety.")
    result = execute_browser_action(*browser_action)
    status: ActionStatus = {
        "handled": "completed",
        "requires_confirmation": "unsupported",
        "blocked": "blocked",
        "unsupported": "unsupported",
        "error": "failed",
    }.get(result.status, "failed")  # type: ignore[assignment]
    return LocalActionResponse(
        ok=status == "completed",
        action_id=None,
        status=status,
        message=result.message,
        approval_required=False,
        risk_level=(
            result.risk_level
            if result.risk_level in {"LOW", "MEDIUM", "HIGH", "BLOCKED"}
            else classify_risk(request)
        ),
        evidence={
            "browser": result.context.to_dict() if result.context else {},
            "visible_only": True,
        },
        error=None if status == "completed" else result.status,
    )


def _preflight_guard(request: LocalActionRequest, risk: RiskLevel) -> LocalActionResponse | None:
    action = _normalise_action_type(request.action_type)
    if action.startswith("file_"):
        paths = [request.target]
        if request.args.get("destination"):
            paths.append(str(request.args["destination"]))
        for raw in paths:
            path = _resolve_path(raw)
            if _is_protected_path(path):
                return LocalActionResponse(
                    ok=False,
                    action_id=None,
                    status="blocked",
                    message="I blocked this file operation because the path is protected.",
                    approval_required=False,
                    risk_level="HIGH",
                    evidence={"path": str(path)},
                    error="protected_path",
                )
    if action == "file_permanent_delete":
        return _blocked("Permanent delete is blocked by Grandpa's safety policy.")
    return None


def _dry_run_message(request: LocalActionRequest, risk: RiskLevel) -> str:
    return f"Dry run: {request.action_type} would run on {request.target or 'the current target'} with {risk} risk."


def _approval_message(request: LocalActionRequest) -> str:
    return f"Approval required before running {request.action_type} on {request.target or 'this PC'}."


def get_approval_db_path() -> Path:
    configured = os.environ.get("GRANDPA_PC_CONTROL_DB")
    if configured:
        return Path(configured)
    return DEFAULT_APPROVAL_DB


def get_retention_config_path() -> Path:
    configured = os.environ.get("GRANDPA_PC_CONTROL_RETENTION_CONFIG")
    if configured:
        return Path(configured)
    return DEFAULT_RETENTION_CONFIG


def load_retention_policy() -> dict[str, int]:
    path = get_retention_config_path()
    policy = dict(DEFAULT_RETENTION_POLICY)
    try:
        if path.exists():
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                for key in policy:
                    value = loaded.get(key)
                    if isinstance(value, int) and value > 0:
                        policy[key] = value
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(policy, indent=2, sort_keys=True), encoding="utf-8")
    except OSError:
        return policy
    except json.JSONDecodeError:
        return policy
    return policy


def _connect_approval_db() -> sqlite3.Connection:
    path = get_approval_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS pc_control_approvals (
            action_id TEXT PRIMARY KEY,
            action_type TEXT NOT NULL,
            target TEXT NOT NULL,
            args_json TEXT NOT NULL,
            risk_level TEXT NOT NULL,
            created_at REAL NOT NULL,
            expires_at REAL NOT NULL,
            status TEXT NOT NULL,
            approval_required INTEGER NOT NULL,
            decision TEXT NOT NULL,
            decision_timestamp REAL
        )
        """
    )
    return conn


def _approval_db_is_healthy() -> bool:
    with _connect_approval_db() as conn:
        result = conn.execute("PRAGMA quick_check").fetchone()
    return bool(result and result[0] == "ok")


def _approval_counts_by_status() -> dict[str, int]:
    with _connect_approval_db() as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) AS count FROM pc_control_approvals GROUP BY status"
        ).fetchall()
    counts = {str(row["status"]): int(row["count"]) for row in rows}
    for status in ("pending", "completed", "approved", "rejected", "expired", "cancelled", "blocked", "failed"):
        counts.setdefault(status, 0)
    return counts


def _request_from_row(row: sqlite3.Row) -> LocalActionRequest:
    try:
        args = json.loads(str(row["args_json"] or "{}"))
    except json.JSONDecodeError:
        args = {}
    if not isinstance(args, dict):
        args = {}
    return LocalActionRequest(
        action_type=str(row["action_type"]),
        target=str(row["target"] or ""),
        args=args,
        require_approval=bool(row["approval_required"]),
        dry_run=False,
    )


def _pending_from_row(row: sqlite3.Row) -> PendingLocalAction:
    return PendingLocalAction(
        action_id=str(row["action_id"]),
        request=_request_from_row(row),
        risk_level=str(row["risk_level"]),  # type: ignore[arg-type]
        created_at=float(row["created_at"]),
        expires_at=float(row["expires_at"]),
        status=str(row["status"]),
        decision=str(row["decision"]),
        decision_timestamp=float(row["decision_timestamp"]) if row["decision_timestamp"] is not None else None,
    )


def _approval_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    action_type = str(row["action_type"])
    return {
        "id": str(row["action_id"]),
        "action_id": str(row["action_id"]),
        "action_type": action_type,
        "target": _redact_target(action_type, str(row["target"] or "")),
        "risk_level": str(row["risk_level"]),
        "status": str(row["status"]),
        "decision": str(row["decision"]),
        "created_at": float(row["created_at"]),
        "expires_at": float(row["expires_at"]),
        "decision_timestamp": float(row["decision_timestamp"]) if row["decision_timestamp"] is not None else None,
        "approval_required": bool(row["approval_required"]),
        "dry_run": False,
    }


def _load_pending_record(action_id: str) -> PendingLocalAction | None:
    with _connect_approval_db() as conn:
        row = conn.execute(
            "SELECT * FROM pc_control_approvals WHERE action_id = ? AND status = 'pending'",
            (action_id,),
        ).fetchone()
    return _pending_from_row(row) if row is not None else None


def _load_approval_record(action_id: str) -> PendingLocalAction | None:
    with _connect_approval_db() as conn:
        row = conn.execute(
            "SELECT * FROM pc_control_approvals WHERE action_id = ?",
            (action_id,),
        ).fetchone()
    return _pending_from_row(row) if row is not None else None


def _mark_pending_decision(action_id: str, *, status: str, decision: str) -> bool:
    with _connect_approval_db() as conn:
        cur = conn.execute(
            """
            UPDATE pc_control_approvals
            SET status = ?, decision = ?, decision_timestamp = ?
            WHERE action_id = ? AND status = 'pending'
            """,
            (status, decision, time.time(), action_id),
        )
        return cur.rowcount == 1


def _set_approval_status(action_id: str, *, status: str, decision: str) -> None:
    with _connect_approval_db() as conn:
        conn.execute(
            """
            UPDATE pc_control_approvals
            SET status = ?, decision = ?, decision_timestamp = ?
            WHERE action_id = ?
            """,
            (status, decision, time.time(), action_id),
        )


def _mark_all_pending_cancelled() -> int:
    with _connect_approval_db() as conn:
        cur = conn.execute(
            """
            UPDATE pc_control_approvals
            SET status = 'cancelled', decision = 'emergency_stop', decision_timestamp = ?
            WHERE status = 'pending'
            """,
            (time.time(),),
        )
        return int(cur.rowcount)


def _missing_or_decided_action(action_id: str) -> LocalActionResponse:
    record = _load_approval_record(action_id)
    if record is None:
        return LocalActionResponse(
            ok=False,
            action_id=action_id,
            status="failed",
            message="No pending local action was found for that ID.",
            approval_required=False,
            risk_level="LOW",
            error="missing_pending_action",
        )
    status = "expired" if record.status == "expired" else "failed"
    return LocalActionResponse(
        ok=False,
        action_id=action_id,
        status=status,  # type: ignore[arg-type]
        message=f"That local action is already {record.status} and will not run again.",
        approval_required=False,
        risk_level=record.risk_level,
        error=f"already_{record.status}",
    )


def _create_pending(request: LocalActionRequest) -> str:
    _expire_pending()
    now = time.time()
    action_id = uuid.uuid4().hex
    risk = classify_risk(request)
    args_json = json.dumps(request.args, ensure_ascii=True, sort_keys=True, default=str)
    with _connect_approval_db() as conn:
        conn.execute(
            """
            INSERT INTO pc_control_approvals (
                action_id, action_type, target, args_json, risk_level, created_at,
                expires_at, status, approval_required, decision, decision_timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, 'pending', NULL)
            """,
            (
                action_id,
                request.action_type,
                request.target,
                args_json,
                risk,
                now,
                now + PENDING_TTL_SECONDS,
                int(request.require_approval or risk == "HIGH"),
            ),
        )
    return action_id


def _cleanup_old_approval_records(policy: dict[str, int]) -> int:
    retention_days = max(1, int(policy.get("approval_retention_days", DEFAULT_RETENTION_DAYS)))
    cutoff = time.time() - retention_days * 86400
    with _connect_approval_db() as conn:
        cur = conn.execute(
            """
            DELETE FROM pc_control_approvals
            WHERE status != 'pending'
              AND COALESCE(decision_timestamp, created_at) < ?
            """,
            (cutoff,),
        )
        return int(cur.rowcount)


def _rotate_audit_log_if_needed(policy: dict[str, int]) -> dict[str, Any]:
    path = get_audit_log_path()
    max_bytes = max(1, int(policy.get("audit_max_bytes", DEFAULT_AUDIT_MAX_BYTES)))
    keep_lines = max(1, int(policy.get("audit_keep_recent_lines", DEFAULT_AUDIT_KEEP_RECENT_LINES)))
    result = {
        "audit_rotated": False,
        "audit_archived_path": None,
        "audit_kept_lines": 0,
    }
    if not path.exists():
        return result
    try:
        if path.stat().st_size <= max_bytes:
            return result
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return result
    archive_lines = lines[:-keep_lines]
    keep = lines[-keep_lines:]
    timestamp = time.strftime("%Y%m%d-%H%M%S", time.localtime())
    archive_path = path.with_name(f"{path.name}.{timestamp}.gz")
    path.parent.mkdir(parents=True, exist_ok=True)
    if archive_lines:
        with gzip.open(archive_path, "wt", encoding="utf-8") as fh:
            fh.write("\n".join(archive_lines) + "\n")
        result["audit_archived_path"] = str(archive_path)
    path.write_text(("\n".join(keep) + "\n") if keep else "", encoding="utf-8")
    result["audit_rotated"] = True
    result["audit_kept_lines"] = len(keep)
    return result


def _expire_pending() -> int:
    now = time.time()
    with _connect_approval_db() as conn:
        rows = conn.execute(
            "SELECT * FROM pc_control_approvals WHERE status = 'pending' AND expires_at <= ?",
            (now,),
        ).fetchall()
        conn.execute(
            """
            UPDATE pc_control_approvals
            SET status = 'expired', decision = 'expired', decision_timestamp = ?
            WHERE status = 'pending' AND expires_at <= ?
            """,
            (now, now),
        )
    for row in rows:
        request = _request_from_row(row)
        response = LocalActionResponse(
            ok=False,
            action_id=str(row["action_id"]),
            status="expired",
            message="That local action approval has expired and was not run.",
            approval_required=False,
            risk_level=str(row["risk_level"]),  # type: ignore[arg-type]
            error="approval_expired",
        )
        _audit(request, response, approval_status="expired")
    return len(rows)


def _audit(request: LocalActionRequest, response: LocalActionResponse, *, approval_status: str) -> None:
    path = get_audit_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": time.time(),
        "action_type": request.action_type,
        "target": _redact_target(request.action_type, request.target),
        "risk_level": response.risk_level,
        "status": response.status,
        "dry_run": request.dry_run,
        "approval_status": approval_status,
        "ok": response.ok,
        "action_id": response.action_id,
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=True) + "\n")


def get_audit_log_path() -> Path:
    configured = os.environ.get("GRANDPA_LOCAL_ACTION_LOG")
    if configured:
        return Path(configured)
    base = Path(os.environ.get("GRANDPA_RUNTIME_DIR", str(RUNTIME_DIR)))
    return base / "logs" / "local_actions.jsonl"


def _coerce_request(payload: dict[str, Any] | LocalActionRequest) -> LocalActionRequest:
    if isinstance(payload, LocalActionRequest):
        return payload
    return LocalActionRequest(
        action_type=_normalise_action_type(str(payload.get("action_type", ""))),
        target=str(payload.get("target", "") or ""),
        args=dict(payload.get("args") or {}),
        require_approval=bool(payload.get("require_approval", False)),
        dry_run=bool(payload.get("dry_run", False)),
    )


def _normalise_action_type(value: str) -> str:
    return value.strip().lower().replace("-", "_").replace(" ", "_")


def _app_id(name: str) -> str | None:
    return SAFE_APP_ALIASES.get(name.strip().lower())


def _resolve_path(path: str) -> Path:
    if not path:
        raise ValueError("path is required")
    candidate = Path(path).expanduser()
    return candidate.resolve(strict=False)


def _is_protected_path(path: Path) -> bool:
    resolved = path.resolve(strict=False)
    raw_lower = str(resolved).lower().replace("/", "\\")
    if any(token in raw_lower for token in ("\\windows", "\\program files", "c:\\windows", "c:\\program files")):
        return True
    parts = {part.lower() for part in resolved.parts}
    if parts & PROTECTED_PATH_PARTS:
        return True
    home = Path.home().resolve(strict=False)
    repo = Path(__file__).resolve().parents[2]
    return resolved in {home, repo}


def _redact_target(action_type: str, target: str) -> str:
    if _normalise_action_type(action_type).startswith("clipboard_"):
        return "[redacted]"
    if any(key in action_type.lower() for key in SECRET_KEYS):
        return "[redacted]"
    return target


def _blocked(message: str) -> LocalActionResponse:
    return LocalActionResponse(False, None, "blocked", message, False, "BLOCKED", error="blocked_by_policy")


def _unsupported(message: str, risk: RiskLevel) -> LocalActionResponse:
    return LocalActionResponse(False, None, "unsupported", message, False, risk, error="unsupported")


__all__ = [
    "AUDIT_LOG_PATH",
    "LocalActionRequest",
    "LocalActionResponse",
    "approve_local_action",
    "classify_risk",
    "emergency_stop",
    "get_audit_log_path",
    "get_approval_db_path",
    "get_pc_control_runtime_health",
    "get_retention_config_path",
    "initialize_pc_control_store",
    "list_approval_records",
    "list_pending_actions",
    "load_retention_policy",
    "pending_action_count",
    "read_recent_audit_entries",
    "reject_local_action",
    "reset_emergency_stop",
    "run_pc_control_maintenance",
    "run_local_action",
]
