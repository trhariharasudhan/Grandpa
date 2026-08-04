"""Provider client wrappers for safe web search."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from grandpa.web_search.models import WebSearchQuery, WebSearchResult
from grandpa.web_search.providers import (
    WebSearchAuthError,
    WebSearchNotConfiguredError,
    WebSearchProviderConfig,
    WebSearchProviderError,
    WebSearchRateLimitError,
    WebSearchTimeoutError,
    default_provider_config,
)
from grandpa.web_search.safety import WebSearchSafetyPolicy


class WebSearchClient:
    """Small provider abstraction for web search APIs."""

    def __init__(
        self,
        config: WebSearchProviderConfig | None = None,
        safety: WebSearchSafetyPolicy | None = None,
    ) -> None:
        self.config = config or default_provider_config()
        self.safety = safety or WebSearchSafetyPolicy()

    def status(self) -> tuple[str, str]:
        if self.config.provider not in {"brave", "bing", "serper"}:
            return (
                "not_configured",
                f"Unsupported web search provider: {self.config.provider}",
            )
        if not self.config.api_key:
            return (
                "not_configured",
                f"Web search is not configured. Set {self.config.api_key_env}.",
            )
        return "ready", f"Web search provider ready: {self.config.provider}."

    def search(self, query: WebSearchQuery) -> tuple[WebSearchResult, ...]:
        status, message = self.status()
        if status != "ready":
            raise WebSearchNotConfiguredError(message)
        if self.config.provider == "brave":
            return self._search_brave(query)
        if self.config.provider == "bing":
            return self._search_bing(query)
        if self.config.provider == "serper":
            return self._search_serper(query)
        raise WebSearchNotConfiguredError(
            f"Unsupported web search provider: {self.config.provider}"
        )

    def _search_brave(self, query: WebSearchQuery) -> tuple[WebSearchResult, ...]:
        params = {
            "q": query.text,
            "count": str(min(query.max_results, self.config.max_results)),
        }
        if query.recency_days is not None:
            params["freshness"] = f"pd{query.recency_days}"
        url = (
            "https://api.search.brave.com/res/v1/web/search?"
            + urllib.parse.urlencode(params)
        )
        data = self._request_json(
            url,
            {"Accept": "application/json", "X-Subscription-Token": self.config.api_key},
        )
        results = data.get("web", {}).get("results", [])
        return tuple(self._result(item) for item in results)

    def _search_bing(self, query: WebSearchQuery) -> tuple[WebSearchResult, ...]:
        params = {
            "q": query.text,
            "count": str(min(query.max_results, self.config.max_results)),
        }
        url = "https://api.bing.microsoft.com/v7.0/search?" + urllib.parse.urlencode(
            params
        )
        data = self._request_json(
            url, {"Ocp-Apim-Subscription-Key": self.config.api_key}
        )
        return tuple(
            self._result(item) for item in data.get("webPages", {}).get("value", [])
        )

    def _search_serper(self, query: WebSearchQuery) -> tuple[WebSearchResult, ...]:
        payload = json.dumps(
            {"q": query.text, "num": min(query.max_results, self.config.max_results)}
        ).encode("utf-8")
        data = self._request_json(
            "https://google.serper.dev/search",
            {"X-API-KEY": self.config.api_key, "Content-Type": "application/json"},
            payload,
        )
        return tuple(self._result(item) for item in data.get("organic", []))

    def _request_json(
        self, url: str, headers: dict[str, str], data: bytes | None = None
    ) -> dict[str, Any]:
        request = urllib.request.Request(
            url, data=data, headers=headers, method="POST" if data else "GET"
        )
        try:
            with urllib.request.urlopen(
                request, timeout=self.config.timeout_seconds
            ) as response:
                return json.loads(response.read().decode("utf-8", errors="replace"))
        except TimeoutError as exc:
            raise WebSearchTimeoutError("Web search provider timed out.") from exc
        except urllib.error.HTTPError as exc:
            if exc.code in {401, 403}:
                raise WebSearchAuthError(
                    "Web search provider rejected the configured API key."
                ) from exc
            if exc.code == 429:
                raise WebSearchRateLimitError(
                    "Web search provider rate limit reached."
                ) from exc
            raise WebSearchProviderError(
                f"Web search provider returned HTTP {exc.code}."
            ) from exc
        except urllib.error.URLError as exc:
            raise WebSearchProviderError(
                f"Web search provider unreachable: {exc.reason}"
            ) from exc

    def _result(self, item: dict[str, Any]) -> WebSearchResult:
        title = self.safety.sanitize_text(
            str(item.get("title") or item.get("name") or ""), limit=200
        )
        url = str(item.get("url") or item.get("link") or "")
        snippet = self.safety.sanitize_text(
            str(item.get("description") or item.get("snippet") or "")
        )
        published = str(
            item.get("age")
            or item.get("datePublished")
            or item.get("published_at")
            or ""
        )
        if not self.safety.safe_url(url):
            return WebSearchResult(
                title=title, url="", snippet=snippet, published_at=published, score=-100
            )
        return WebSearchResult(
            title=title,
            url=url,
            snippet=snippet,
            source=self.safety.domain(url),
            published_at=published,
        )


__all__ = ["WebSearchClient"]
