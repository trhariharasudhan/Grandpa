"""Parser for safe web search commands."""

from __future__ import annotations

import re

from grandpa.web_search.models import WebSearchAction, WebSearchQuery


class WebSearchParser:
    """Parse confident web search commands."""

    def parse(self, text: str) -> WebSearchAction | None:
        raw = _clean(text)
        command = raw.casefold()
        if not command:
            return None
        if command in {"search status", "web search status"}:
            return WebSearchAction("status")
        if command in {"show sources", "search sources", "web search sources"}:
            return WebSearchAction("sources")
        if command in {"clear search cache", "clear web search cache", "search clear-cache"}:
            return WebSearchAction("clear_cache")
        return self._parse_search(command, raw)

    def _parse_search(self, command: str, raw: str) -> WebSearchAction | None:
        patterns = (
            (r"search the web for (.+)", "web"),
            (r"search web (.+)", "web"),
            (r"find recent (.+)", "news"),
            (r"what happened in (.+) today", "news"),
            (r"search news for (.+)", "news"),
            (r"search news from the last (\d+) days(?: for)? (.+)", "news_days"),
            (r"find recent articles from the last week(?: about)? (.+)", "week"),
            (r"search official (.+?) docs for (.+)", "official_docs"),
            (r"search official (?:documentation|docs)? ?for (.+)", "official"),
            (r"search only official documentation(?: for)? (.+)", "official"),
            (r"official docs for (.+)", "official"),
            (r"compare (.+)", "web"),
            (r"find jobs in (.+)", "web"),
            (r"summarize the top (\d+) results for (.+)", "top"),
        )
        for pattern, mode in patterns:
            match = re.fullmatch(pattern, command)
            if not match:
                continue
            if mode == "news_days":
                days = int(match.group(1))
                query = raw[match.start(2) : match.end(2)]
                return WebSearchAction("search", WebSearchQuery(query, mode="news", recency_days=days))
            if mode == "week":
                query = raw[match.start(1) : match.end(1)]
                return WebSearchAction("search", WebSearchQuery(query, mode="news", recency_days=7))
            if mode == "top":
                count = int(match.group(1))
                query = raw[match.start(2) : match.end(2)]
                return WebSearchAction("search", WebSearchQuery(query, max_results=min(count, 10)))
            if mode == "official_docs":
                domain_hint = raw[match.start(1) : match.end(1)]
                query = raw[match.start(2) : match.end(2)]
                return WebSearchAction("search", WebSearchQuery(f"official {domain_hint} docs {query}", official_only=True))
            query = raw[match.start(1) : match.end(1)]
            if mode == "official":
                return WebSearchAction("search", WebSearchQuery(query, official_only=True))
            if mode == "news":
                return WebSearchAction("search", WebSearchQuery(query, mode="news", recency_days=1))
            return WebSearchAction("search", WebSearchQuery(query))
        if command.startswith("site:"):
            return WebSearchAction("search", WebSearchQuery(raw, official_only=True))
        return None


def _clean(text: str) -> str:
    value = re.sub(r"[?!,;]+", " ", str(text))
    return re.sub(r"\s+", " ", value).strip()


__all__ = ["WebSearchParser"]
