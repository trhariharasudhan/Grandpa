"""What a parsed action is allowed to do, and who has to be asked.

This is the tier decision for the local router: whether a described action is
allowed outright, needs consent, or is refused -- and, when consent is needed,
whether it can be staged for later or has to be asked as it happens.
"""

from __future__ import annotations

import logging
from typing import Any

from grandpa.local import audit, parsers
from grandpa.local.types import BLOCKED_MESSAGE, ConfirmationCallback
from grandpa.local_action_result import LocalActionResult, PermissionStatus

logger = logging.getLogger(__name__)


CONFIRMATION_PREFIX = "Confirmation required before I run this action."


CANCELLED_MESSAGE = "Cancelled the pending local action."


def approve_pending_action(
    action_id: str | None = None,
    *,
    confirm: ConfirmationCallback | None = None,
    origin: str | None = None,
) -> LocalActionResult:
    """Run the one action ``origin`` staged. Kept for the yes/no words below."""
    from grandpa.deferred_actions import approve

    return approve(action_id, origin=origin, confirm=confirm)


def deny_pending_action(
    action_id: str | None = None, *, origin: str | None = None
) -> LocalActionResult:
    """Refuse the one action ``origin`` staged. Kept for the yes/no words below."""
    from grandpa.deferred_actions import deny

    return deny(action_id, origin=origin)


def handle_confirmation_command(
    command: str,
    *,
    confirm: ConfirmationCallback | None = None,
    origin: str | None = None,
) -> LocalActionResult:
    if command in {"yes", "confirm", "approve", "run it", "do it"}:
        return approve_pending_action(confirm=confirm, origin=origin)
    if command in {"no", "cancel", "deny", "stop", "don't", "do not"}:
        return deny_pending_action(origin=origin)
    return LocalActionResult(status="no_match")


def with_permission(
    command: str,
    result: LocalActionResult,
    *,
    confirm: ConfirmationCallback | None = None,
    deferred_origin: str | None = None,
) -> LocalActionResult:
    permission = (
        result.permission
        if result.permission == "requires_confirmation"
        else classify_permission(command, result)
    )
    if permission == "allowed":
        return LocalActionResult(
            status=result.status,
            kind=result.kind,
            target=result.target,
            message=result.message,
            tts_text=result.tts_text,
            permission="allowed",
        )
    if permission == "unsupported":
        return LocalActionResult(
            status="unsupported",
            kind=result.kind,
            target=result.target,
            message="That local action is not supported yet.",
            tts_text="That local action is not supported yet.",
            permission="unsupported",
        )
    if permission == "blocked":
        blocked = LocalActionResult(
            status="blocked",
            kind="blocked",
            target=command,
            message=BLOCKED_MESSAGE,
            tts_text=BLOCKED_MESSAGE,
            permission="blocked",
        )
        audit.audit_decision(command, blocked, "blocked")
        return blocked

    summary = _confirmation_summary(command, result)
    # The action needs consent. Three ways to get it, the same three the action
    # layer has (natural_actions.run_parsed), with one difference in order: a
    # caller that opted into deferred consent is staged even when it also has
    # an inline prompt. That is chat, whose not-yet-migrated shapes have always
    # been two-turn ("search python packaging", then "yes"); it goes away as
    # those shapes move onto the layer.
    #
    # Synthetic input is the exception, and always will be: a keystroke goes to
    # whatever has focus at the instant it is sent, so a yes given a turn ago
    # is consent for a screen that may no longer be there. Keys and mouse are
    # asked inline, at the moment they run, or refused.
    if result.kind == "automation":
        # ...and this module does not ask for it either. The action layer asks,
        # once, as the keys are sent; asking here as well is the double prompt
        # that taught a user to answer the first question without reading it.
        # With no one to ask, the layer refuses, so nothing is let through.
        return LocalActionResult(
            status=result.status,
            kind=result.kind,
            target=result.target,
            message=result.message,
            tts_text=result.tts_text,
            permission="requires_confirmation",
        )
    if deferred_origin:
        from grandpa.desktop.kernel import approvals

        payload = {
            "kind": result.kind,
            "target": result.target,
            "message": result.message,
            "tts_text": result.tts_text,
            "source_text": command,
        }
        staged = approvals.stage_deferred(
            origin=deferred_origin,
            action=f"local_{result.kind or 'action'}",
            target=result.target,
            parameters={},
            payload=payload,
            risk_level="medium",
        )
        return LocalActionResult(
            status="requires_confirmation",
            kind=result.kind,
            target=result.target,
            message=_confirmation_message(command, result, staged["id"]),
            tts_text="Please confirm this local action.",
            permission="requires_confirmation",
            pending_action=_pending_metadata(
                {**staged, "payload": payload}, status="pending"
            ),
        )
    if confirm is not None:
        if confirm(summary, "requires_confirmation"):
            return LocalActionResult(
                status=result.status,
                kind=result.kind,
                target=result.target,
                message=result.message,
                tts_text=result.tts_text,
                permission="allowed",
            )
        cancelled = LocalActionResult(
            status="cancelled",
            kind=result.kind,
            target=result.target,
            message=CANCELLED_MESSAGE,
            tts_text=CANCELLED_MESSAGE,
            permission="requires_confirmation",
        )
        audit.audit_decision(command, cancelled, "denied")
        return cancelled
    # No one to ask and no opt-in: refused, and nothing is staged.
    refused = LocalActionResult(
        status="blocked",
        kind=result.kind,
        target=result.target,
        message=f"{summary} There is no way to ask for that here, so nothing was run.",
        tts_text="I need your confirmation for that, and cannot ask here.",
        permission="requires_confirmation",
    )
    audit.audit_decision(command, refused, "refused")
    return refused


