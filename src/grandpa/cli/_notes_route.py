"""Chat's notes phrases, routed into the action layer.

This is the seam the first migration cuts along. The natural-language *parser*
stays where it is -- turning "delete note shopping" into a structured
``NotesAction`` is a front end, not a handler. What moves is everything after
it: the layer decides risk, asks for confirmation, calls the one existing notes
implementation, and writes an audit record. Chat no longer holds any of that.

The result is that chat's notes branch shrinks to "parse, execute, print", and
the next domain follows the same three steps -- see
``docs/architecture/MIGRATION-PATTERN.md``.
"""

from __future__ import annotations

from typing import Any, Mapping

from grandpa.action_layer.catalogue import get
from grandpa.action_layer.model import ActionRequest, ActionResult, Origin

__all__ = ["notes_reply", "notes_request", "notes_status"]

# NotesAction.action -> the catalogue name. Only "open" is renamed: "read" says
# what it does to a model choosing a tool, where "open" suggests a window.
_ACTION_NAMES: Mapping[str, str] = {
    "list": "notes_list",
    "recent": "notes_recent",
    "search": "notes_search",
    "open": "notes_read",
    "create": "notes_create",
    "append": "notes_append",
    "rename": "notes_rename",
    "delete": "notes_delete",
    "archive": "notes_archive",
    "restore": "notes_restore",
    "pin": "notes_pin",
    "unpin": "notes_unpin",
}

# Actions that name an existing note. Notes finds one by `query or title`, so
# the parser may have filled either.
_BY_NAME = frozenset(
    {"open", "append", "rename", "delete", "archive", "restore", "pin", "unpin"}
)

CANCELLED = "Note deletion cancelled."
"""What chat has always said when a note delete is declined. Kept verbatim:
the e2e suite pins it, and the point of a migration is that nobody notices."""


def notes_request(text: str, *, origin: Origin = Origin.USER_CHAT):
    """Parse a phrase into an ActionRequest, or return ``(None, None)``.

    Returns the parsed ``NotesAction`` alongside the request so the caller can
    still report what was asked for, as chat's outcome record did.
    """
    from grandpa.notes.parser import NotesParser

    parsed = NotesParser().parse(text)
    if parsed is None:
        return None, None

    name = _ACTION_NAMES.get(parsed.action)
    if name is None:  # pragma: no cover - the map covers NotesActionType
        return None, None

    identifier = (parsed.query or parsed.title).strip()
    parameters: dict[str, Any] = {}
    if parsed.action in _BY_NAME:
        parameters["title"] = identifier
    if parsed.action == "search":
        parameters["query"] = parsed.query or parsed.title
    if parsed.action == "create":
        # NotesAutomation._execute defaults an empty title the same way.
        parameters["title"] = parsed.title or "Quick Note"
        if parsed.tags:
            parameters["tags"] = list(parsed.tags)
        if parsed.category:
            parameters["category"] = parsed.category
    if parsed.action in {"create", "append"} and parsed.content:
        parameters["content"] = parsed.content
    if parsed.action == "rename":
        parameters["new_title"] = parsed.new_title

    spec = get(name)
    request = ActionRequest(
        name,
        parameters,
        origin=origin,
        risk=spec.risk,
        requires_confirmation=spec.requires_confirmation,
    )
    return request, parsed


def notes_reply(result: ActionResult) -> str:
    """What to show the user, keeping chat's existing wording."""
    if result.error == "confirmation_declined":
        return CANCELLED
    if result.error == "confirmation_required":
        # No terminal to ask on. Saying nothing happened is the honest reply.
        return CANCELLED
    return result.message


def notes_status(result: ActionResult) -> str:
    """The status chat records against the outcome, as NotesResult reported it."""
    recorded = result.data.get("status")
    if isinstance(recorded, str) and recorded:
        return recorded
    return "handled" if result.success else "error"
