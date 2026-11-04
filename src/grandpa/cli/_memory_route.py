"""Chat's memory phrases, routed into the action layer.

The third migration. Memory is where the pattern's first step earned its
wording: it had no structured seam at all, so one was extracted first
(``parse_memory_command`` and ``execute_memory_action`` in
``grandpa.memory_context``) before anything could be catalogued. This module is
then the same three lines as notes and downloads.
"""

from __future__ import annotations

from typing import Any

from grandpa.action_layer.catalogue import get
from grandpa.action_layer.model import ActionRequest, ActionResult, Origin

__all__ = [
    "memory_is_miss",
    "memory_reply",
    "memory_request",
    "memory_status",
    "memory_target",
]

# Actions that need the parsed subject; the rest take nothing.
_WITH_SUBJECT = frozenset(
    {"remember", "recall", "attribute", "continue_project", "forget"}
)

CANCELLED = "Memory was left unchanged."
"""Said when an irreversible wipe is declined. There was no such message
before, because chat never asked."""


def memory_request(text: str, *, origin: Origin = Origin.USER_CHAT):
    """Parse a phrase into an ActionRequest, or return ``(None, None)``."""
    from grandpa.memory_context import parse_memory_command

    parsed = parse_memory_command(text)
    if parsed is None:
        return None, None
    action, subject = parsed

    name = f"memory_{action}"
    parameters: dict[str, Any] = {}
    if action in _WITH_SUBJECT and subject:
        parameters["subject"] = subject

    spec = get(name)
    request = ActionRequest(
        name,
        parameters,
        origin=origin,
        risk=spec.risk,
        requires_confirmation=spec.requires_confirmation,
    )
    return request, subject


def memory_is_miss(result: ActionResult) -> bool:
    """Whether the lookup found nothing, so the caller should keep going.

    A hit may answer directly. A miss may not: "I don't know" depends on the
    conversation history and on what the model knows, and a lookup against one
    table cannot see either. Reported -- "what is my sister name and is she
    elder or younger" was answered from this layer, the model never asked, and
    a turn later the model answered the same question from history.
    """
    return bool(result.data.get("should_fallback"))


def memory_reply(result: ActionResult) -> str:
    if result.error in {"confirmation_declined", "confirmation_required"}:
        return CANCELLED
    return result.message


def memory_status(result: ActionResult) -> str:
    recorded = result.data.get("status")
    if isinstance(recorded, str) and recorded:
        return recorded
    return "handled" if result.success else "error"


def memory_target(result: ActionResult, subject: str | None) -> str | None:
    """What chat records as the outcome's target, as MemoryCommandResult did."""
    recorded = result.data.get("target")
    if isinstance(recorded, str) and recorded:
        return recorded
    return subject or None
