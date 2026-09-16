"""Map a chat phrase to a catalogued browser-awareness action.

``BrowserAwarenessParser`` still reads the phrase, so the same wording is caught
as before. What moved is the half after it: the action is rated and recorded by
the layer like every other, instead of chat calling the package directly.

Every one of these is a read of the page the user is already looking at, so
none of them confirms. What matters for them is not approval but redaction, and
that happens at ``browser_control``'s ingress boundary before any text leaves
the browser -- the same boundary the action layer, ``pc_control`` and
``browser_intelligence`` pass through, which is the point of it being one
boundary.
"""

from __future__ import annotations

from typing import Any

from grandpa.action_layer.catalogue import get
from grandpa.action_layer.model import ActionRequest, Origin
from grandpa.browser_awareness.models import BrowserAwarenessAction

__all__ = ["ACTION_FOR", "build_awareness_request"]

ACTION_FOR: dict[str, str] = {
    "current": "browser_context",
    "title": "browser_title",
    "url": "browser_url",
    "read": "browser_read",
    "summarize": "browser_summary",
    "find_text": "browser_find_text",
    "links": "browser_links",
    "selected_text": "browser_selected_text",
    "tabs": "browser_tabs",
}
"""Every action the parser can produce, and the catalogue entry for it."""


def build_awareness_request(
    text: str,
) -> tuple[ActionRequest | None, BrowserAwarenessAction | None]:
    """The request for ``text``, or ``(None, None)`` when this is not for us."""
    from grandpa.browser_awareness.parser import BrowserAwarenessParser

    parsed = BrowserAwarenessParser().parse(text)
    if parsed is None:
        return None, None

    name = ACTION_FOR.get(parsed.action)
    if name is None:
        # The parser grew an action the catalogue has not been told about.
        # Falling through leaves the phrase to the handlers below.
        return None, None

    parameters: dict[str, Any] = {}
    if parsed.action == "find_text" and parsed.query:
        parameters["query"] = parsed.query

    spec = get(name)
    return (
        ActionRequest(
            name,
            parameters,
            origin=Origin.USER_CHAT,
            risk=spec.risk,
            requires_confirmation=spec.requires_confirmation,
        ),
        parsed,
    )
