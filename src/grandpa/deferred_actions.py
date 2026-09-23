"""Resolving an action that was staged for a later yes.

Deferred consent is staged in the kernel's approval store, bound to the origin
that asked (``grandpa.desktop.kernel.approvals``). Claiming one and running it
used to live in ``local_actions``, which meant the HTTP API imported the phrase
parser to answer ``POST /v1/local-actions/{id}/approve``.

It lives here instead: this module claims through the kernel facade and then
performs the staged phrase. It does not go in the facade itself, because the
kernel would then have to know what a parsed phrase is -- the layering the
direct-executor baseline exists to protect. The execution hop into
``local_actions`` below is the last of it, and goes away with that module.

Synthetic input is never staged, so nothing here can send keys or move the
mouse: the layer refuses to defer anything the automation service implements
(``natural_actions``), and a keystroke's target is whatever has focus at the
instant it is sent, not whenever the yes arrives.
"""

from __future__ import annotations

import sys
from collections.abc import Callable

from grandpa.local_action_result import LocalActionResult

ConfirmationCallback = Callable[[str, str], bool]

CANCELLED_MESSAGE = "Cancelled the pending local action."


def _metadata(row: dict, *, status: str) -> dict:
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


def approve(
    action_id: str | None = None,
    *,
    origin: str | None = None,
    confirm: ConfirmationCallback | None = None,
) -> LocalActionResult:
    """Run the one action ``origin`` staged, if there is one.

    No origin, no approval: a "yes" from a caller that never opted into
    deferred consent has nothing to approve, and one origin's yes cannot reach
    an action staged by another.
    """
    from grandpa.desktop.kernel import approvals
    from grandpa.local.audit import audit_decision, log_attempt
    from grandpa.local.execute import execute_parsed_action

    claimed = (
        approvals.approve_deferred(origin=origin, action_id=action_id)
        if origin
        else None
    )
    if claimed is None:
        return LocalActionResult(
            status="unsupported",
            kind="blocked",
            target=action_id or "",
            message="There is no pending local action to approve.",
            tts_text="There is no pending action.",
            permission="unsupported",
        )
    payload = claimed.get("payload") or {}
    metadata = _metadata(claimed, status="approved")
    staged = LocalActionResult(
        status="handled",
        kind=payload.get("kind"),
        target=str(payload.get("target") or ""),
        message=str(payload.get("message") or ""),
        tts_text=str(payload.get("tts_text") or ""),
        permission="allowed",
        pending_action=metadata,
    )
    if staged.kind in {"app", "folder", "url", "browser"} and sys.platform != "win32":
        result = LocalActionResult(
            status="unsupported",
            kind=staged.kind,
            target=staged.target,
            message="Windows local actions are not supported in this environment.",
            tts_text="Windows local actions are not supported here.",
            permission="unsupported",
            pending_action=metadata,
        )
    else:
        try:
            executed = execute_parsed_action(staged, confirm=confirm, consented=True)
            result = LocalActionResult(
                status=executed.status,
                kind=executed.kind,
                target=executed.target,
                message=executed.message,
                tts_text=executed.tts_text,
                permission="allowed",
                pending_action=metadata,
            )
        except Exception:  # pragma: no cover - defensive edge
            result = LocalActionResult(
                status="error",
                kind=staged.kind,
                target=staged.target,
                message="I couldn't complete that local action.",
                tts_text="I could not complete that local action.",
                permission="allowed",
                pending_action=metadata,
            )
    source_text = str(payload.get("source_text") or staged.target)
    audit_decision(source_text, result, "approved")
    log_attempt(source_text, result)
    return result


def deny(
    action_id: str | None = None, *, origin: str | None = None
) -> LocalActionResult:
    """Refuse the one action ``origin`` staged, if there is one."""
    from grandpa.desktop.kernel import approvals
    from grandpa.local.audit import audit_decision, log_attempt

    claimed = (
        approvals.deny_deferred(origin=origin, action_id=action_id) if origin else None
    )
    if claimed is None:
        return LocalActionResult(
            status="unsupported",
            kind="blocked",
            target=action_id or "",
            message="There is no pending local action to cancel.",
            tts_text="There is no pending action.",
            permission="unsupported",
        )
    payload = claimed.get("payload") or {}
    result = LocalActionResult(
        status="cancelled",
        kind=payload.get("kind"),
        target=str(payload.get("target") or ""),
        message=CANCELLED_MESSAGE,
        tts_text=CANCELLED_MESSAGE,
        permission="requires_confirmation",
        pending_action=_metadata(claimed, status="denied"),
    )
    source_text = str(payload.get("source_text") or result.target)
    audit_decision(source_text, result, "denied")
    log_attempt(source_text, result)
    return result


__all__ = ["approve", "deny"]
