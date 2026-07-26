"""Local TTL cache for web search results."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from grandpa.core.config import DEFAULT_CONFIG_DIR
from grandpa.web_search.models import WebSearchQuery, WebSearchResult

DEFAULT_WEB_SEARCH_CACHE_DIR = DEFAULT_CONFIG_DIR / "cache" / "web_search"


class WebSearchCache:
    """File-backed cache keyed by normalized provider/query/filter data."""

    def __init__(self, root: Path | str = DEFAULT_WEB_SEARCH_CACHE_DIR, ttl_minutes: int = 15) -> None:
        self.root = Path(root)
        self.ttl_seconds = ttl_minutes * 60

    def get(self, provider: str, query: WebSearchQuery) -> tuple[WebSearchResult, ...] | None:
        path = self._path(provider, query)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if time.time() - float(payload.get("created_at", 0)) > self.ttl_seconds:
                return None
            return tuple(WebSearchResult(**item) for item in payload.get("results", []))
        except Exception:
            return None

    def set(self, provider: str, query: WebSearchQuery, results: tuple[WebSearchResult, ...]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self._path(provider, query)
        payload = {
            "created_at": time.time(),
            "results": [result.__dict__ for result in results],
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def clear(self) -> int:
        if not self.root.exists():
            return 0
        count = 0
        for path in self.root.glob("*.json"):
            path.unlink(missing_ok=True)
            count += 1
        return count

    def _path(self, provider: str, query: WebSearchQuery) -> Path:
        key = json.dumps(
            {
                "provider": provider,
                "text": query.text.casefold(),
                "mode": query.mode,
                "max_results": query.max_results,
                "recency_days": query.recency_days,
                "official_only": query.official_only,
                "region": query.region,
                "language": query.language,
            },
            sort_keys=True,
        )
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self.root / f"{digest}.json"


__all__ = ["DEFAULT_WEB_SEARCH_CACHE_DIR", "WebSearchCache"]
