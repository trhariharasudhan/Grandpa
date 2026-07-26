"""URL normalization and search URL helpers for browser automation."""

from __future__ import annotations

from urllib.parse import quote_plus, urlparse

SITE_ALIASES: dict[str, tuple[str, str]] = {
    "youtube": ("YouTube", "https://www.youtube.com"),
    "github": ("GitHub", "https://github.com"),
    "gmail": ("Gmail", "https://mail.google.com"),
    "google": ("Google", "https://www.google.com"),
    "reddit": ("Reddit", "https://www.reddit.com"),
    "stack overflow": ("Stack Overflow", "https://stackoverflow.com"),
    "stackoverflow": ("Stack Overflow", "https://stackoverflow.com"),
    "localhost": ("localhost", "http://localhost"),
}

SEARCH_PROVIDERS: dict[str, tuple[str, str]] = {
    "google": ("Google", "https://www.google.com/search?q={query}"),
    "youtube": ("YouTube", "https://www.youtube.com/results?search_query={query}"),
    "github": ("GitHub", "https://github.com/search?q={query}"),
    "stack overflow": ("Stack Overflow", "https://stackoverflow.com/search?q={query}"),
    "stackoverflow": ("Stack Overflow", "https://stackoverflow.com/search?q={query}"),
}

BLOCKED_SCHEMES = {"javascript", "data", "file", "powershell", "cmd"}
ALLOWED_SCHEMES = {"http", "https"}


def site_url(name: str) -> tuple[str, str] | None:
    return SITE_ALIASES.get(_normalize_alias(name))


def search_url(provider: str, query: str) -> tuple[str, str] | None:
    item = SEARCH_PROVIDERS.get(_normalize_alias(provider))
    if item is None:
        return None
    label, template = item
    return label, template.format(query=quote_plus(query.strip()))


def normalize_url(value: str) -> str:
    """Normalize a user URL and allow only http/https."""

    raw = value.strip()
    if not raw:
        raise ValueError("No URL was provided.")
    parsed_initial = urlparse(raw)
    if parsed_initial.scheme and parsed_initial.scheme.casefold() in BLOCKED_SCHEMES:
        raise ValueError(f"Blocked unsafe URL scheme: {parsed_initial.scheme}.")
    if not parsed_initial.scheme:
        raw = f"https://{raw}"
    parsed = urlparse(raw)
    scheme = parsed.scheme.casefold()
    if scheme not in ALLOWED_SCHEMES:
        raise ValueError(f"Unsupported URL scheme: {parsed.scheme}.")
    if not parsed.netloc:
        raise ValueError("That does not look like a valid web address.")
    return raw


def _normalize_alias(value: str) -> str:
    return " ".join(value.casefold().replace("-", " ").split())


__all__ = [
    "ALLOWED_SCHEMES",
    "BLOCKED_SCHEMES",
    "SEARCH_PROVIDERS",
    "SITE_ALIASES",
    "normalize_url",
    "search_url",
    "site_url",
]
