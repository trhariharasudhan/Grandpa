"""User-facing formatting for web search results."""

from __future__ import annotations

from grandpa.web_search.models import WebSearchResult


def format_search_response(summary: str, results: tuple[WebSearchResult, ...]) -> str:
    if not results:
        return summary
    lines = [f"Found {len(results)} relevant source{'s' if len(results) != 1 else ''}.", "", "Summary:", summary, "", "Sources:"]
    for index, result in enumerate(results, start=1):
        date = f" — {result.published_at}" if result.published_at else ""
        lines.append(f"{index}. {result.title} — {result.source or result.url}{date}")
        lines.append(f"   {result.url}")
    return "\n".join(lines)


def format_sources(results: tuple[WebSearchResult, ...]) -> str:
    if not results:
        return "No web search sources are available yet."
    lines = ["Sources:"]
    for index, result in enumerate(results, start=1):
        lines.append(f"{index}. {result.title} — {result.url}")
    return "\n".join(lines)


__all__ = ["format_search_response", "format_sources"]
