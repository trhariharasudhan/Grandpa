"""Parser for read-only browser awareness commands."""

from __future__ import annotations

import re

from grandpa.browser_awareness.models import BrowserAwarenessAction


class BrowserAwarenessParser:
    """Parse confident browser-page awareness commands."""

    def parse(self, text: str) -> BrowserAwarenessAction | None:
        command = _normalize(text)
        if not command:
            return None
        if command in {
            "what page am i on",
            "current page",
            "show current page",
            "where am i in the browser",
        }:
            return BrowserAwarenessAction("current")
        if command in {
            "what is the title of this page",
            "page title",
            "show page title",
            "browser title",
        }:
            return BrowserAwarenessAction("title")
        if command in {
            "show the current url",
            "current url",
            "show url",
            "what is the url",
            "browser url",
        }:
            return BrowserAwarenessAction("url")
        if command in {
            "read this page",
            "read the page",
            "read page",
            "summarize visible content",
        }:
            return BrowserAwarenessAction("read")
        if command in {
            "summarize this page",
            "summarize the page",
            "page summary",
            "summarize visible page",
        }:
            return BrowserAwarenessAction("summarize")
        if command in {
            "list the links on this page",
            "list links on this page",
            "show page links",
            "browser links",
        }:
            return BrowserAwarenessAction("links")
        if command in {"read the selected text", "read selected text", "selected text"}:
            return BrowserAwarenessAction("selected_text")
        if command in {
            "what tabs are open",
            "what tabs are open in the browser",
            "list browser tabs",
            "browser tabs",
        }:
            return BrowserAwarenessAction("tabs")
        match = re.fullmatch(r"find text ['\"]?(.+?)['\"]? on this page", command)
        if match:
            return BrowserAwarenessAction("find_text", match.group(1).strip())
        match = re.fullmatch(r"find ['\"]?(.+?)['\"]? on this page", command)
        if match:
            return BrowserAwarenessAction("find_text", match.group(1).strip())
        return None


def _normalize(text: str) -> str:
    value = str(text).casefold().strip()
    value = re.sub(r"[?!,;:]+", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


__all__ = ["BrowserAwarenessParser"]
