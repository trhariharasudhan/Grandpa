"""Unified safe PC control layer for Grandpa.

The public entry points in this module separate action planning, risk
classification, approval, execution, and audit logging. Tests use dry-run and
mocked OS calls so dangerous operations never run during validation.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import os
import secrets
import sqlite3
import sys
import threading
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import TYPE_CHECKING, Any, Literal

from grandpa.core.config import DEFAULT_CONFIG_DIR
from grandpa.policy.models import (
    ACTION_ORIGINS,
    DEFAULT_ACTION_ORIGIN,
    ActionOrigin,
    LocalActionRequest,
    LocalActionResponse,
)

if TYPE_CHECKING:
    from grandpa.policy.engine import RiskTables

logger = logging.getLogger(__name__)

RiskLevel = Literal["LOW", "MEDIUM", "HIGH", "BLOCKED"]
ActionStatus = Literal[
    "completed",
    "partial_success",
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
    "open_folder",
    "detect_app",
    "list_windows",
    "volume_up",
    "volume_down",
    "volume_mute",
    "volume_unmute",
    "volume_set",
    "brightness_get",
    "brightness_set",
    "clipboard_read",
    "clipboard_write",
    "clipboard_clear",
    "clipboard_inspect",
    "clipboard_history",
    "list_monitors",
    "monitor_info",
    "active_process",
    "list_processes",
    "desktop_summary",
    "pc_diagnostics",
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
    "browser_diagnostics",
    "browser_media",
    "browser_task",
    "system_lock",
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
    "mouse_drag",
    "desktop_navigate",
    "browser_click",
    "browser_focus",
    "browser_back",
    "browser_forward",
    "browser_reload",
    "browser_form_fill",
    "browser_download",
}
HIGH_RISK_ACTIONS = {
    "file_delete",
    "system_sleep",
    "system_restart",
    "system_shutdown",
    "empty_recycle_bin",
}
BLOCKED_ACTIONS = {
    "file_permanent_delete",
    "script_run",
    "shell_run",
    "browser_submit_form",
    "browser_extract_password",
    "browser_purchase",
}

# Actions that always require explicit human approval, regardless of risk tier.
#
# Synthetic keyboard and mouse input is equivalent to arbitrary code execution:
# ``keyboard_hotkey`` opens a launcher and ``keyboard_type`` fills it in, which
# reaches exactly the capability ``script_run``/``shell_run`` are BLOCKED to
# prevent. Their blast radius is still classified MEDIUM (they are recoverable
# and scoped to the visible desktop), so rather than inflate the risk tier we
# gate them on approval directly.
#
# ``mouse_move`` and ``mouse_scroll`` are deliberately excluded — moving the
# cursor or scrolling cannot commit an action on its own.
APPROVAL_REQUIRED_ACTIONS = {
    "keyboard_type",
    "keyboard_hotkey",
    "mouse_click",
    "mouse_drag",
    "browser_form_fill",
    "browser_download",
}

SAFE_APP_ALIASES = {
    "notepad": "notepad",
    "calculator": "calculator",
    "calc": "calculator",
    "chrome": "chrome",
    "firefox": "firefox",
    "mozilla firefox": "firefox",
    "edge": "edge",
    "vscode": "vscode",
    "vs code": "vscode",
    "visual studio code": "vscode",
    "code": "vscode",
    "paint": "paint",
    "mspaint": "paint",
    "file explorer": "explorer",
    "explorer": "explorer",
    "terminal": "terminal",
    "windows terminal": "terminal",
    "task manager": "task_manager",
    "control panel": "control_panel",
    "settings": "settings",
    "windows settings": "settings",
}
PROTECTED_WINDOWS_ROOT_NAMES = {
    "windows",
    "program files",
    "program files (x86)",
}
PROTECTED_PATH_PARTS = {
    "$recycle.bin",
    "system volume information",
}
PROTECTED_PATH_SEQUENCES = (
    (".ssh",),
    ("appdata", "local", "google", "chrome", "user data"),
    ("appdata", "local", "microsoft", "edge", "user data"),
    ("appdata", "local", "bravesoftware", "brave-browser", "user data"),
    ("appdata", "roaming", "mozilla", "firefox", "profiles"),
)
SECRET_KEYS = {"content", "text", "value", "clipboard", "password", "secret", "token"}


DEFAULT_RETENTION_POLICY = {
    "approval_retention_days": DEFAULT_RETENTION_DAYS,
    "audit_max_bytes": DEFAULT_AUDIT_MAX_BYTES,
    "audit_keep_recent_lines": DEFAULT_AUDIT_KEEP_RECENT_LINES,
}


#: Who asked for an action. AD-022 (RESOLVED) makes provenance first-class:
#: agent-invocable skills are a designed feature, so model-chosen parameters do
#: reach this layer, and the audit trail could not previously tell a user-typed
#: action from a model-selected one.
#:
#: Re-exported, not defined. ``grandpa.policy.models`` is the canonical home
#: (D-5): it imports nothing from this package, so any layer can name a
#: provenance without depending on the execution module. These names stay
#: importable from ``pc_control`` because callers and tests already bind to
#: them here, and breaking that would be a change to a public surface for no
#: benefit.
#:
#: ``direct`` is the default so every existing caller keeps working unchanged.
#: Recording origin does not by itself change any decision -- risk is still
#: computed from the action, never from who asked -- but it is what a future
#: origin-aware policy (Q-10, still open) would key on.
#: (Imported at the top of the module with the other package imports; the
#: comment lives here because this is where the definitions used to be and
#: where a reader looks for them.)


#: ``LocalActionRequest`` and ``LocalActionResponse`` are re-exported, not
#: defined. ``grandpa.policy.models`` is the canonical home (AD-028), on the same
#: terms as ``ActionOrigin`` above: it imports nothing from this package, so
#: ``desktop/`` can name the executor's types without depending on the executor.
#: They stay importable from ``pc_control`` because callers and tests already
#: bind to them here.


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
    # Out-of-band approval code; never surfaced through the HTTP API.
    approval_token: str = ""
    # Fingerprint of the action as staged. Empty means "written before
    # approvals were bound", which is refused rather than trusted.
    action_digest: str = ""


def run_local_action(
    payload: dict[str, Any] | LocalActionRequest,
) -> LocalActionResponse:
    from grandpa.desktop.kernel.requests import coerce_request
    from grandpa.desktop.kernel.risk import classify

    request = coerce_request(payload)
    risk = classify(request)
    return _run_local_action_impl(request, risk=risk)


def _run_local_action_impl(
    payload: dict[str, Any] | LocalActionRequest,
    *,
    risk: RiskLevel | None = None,
) -> LocalActionResponse:
    request = _coerce_request(payload)
    risk = risk or classify_risk(request)
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
        _audit(
            request,
            guard,
            approval_status="blocked" if guard.status == "blocked" else "none",
        )
        return guard

    if request.dry_run:
        response = LocalActionResponse(
            ok=True,
            action_id=None,
            status="dry_run",
            message=_dry_run_message(request, risk),
            approval_required=False,
            risk_level=risk,
            evidence={
                "would_execute": True,
                "action_type": request.action_type,
                "target": request.target,
            },
        )
        _audit(request, response, approval_status="dry_run")
        return response

    if (
        request.require_approval
        or risk == "HIGH"
        or _normalise_action_type(request.action_type) in APPROVAL_REQUIRED_ACTIONS
        # HIGH is already staged by the rule above; this is what makes the
        # MEDIUM tier of SENSITIVE_APP_RISK ask before it runs.
        or _launch_needs_approval(request)
    ):
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

    # A stop stops everything that acts.
    #
    # This read ``risk in {"MEDIUM", "HIGH"}``, which let the 36 LOW actions
    # carry on -- including open_app, open_folder, file_create, system_lock and
    # twelve browser_* actions. Risk tiers rank consequence, not whether
    # something is an action, so filtering by tier answers a question the user
    # did not ask: someone who hits stop wants the assistant to stop touching
    # the machine, not to pause the dangerous half of it.
    #
    # Dry run is checked above and is deliberately still allowed: it actuates
    # nothing, and previewing is the safest thing available while a stop is in
    # force.
    if _EMERGENCY_STOP_ACTIVE:
        response = LocalActionResponse(
            ok=False,
            action_id=None,
            status="blocked",
            message="Emergency stop is active. Local actions are paused.",
            approval_required=False,
            risk_level=risk,
            error="emergency_stop_active",
        )
        _audit(request, response, approval_status="blocked")
        return response

    # Relative actions are judged against the state before they ran, so the
    # baseline is taken here -- after every policy gate, so a blocked or
    # dry-run request never reaches a device, and immediately before the
    # actuator so nothing can drift in between.
    pre_state = _capture_pre_state(request)
    response = _execute(request, risk)
    response = _apply_verification(request, response, pre_state)
    _audit(request, response, approval_status="none")
    return response


def approve_local_action(action_id: str, token: str = "") -> LocalActionResponse:
    from grandpa.desktop.kernel.approvals import approve

    return approve(action_id, token)


def _approve_local_action_impl(action_id: str, token: str = "") -> LocalActionResponse:
    with _STORE_LOCK:
        _expire_pending()
        pending = _load_pending_record(action_id)
        if pending is None:
            return _missing_or_decided_action(action_id)
        request = pending.request
        risk = classify_risk(request)
        # An action_id is not an authorisation. The approval code is delivered
        # out of band (operator console/log), so a caller that can only see the
        # HTTP response cannot approve what it staged. A wrong code is refused
        # without consuming the pending action, so a typo is recoverable.
        expected = pending.approval_token
        if not expected or not secrets.compare_digest(str(token or ""), expected):
            logger.warning(
                "Rejected approval for local action %s: invalid approval code",
                action_id,
            )
            response = LocalActionResponse(
                ok=False,
                action_id=action_id,
                status="blocked",
                message=(
                    "That approval code is not valid for this action. The code is "
                    "shown on the Grandpa console when the action is staged."
                ),
                approval_required=True,
                risk_level=risk,
                error="invalid_approval_token",
            )
            _audit(request, response, approval_status="invalid_token")
            return response
        # The binding check. The token above proved *who* may approve; this
        # proves *what* was approved. Two separate questions, deliberately two
        # separate checks: a correct code for an action that has since changed
        # meaning is not an authorisation for the new one.
        #
        # Ordered after the token so an attacker without the code learns
        # nothing about the inventory, and before expiry only in the sense that
        # both refuse -- neither runs anything.
        current_executable, current_launch_path = _canonical_launch_identity(request)
        current_digest = _action_digest(
            request, current_executable, current_launch_path
        )
        if not pending.action_digest:
            # Written before approvals carried a binding. Missing is not valid:
            # recomputing one now from today's inventory would manufacture the
            # authorisation this check exists to test. Pending rows live
            # ``PENDING_TTL_SECONDS``, so existing expiry clears them.
            _mark_pending_decision(
                action_id, status="cancelled", decision="binding_missing"
            )
            response = LocalActionResponse(
                ok=False,
                action_id=action_id,
                status="blocked",
                message=(
                    "This pending action predates approval identity binding and "
                    "was not run. Ask again to stage a fresh one."
                ),
                approval_required=False,
                risk_level=risk,
                error="approval_binding_missing",
            )
            _audit(request, response, approval_status="binding_missing")
            return response
        if not secrets.compare_digest(current_digest, pending.action_digest):
            _mark_pending_decision(
                action_id, status="cancelled", decision="action_changed"
            )
            response = LocalActionResponse(
                ok=False,
                action_id=action_id,
                status="blocked",
                message=(
                    "What this action refers to changed after it was staged, so "
                    "it was not run. Ask again to stage it against the current "
                    "application."
                ),
                approval_required=False,
                risk_level=risk,
                error="approved_action_changed",
                evidence={"binding": "mismatch"},
            )
            _audit(request, response, approval_status="action_changed")
            return response
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
        if _EMERGENCY_STOP_ACTIVE:
            _mark_pending_decision(
                action_id, status="cancelled", decision="emergency_stop"
            )
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
        approved_launch_path = current_launch_path
        # Claiming the row is what authorises execution, and the claim can
        # fail. ``_mark_pending_decision`` updates only while the row is still
        # pending and reports whether it won, so exactly one caller can take
        # it -- SQLite settles that, which matters because ``_STORE_LOCK`` is
        # a thread lock and the approval database is shared across processes.
        #
        # Discarding the answer meant two approvers could both pass the token
        # and the identity binding, both claim, and both run: an approved
        # delete executed twice with both callers reporting success. The loser
        # gets the response this module already had for an action that is no
        # longer pending.
        if not _mark_pending_decision(
            action_id, status="approved", decision="approved"
        ):
            return _missing_or_decided_action(action_id)

    if _EMERGENCY_STOP_ACTIVE:
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
    # Relative actions are judged against the state before they ran, so the
    # baseline is taken here -- after every policy gate, so a blocked or
    # dry-run request never reaches a device, and immediately before the
    # actuator so nothing can drift in between.
    pre_state = _capture_pre_state(request)
    # Execution consumes the identity the binding just verified rather than
    # asking the inventory again. Re-resolving here would reopen the window
    # this whole check exists to close, between "the answer matched" and "the
    # program started".
    response = _execute(request, risk, launch_path=approved_launch_path)
    response = _apply_verification(request, response, pre_state)
    response.action_id = action_id
    if response.ok:
        _set_approval_status(action_id, status="completed", decision="approved")
    else:
        _set_approval_status(action_id, status=response.status, decision="approved")
    _audit(request, response, approval_status="approved")
    return response


def reject_local_action(action_id: str) -> LocalActionResponse:
    from grandpa.desktop.kernel.approvals import reject

    return reject(action_id)


def _reject_local_action_impl(action_id: str) -> LocalActionResponse:
    with _STORE_LOCK:
        _expire_pending()
        pending = _load_pending_record(action_id)
        if pending is None:
            return _missing_or_decided_action(action_id)
        request = pending.request
        # The same claim the approve path makes, and the same reason to read
        # its answer: the row can be taken by another process between the read
        # above and this write, and only one caller can have it.
        #
        # Reporting success regardless was worse than an error. A person who
        # pressed reject was told the action had been stopped while an approver
        # elsewhere won the row and ran it -- an acknowledged safety decision
        # that never took effect, and no signal to look again.
        if not _mark_pending_decision(
            action_id, status="rejected", decision="rejected"
        ):
            return _missing_or_decided_action(action_id)
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
    from grandpa.desktop.kernel.emergency import activate

    return activate()


def _emergency_stop_impl() -> LocalActionResponse:
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
    from grandpa.desktop.kernel.emergency import reset

    reset()


def _reset_emergency_stop_impl() -> None:
    global _EMERGENCY_STOP_ACTIVE
    _EMERGENCY_STOP_ACTIVE = False


def pending_action_count() -> int:
    from grandpa.desktop.kernel.approvals import count_pending

    return count_pending()


def _pending_action_count_impl() -> int:
    _expire_pending()
    return len(list_pending_actions())


def initialize_pc_control_store() -> dict[str, Any]:
    return _initialize_pc_control_store_impl()


def _initialize_pc_control_store_impl() -> dict[str, Any]:
    return _run_pc_control_maintenance_impl()


def run_pc_control_maintenance() -> dict[str, Any]:
    from grandpa.desktop.kernel.audits import cleanup

    return cleanup()


def _run_pc_control_maintenance_impl() -> dict[str, Any]:
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
            summary["deleted_approval_records"] = _cleanup_old_approval_records(
                summary["retention"]
            )
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
    return _get_pc_control_runtime_health_impl()


def _get_pc_control_runtime_health_impl() -> dict[str, Any]:
    summary = _LAST_MAINTENANCE_SUMMARY or run_pc_control_maintenance()
    try:
        from grandpa.desktop_context import pc_control_diagnostics

        diagnostics = pc_control_diagnostics()
    except Exception as exc:
        diagnostics = {"error": exc.__class__.__name__}
    try:
        from grandpa.desktop.control import desktop_control_diagnostics

        services = desktop_control_diagnostics(platform=sys.platform)
    except Exception as exc:
        services = {"status": "failed", "error": exc.__class__.__name__, "services": []}
    return {
        "storage": summary.get("storage", {}),
        "retention": summary.get("retention", load_retention_policy()),
        "maintenance": summary,
        "counts": _approval_counts_by_status(),
        "diagnostics": diagnostics,
        "desktop_services": services,
    }


def list_pending_actions() -> list[dict[str, Any]]:
    from grandpa.desktop.kernel.approvals import pending

    return pending()


def _list_pending_actions_impl() -> list[dict[str, Any]]:
    _expire_pending()
    return list_approval_records(statuses=("pending",))


def list_approval_records(
    *,
    statuses: tuple[str, ...] = (
        "pending",
        "approved",
        "completed",
        "rejected",
        "expired",
        "cancelled",
        "blocked",
        "failed",
    ),
    limit: int = 100,
) -> list[dict[str, Any]]:
    return _list_approval_records_impl(statuses=statuses, limit=limit)


def _list_approval_records_impl(
    *,
    statuses: tuple[str, ...] = (
        "pending",
        "approved",
        "completed",
        "rejected",
        "expired",
        "cancelled",
        "blocked",
        "failed",
    ),
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
    from grandpa.desktop.kernel.audits import recent

    return recent(limit)


def _read_recent_audit_entries_impl(limit: int = 100) -> list[dict[str, Any]]:
    path = get_audit_log_path()
    if not path.exists():
        return []
    safe_limit = max(1, min(int(limit or 100), 500))
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[
            -safe_limit:
        ]
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


#: Applications whose launch is more consequential than an ordinary one.
#:
#: ``shell_run`` and ``script_run`` are BLOCKED, but *launching the shell
#: application* was not gated at all: ``open_app`` is LOW, risk was computed
#: from the action type alone, and the surface denylist that was doing the work
#: matched ``\bcmd\b`` while missing "command prompt", "terminal", "regedit"
#: and "task manager". Matching more phrases would not fix that -- the tier has
#: to depend on what is being launched.
#:
#: Keys are canonical application ids where the launcher has one, and the
#: spoken or typed name where it does not. Every entry raises the tier; none
#: lowers it, and nothing outside this table is affected.
#:
#: Every spelling of one program needs its own key, because a launch is
#: classified from the exact string the caller passed and nothing normalises
#: ``wt`` into "terminal" beforehand. So the executable name sits beside the
#: spoken one: ``taskmgr.exe`` is Task Manager, ``wt`` is what the app resolver
#: itself calls Windows Terminal, ``pwsh`` is the shell this project records as
#: the preferred one. Each of those was an ordinary LOW launch until it was
#: listed here.
#:
#: Being listed here decides whether Grandpa *asks*, which is not the same
#: question as whether a launch can succeed. ``is_safe_launch_target`` refuses
#: cmd.exe, powershell.exe, pwsh.exe, regedit.exe and diskpart.exe at the
#: launch leaf regardless, so for those five this table only means the user is
#: asked before being refused. The ones where it is the sole gate are the
#: launchable ones -- wt.exe and taskmgr.exe are in no denylist.
#:
#: Inventory display names ("Command Prompt (Admin)") are still out of reach;
#: see ``_sensitive_app_risk`` for why resolution cannot move ahead of
#: classification here.
SENSITIVE_APP_RISK: dict[str, RiskLevel] = {
    # Shells: a command prompt is a general-purpose execution surface, which is
    # the same reason shell_run is blocked outright.
    "cmd": "MEDIUM",
    "cmd.exe": "MEDIUM",
    "command prompt": "MEDIUM",
    "powershell": "MEDIUM",
    "powershell.exe": "MEDIUM",
    "windows powershell": "MEDIUM",
    "pwsh": "MEDIUM",
    "pwsh.exe": "MEDIUM",
    "terminal": "MEDIUM",
    "wt": "MEDIUM",
    "wt.exe": "MEDIUM",
    "windowsterminal": "MEDIUM",
    # Process control.
    "task_manager": "MEDIUM",
    "task manager": "MEDIUM",
    "taskmgr": "MEDIUM",
    "taskmgr.exe": "MEDIUM",
    # The registry editor can change how the machine boots.
    "regedit": "HIGH",
    "regedit.exe": "HIGH",
    "registry editor": "HIGH",
    # Partitioning: diskpart can repartition or wipe a disk outright.
    "diskpart": "HIGH",
    "diskpart.exe": "HIGH",
}


#: Applications recognised by the executable that actually runs, rather than by
#: the name a shortcut or a user gave them.
#:
#: Deliberately tiny. Every entry must be an executable this system can
#: actually identify today, and the evidence for adding one is that the program
#: is a general-purpose command surface -- the same reason ``cmd`` and
#: ``powershell`` are MEDIUM in ``SENSITIVE_APP_RISK``.
#:
#: ``git-bash.exe`` is here because an inventory row backed by that executable
#: is reachable directly, with no shortcut in the way, and was classified as an
#: ordinary launch. Shells reached only through a ``.lnk`` are not listed: their
#: executable identity cannot currently be recovered, so an entry for them would
#: be unreachable and untestable, which is coverage in appearance only.
#:
#: This is not the launch denylist. ``BLOCKED_EXECUTABLE_NAMES`` refuses a
#: launch outright; this decides the tier, and therefore whether to ask first.
SENSITIVE_EXECUTABLE_RISK: dict[str, RiskLevel] = {
    "git-bash.exe": "MEDIUM",
}


def _sensitive_app_risk(target: str) -> RiskLevel | None:
    """The raised tier for launching *target*, or None for an ordinary app.

    Resolved through ``SAFE_APP_ALIASES`` -- the same table the launcher itself
    uses -- so "windows terminal" and "terminal" are recognised as one
    application rather than as two strings to match.

    Delegates to ``grandpa.policy.engine`` so the approval gate and the
    classifier read the same rules from the same place. Before this it held a
    second copy of the lookup, which meant an executable could be MEDIUM to the
    classifier and invisible to ``_launch_needs_approval``.

    Deliberately no inventory lookup. Classification runs before execution and
    several times per request, so it must stay cheap and side-effect free,
    while the inventory is a JSON read. The consequence is a known limit: a
    shell reachable only under an inventory display name, or behind a shortcut
    whose target cannot be read, is still classified as an ordinary launch.
    Closing that needs resolution to move ahead of classification, which is a
    larger change than this.
    """
    from grandpa.policy.engine import sensitive_app_risk as _policy_lookup

    return _policy_lookup(target, _risk_tables())


def _launch_needs_approval(request: LocalActionRequest) -> bool:
    """Whether this is the launch of an application that must be confirmed.

    Separate from the risk tier because the approval gate keys on the action
    type, and ``open_app`` as a whole must not become approval-gated -- that
    would ask before opening a browser.
    """
    # Read defensively: this is reached from the kernel facade as well as the
    # gate, and that facade has always answered rather than raised for a
    # request too malformed to classify. Such a request is not a launch.
    action = _normalise_action_type(str(getattr(request, "action_type", "") or ""))
    if action != "open_app":
        return False
    return _sensitive_app_risk(str(getattr(request, "target", "") or "")) is not None


def classify_risk(request: LocalActionRequest) -> RiskLevel:
    from grandpa.desktop.kernel.risk import classify

    return classify(request)  # type: ignore[return-value]


def _risk_tables() -> RiskTables:
    """The data classification reads, gathered here and passed to the engine.

    ``grandpa.policy`` deliberately imports nothing from this module, so the
    tables travel as an argument rather than as an import. That keeps the
    dependency pointing one way -- pc_control -> policy -- and leaves the alias
    table where the launcher already owns it.
    """
    from grandpa.policy.engine import RiskTables as _RiskTables

    try:
        from grandpa.desktop.control.applications import SAFE_APP_ALIASES

        aliases: Mapping[str, str] = SAFE_APP_ALIASES
    except Exception:
        # Unchanged from the original lookup: an unavailable alias table means
        # names are matched as typed, not that classification fails.
        aliases = {}
    return _RiskTables(
        blocked=BLOCKED_ACTIONS,
        high=HIGH_RISK_ACTIONS,
        medium=MEDIUM_RISK_ACTIONS,
        low=LOW_RISK_ACTIONS,
        sensitive_apps=SENSITIVE_APP_RISK,
        sensitive_executables=SENSITIVE_EXECUTABLE_RISK,
        aliases=aliases,
        approval_required=APPROVAL_REQUIRED_ACTIONS,
    )


def _classify_risk_impl(request: LocalActionRequest) -> RiskLevel:
    """Delegates to ``grandpa.policy.engine``; the logic moved, not the policy.

    The engine reproduces the previous ordering exactly -- BLOCKED first, then
    the sensitive-application raise for ``open_app`` only, then HIGH/MEDIUM/LOW
    by action type, then default deny. Parity across every action type and
    every sensitive key is held by ``tests/test_policy_engine_parity.py``.

    Only classification moved. The approval gate, the emergency stop, dry run,
    provenance, verification and execution all remain in this module.
    """
    from grandpa.policy.engine import classify_risk as _policy_classify

    return _policy_classify(request, _risk_tables()).risk_level  # type: ignore[arg-type]


def _execute(
    request: LocalActionRequest,
    risk: RiskLevel,
    *,
    launch_path: str = "",
) -> LocalActionResponse:
    """Run *request*.

    ``launch_path`` is supplied only by the approval path, where the program to
    start has already been resolved and verified against the staged binding.
    Passing it through means execution starts the application that was
    approved, not whatever the inventory resolves to a moment later. The direct
    path leaves it empty and resolves as it always has.
    """
    try:
        action = _normalise_action_type(request.action_type)
        if action in {"open_app", "detect_app"}:
            return _execute_app(request, action, launch_path=launch_path)
        if action == "open_folder":
            return _execute_open_folder(request)
        if action == "close_app":
            return _execute_window_alias(request, "close")
        if action in {
            "list_windows",
            "focus_window",
            "minimize_window",
            "maximize_window",
            "restore_window",
            "close_window",
        }:
            return _execute_window(request, action)
        if action.startswith("volume_"):
            return _execute_volume(request, action)
        if action == "empty_recycle_bin":
            return _execute_empty_recycle_bin()
        if action.startswith("brightness_"):
            return _execute_brightness(request, action)
        if action.startswith("clipboard_"):
            return _execute_clipboard(request, action)
        if action in {"list_monitors", "monitor_info"}:
            return _execute_monitor(request, action)
        if action in {
            "active_process",
            "list_processes",
            "desktop_summary",
            "pc_diagnostics",
        }:
            return _execute_desktop_context(request, action)
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


def _execute_app(
    request: LocalActionRequest, action: str, *, launch_path: str = ""
) -> LocalActionResponse:
    from grandpa.desktop.control import get_application_service

    return get_application_service().execute(request, action, launch_path=launch_path)


def _execute_open_folder(request: LocalActionRequest) -> LocalActionResponse:
    path = _resolve_path(request.target)
    if not path.exists() or not path.is_dir():
        return LocalActionResponse(
            False,
            None,
            "failed",
            f"I could not find the folder: {request.target}",
            False,
            "LOW",
            {"path": str(path)},
            error="missing_folder",
        )
    if _is_protected_path(path):
        return LocalActionResponse(
            False,
            None,
            "blocked",
            "I blocked this folder action because the path is protected.",
            False,
            "HIGH",
            {"path": str(path)},
            error="protected_path",
        )
    os.startfile(path)  # type: ignore[attr-defined]  # noqa: S606
    return LocalActionResponse(
        True,
        None,
        "completed",
        f"Opened folder: {path}",
        False,
        "LOW",
        {"path": str(path)},
    )


def _execute_window_alias(
    request: LocalActionRequest, action: str
) -> LocalActionResponse:
    from grandpa.desktop.control import get_window_service

    return get_window_service().execute_alias(request, action)


def _execute_window(request: LocalActionRequest, action: str) -> LocalActionResponse:
    from grandpa.desktop.control import get_window_service

    return get_window_service().execute(request, action)


def _execute_volume(request: LocalActionRequest, action: str) -> LocalActionResponse:
    from grandpa.desktop.control import get_power_service

    return get_power_service().execute_volume(request, action, platform=sys.platform)


def _execute_empty_recycle_bin() -> LocalActionResponse:
    from grandpa.desktop.control import get_power_service

    return get_power_service().execute_empty_recycle_bin(platform=sys.platform)


def _execute_brightness(
    request: LocalActionRequest, action: str
) -> LocalActionResponse:
    from grandpa.desktop.control import get_power_service

    return get_power_service().execute_brightness(request, action)


def _execute_monitor(request: LocalActionRequest, action: str) -> LocalActionResponse:
    from grandpa.desktop.control import get_monitor_service

    return get_monitor_service().execute(request, action)


def _execute_desktop_context(
    request: LocalActionRequest, action: str
) -> LocalActionResponse:
    from grandpa.desktop.control import get_diagnostics_service

    return get_diagnostics_service().execute(request, action)


def _execute_clipboard(request: LocalActionRequest, action: str) -> LocalActionResponse:
    from grandpa.desktop.control import get_clipboard_service

    return get_clipboard_service().execute(request, action)


def _execute_file(request: LocalActionRequest, action: str) -> LocalActionResponse:
    from grandpa.desktop.control import get_file_service

    return get_file_service().execute(request, action)


def _execute_input(request: LocalActionRequest, action: str) -> LocalActionResponse:
    from grandpa.desktop.control import get_automation_service

    return get_automation_service().execute(request, action, platform=sys.platform)


def _execute_system(request: LocalActionRequest, action: str) -> LocalActionResponse:
    from grandpa.desktop.control import get_power_service

    return get_power_service().execute_system(action, platform=sys.platform)


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
        "browser_diagnostics": ("diagnostics", "browser"),
        "browser_media": ("media", request.target),
        "browser_task": ("task", request.target),
        "browser_click": ("click", request.target),
        "browser_focus": ("focus_search", request.target or "visible"),
        "browser_back": ("back", "visible"),
        "browser_forward": ("forward", "visible"),
        "browser_reload": ("reload", "visible"),
        "browser_form_fill": ("form_fill", request.target),
        "browser_download": ("download", request.target),
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
            "details": _browser_result_details(result.target),
            "visible_only": True,
        },
        error=None if status == "completed" else result.status,
    )


def _preflight_guard(
    request: LocalActionRequest, risk: RiskLevel
) -> LocalActionResponse | None:
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
    if action == "keyboard_hotkey":
        # Checked here, before the approval gate, so a denied shortcut fails
        # immediately instead of asking the operator to approve something that
        # can never run. The actuation layer re-checks as defence in depth.
        from grandpa.desktop.control.automation import is_blocked_hotkey

        # Check both slots independently rather than resolving one. An empty
        # ``keys`` entry suppresses the fallback to ``target``, so checking only
        # the resolved value would let ``{"target": "win+r", "keys": ""}`` stage
        # for approval. Checking both can only ever block more, never less.
        if is_blocked_hotkey(request.args.get("keys")) or is_blocked_hotkey(
            request.target
        ):
            return _blocked(
                "I blocked this hotkey because it opens a command-execution surface."
            )
    if action in {"keyboard_type", "keyboard_hotkey", "mouse_click", "mouse_drag"}:
        try:
            from grandpa.desktop_context import active_window_is_protected

            if active_window_is_protected():
                return LocalActionResponse(
                    ok=False,
                    action_id=None,
                    status="blocked",
                    message="I blocked this automation action because the active window appears sensitive.",
                    approval_required=False,
                    risk_level="HIGH",
                    evidence={"protected_window": True},
                    error="protected_window",
                )
        except Exception:
            pass
    return None


def _browser_result_details(target: str) -> dict[str, Any]:
    try:
        value = json.loads(target)
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def _dry_run_message(request: LocalActionRequest, risk: RiskLevel) -> str:
    return f"Dry run: {request.action_type} would run on {request.target or 'the current target'} with {risk} risk."


def _approval_message(request: LocalActionRequest) -> str:
    return f"Approval required before running {request.action_type} on {request.target or 'this PC'}."


def get_approval_db_path() -> Path:
    return _get_approval_db_path_impl()


def _get_approval_db_path_impl() -> Path:
    configured = os.environ.get("GRANDPA_PC_CONTROL_DB")
    if configured:
        return Path(configured)
    return DEFAULT_APPROVAL_DB


def get_retention_config_path() -> Path:
    return _get_retention_config_path_impl()


def _get_retention_config_path_impl() -> Path:
    configured = os.environ.get("GRANDPA_PC_CONTROL_RETENTION_CONFIG")
    if configured:
        return Path(configured)
    return DEFAULT_RETENTION_CONFIG


def load_retention_policy() -> dict[str, int]:
    from grandpa.desktop.kernel.audits import retention_policy

    return retention_policy()


def _load_retention_policy_impl() -> dict[str, int]:
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
            path.write_text(
                json.dumps(policy, indent=2, sort_keys=True), encoding="utf-8"
            )
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
            decision_timestamp REAL,
            approval_token TEXT NOT NULL DEFAULT '',
            action_digest TEXT NOT NULL DEFAULT '',
            origin TEXT NOT NULL DEFAULT ''
        )
        """
    )
    # Migrate approval databases created before out-of-band approval codes.
    columns = {
        str(row["name"])
        for row in conn.execute("PRAGMA table_info(pc_control_approvals)")
    }
    if "approval_token" not in columns:
        conn.execute(
            "ALTER TABLE pc_control_approvals "
            "ADD COLUMN approval_token TEXT NOT NULL DEFAULT ''"
        )
    # Migrate databases created before approvals were bound to an identity.
    # Rows written then carry an empty digest, and an empty digest is refused
    # rather than recomputed -- see ``_approve_local_action_impl``.
    if "action_digest" not in columns:
        conn.execute(
            "ALTER TABLE pc_control_approvals "
            "ADD COLUMN action_digest TEXT NOT NULL DEFAULT ''"
        )
    # Migrate databases created before provenance was persisted (AD-022). Rows
    # written then carry an empty origin, which ``_coerce_origin`` reads as
    # ``direct`` -- the least-privileged label, never a trusted one.
    if "origin" not in columns:
        conn.execute(
            "ALTER TABLE pc_control_approvals "
            "ADD COLUMN origin TEXT NOT NULL DEFAULT ''"
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
    for status in (
        "pending",
        "completed",
        "approved",
        "rejected",
        "expired",
        "cancelled",
        "blocked",
        "failed",
    ):
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
        # AD-022. Without this the request was rebuilt with the default and
        # every approved action was audited as ``direct``, whoever had asked --
        # so the trail lost provenance exactly for the actions important enough
        # to need a human decision.
        #
        # Coerced rather than trusted: the value is read back from a database,
        # and a row predating this column, or one edited outside the
        # application, must not be able to name an origin that does not exist.
        # Unknown becomes ``direct``, the least-privileged label.
        origin=_coerce_origin(
            row["origin"] if "origin" in row.keys() else DEFAULT_ACTION_ORIGIN
        ),
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
        decision_timestamp=float(row["decision_timestamp"])
        if row["decision_timestamp"] is not None
        else None,
        approval_token=str(
            row["approval_token"] if "approval_token" in row.keys() else ""
        ),
        action_digest=str(
            row["action_digest"] if "action_digest" in row.keys() else ""
        ),
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
        "decision_timestamp": float(row["decision_timestamp"])
        if row["decision_timestamp"] is not None
        else None,
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


def _canonical_launch_identity(request: LocalActionRequest) -> tuple[str, str]:
    """The executable and launch path *this* request would start, or two empty
    strings when the action does not name an application.

    One inventory read. Only ``open_app`` resolves: every other action carries
    its own target, so there is nothing to look up and nothing that could drift
    between staging and approval.

    A failure to resolve is an empty identity rather than an exception. That is
    deliberate: an approval staged against a resolvable application and later
    meeting an unresolvable one must *fail the comparison*, which is a refusal,
    not crash the approve path.
    """
    if _normalise_action_type(str(getattr(request, "action_type", "") or "")) != (
        "open_app"
    ):
        return "", ""
    target = str(getattr(request, "target", "") or "")
    if not target:
        return "", ""
    try:
        from grandpa.apps.inventory import find_app

        result = find_app(target)
        if result.status != "found" or not result.matches:
            return "", ""
        path = result.matches[0].path
    except Exception:
        return "", ""
    return Path(path).name.lower(), str(path)


def _action_digest(
    request: LocalActionRequest, executable: str, launch_path: str
) -> str:
    """A deterministic fingerprint of *what* this action would do.

    Covers the action type, the target as asked, the arguments, and the
    program the target resolved to. Sorted keys and separator-tight JSON make
    it independent of dictionary ordering, so the same action written two ways
    fingerprints identically.

    Excludes ``origin``, ``require_approval``, ``dry_run``, the approval token,
    the risk tier and every timestamp. The digest answers "what was approved",
    not "who asked", "when", or "what did policy think of it" -- and folding
    those in would make an approval fail for reasons that have nothing to do
    with the action changing.
    """
    payload = {
        "action_type": _normalise_action_type(
            str(getattr(request, "action_type", "") or "")
        ),
        "target": str(getattr(request, "target", "") or ""),
        "args": getattr(request, "args", None) or {},
        "executable": executable,
        "launch_path": launch_path,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _create_pending(request: LocalActionRequest) -> str:
    _expire_pending()
    now = time.time()
    action_id = uuid.uuid4().hex
    risk = classify_risk(request)
    # Out-of-band approval code. The API caller that stages an action never
    # receives this; it is emitted only to the local operator's console/log, so
    # possession of an action_id alone cannot authorise execution.
    token = secrets.token_hex(4).upper()
    # Resolved once, here, and fingerprinted: this is the identity a person is
    # about to be shown and asked to approve. Approval recomputes it and
    # refuses if it has moved.
    executable, launch_path = _canonical_launch_identity(request)
    digest = _action_digest(request, executable, launch_path)
    args_json = json.dumps(request.args, ensure_ascii=True, sort_keys=True, default=str)
    with _connect_approval_db() as conn:
        conn.execute(
            """
            INSERT INTO pc_control_approvals (
                action_id, action_type, target, args_json, risk_level, created_at,
                expires_at, status, approval_required, decision, decision_timestamp,
                approval_token, action_digest, origin
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, 'pending', NULL, ?, ?, ?)
            """,
            (
                action_id,
                request.action_type,
                request.target,
                args_json,
                risk,
                now,
                now + PENDING_TTL_SECONDS,
                int(
                    request.require_approval
                    or risk == "HIGH"
                    or _normalise_action_type(request.action_type)
                    in APPROVAL_REQUIRED_ACTIONS
                ),
                token,
                digest,
                request.origin,
            ),
        )
    logger.warning(
        "Local action %s requires approval: %s (risk %s). Approval code: %s "
        "(expires in %ds)",
        action_id,
        request.action_type,
        risk,
        token,
        PENDING_TTL_SECONDS,
    )
    return action_id


def _cleanup_old_approval_records(policy: dict[str, int]) -> int:
    retention_days = max(
        1, int(policy.get("approval_retention_days", DEFAULT_RETENTION_DAYS))
    )
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
    keep_lines = max(
        1, int(policy.get("audit_keep_recent_lines", DEFAULT_AUDIT_KEEP_RECENT_LINES))
    )
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


def _audit(
    request: LocalActionRequest, response: LocalActionResponse, *, approval_status: str
) -> None:
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
        # AD-022 consequence 3: the trail must distinguish a user-typed action
        # from a model-selected one. Without this the audit log cannot answer
        # "who asked for this?" after the fact.
        "origin": request.origin,
        # Whether the action was confirmed to have taken effect. "unknown"
        # means it could not be checked, not that it went wrong.
        "verification": (response.evidence or {})
        .get("verification", {})
        .get("status", "unknown"),
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=True) + "\n")


