"""Chat's reminder and routine phrases, routed into the action layer.

Chat had *two* reminder branches in the waterfall, in this order:

1. a one-shot reminder helper, writing to reminders.db
2. the task scheduler, writing routines and recurring reminders to scheduler.db

The order matters and is preserved exactly: whichever parser claims a phrase
first decides which store it lands in. That is the behaviour the audit
described, and reproducing it is the point -- joining the stores is a separate
task, and doing it inside a migration would hide it.
"""

from __future__ import annotations

from typing import Any

from grandpa.action_layer.catalogue import get
from grandpa.action_layer.model import ActionRequest, ActionResult, Origin

__all__ = ["reminder_reply", "reminder_request", "reminder_status", "routine_request"]

_SCHEDULER_NAMES = {
    "create_morning_routine": "routine_create_morning",
    "set_morning_routine": "routine_set_morning",
    "list_schedule": "routine_list",
    "enable_routine": "routine_enable",
    "disable_routine": "routine_disable",
    "run_routine": "routine_run",
    "create_recurring_reminder": "routine_create_reminder",
}


def _build(name: str, parameters: dict[str, Any], origin: Origin) -> ActionRequest:
    spec = get(name)
    return ActionRequest(
        name,
        parameters,
        origin=origin,
        risk=spec.risk,
        requires_confirmation=spec.requires_confirmation,
    )


def reminder_request(text: str, *, origin: Origin = Origin.USER_CHAT):
    """One-shot reminders: create, list, cancel. ``(None, None)`` if no match."""
    from grandpa.reminders import parse_reminder_intent

    parsed = parse_reminder_intent(text)
    if parsed is None:
        return None, None
    action, subject = parsed

    parameters: dict[str, Any] = {}
    if subject:
        parameters["subject"] = subject
    return _build(f"reminder_{action}", parameters, origin), subject


def routine_request(text: str, *, origin: Origin = Origin.USER_CHAT):
    """Routines and recurring reminders. ``(None, None)`` if no match."""
    from grandpa.task_scheduler import parse_scheduler_command

    parsed = parse_scheduler_command(text)
    if parsed is None:
        return None, None
    action, parameters = parsed

    name = _SCHEDULER_NAMES.get(action)
    if name is None:  # pragma: no cover - the map covers SCHEDULER_ACTIONS
        return None, None
    return _build(name, dict(parameters), origin), parameters.get("name") or None


def reminder_reply(result: ActionResult) -> str:
    if result.error in {"confirmation_declined", "confirmation_required"}:
        return "Left unchanged."
    return result.message


def reminder_status(result: ActionResult) -> str:
    recorded = result.data.get("status")
    if isinstance(recorded, str) and recorded:
        return recorded
    return "handled" if result.success else "error"
