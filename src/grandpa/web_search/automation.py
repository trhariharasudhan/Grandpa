"""Safe web search automation facade."""

from __future__ import annotations

from grandpa.web_search.cache import WebSearchCache
from grandpa.web_search.client import WebSearchClient
from grandpa.web_search.formatter import format_search_response, format_sources
from grandpa.web_search.models import (
    WebSearchAction,
    WebSearchResponse,
    WebSearchResult,
)
from grandpa.web_search.parser import WebSearchParser
from grandpa.web_search.providers import (
    WebSearchAuthError,
    WebSearchNotConfiguredError,
    WebSearchProviderError,
    WebSearchRateLimitError,
    WebSearchTimeoutError,
)
from grandpa.web_search.ranking import WebSearchRanker
from grandpa.web_search.safety import WebSearchSafetyPolicy
from grandpa.web_search.summarizer import WebSearchSummarizer


class WebSearchAutomation:
    """Parse, run, rank, cache, and format web search commands."""

    def __init__(
        self,
        parser: WebSearchParser | None = None,
        client: object | None = None,
        cache: WebSearchCache | None = None,
        ranker: WebSearchRanker | None = None,
        summarizer: WebSearchSummarizer | None = None,
        safety: WebSearchSafetyPolicy | None = None,
    ) -> None:
        self.parser = parser or WebSearchParser()
        self.client = client or WebSearchClient()
        self.cache = cache or WebSearchCache(ttl_minutes=getattr(getattr(self.client, "config", None), "cache_minutes", 15))
        self.safety = safety or WebSearchSafetyPolicy()
        self.ranker = ranker or WebSearchRanker(self.safety)
        self.summarizer = summarizer or WebSearchSummarizer()
        self._last_results: tuple[WebSearchResult, ...] = ()

    def handle(self, text: str) -> WebSearchResponse:
        action = self.parser.parse(text)
        if action is None:
            return WebSearchResponse("no_match", "")
        return self.execute(action)

    def execute(self, action: WebSearchAction) -> WebSearchResponse:
        try:
            if action.action == "status":
                status, message = self.client.status()  # type: ignore[attr-defined]
                return WebSearchResponse("handled" if status == "ready" else "not_configured", message, action)
            if action.action == "clear_cache":
                count = self.cache.clear()
                return WebSearchResponse("handled", f"Cleared {count} cached web search entr{'y' if count == 1 else 'ies'}.", action)
            if action.action == "sources":
                return WebSearchResponse("handled", format_sources(self._last_results), action, self._last_results)
            if action.action != "search" or action.query is None:
                return WebSearchResponse("unsupported", "That web search action is not supported yet.", action)
            return self._search(action)
        except WebSearchNotConfiguredError as exc:
            return WebSearchResponse("not_configured", str(exc), action, error=str(exc))
        except WebSearchAuthError as exc:
            return WebSearchResponse("error", str(exc), action, error=str(exc))
        except WebSearchRateLimitError as exc:
            return WebSearchResponse("error", str(exc), action, error=str(exc))
        except WebSearchTimeoutError as exc:
            return WebSearchResponse("error", str(exc), action, error=str(exc))
        except WebSearchProviderError as exc:
            return WebSearchResponse("error", str(exc), action, error=str(exc))
        except Exception as exc:
            return WebSearchResponse("error", f"Web search failed: {exc}", action, error=str(exc))

    def _search(self, action: WebSearchAction) -> WebSearchResponse:
        query = action.query
        safe_query = query.__class__(
            text=self.safety.sanitize_query(query.text),
            mode=query.mode,
            max_results=query.max_results,
            recency_days=query.recency_days,
            official_only=query.official_only,
            region=query.region,
            language=query.language,
        )
        provider = getattr(getattr(self.client, "config", None), "provider", "unknown")
        cached = self.cache.get(provider, safe_query)
        if cached is None:
            raw_results = tuple(self.client.search(safe_query))  # type: ignore[attr-defined]
            ranked = self.ranker.rank(raw_results, safe_query)
            self.cache.set(provider, safe_query, ranked)
        else:
            ranked = cached
        self._last_results = ranked
        summary = self.summarizer.summarize(safe_query, ranked)
        return WebSearchResponse("handled", format_search_response(summary, ranked), action, ranked)


def handle_web_search_command(
    text: str,
    *,
    client: object | None = None,
    cache: WebSearchCache | None = None,
) -> WebSearchResponse:
    return WebSearchAutomation(client=client, cache=cache).handle(text)


__all__ = ["WebSearchAutomation", "handle_web_search_command"]
