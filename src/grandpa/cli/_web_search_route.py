"""Chat's web-search phrases, routed into the action layer.

The sixth migration, and the easiest: WebSearchAutomation.execute already took
a parsed action, so there was no seam to extract first.
"""

from __future__ import annotations

from typing import Any

from grandpa.action_layer.catalogue import get
from grandpa.action_layer.model import ActionRequest, ActionResult, Origin

__all__ = ["web_search_reply", "web_search_request", "web_search_status"]

_ACTION_NAMES = {
    "search": "web_search",
    "sources": "web_sources",
    "status": "web_search_status",
    "clear_cache": "web_clear_cache",
}


def web_search_request(text: str, *, origin: Origin = Origin.USER_CHAT):
    """Parse a phrase into an ActionRequest, or return ``(None, None)``."""
    from grandpa.web_search.parser import WebSearchParser

    parsed = WebSearchParser().parse(text)
    if parsed is None:
        return None, None

    name = _ACTION_NAMES.get(parsed.action)
    if name is None:  # pragma: no cover - the map covers WebSearchActionType
        return None, None

    parameters: dict[str, Any] = {}
    if parsed.action == "search" and parsed.query is not None:
        parameters["query"] = parsed.query.text
        if parsed.query.max_results:
            parameters["max_results"] = parsed.query.max_results

    spec = get(name)
    request = ActionRequest(
        name,
        parameters,
        origin=origin,
        risk=spec.risk,
        requires_confirmation=spec.requires_confirmation,
    )
    return request, parsed


def web_search_reply(result: ActionResult) -> str:
    return result.message


def web_search_status(result: ActionResult) -> str:
    recorded = result.data.get("status")
    if isinstance(recorded, str) and recorded:
        return recorded
    return "handled" if result.success else "error"