def get_audit_log_path() -> Path:
    return _get_audit_log_path_impl()


def _get_audit_log_path_impl() -> Path:
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
        origin=_coerce_origin(payload.get("origin")),
    )


def _capture_pre_state(request: LocalActionRequest) -> dict[str, Any] | None:
    """Take the baseline a relative action will be judged against.

    Returns None -- touching no device at all -- for every action that does not
    need one, which is all but ``volume_up`` and ``volume_down``. The scoping
    decision lives in the verification module so the set of actions that pay
    for a pre-read sits next to the verifiers that consume it.

    A baseline that cannot be taken means "unverifiable", never a failed
    action, and never a failed request.
    """
    from grandpa.desktop.control.verification import capture_pre_state

    try:
        return capture_pre_state(request)
    except Exception:
        return None


def _apply_verification(
    request: LocalActionRequest,
    response: LocalActionResponse,
    pre_state: dict[str, Any] | None = None,
) -> LocalActionResponse:
    """Read state back after a successful execute and record what was seen.

    Runs between ``_execute`` and ``_audit`` so the audit record carries the
    verification outcome. Only successful executions are checked -- an actuator
    that already reported failure is left exactly as it is.

    A ``failed`` verification downgrades the response, because reporting
    success for an action that demonstrably did not happen is the behaviour
    this exists to prevent. ``unknown`` never downgrades: it means the action
    could not be checked, which is not evidence that it went wrong.

    Verification is observational. It never touches ``risk_level`` or
    ``approval_required``, so it cannot widen or narrow a policy decision.
    """
    if not response.ok or response.status != "completed":
        return response

    from grandpa.desktop.control.verification import verify_action

    outcome = verify_action(request, response, pre_state)
    evidence = dict(response.evidence or {})
    evidence["verification"] = outcome.to_dict()
    response.evidence = evidence

    if outcome.status == "failed":
        response.ok = False
        response.status = "failed"
        response.error = "verification_failed"
        response.message = (
            f"{response.message} However, I could not confirm it took effect: "
            f"{outcome.detail}."
        ).strip()
    return response


