"""What the local router records about a decision it made."""

from __future__ import annotations

import logging

from grandpa.local_action_approvals import LocalActionApprovalStore
from grandpa.local_action_result import LocalActionResult

logger = logging.getLogger(__name__)


def audit_decision(command: str, result: LocalActionResult, decision: str) -> None:
    try:
        LocalActionApprovalStore().audit(
            action_id=(result.pending_action or {}).get("id"),
            decision=decision,
            source_text=command,
            kind=result.kind,
            target=result.target,
            detail={"permission": result.permission, "status": result.status},
        )
    except Exception:
        logger.debug("Failed to audit local action decision", exc_info=True)


def log_attempt(command: str, result: LocalActionResult) -> None:
    logger.info(
        "local_action_attempt command=%r status=%s kind=%s target=%r",
        command,
        result.status,
        result.kind,
        result.target,
    )
    try:
        from grandpa.memory_context import record_activity

        action = "blocked" if result.status == "blocked" else "open"
        if result.kind in {
            "time",
            "system_info",
            "screen",
            "screenshot",
            "automation",
            "window",
            "pc_control",
        }:
            action = result.kind
        record_activity(
            result.kind if result.kind != "blocked" else "safety",
            action,
            result.target,
            command,
            result.status,
        )
    except Exception:
        logger.debug("Failed to record local action activity", exc_info=True)
