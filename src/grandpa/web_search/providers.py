"""Provider configuration for Grandpa web search."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class WebSearchProviderConfig:
    provider: str = "brave"
    api_key_env: str = "BRAVE_SEARCH_API_KEY"
    max_results: int = 8
    timeout_seconds: int = 10
    cache_minutes: int = 15

    @property
    def api_key(self) -> str:
        return os.environ.get(self.api_key_env, "").strip()


KEYLESS_PROVIDER = "duckduckgo"
_KEYED_PROVIDERS = (
    ("brave", "BRAVE_SEARCH_API_KEY"),
    ("bing", "BING_SEARCH_API_KEY"),
    ("serper", "SERPER_API_KEY"),
)


def default_provider_config() -> WebSearchProviderConfig:
    env_by_provider = dict(_KEYED_PROVIDERS)
    explicit = os.environ.get("GRANDPA_WEB_SEARCH_PROVIDER", "").strip().lower()
    key_env_override = os.environ.get("GRANDPA_WEB_SEARCH_API_KEY_ENV", "").strip()
    if explicit:
        provider = explicit
    elif key_env_override:
        # A custom key variable implies a keyed provider; keep the old default.
        provider = "brave"
    else:
        # Use a keyed provider whose API key is present; otherwise fall back to
        # keyless DuckDuckGo so search works without any setup.
        provider = next(
            (name for name, env in _KEYED_PROVIDERS if os.environ.get(env, "").strip()),
            KEYLESS_PROVIDER,
        )
    api_key_env = key_env_override or env_by_provider.get(provider, "")
    max_results = _int_env("GRANDPA_WEB_SEARCH_MAX_RESULTS", 8)
    timeout_seconds = _int_env("GRANDPA_WEB_SEARCH_TIMEOUT_SECONDS", 10)
    cache_minutes = _int_env("GRANDPA_WEB_SEARCH_CACHE_MINUTES", 15)
    return WebSearchProviderConfig(
        provider, api_key_env, max_results, timeout_seconds, cache_minutes
    )


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


class WebSearchProviderError(RuntimeError):
    """Base provider error."""


class WebSearchNotConfiguredError(WebSearchProviderError):
    """Raised when no search provider is configured."""


class WebSearchRateLimitError(WebSearchProviderError):
    """Raised when a provider reports rate limiting."""


class WebSearchAuthError(WebSearchProviderError):
    """Raised when a provider rejects credentials."""


class WebSearchTimeoutError(WebSearchProviderError):
    """Raised when a provider times out."""


__all__ = [
    "KEYLESS_PROVIDER",
    "WebSearchAuthError",
    "WebSearchNotConfiguredError",
    "WebSearchProviderConfig",
    "WebSearchProviderError",
    "WebSearchRateLimitError",
    "WebSearchTimeoutError",
    "default_provider_config",
]
