"""Models for read-only browser awareness."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

BrowserAwarenessActionType = Literal[
    "current",
    "title",
    "url",
    "read",
    "summarize",
    "find_text",
    "links",
    "selected_text",
    "tabs",
]

BrowserAwarenessStatus = Literal["handled", "unsupported", "no_match", "error"]


@dataclass(frozen=True)
class BrowserPageSnapshot:
    """Safe visible browser page snapshot."""

    supported: bool
    title: str = ""
    url: str = ""
    visible_text: str = ""
    selected_text: str = ""
    links: tuple[dict[str, str], ...] = ()
    tabs: tuple[str, ...] = ()
    source: str = "unknown"
    message: str = ""


@dataclass(frozen=True)
class BrowserAwarenessAction:
    """Parsed read-only browser awareness action."""

    action: BrowserAwarenessActionType
    query: str = ""


@dataclass(frozen=True)
class BrowserAwarenessResult:
    """User-facing browser awareness result."""

    status: BrowserAwarenessStatus
    message: str
    action: BrowserAwarenessAction | None = None
    snapshot: BrowserPageSnapshot | None = None

    @property
    def should_fallback(self) -> bool:
        return self.status == "no_match"


__all__ = [
    "BrowserAwarenessAction",
    "BrowserAwarenessActionType",
    "BrowserAwarenessResult",
    "BrowserAwarenessStatus",
    "BrowserPageSnapshot",
]
