"""Persistent approval lifecycle facade for PC-control actions."""

from __future__ import annotations

from typing import Any


def create(request: Any) -> str:
    from grandpa import pc_control

    return pc_control._create_pending(request)


def approve(action_id: str):
    from grandpa import pc_control

    return pc_control._approve_local_action_impl(action_id)


def reject(action_id: str):
    from grandpa import pc_control

    return pc_control._reject_local_action_impl(action_id)


def pending() -> list[dict[str, Any]]:
    from grandpa import pc_control

    return pc_control._list_pending_actions_impl()


def records(*, limit: int = 100, statuses: tuple[str, ...] | None = None) -> list[dict[str, Any]]:
    from grandpa import pc_control

    if statuses is None:
        return pc_control._list_approval_records_impl(limit=limit)
    return pc_control._list_approval_records_impl(statuses=statuses, limit=limit)


def count_pending() -> int:
    from grandpa import pc_control

    return pc_control._pending_action_count_impl()


def counts() -> dict[str, int]:
    from grandpa import pc_control

    return pc_control._approval_counts_by_status()


def readiness() -> dict[str, Any]:
    from grandpa import pc_control

    return {
        "status": "ready" if pc_control._approval_db_is_healthy() else "failed",
        "database": str(pc_control._get_approval_db_path_impl()),
        "counts": counts(),
        "persistent": True,
        "local_only": True,
    }
