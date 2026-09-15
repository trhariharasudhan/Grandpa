"""Chat's downloads phrases, routed into the action layer.

The second migration, following ``docs/architecture/MIGRATION-PATTERN.md``. The
shape is the same as notes -- parse here, decide and perform in the layer --
with one difference that the pattern doc did not anticipate: downloads decides
*for itself* whether a change is worth asking about, because that depends on how
many files the scan turned up. So these actions are declared
``Confirmation.DOMAIN`` and the layer hands its callback over rather than using
it first.
"""

from __future__ import annotations

from typing import Any, Mapping

from grandpa.action_layer.catalogue import get
from grandpa.action_layer.model import ActionRequest, ActionResult, Origin

__all__ = ["downloads_reply", "downloads_request", "downloads_status"]

# DownloadAction.action -> the catalogue name.
_ACTION_NAMES: Mapping[str, str] = {
    "recent": "downloads_recent",
    "today": "downloads_today",
    "latest": "downloads_latest",
    "search": "downloads_search",
    "large": "downloads_large",
    "incomplete": "downloads_incomplete",
    "duplicates": "downloads_duplicates",
    "info": "downloads_info",
    "open": "downloads_open",
    "open_folder": "downloads_open_folder",
    "move": "downloads_move",
    "organize": "downloads_organize",
    "archive": "downloads_archive",
    "delete": "downloads_delete",
}

# Actions that take a selector naming which downloads to act on.
_BY_SELECTOR = frozenset({"info", "open", "open_folder", "move", "archive", "delete"})

CANCELLED = "Downloads change cancelled."
"""What chat has always said when a downloads change is declined."""


def downloads_request(text: str, *, origin: Origin = Origin.USER_CHAT):
    """Parse a phrase into an ActionRequest, or return ``(None, None)``."""
    from grandpa.downloads.parser import DownloadsParser

    parsed = DownloadsParser().parse(text)
    if parsed is None:
        return None, None

    name = _ACTION_NAMES.get(parsed.action)
    if name is None:  # pragma: no cover - the map covers DownloadActionType
        return None, None

    parameters: dict[str, Any] = {}
    if parsed.action in _BY_SELECTOR and parsed.selector:
        parameters["which"] = parsed.selector
    if parsed.action == "search":
        parameters["query"] = parsed.query or parsed.selector
    if parsed.action == "move":
        parameters["destination"] = parsed.destination
    if parsed.action in {"move", "archive", "delete"} and parsed.days:
        parameters["days"] = parsed.days

    spec = get(name)
    request = ActionRequest(
        name,
        parameters,
        origin=origin,
        risk=spec.risk,
        requires_confirmation=spec.requires_confirmation,
    )
    return request, parsed


def downloads_reply(result: ActionResult) -> str:
    """What to show the user, keeping chat's existing wording."""
    if result.error in {"confirmation_declined", "confirmation_required"}:
        return CANCELLED
    if result.data.get("status") == "needs_confirmation":
        # Downloads asked and was told no, or had nobody to ask.
        return CANCELLED
    return result.message


def downloads_status(result: ActionResult) -> str:
    recorded = result.data.get("status")
    if isinstance(recorded, str) and recorded:
        return recorded
    return "handled" if result.success else "error"
