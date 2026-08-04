"""Models for Grandpa's safe Downloads manager."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

DownloadActionType = Literal[
    "recent",
    "today",
    "latest",
    "search",
    "large",
    "incomplete",
    "organize",
    "move",
    "archive",
    "delete",
    "duplicates",
    "info",
    "open",
    "open_folder",
]

DownloadActionStatus = Literal[
    "handled", "needs_confirmation", "blocked", "unsupported", "no_match", "error"
]


@dataclass(frozen=True)
class DownloadItem:
    """One file in a Downloads directory."""

    path: Path
    name: str
    size_bytes: int
    modified_at: str
    kind: str
    safe_to_open: bool
    incomplete: bool = False
    duplicate_group: str = ""


@dataclass(frozen=True)
class DownloadAction:
    """Parsed Downloads command."""

    action: DownloadActionType
    selector: str = ""
    destination: str = ""
    query: str = ""
    days: int = 30
    args: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DownloadResult:
    """User-facing Downloads result."""

    status: DownloadActionStatus
    message: str
    action: DownloadAction | None = None
    items: tuple[DownloadItem, ...] = ()
    requires_confirmation: bool = False
    error: str | None = None

    @property
    def should_fallback(self) -> bool:
        return self.status == "no_match"


__all__ = [
    "DownloadAction",
    "DownloadActionStatus",
    "DownloadActionType",
    "DownloadItem",
    "DownloadResult",
]
