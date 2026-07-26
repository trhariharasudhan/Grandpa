"""Ranking and duplicate removal for web search results."""

from __future__ import annotations

from urllib.parse import urlparse

from grandpa.web_search.models import WebSearchQuery, WebSearchResult
from grandpa.web_search.safety import WebSearchSafetyPolicy

OFFICIAL_MARKERS = (".gov", ".edu", "docs.", "developer.", "github.com", "python.org", "fastapi.tiangolo.com")
SPAM_MARKERS = ("content-farm", "coupon", "cracked", "warez", "free-download")


class WebSearchRanker:
    """Rank results using source quality, overlap, recency intent, and dedupe."""

    def __init__(self, safety: WebSearchSafetyPolicy | None = None) -> None:
        self.safety = safety or WebSearchSafetyPolicy()

    def rank(self, results: tuple[WebSearchResult, ...], query: WebSearchQuery) -> tuple[WebSearchResult, ...]:
        seen: set[str] = set()
        ranked = []
        terms = {term for term in query.text.casefold().split() if len(term) > 2}
        for index, result in enumerate(results):
            if not result.url or not self.safety.safe_url(result.url):
                continue
            key = _canonical_url(result.url)
            if key in seen:
                continue
            seen.add(key)
            score = 100 - index
            domain = self.safety.domain(result.url)
            haystack = f"{result.title} {result.snippet} {domain}".casefold()
            score += sum(4 for term in terms if term in haystack)
            if query.official_only or any(marker in domain for marker in OFFICIAL_MARKERS):
                score += 20
            if query.recency_days is not None and result.published_at:
                score += 8
            if any(marker in domain for marker in SPAM_MARKERS) or self.safety.is_low_quality(result.url):
                score -= 40
            ranked.append(_with_score(result, float(score)))
        return tuple(sorted(ranked, key=lambda item: item.score, reverse=True)[: query.max_results])


def _canonical_url(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.netloc.lower().removeprefix('www.')}{parsed.path.rstrip('/')}"


def _with_score(result: WebSearchResult, score: float) -> WebSearchResult:
    return WebSearchResult(
        title=result.title,
        url=result.url,
        snippet=result.snippet,
        source=result.source,
        published_at=result.published_at,
        score=score,
    )


__all__ = ["WebSearchRanker"]