def _describe_permission(command: str, result: LocalActionResult) -> LocalActionResult:
    """What a dry run reports: the permission, with nothing staged or asked."""
    permission = (
        result.permission
        if result.permission == "requires_confirmation"
        else classify_permission(command, result)
    )
    if permission == "requires_confirmation":
        summary = _confirmation_summary(command, result)
        return LocalActionResult(
            status="requires_confirmation",
            kind=result.kind,
            target=result.target,
            message=summary,
            tts_text=summary,
            permission="requires_confirmation",
        )
    return with_permission(command, result)


def _confirmation_message(
    command: str,
    result: LocalActionResult,
    action_id: str,
) -> str:
    summary = _confirmation_summary(command, result)
    return (
        f"{summary}\n\n"
        "Reply with yes/confirm to approve, or cancel to deny.\n"
        f"Action ID: {action_id}"
    )


def _confirmation_summary(command: str, result: LocalActionResult) -> str:
    if result.kind == "window" and result.target.startswith("close|"):
        return f"Confirmation required before closing {_target_label(result.target)}."
    if result.kind == "automation":
        if result.target.startswith("type|"):
            return "Confirmation required before typing into the active app."
        if result.target.startswith("hotkey|ctrl+v"):
            return "Confirmation required before pasting into the active app."
        if result.target.startswith("click|"):
            return "Confirmation required before clicking the screen."
        return "Confirmation required before controlling the active app."
    if result.kind == "folder":
        return "Confirmation required before opening that folder."
    if result.kind in {"url", "browser"} and parsers._is_browser_navigation(
        result.target
    ):
        return f"Confirmation required before opening {result.target} in your browser."
    if result.kind == "url":
        return "Confirmation required before opening that URL."
    if result.kind == "browser":
        if result.target.startswith("click|"):
            return "Confirmation required before clicking a visible browser element."
        if result.target.startswith("focus_search|"):
            return "Confirmation required before focusing a browser input."
        if result.target.startswith("form_fill|"):
            return "Confirmation required before filling a browser field."
        if result.target.startswith("download|"):
            return "Confirmation required before starting a browser download."
        return "Confirmation required before controlling the visible browser."
    return CONFIRMATION_PREFIX


def _target_label(target: str) -> str:
    raw = target.split("|", 1)[-1].replace("_", " ").strip()
    if not raw:
        return "that window"
    return parsers._APP_ALLOWLIST.get(raw, (raw, raw.title()))[1]


def classify_permission(command: str, result: LocalActionResult) -> PermissionStatus:
    if result.kind == "automation":
        return "requires_confirmation"
    if result.kind == "window" and result.target == "close|task_manager":
        return "blocked"
    if result.kind == "window" and result.target.startswith("close|"):
        return "requires_confirmation"
    if result.kind == "folder" and parsers._is_protected_folder(result.target):
        # Refused before anyone is asked: a yes to a folder that will then be
        # blocked is a yes that does nothing.
        return "blocked"
    if result.kind == "folder" and not parsers._is_known_safe_folder(result.target):
        return "requires_confirmation"
    if result.kind in {"url", "browser"} and parsers._is_browser_navigation(
        result.target
    ):
        return (
            "allowed"
            if parsers._is_trusted_navigation(result.target)
            else "requires_confirmation"
        )
    if result.kind == "browser" and result.target.startswith("click|"):
        if any(
            word in result.target.lower()
            for word in ("submit", "checkout", "payment", "purchase", "buy", "login")
        ):
            return "blocked"
        return "requires_confirmation"
    if result.kind == "browser" and result.target.startswith(
        ("focus_search|", "back|", "forward|", "reload|")
    ):
        return "requires_confirmation"
    if result.kind == "browser" and result.target.startswith(
        ("form_fill|", "download|")
    ):
        return "requires_confirmation"
    if result.kind in {
        "app",
        "folder",
        "url",
        "browser",
        "time",
        "system_info",
        "screen",
        "screenshot",
        "window",
        "app_lookup",
        "pc_control",
    }:
        return "allowed"
    if result.kind == "blocked":
        return "blocked"
    return "unsupported"


def _pending_metadata(row: dict[str, Any], *, status: str) -> dict[str, Any]:
    payload = row.get("payload") or {}
    return {
        "id": row["id"],
        "status": status,
        "kind": payload.get("kind"),
        "target": payload.get("target", ""),
        "source_text": payload.get("source_text", ""),
        "origin": row.get("origin"),
        "expires_at": row.get("expires_at"),
    }
