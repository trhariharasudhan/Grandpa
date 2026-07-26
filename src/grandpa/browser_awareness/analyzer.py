"""Analyze safe visible browser page snapshots."""

from __future__ import annotations

import re

from grandpa.browser_awareness.models import (
    BrowserAwarenessAction,
    BrowserAwarenessResult,
    BrowserPageSnapshot,
)


class BrowserPageAnalyzer:
    """Create user-facing read-only responses from page snapshots."""

    def analyze(self, action: BrowserAwarenessAction, snapshot: BrowserPageSnapshot) -> BrowserAwarenessResult:
        if not snapshot.supported:
            return BrowserAwarenessResult("unsupported", snapshot.message or _unsupported_message(), action, snapshot)
        handler = getattr(self, f"_handle_{action.action}", None)
        if handler is None:
            return BrowserAwarenessResult("unsupported", "That browser awareness action is not supported yet.", action, snapshot)
        return handler(action, snapshot)

    def _handle_current(self, action: BrowserAwarenessAction, snapshot: BrowserPageSnapshot) -> BrowserAwarenessResult:
        lines = ["Current page:"]
        lines.append(f"Title: {snapshot.title or 'Unknown'}")
        lines.append(f"URL: {snapshot.url or 'Unknown'}")
        return BrowserAwarenessResult("handled", "\n".join(lines), action, snapshot)

    def _handle_title(self, action: BrowserAwarenessAction, snapshot: BrowserPageSnapshot) -> BrowserAwarenessResult:
        return BrowserAwarenessResult("handled", f"Title: {snapshot.title or 'Unknown'}", action, snapshot)

    def _handle_url(self, action: BrowserAwarenessAction, snapshot: BrowserPageSnapshot) -> BrowserAwarenessResult:
        return BrowserAwarenessResult("handled", f"URL: {snapshot.url or 'Unknown'}", action, snapshot)

    def _handle_read(self, action: BrowserAwarenessAction, snapshot: BrowserPageSnapshot) -> BrowserAwarenessResult:
        if not snapshot.visible_text:
            return BrowserAwarenessResult("unsupported", "Readable visible page text is not available yet.", action, snapshot)
        return BrowserAwarenessResult("handled", f"Visible content:\n{snapshot.visible_text}", action, snapshot)

    def _handle_summarize(self, action: BrowserAwarenessAction, snapshot: BrowserPageSnapshot) -> BrowserAwarenessResult:
        if not snapshot.visible_text:
            return BrowserAwarenessResult("unsupported", "Readable visible page text is not available yet.", action, snapshot)
        summary = _summarize(snapshot.visible_text)
        return BrowserAwarenessResult("handled", f"Summary:\n{summary}", action, snapshot)

    def _handle_find_text(self, action: BrowserAwarenessAction, snapshot: BrowserPageSnapshot) -> BrowserAwarenessResult:
        if not snapshot.visible_text:
            return BrowserAwarenessResult("unsupported", "Readable visible page text is not available yet.", action, snapshot)
        query = action.query.strip()
        if not query:
            return BrowserAwarenessResult("unsupported", "Tell me what text to find on this page.", action, snapshot)
        count = len(re.findall(re.escape(query), snapshot.visible_text, flags=re.IGNORECASE))
        return BrowserAwarenessResult("handled", f'Found "{query}" {count} time{"s" if count != 1 else ""} in visible content.', action, snapshot)

    def _handle_links(self, action: BrowserAwarenessAction, snapshot: BrowserPageSnapshot) -> BrowserAwarenessResult:
        if not snapshot.links:
            return BrowserAwarenessResult("unsupported", "I do not see any visible links in the latest browser snapshot.", action, snapshot)
        lines = ["Visible links:"]
        for index, link in enumerate(snapshot.links[:12], start=1):
            text = link.get("text") or link.get("href") or "Untitled link"
            href = link.get("href") or ""
            lines.append(f"{index}. {text}" + (f" ({href})" if href else ""))
        return BrowserAwarenessResult("handled", "\n".join(lines), action, snapshot)

    def _handle_selected_text(self, action: BrowserAwarenessAction, snapshot: BrowserPageSnapshot) -> BrowserAwarenessResult:
        if not snapshot.selected_text:
            return BrowserAwarenessResult("unsupported", "No selected browser text is available in the latest snapshot.", action, snapshot)
        return BrowserAwarenessResult("handled", f"Selected text:\n{snapshot.selected_text}", action, snapshot)

    def _handle_tabs(self, action: BrowserAwarenessAction, snapshot: BrowserPageSnapshot) -> BrowserAwarenessResult:
        if not snapshot.tabs:
            return BrowserAwarenessResult("unsupported", "Browser tab titles are not safely available yet.", action, snapshot)
        lines = ["Visible browser tabs:"]
        lines.extend(f"{index}. {title}" for index, title in enumerate(snapshot.tabs[:12], start=1))
        return BrowserAwarenessResult("handled", "\n".join(lines), action, snapshot)


def _summarize(text: str) -> str:
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    useful = [sentence.strip() for sentence in sentences if sentence.strip()]
    return " ".join(useful[:3]) if useful else text[:500]


def _unsupported_message() -> str:
    return "Browser awareness is unavailable. Connect the Grandpa browser extension or open a visible supported browser page."


__all__ = ["BrowserPageAnalyzer"]
