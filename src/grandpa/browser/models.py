"""Models for safe browser automation commands."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

BrowserActionType = Literal[
    "open_url",
    "search",
    "new_tab",
    "close_tab",
    "refresh",
    "back",
    "forward",
    "reopen_closed_tab",
    "focus_address_bar",
    "open_page",
]

BrowserActionStatus = Literal[
    "handled",
    "blocked",
    "unsupported",
    "no_match",
    "error",
]


@dataclass(frozen=True)
class BrowserAction:
    """Parsed browser automation action."""

    action: BrowserActionType
    target: str = ""
    provider: str = ""
    query: str = ""
    url: str = ""
    args: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BrowserOperationResult:
    """User-facing result from browser automation."""

    status: BrowserActionStatus
    message: str
    action: BrowserAction | None = None
    url: str = ""
    error: str | None = None

    @property
    def should_fallback(self) -> bool:
        return self.status == "no_match"


__all__ = [
    "BrowserAction",
    "BrowserActionStatus",
    "BrowserActionType",
    "BrowserOperationResult",
]
