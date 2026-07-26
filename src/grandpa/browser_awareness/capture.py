"""Capture safe visible browser page context."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from grandpa.browser_awareness.models import BrowserPageSnapshot
from grandpa.browser_awareness.safety import sanitize_link_text, sanitize_visible_text

CaptureProvider = Callable[[], BrowserPageSnapshot]


class BrowserPageCapture:
    """Read visible browser context from existing local-only adapters."""

    def capture(self) -> BrowserPageSnapshot:
        return _snapshot_from_visible_context()


def _snapshot_from_visible_context() -> BrowserPageSnapshot:
    from grandpa.browser_control import BrowserContextStore, get_visible_browser_context

    context = get_visible_browser_context()
    if not context.supported:
        return BrowserPageSnapshot(supported=False, message=context.message)
    recent = BrowserContextStore().recent(limit=8)
    tabs = tuple(str(item.get("title") or item.get("url") or item.get("action") or "") for item in recent)
    return BrowserPageSnapshot(
        supported=True,
        title=str(context.title or ""),
        url=str(context.url or ""),
        visible_text=sanitize_visible_text(context.visible_text),
        selected_text=_selected_text_from_mapping(context.session or {}),
        links=_sanitize_links(context.links),
        tabs=tuple(item for item in tabs if item),
        source="visible_context",
        message=context.message,
    )


def _selected_text_from_mapping(data: dict[str, Any]) -> str:
    for key in ("selected_text", "selection", "selectedText"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return sanitize_visible_text(value)
    session = data.get("session") if isinstance(data, dict) else None
    if isinstance(session, dict):
        return _selected_text_from_mapping(session)
    return ""


def _sanitize_links(links: tuple[Any, ...]) -> tuple[dict[str, str], ...]:
    sanitized: list[dict[str, str]] = []
    for link in links[:50]:
        if isinstance(link, dict):
            text = sanitize_link_text(str(link.get("text") or link.get("label") or link.get("href") or ""))
            href = str(link.get("href") or link.get("url") or "")
            sanitized.append({"text": text, "href": href})
        elif isinstance(link, str):
            sanitized.append({"text": sanitize_link_text(link), "href": ""})
    return tuple(sanitized)


__all__ = ["BrowserPageCapture", "CaptureProvider"]
