"""Chat's calendar and mail phrases, routed into the action layer.

The eighth and ninth migrations, done together because they are the same shape
twice: both already had ``execute(action, confirmed=, confirm=)``, and both
decide whether to ask from what they parsed, so both use
``Confirmation.DOMAIN`` and write their own prompt.
"""

from __future__ import annotations

from typing import Any

from grandpa.action_layer.catalogue import get
from grandpa.action_layer.model import ActionRequest, ActionResult, Origin

__all__ = [
    "calendar_request",
    "gmail_request",
    "google_reply",
    "google_status",
]

CANCELLED = {
    "calendar": "Calendar change cancelled.",
    "gmail": "Mail change cancelled.",
}

# Which CalendarAction / GmailAction fields each catalogued action takes. Only
# non-empty ones are passed, so the domain's own defaults still apply.
_CALENDAR_FIELDS = (
    "query",
    "title",
    "start_text",
    "end_text",
    "date_range",
    "timezone",
)
_GMAIL_FIELDS = ("query", "selector", "recipient", "subject", "body", "label")


def _request(
    prefix: str, parsed: Any, fields: tuple[str, ...], origin: Origin
) -> ActionRequest | None:
    name = f"{prefix}_{parsed.action}"
    try:
        spec = get(name)
    except KeyError:  # pragma: no cover - the catalogue covers the vocabulary
        return None

    allowed = set(spec.parameters.get("properties", ()))
    parameters: dict[str, Any] = {}
    for field in fields:
        value = getattr(parsed, field, "")
        if value and field in allowed:
            parameters[field] = value

    return ActionRequest(
        name,
        parameters,
        origin=origin,
        risk=spec.risk,
        requires_confirmation=spec.requires_confirmation,
    )


def calendar_request(text: str, *, origin: Origin = Origin.USER_CHAT):
    from grandpa.calendar.parser import CalendarParser

    parsed = CalendarParser().parse(text)
    if parsed is None:
        return None, None
    return _request("calendar", parsed, _CALENDAR_FIELDS, origin), parsed


def gmail_request(text: str, *, origin: Origin = Origin.USER_CHAT):
    from grandpa.gmail.parser import GmailParser

    parsed = GmailParser().parse(text)
    if parsed is None:
        return None, None
    return _request("gmail", parsed, _GMAIL_FIELDS, origin), parsed


def google_reply(result: ActionResult, kind: str) -> str:
    if result.error in {"confirmation_declined", "confirmation_required"}:
        return CANCELLED[kind]
    if result.data.get("status") == "needs_confirmation":
        return CANCELLED[kind]
    return result.message


def google_status(result: ActionResult) -> str:
    recorded = result.data.get("status")
    if isinstance(recorded, str) and recorded:
        return recorded
    return "handled" if result.success else "error"
