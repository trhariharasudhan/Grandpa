"""Map a chat phrase to a catalogued browser action.

The parse half of the browser domain stays where it is: ``BrowserParser`` reads
the phrase, exactly as ``handle_browser_command`` had it read, so the same
phrases are caught here as before and nothing new is claimed from the handlers
further down chat's waterfall.

What changed is the half after the parser. Wave 2 gave the browser its own
approval path, which left two mechanisms side by side -- chat asked before
navigating, and the action layer, pointed at a different module, opened URLs
with no question at all. Both now go through the layer, and the *rule* stays
in the domain, because only it knows the resolved address and whether the host
is in ``tools.browser.trusted_domains``.
"""

from __future__ import annotations

from typing import Any

from grandpa.action_layer.catalogue import get
from grandpa.action_layer.model import ActionRequest, Origin
from grandpa.browser.models import BrowserAction

__all__ = ["ACTION_FOR", "build_browser_request"]

ACTION_FOR: dict[str, str] = {
    "open_url": "browser_open",
    "search": "browser_search",
    "open_page": "browser_page",
    "new_tab": "browser_new_tab",
    "close_tab": "browser_close_tab",
    "refresh": "browser_refresh",
    "back": "browser_back",
    "forward": "browser_forward",
    "reopen_closed_tab": "browser_reopen_closed_tab",
    "focus_address_bar": "browser_focus_address_bar",
}
"""Every action the parser can produce, and the catalogue entry for it.

The whole vocabulary, not the common part of it: a phrase the parser still
recognises but the catalogue could not name would be a phrase chat silently
stopped answering.
"""


def _parameters(action: BrowserAction) -> dict[str, Any]:
    if action.action == "open_url":
        return {"url": action.url or action.target}
    if action.action == "search":
        parameters: dict[str, Any] = {"query": action.query}
        if action.provider:
            parameters["provider"] = action.provider
        return parameters
    if action.action == "open_page":
        return {"page": action.target}
    return {}


def build_browser_request(
    text: str,
) -> tuple[ActionRequest | None, BrowserAction | None]:
    """The request for ``text``, or ``(None, None)`` when this is not for us."""
    from grandpa.browser.parser import BrowserParser

    parsed = BrowserParser().parse(text)
    if parsed is None:
        return None, None

    name = ACTION_FOR.get(parsed.action)
    if name is None:
        # The parser grew an action the catalogue has not been told about.
        # Falling through leaves the phrase to the handlers below rather than
        # answering it with a guess.
        return None, None

    spec = get(name)
    return (
        ActionRequest(
            name,
            _parameters(parsed),
            origin=Origin.USER_CHAT,
            risk=spec.risk,
            requires_confirmation=spec.requires_confirmation,
        ),
        parsed,
    )
