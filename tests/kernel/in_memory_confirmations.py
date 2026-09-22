"""A single-process confirmation service, for tests that want one.

This lived in ``src/grandpa/kernel/compat.py`` with a docstring saying
"compatibility tests only" -- while ``files/automation`` reached it in
production, which made its 120-second expiry the fourth live expiry policy in
the product. Production now uses
``grandpa.kernel.confirmations.StoredConfirmationService``, which is the kernel
approval store and its one policy. A test-only stand-in belongs here, where it
cannot be reached by accident.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

from grandpa.kernel.models import (
    AssistantRequest,
    ConfirmationRequest,
    PlannedAction,
    PolicyDecision,
)


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


class InMemoryConfirmationService:
    """Exact-action confirmation held in a dict, for one process."""

    def __init__(self, *, ttl_seconds: int = 120) -> None:
        self._ttl_seconds = ttl_seconds
        self._pending: dict[str, ConfirmationRequest] = {}

    def issue(
        self,
        request: AssistantRequest,
        action: PlannedAction,
        decision: PolicyDecision,
    ) -> ConfirmationRequest:
        confirmation = ConfirmationRequest(
            token=secrets.token_urlsafe(24),
            request_id=request.request_id,
            session_id=request.session_id,
            action_id=action.action_id,
            action_digest=decision.action_digest,
            expires_at=_utc_now() + timedelta(seconds=self._ttl_seconds),
        )
        self._pending[confirmation.token] = confirmation
        return confirmation

    def validate(
        self,
        token: str,
        request: AssistantRequest,
        action: PlannedAction,
        decision: PolicyDecision,
    ) -> bool:
        confirmation = self._pending.get(token)
        valid = bool(
            confirmation
            and confirmation.expires_at > _utc_now()
            and confirmation.request_id == request.request_id
            and confirmation.session_id == request.session_id
            and confirmation.action_id == action.action_id
            and confirmation.action_digest == decision.action_digest
        )
        if valid:
            self._pending.pop(token, None)
        return valid


__all__ = ["InMemoryConfirmationService"]
