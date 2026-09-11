"""Keyless DuckDuckGo search through the ``ddgs`` package.

The single place Grandpa calls ``ddgs``. Used by ``WebSearchClient`` (the
``grandpa search`` and chat path) and by the ``web_search`` agent tool.
"""

from __future__ import annotations

from typing import Any


def duckduckgo_text_search(
    query: str, *, max_results: int, timelimit: str | None = None
) -> list[dict[str, str]]:
    """Return DuckDuckGo results as ``{"title", "url", "snippet"}`` dicts.

    ``timelimit`` is ddgs' recency filter (``"d"``, ``"w"``, ``"m"`` or
    ``"y"``). Raises ``ImportError`` if ``ddgs`` is missing and lets ddgs'
    own exceptions propagate so callers can map them.
    """
    from ddgs import DDGS

    kwargs: dict[str, Any] = {"max_results": max_results}
    if timelimit:
        kwargs["timelimit"] = timelimit
    raw = DDGS().text(query, **kwargs) or []
    return [
        {
            "title": str(item.get("title") or ""),
            "url": str(item.get("href") or ""),
            "snippet": str(item.get("body") or ""),
        }
        for item in raw
    ]


__all__ = ["duckduckgo_text_search"]
