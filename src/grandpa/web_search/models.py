"""Models for Grandpa's safe web search layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

WebSearchActionType = Literal["search", "sources", "clear_cache", "status"]
WebSearchStatus = Literal[
    "handled", "not_configured", "blocked", "unsupported", "no_match", "error"
]


@dataclass(frozen=True)
class WebSearchQuery:
    """Normalized search query."""

    text: str
    mode: str = "web"
    max_results: int = 5
    recency_days: int | None = None
    official_only: bool = False
    region: str = ""
    language: str = ""


@dataclass(frozen=True)
class WebSearchAction:
    """Parsed web search command."""

    action: WebSearchActionType
    query: WebSearchQuery | None = None
    args: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WebSearchResult:
    """One safe search result."""

    title: str
    url: str
    snippet: str = ""
    source: str = ""
    published_at: str = ""
    score: float = 0.0


@dataclass(frozen=True)
class WebSearchResponse:
    """User-facing web search response."""

    status: WebSearchStatus
    message: str
    action: WebSearchAction | None = None
    results: tuple[WebSearchResult, ...] = ()
    error: str | None = None

    @property
    def should_fallback(self) -> bool:
        return self.status == "no_match"


__all__ = [
    "WebSearchAction",
    "WebSearchActionType",
    "WebSearchQuery",
    "WebSearchResponse",
    "WebSearchResult",
    "WebSearchStatus",
]
