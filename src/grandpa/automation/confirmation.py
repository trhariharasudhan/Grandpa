"""Pending confirmations for interactive automation, held by the kernel.

This used to be a store of its own: tokens in a dict, a 120-second expiry, and
no idea who had asked. That made it the third expiry policy in the product,
next to pc_control's 300 seconds and local_actions' own 120. It is now the
kernel's approval store, through ``grandpa.desktop.kernel.approvals``, which
gives a pending automation confirmation the same three rules as every other
action waiting for a yes: one expiry (300 seconds), bound to the origin that
asked, and one approval resolves exactly one action.

What stays in memory is the :class:`AutomationAction` itself, keyed by the
kernel's action id. It holds a resolved window handle, which means nothing in
another process and nothing after a restart, so there is no version of this
that could usefully be persisted. If the row is claimable but the action is
gone -- a restart between the question and the answer -- the caller is told the
confirmation is no longer available rather than something being done to a
window that may now be someone else's.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from grandpa.automation.models import AutomationAction


@dataclass(frozen=True)
class PendingAutomationAction:
    token: str
    action: AutomationAction
    created_at: float
    expires_at: float


class ConfirmationManager:
    def __init__(self, *, origin: str = "chat") -> None:
        self.origin = origin
        self._actions: dict[str, AutomationAction] = {}
        self._lock = threading.RLock()

    def create(self, action: AutomationAction) -> PendingAutomationAction:
        from grandpa.desktop.kernel import approvals

        staged = approvals.stage_deferred(
            origin=self.origin,
            action=f"screen_automation_{action.kind}",
            target=str(getattr(action, "target", "") or ""),
            parameters={},
            payload={"kind": action.kind, "target": str(action.target or "")},
            risk_level="MEDIUM",
        )
        token = str(staged["id"])
        with self._lock:
            self._actions[token] = action
        return PendingAutomationAction(
            token, action, time.time(), float(staged["expires_at"])
        )

    def consume(self, token: str) -> AutomationAction | None:
        """Claim this confirmation, once, from the origin that asked for it."""
        from grandpa.desktop.kernel import approvals

        if approvals.approve_deferred(origin=self.origin, action_id=token) is None:
            return None
        with self._lock:
            return self._actions.pop(token, None)

    def reject(self, token: str) -> bool:
        from grandpa.desktop.kernel import approvals

        claimed = approvals.deny_deferred(origin=self.origin, action_id=token)
        with self._lock:
            self._actions.pop(token, None)
        return claimed is not None


__all__ = ["ConfirmationManager", "PendingAutomationAction"]
