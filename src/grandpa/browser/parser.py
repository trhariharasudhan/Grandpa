"""Natural-language parser for safe browser automation."""

from __future__ import annotations

import re

from grandpa.browser.models import BrowserAction
from grandpa.browser.urls import SEARCH_PROVIDERS, site_url


class BrowserParser:
    """Parse confident browser commands without executing anything."""

    def parse(self, text: str) -> BrowserAction | None:
        raw = _clean_text(text)
        command = _normalize(text)
        if not command:
            return None
        return (
            self._parse_navigation(command)
            or self._parse_browser_pages(command)
            or self._parse_search(command, raw)
            or self._parse_open(command, raw)
        )

    def _parse_open(self, command: str, raw: str) -> BrowserAction | None:
        target = _strip_prefix(command, ("open ", "launch ", "go to "))
        if target is None:
            return None
        raw_target = raw[len(command) - len(target) :].strip()
        if re.match(r"^[a-z][a-z0-9+.-]*:", target) or re.match(
            r"^[a-z0-9.-]+\.[a-z]{2,}(?:/.*)?$", target
        ):
            return BrowserAction("open_url", target=raw_target, url=raw_target)
        site = site_url(target)
        if site is None:
            return None
        label, url = site
        return BrowserAction("open_url", target=label, url=url)

    def _parse_search(self, command: str, raw: str) -> BrowserAction | None:
        for provider in SEARCH_PROVIDERS:
            prefix = f"search {provider} for "
            if command.startswith(prefix):
                query = raw[len(prefix) :].strip()
                return (
                    BrowserAction("search", provider=provider, query=query)
                    if query
                    else None
                )
            prefix = f"{provider} "
            if command.startswith(prefix):
                query = raw[len(prefix) :].strip()
                return (
                    BrowserAction("search", provider=provider, query=query)
                    if query
                    else None
                )
        return None

    def _parse_navigation(self, command: str) -> BrowserAction | None:
        mapping = {
            "open a new tab": "new_tab",
            "open new tab": "new_tab",
            "new tab": "new_tab",
            "close current tab": "close_tab",
            "close the current tab": "close_tab",
            "close tab": "close_tab",
            "refresh page": "refresh",
            "refresh the page": "refresh",
            "reload page": "refresh",
            "reload the page": "refresh",
            "go back": "back",
            "back": "back",
            "go forward": "forward",
            "forward": "forward",
            "reopen closed tab": "reopen_closed_tab",
            "reopen the closed tab": "reopen_closed_tab",
            "focus address bar": "focus_address_bar",
        }
        action = mapping.get(command)
        return BrowserAction(action) if action is not None else None

    def _parse_browser_pages(self, command: str) -> BrowserAction | None:
        mapping = {
            "open browser history": "history",
            "browser history": "history",
            "open browser downloads": "downloads",
            "browser downloads": "downloads",
            "open browser bookmarks": "bookmarks",
            "browser bookmarks": "bookmarks",
            "open browser settings": "settings",
            "browser settings": "settings",
        }
        page = mapping.get(command)
        return BrowserAction("open_page", target=page) if page is not None else None


def _normalize(text: str) -> str:
    return _clean_text(text).casefold()


def _clean_text(text: str) -> str:
    value = re.sub(r"[?!,;]+", " ", str(text))
    return re.sub(r"\s+", " ", value).strip()


def _strip_prefix(value: str, prefixes: tuple[str, ...]) -> str | None:
    for prefix in prefixes:
        if value.startswith(prefix):
            return value[len(prefix) :].strip()
    return None


__all__ = ["BrowserParser"]
