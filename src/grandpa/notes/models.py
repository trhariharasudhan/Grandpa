"""Models for Grandpa's local notes system."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

NotesActionType = Literal[
    "list",
    "recent",
    "search",
    "open",
    "create",
    "append",
    "rename",
    "delete",
    "archive",
    "restore",
    "pin",
    "unpin",
]

NotesActionStatus = Literal[
    "handled", "needs_confirmation", "blocked", "unsupported", "no_match", "error"
]


@dataclass(frozen=True)
class Note:
    """One local Markdown note."""

    note_id: str
    title: str
    slug: str
    content: str = ""
    tags: tuple[str, ...] = ()
    category: str = "general"
    pinned: bool = False
    archived: bool = False
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass(frozen=True)
class NotesAction:
    """Parsed notes command."""

    action: NotesActionType
    title: str = ""
    content: str = ""
    query: str = ""
    new_title: str = ""
    tags: tuple[str, ...] = ()
    category: str = ""
    args: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class NotesResult:
    """User-facing notes result."""

    status: NotesActionStatus
    message: str
    action: NotesAction | None = None
    notes: tuple[Note, ...] = ()
    requires_confirmation: bool = False
    error: str | None = None

    @property
    def should_fallback(self) -> bool:
        return self.status == "no_match"


__all__ = ["Note", "NotesAction", "NotesActionStatus", "NotesActionType", "NotesResult"]
