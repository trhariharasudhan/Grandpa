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

Synthetic input is stageable only against a focus witness. A keystroke's target
is whatever has focus at the instant it is sent, not whenever the yes arrives, so
a staged row carries a reading of the foreground window and that reading is taken
again here before anything is sent (``grandpa.desktop.focus_witness``). Three
preconditions, all checked in ``_witness_verdict`` below:

* the row is inside the store's single wall-clock TTL -- applied by the peek, so
  an expired row is simply not found;
* the origin's turn counter is exactly one past the turn the row was staged on,
  because a turn has no fixed duration and "the screen you were just looking at"
  is a turn, not a number of seconds;
* the witness still matches, tiered as ``focus_witness.compare`` defines.

A mismatch discards the row, re-stages against the new reading and says so --
once. A second mismatch refuses aloud and drops it, because a window that changes
every turn must not become an endless prompt: that is how "yes" becomes a reflex.

A row with no witness is a non-synthetic action and behaves as it always has.
"""

from __future__ import annotations

import sys
from collections.abc import Callable

from grandpa.local_action_result import LocalActionResult

ConfirmationCallback = Callable[[str, str], bool]

CANCELLED_MESSAGE = "Cancelled the pending local action."


#: One re-ask per original intent. The second mismatch refuses and drops it.
MAX_REASKS = 1


def _check_witness_before_claiming(
    *, origin: str, action_id: str | None
) -> LocalActionResult | None:
    """None to proceed with the claim, or the result to return instead.

    Only witnessed rows are checked. Everything else -- every non-synthetic
    deferred action -- reaches the claim untouched, which is why adding this did
    not change how staging a folder or a URL behaves.
    """
    from grandpa.desktop import consent_readback, focus_witness
    from grandpa.desktop.kernel import approvals

    row = approvals.peek_deferred(origin=origin, action_id=action_id)
    if row is None or not row.get("witness"):
        return None

    action = str(row.get("action") or "")
    parameters = dict(row.get("parameters") or {})
    staged = focus_witness.Witness.from_dict(row.get("witness"))

    # The turn window. Redeemable only on the turn immediately after staging:
    # a "yes" two turns later is about something the user has moved on from, and
    # leaving the row pending would let any later "yes" drain it.
    staged_turn = int(row.get("staged_turn_seq", -1))
    current_turn = approvals.current_turn(origin)
    if staged_turn >= 0 and current_turn != staged_turn + 1:
        approvals.cancel_deferred(
            origin=origin, action_id=str(row["id"]), reason="stale_turn"
        )
        spoken = (
            "That yes came too late for the keystroke I asked about, so I did not "
            "send it. Tell me again if you still want it."
        )
        return LocalActionResult(
            status="blocked",
            kind="blocked",
            target=str(row.get("target") or ""),
            message=spoken,
            tts_text=spoken,
            permission="requires_confirmation",
        )

    current = focus_witness.capture(control_target=str(parameters.get("control") or ""))
    verdict = focus_witness.compare(staged, current, action=action)
    if verdict.matched:
        return None

    # Mismatched. Drop this row whatever happens next: it was approved against a
    # screen that is not there.
    approvals.cancel_deferred(
        origin=origin, action_id=str(row["id"]), reason="witness_mismatch"
    )
    reasks = int(row.get("reask_count", 0))

    if reasks >= MAX_REASKS or staged is None or current is None:
        # No second re-ask, and nothing to re-ask against when either reading is
        # missing. Refuse aloud and stop.
        spoken = (
            consent_readback.refuse(action)
            if staged is not None and current is not None
            else consent_readback.cannot_witness(action)
        )
        return LocalActionResult(
            status="blocked",
            kind="blocked",
            target=str(row.get("target") or ""),
            message=f"{spoken} ({verdict.reason})" if verdict.reason else spoken,
            tts_text=spoken,
            permission="requires_confirmation",
        )

    # One re-ask: stage fresh against the reading that is actually in front of the
    # user, and say what did not happen before offering it again.
    restaged = approvals.stage_deferred(
        origin=origin,
        action=action,
        target=str(row.get("target") or ""),
        parameters=parameters,
        payload=dict(row.get("payload") or {}),
        risk_level=str(row.get("risk_level") or "MEDIUM"),
        witness=current.to_dict(),
        reask_count=reasks + 1,
    )
    spoken = consent_readback.reask(action, parameters, staged, current)
    return LocalActionResult(
        status="requires_confirmation",
        kind=str((row.get("payload") or {}).get("kind") or ""),
        target=str(row.get("target") or ""),
        message=f"{spoken}\n\nAction ID: {restaged['id']}",
        tts_text=spoken,
        permission="requires_confirmation",
        pending_action=restaged,
    )


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

    # A witnessed row is checked before it is claimed: a mismatch has to re-stage,
    # and a claim that had already fired would leave nothing to re-ask about.
    if origin:
        refusal = _check_witness_before_claiming(origin=origin, action_id=action_id)
        if refusal is not None:
            return refusal

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
