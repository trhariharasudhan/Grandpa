"""Short-lived explicit confirmation records for interactive automation."""

from __future__ import annotations

import secrets
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
    def __init__(self, *, ttl_seconds: float = 120.0) -> None:
        self.ttl_seconds = ttl_seconds
        self._pending: dict[str, PendingAutomationAction] = {}
        self._lock = threading.RLock()

    def create(self, action: AutomationAction) -> PendingAutomationAction:
        now = time.monotonic()
        record = PendingAutomationAction(
            secrets.token_urlsafe(18), action, now, now + self.ttl_seconds
        )
        with self._lock:
            self._purge(now)
            self._pending[record.token] = record
        return record

    def consume(self, token: str) -> AutomationAction | None:
        now = time.monotonic()
        with self._lock:
            self._purge(now)
            record = self._pending.pop(token, None)
        return record.action if record is not None else None

    def reject(self, token: str) -> bool:
        with self._lock:
            return self._pending.pop(token, None) is not None

    def _purge(self, now: float) -> None:
        expired = [token for token, item in self._pending.items() if item.expires_at <= now]
        for token in expired:
            self._pending.pop(token, None)


__all__ = ["ConfirmationManager", "PendingAutomationAction"]
