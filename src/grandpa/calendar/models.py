"""Models for Grandpa's safe Google Calendar integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

CalendarActionType = Literal[
    "status",
    "setup",
    "disconnect",
    "list",
    "search",
    "read",
    "create",
    "update",
    "delete",
    "freebusy",
    "upcoming",
]

CalendarActionStatus = Literal[
    "handled",
    "needs_confirmation",
    "blocked",
    "unsupported",
    "not_configured",
    "no_match",
    "error",
]


@dataclass(frozen=True)
class CalendarAction:
    """Parsed Calendar command."""

    action: CalendarActionType
    query: str = ""
    event_id: str = ""
    title: str = ""
    start_text: str = ""
    end_text: str = ""
    date_range: str = ""
    timezone: str = ""
    duration_minutes: int = 60
    args: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CalendarEventSummary:
    """Safe compact representation of one Calendar event."""

    event_id: str
    title: str = ""
    start: str = ""
    end: str = ""
    location: str = ""
    attendees: tuple[str, ...] = ()
    description: str = ""
    recurring: bool = False


@dataclass(frozen=True)
class CalendarResult:
    """User-facing Calendar result."""

    status: CalendarActionStatus
    message: str
    action: CalendarAction | None = None
    events: tuple[CalendarEventSummary, ...] = ()
    requires_confirmation: bool = False
    account: str = ""
    error: str | None = None

    @property
    def should_fallback(self) -> bool:
        return self.status == "no_match"


__all__ = [
    "CalendarAction",
    "CalendarActionStatus",
    "CalendarActionType",
    "CalendarEventSummary",
    "CalendarResult",
]
