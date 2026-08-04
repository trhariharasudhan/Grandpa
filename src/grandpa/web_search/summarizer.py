"""Deterministic source-grounded summaries for search results."""

from __future__ import annotations

from grandpa.web_search.models import WebSearchQuery, WebSearchResult


class WebSearchSummarizer:
    """Create concise summaries from provider snippets without inventing facts."""

    def summarize(
        self, query: WebSearchQuery, results: tuple[WebSearchResult, ...]
    ) -> str:
        if not results:
            return "No reliable web search results were found."
        snippets = [result.snippet for result in results[:3] if result.snippet]
        if not snippets:
            return "I found sources, but they did not include enough snippet text to summarize safely."
        mode = (
            "recent " if query.recency_days is not None or query.mode == "news" else ""
        )
        return f"Summary from {mode}search results: " + " ".join(snippets)


__all__ = ["WebSearchSummarizer"]
