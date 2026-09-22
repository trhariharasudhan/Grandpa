"""The kernel's confirmations, kept in the one approval store.

``kernel/compat.py`` used to hold these in a dict with a 120-second expiry, in a
class whose docstring said "compatibility tests only" while ``files/automation``
reached it in production. That made it the fourth expiry policy in the product,
after pc_control's 300 seconds, local_actions' 120 and Screen Automation V2's
120. The first three are now one; this is the last of them.

A confirmation here is deferred consent, which is exactly what the kernel store
already holds: it expires on ``PENDING_TTL_SECONDS``, it is bound to the origin
that asked, and one approval resolves one action. Unlike synthetic input, a file
action *can* be consented to a turn later -- "copy this file" means the same
thing in a minute -- so staging is right for it.

A token is only accepted back for the request, session, action and digest it was
issued for, which is what the in-memory version checked too: a token is not a
licence to run something else.
"""

from __future__ import annotations

from datetime import UTC, datetime

from grandpa.kernel.models import (
    AssistantRequest,
    ConfirmationRequest,
    PlannedAction,
    PolicyDecision,
)


class StoredConfirmationService:
    """Issue and validate confirmations through the kernel's approval store."""

    def _origin(self, request: AssistantRequest) -> str:
        # Bound to the session that asked, so one session's token cannot answer
        # another's question.
        return f"kernel:{request.session_id}"

    def issue(
        self,
        request: AssistantRequest,
        action: PlannedAction,
        decision: PolicyDecision,
    ) -> ConfirmationRequest:
        from grandpa.desktop.kernel import approvals

        staged = approvals.stage_deferred(
            origin=self._origin(request),
            action=action.tool_name,
            target="",
            parameters={},
            payload={
                "request_id": request.request_id,
                "session_id": request.session_id,
                "action_id": action.action_id,
                "action_digest": decision.action_digest,
            },
            risk_level="MEDIUM",
        )
        return ConfirmationRequest(
            token=str(staged["id"]),
            request_id=request.request_id,
            session_id=request.session_id,
            action_id=action.action_id,
            action_digest=decision.action_digest,
            expires_at=datetime.fromtimestamp(float(staged["expires_at"]), tz=UTC),
        )

    def validate(
        self,
        token: str,
        request: AssistantRequest,
        action: PlannedAction,
        decision: PolicyDecision,
    ) -> bool:
        from grandpa.desktop.kernel import approvals

        origin = self._origin(request)
        waiting = {
            str(row["id"]): row.get("payload") or {}
            for row in approvals.pending_deferred(origin)
        }
        payload = waiting.get(token)
        if payload is None:
            # Unknown, already used, expired, or another session's.
            return False
        if (
            payload.get("request_id") != request.request_id
            or payload.get("session_id") != request.session_id
            or payload.get("action_id") != action.action_id
            or payload.get("action_digest") != decision.action_digest
        ):
            return False
        # Claimed only once it is known to match: the claim is what makes it
        # single-use.
        return approvals.approve_deferred(origin=origin, action_id=token) is not None


__all__ = ["StoredConfirmationService"]
