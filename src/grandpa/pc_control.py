"""Unified safe PC control layer for Grandpa.

The public entry points in this module separate action planning, risk
classification, approval, execution, and audit logging. Tests use dry-run and
mocked OS calls so dangerous operations never run during validation.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
import uuid
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
]

RUNTIME_DIR = Path("runtime")
AUDIT_LOG_PATH = RUNTIME_DIR / "logs" / "local_actions.jsonl"
PENDING_TTL_SECONDS = 300

_PENDING_ACTIONS: dict[str, "LocalActionRequest"] = {}
_EMERGENCY_STOP_ACTIVE = False

LOW_RISK_ACTIONS = {
    "open_app",
    "detect_app",
    "list_windows",
    "volume_up",
    "volume_down",
    "volume_mute",
    "volume_unmute",
    "brightness_get",
    "clipboard_read",
    "clipboard_write",
    "clipboard_clear",
    "file_create",
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
}
HIGH_RISK_ACTIONS = {
    "file_delete",
    "system_sleep",
    "system_restart",
    "system_shutdown",
    "system_lock",
}
BLOCKED_ACTIONS = {"file_permanent_delete", "script_run", "shell_run"}

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


@dataclass(frozen=True)
class LocalActionRequest:
    action_type: str
    target: str = ""
    args: dict[str, Any] = field(default_factory=dict)
    require_approval: bool = False
    dry_run: bool = False


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
    request = _PENDING_ACTIONS.pop(action_id, None)
    if request is None:
        return LocalActionResponse(
            ok=False,
            action_id=action_id,
            status="failed",
            message="No pending local action was found for that ID.",
            approval_required=False,
            risk_level="LOW",
            error="missing_pending_action",
        )
    risk = classify_risk(request)
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
    _audit(request, response, approval_status="approved")
    return response


def reject_local_action(action_id: str) -> LocalActionResponse:
    request = _PENDING_ACTIONS.pop(action_id, None)
    if request is None:
        return LocalActionResponse(
            ok=False,
            action_id=action_id,
            status="failed",
            message="No pending local action was found for that ID.",
            approval_required=False,
            risk_level="LOW",
            error="missing_pending_action",
        )
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
    count = len(_PENDING_ACTIONS)
    _PENDING_ACTIONS.clear()
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
    return len(_PENDING_ACTIONS)


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
        target.rename(destination)
        return LocalActionResponse(True, None, "completed", "Renamed item.", False, "MEDIUM", {"from": str(target), "to": str(destination)})
    if action == "file_move":
        if destination is None:
            raise ValueError("destination is required")
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


def _create_pending(request: LocalActionRequest) -> str:
    _expire_pending()
    action_id = uuid.uuid4().hex
    _PENDING_ACTIONS[action_id] = request
    return action_id


def _expire_pending() -> None:
    # Pending actions are intentionally in-memory for this structured API. They
    # expire when the backend process exits; future persistence can store args.
    return None


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
    "pending_action_count",
    "reject_local_action",
    "reset_emergency_stop",
    "run_local_action",
]
