"""Safety helpers for browser automation."""

from __future__ import annotations

from grandpa.browser.urls import normalize_url


def validate_browser_url(value: str) -> tuple[bool, str, str]:
    """Return ``(ok, url, message)`` for a user-supplied browser URL."""

    try:
        return True, normalize_url(value), ""
    except ValueError as exc:
        return False, "", str(exc)


__all__ = ["validate_browser_url"]
