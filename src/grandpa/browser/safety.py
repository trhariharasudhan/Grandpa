"""Safety helpers for browser automation.

Opening a URL, a site, a search or an internal browser page navigates the
user's real browser, and in chat the address comes from the model. Those
actions are confirmed unless their domain is in
``tools.browser.trusted_domains``.
"""

from __future__ import annotations

from urllib.parse import urlparse

from grandpa.browser.models import BrowserAction
from grandpa.browser.urls import normalize_url

# Actions that navigate the browser. The hotkey actions (new tab, back,
# refresh, ...) act on whatever page the user already has open.
CONFIRMED_ACTIONS = frozenset({"open_url", "search", "open_page"})


def validate_browser_url(value: str) -> tuple[bool, str, str]:
    """Return ``(ok, url, message)`` for a user-supplied browser URL."""

    try:
        return True, normalize_url(value), ""
    except ValueError as exc:
        return False, "", str(exc)


def parse_trusted_domains(value: str | None) -> tuple[str, ...]:
    """Split a ``tools.browser.trusted_domains`` setting into domains."""
    if not value:
        return ()
    return tuple(
        item.strip().lower().removeprefix("www.")
        for item in str(value).replace(";", ",").split(",")
        if item.strip()
    )


def configured_trusted_domains() -> tuple[str, ...]:
    """Trusted domains from config, or none when config cannot be read."""
    try:
        from grandpa.core.config import load_config

        return parse_trusted_domains(load_config().tools.browser.trusted_domains)
    except Exception:
        return ()


def is_trusted_url(url: str, trusted_domains: tuple[str, ...]) -> bool:
    """True when ``url``'s host is a trusted domain or a subdomain of one."""
    if not trusted_domains:
        return False
    host = urlparse(url).hostname or ""
    host = host.lower().removeprefix("www.")
    if not host:
        return False
    return any(
        host == domain or host.endswith(f".{domain}") for domain in trusted_domains
    )


def needs_confirmation(
    action: BrowserAction, url: str, trusted_domains: tuple[str, ...]
) -> bool:
    if action.action not in CONFIRMED_ACTIONS:
        return False
    return not is_trusted_url(url, trusted_domains)


def confirmation_prompt(action: BrowserAction, url: str, label: str) -> str:
    """The exact address or query the user is being asked to approve."""
    if action.action == "search":
        return f"search {label} for {action.query!r} ({url})"
    if action.action == "open_page":
        return f"open the browser {action.target} page ({url})"
    return f"open {url} in your browser"


__all__ = [
    "CONFIRMED_ACTIONS",
    "configured_trusted_domains",
    "confirmation_prompt",
    "is_trusted_url",
    "needs_confirmation",
    "parse_trusted_domains",
    "validate_browser_url",
]
