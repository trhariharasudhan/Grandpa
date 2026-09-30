"""Persistent approval lifecycle facade for PC-control actions."""

from __future__ import annotations

from typing import Any


def create(request: Any) -> str:
    from grandpa import pc_control

    return pc_control._create_pending(request)


def approve(action_id: str, token: str = ""):
    from grandpa import pc_control

    return pc_control._approve_local_action_impl(action_id, token)


def reject(action_id: str):
    from grandpa import pc_control

    return pc_control._reject_local_action_impl(action_id)


def db_path():
    """Where the one approval store lives."""
    from grandpa import pc_control

    return pc_control.get_approval_db_path()


def pending() -> list[dict[str, Any]]:
    """Actions waiting for a code. Deferred ones are not listed: no code approves them."""
    from grandpa import pc_control

    return [
        row
        for row in pc_control._list_pending_actions_impl()
        if pc_control._consent_of(str(row.get("action_id") or ""))
        != pc_control.DEFERRED
    ]


def records(
    *, limit: int = 100, statuses: tuple[str, ...] | None = None
) -> list[dict[str, Any]]:
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


# --- deferred consent ---------------------------------------------------------
#
# The one owner of approvals. Everything that stages an action waiting for a
# human goes through here, whether the human answers with a code (pc_control's
# create/approve above) or with a "yes" on their next turn (below). There used
# to be a second store in local_action_approvals.py with its own 120-second
# expiry and no idea who staged what; it is gone.
#
# Deferred consent is opted into by passing an origin. Nothing infers it: a
# caller with no callback and no origin is refused by the action layer and
# stages nothing, which is the property verify_confirmation_enforcement's P1
# probe proves.


def stage_deferred(
    *,
    origin: str,
    action: str,
    target: str,
    parameters: dict[str, Any],
    payload: dict[str, Any],
    risk_level: str,
    witness: dict[str, Any] | None = None,
    reask_count: int = 0,
) -> dict[str, Any]:
    """Stage an action for a later yes from ``origin``, and only from it.

    ``witness`` is the focus reading a synthetic-input action was approved
    against (see grandpa.desktop.focus_witness). Passing one also records the
    origin's current turn, which is what makes the approval good for exactly the
    next turn. A row with no witness behaves as it always has.
    """
    from grandpa import pc_control

    return pc_control._stage_deferred_impl(
        origin=origin,
        action=action,
        target=target,
        parameters=parameters,
        payload=payload,
        risk_level=risk_level,
        witness=witness,
        reask_count=reask_count,
    )


def peek_deferred(*, origin: str, action_id: str | None = None):
    """This origin's pending row, unresolved, so its witness can be checked."""
    from grandpa import pc_control

    return pc_control._peek_deferred_impl(origin=origin, action_id=action_id)


def cancel_deferred(*, origin: str, action_id: str, reason: str) -> bool:
    """Drop a pending row without running it."""
    from grandpa import pc_control

    return pc_control._cancel_deferred_impl(
        origin=origin, action_id=action_id, reason=reason
    )


def current_turn(origin: str) -> int:
    """``origin``'s completed-turn count."""
    from grandpa import pc_control

    return pc_control._current_turn_impl(origin)


def bump_turn(origin: str) -> int:
    """Record that ``origin`` completed a turn. Called once per turn."""
    from grandpa import pc_control

    return pc_control._bump_turn_impl(origin)


def approve_deferred(
    *, origin: str, action_id: str | None = None
) -> dict[str, Any] | None:
    """Claim ``origin``'s one pending action, or None if there is none."""
    from grandpa import pc_control

    return pc_control._claim_deferred_impl(
        origin=origin, decision="approved", action_id=action_id
    )


def deny_deferred(
    *, origin: str, action_id: str | None = None
) -> dict[str, Any] | None:
    """Refuse ``origin``'s one pending action, or None if there is none."""
    from grandpa import pc_control

    return pc_control._claim_deferred_impl(
        origin=origin, decision="denied", action_id=action_id
    )


def pending_deferred(origin: str) -> list[dict[str, Any]]:
    """What ``origin`` has waiting for a yes -- at most one row, by construction."""
    from grandpa import pc_control

    return pc_control._list_deferred_impl(origin)