def _coerce_origin(value: Any) -> ActionOrigin:
    """Normalise an origin, falling back to ``direct`` for anything unknown.

    Unrecognised values fall back rather than raise: origin is provenance for
    the audit trail, and a caller passing something unexpected should not turn
    into a failed action. The fallback is the least-privileged label, so an
    unknown caller is never recorded as a trusted one.
    """
    candidate = str(value or "").strip().lower()
    if candidate in ACTION_ORIGINS:
        return candidate  # type: ignore[return-value]
    return DEFAULT_ACTION_ORIGIN


def _normalise_action_type(value: str) -> str:
    return value.strip().lower().replace("-", "_").replace(" ", "_")


def _app_id(name: str) -> str | None:
    from grandpa.desktop.control import get_application_service

    return get_application_service().app_id(name)


def _resolve_path(path: str) -> Path:
    from grandpa.desktop.control import get_file_service

    return get_file_service().resolve_path(path)


def _is_protected_path(path: Path) -> bool:
    parts = _normalised_path_parts(path)
    if _is_windows_root_protected(parts):
        return True
    if set(parts) & PROTECTED_PATH_PARTS:
        return True
    return any(
        _contains_path_sequence(parts, sequence)
        for sequence in PROTECTED_PATH_SEQUENCES
    )


