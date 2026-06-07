"""Audit logging, retention, and cleanup facade for PC-control actions."""

from __future__ import annotations

from typing import Any


def audit(request: Any, response: Any, *, approval_status: str) -> None:
    from grandpa import pc_control

    pc_control._audit(request, response, approval_status=approval_status)


def recent(limit: int = 100) -> list[dict[str, Any]]:
    from grandpa import pc_control

    return pc_control._read_recent_audit_entries_impl(limit)


def retention_policy() -> dict[str, int]:
    from grandpa import pc_control

    return pc_control._load_retention_policy_impl()


def cleanup() -> dict[str, Any]:
    from grandpa import pc_control

    return pc_control._run_pc_control_maintenance_impl()


def readiness() -> dict[str, Any]:
    from grandpa import pc_control

    path = pc_control._get_audit_log_path_impl()
    return {
        "status": "ready",
        "audit_log": str(path),
        "exists": path.exists(),
        "retention": retention_policy(),
    }
