"""Session-based continuous conversation mode state.

This module does not start microphone capture, timers, threads, or background
workers. Timeout expiration is evaluated only when callers interact with the
session.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

DEFAULT_CONVERSATION_MODE_TIMEOUT_SECONDS = 60


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


@dataclass
class ConversationModeSession:
    enabled: bool = False
    active: bool = False
    started_at: datetime | None = None
    last_activity_at: datetime | None = None
    timeout_seconds: int = DEFAULT_CONVERSATION_MODE_TIMEOUT_SECONDS
    last_transcript: str | None = None
    turn_count: int = 0

    def enable(self) -> dict[str, Any]:
        self.enabled = True
        return self.status()

    def disable(self) -> dict[str, Any]:
        self.enabled = False
        self.active = False
        return self.status()

    def start(self) -> dict[str, Any]:
        self.enabled = True
        self.active = True
        now = _now()
        self.started_at = now
        self.last_activity_at = now
        return self.status()

    def stop(self) -> dict[str, Any]:
        self._expire_if_needed()
        self.active = False
        return self.status()

    def touch(self, transcript: str | None = None) -> dict[str, Any]:
        self._expire_if_needed()
        if not self.enabled or not self.active:
            return self.status()
        now = _now()
        self.last_activity_at = now
        if transcript is not None:
            text = transcript.strip()
            if text:
                self.last_transcript = text
                self.turn_count += 1
        return self.status()

    def status(self) -> dict[str, Any]:
        self._expire_if_needed()
        return {
            "enabled": self.enabled,
            "active": self.active,
            "started_at": _iso(self.started_at),
            "last_activity_at": _iso(self.last_activity_at),
            "timeout_seconds": self.timeout_seconds,
            "last_transcript": self.last_transcript,
            "turn_count": self.turn_count,
            "microphone_required": False,
            "background_thread": False,
        }

    def _expire_if_needed(self) -> None:
        if not self.active or not self.last_activity_at:
            return
        elapsed = (_now() - self.last_activity_at).total_seconds()
        if elapsed > self.timeout_seconds:
            self.active = False


__all__ = [
    "DEFAULT_CONVERSATION_MODE_TIMEOUT_SECONDS",
    "ConversationModeSession",
]