def _normalised_path_parts(path: Path) -> tuple[str, ...]:
    resolved = path.expanduser().resolve(strict=False)
    raw = str(resolved).replace("/", "\\")
    if len(raw) >= 2 and raw[1] == ":":
        return tuple(
            part.rstrip("\\/").lower()
            for part in PureWindowsPath(raw).parts
            if part.rstrip("\\/")
        )
    return tuple(part.lower() for part in resolved.parts if part)


def _is_windows_root_protected(parts: tuple[str, ...]) -> bool:
    if len(parts) < 2:
        return False
    drive = parts[0]
    first_directory = parts[1]
    return drive.endswith(":") and first_directory in PROTECTED_WINDOWS_ROOT_NAMES


def _contains_path_sequence(parts: tuple[str, ...], sequence: tuple[str, ...]) -> bool:
    if len(sequence) > len(parts):
        return False
    return any(
        parts[index : index + len(sequence)] == sequence
        for index in range(len(parts) - len(sequence) + 1)
    )


def _redact_target(action_type: str, target: str) -> str:
    if _normalise_action_type(action_type).startswith("clipboard_"):
        return "[redacted]"
    if any(key in action_type.lower() for key in SECRET_KEYS):
        return "[redacted]"
    return target


def _blocked(message: str) -> LocalActionResponse:
    return LocalActionResponse(
        False, None, "blocked", message, False, "BLOCKED", error="blocked_by_policy"
    )


def _unsupported(message: str, risk: RiskLevel) -> LocalActionResponse:
    return LocalActionResponse(
        False, None, "unsupported", message, False, risk, error="unsupported"
    )


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
