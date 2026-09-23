"""The local router: parse, decide, then perform.

``handle_local_action`` is the whole of this package's public surface. It was
the entry point of ``local_actions.py``, a 2200-line module that held the
parsers, the tier decision, the executor and the audit trail at once; they are
separate modules now, and this is the only one that knows about all of them.
"""

from __future__ import annotations

import logging
import re
import sys
from dataclasses import replace

from grandpa.local import audit, parsers, permissions

# Aliased: handle_local_action has an execute parameter, and a module
# named the same would be shadowed by it inside the function.
from grandpa.local import execute as executor
from grandpa.local.types import BLOCKED_MESSAGE, ConfirmationCallback
from grandpa.local_action_result import LocalActionResult

logger = logging.getLogger(__name__)


def refuse_confirmation(spec: str, permission: str) -> bool:
    """Confirm callback for callers that cannot ask the user mid-execution.

    Always returns ``False``, so the confirm-required tier in
    ``desktop_automation.py:37-45`` refuses. The voice layer uses this: its
    only confirmation is turn-based (the next utterance), which cannot
    answer synchronously inside ``execute_automation``. Signature matches
    the automation service.
    """
    return False


def handle_local_action(
    text: str,
    *,
    execute: bool = True,
    confirm: ConfirmationCallback | None = None,
    deferred_origin: str | None = None,
) -> LocalActionResult:
    """Parse and execute a safe local action if ``text`` asks for one.

    Returns ``no_match`` when the normal assistant pipeline should handle the
    query.

    An action that needs consent gets it one of three ways:

    * ``confirm``: the caller's inline prompt, asked before the action runs.
    * ``deferred_origin``: the caller opts into deferred consent. The action is
      staged in the kernel's approval store, bound to that origin, and runs
      when the same origin sends a "yes" on a later turn. Voice opts in, with
      origin "voice"; nothing is opted in by default.
    * neither: refused, and nothing is staged.

    ``deferred_origin`` is also what a "yes" or "cancel" resolves against, so a
    caller that never opted in has nothing to approve.
    """
    command = parsers._normalise(text)
    if not command:
        return LocalActionResult(status="no_match")

    cancel_phrases = {
        "stop reasoning",
        "stop thinking",
        "cancel that",
        "cancel current action",
        "cancel current task",
        "never mind",
    }
    if command in cancel_phrases:
        return LocalActionResult(
            status="handled",
            kind="session_control",
            target=command,
            message="Acknowledged. Action cancelled.",
            tts_text="Acknowledged.",
        )

    confirmation_result = permissions.handle_confirmation_command(
        command, confirm=confirm, origin=deferred_origin
    )
    if confirmation_result.status != "no_match":
        return confirmation_result

    if parsers._is_dangerous(command):
        result = LocalActionResult(
            status="blocked",
            kind="blocked",
            target=command,
            message=BLOCKED_MESSAGE,
            tts_text=BLOCKED_MESSAGE,
            permission="blocked",
        )
        audit.audit_decision(command, result, "blocked")
        audit.log_attempt(command, result)
        return result

    if parsers._is_safe_desktop_operator_request(command):
        result = parsers._parse_desktop_operator_action(command)
        if result.status != "no_match":
            if result.permission == "requires_confirmation":
                # Staged or refused, never asked inline: these branches return
                # without executing, so an inline yes would run nothing.
                result = permissions.with_permission(
                    command, result, deferred_origin=deferred_origin
                )
            audit.audit_decision(command, result, result.status)
            audit.log_attempt(command, result)
            return result

    user_skill_result = parsers._parse_user_skill_action(command, confirm=confirm)
    if user_skill_result.status != "no_match":
        if user_skill_result.permission == "requires_confirmation":
            user_skill_result = permissions.with_permission(
                command, user_skill_result, deferred_origin=deferred_origin
            )
        audit.audit_decision(command, user_skill_result, user_skill_result.status)
        audit.log_attempt(command, user_skill_result)
        return user_skill_result

    if execute and not _prefer_deterministic_browser_route(command):
        routed = _route_with_intent_router(command)
        if routed is not None:
            audit.audit_decision(command, routed, routed.status)
            audit.log_attempt(command, routed)
            return routed

    result = parsers._parse_safe_action(command)
    if result.status == "no_match":
        return result

    if result.status == "pending_confirmation":
        audit.log_attempt(command, result)
        return result

    # Unimplemented actions fail here, before permissions.with_permission, which would
    # otherwise queue an approval for an action that cannot run.
    if result.status == "unsupported":
        audit.log_attempt(command, result)
        return result

    # Migrated shapes are performed by the action layer. This sits after every
    # guard above -- session control, the pending-approval replies, the
    # dangerous-text refusal -- and before permissions.with_permission, which is where this
    # module would otherwise write a pending approval of its own.
    from grandpa.natural_actions import run_parsed

    # permissions.classify_permission refuses some shapes outright, before anyone is asked:
    # closing Task Manager, a browser click on "submit", "checkout", "payment",
    # "buy" or "login". The layer would ask first and only then refuse -- or, for
    # a click, not refuse at all -- so those refusals stay in front of it.
    if permissions.classify_permission(command, result) == "blocked":
        blocked = permissions.with_permission(command, result)
        audit.log_attempt(command, blocked)
        return blocked

    migrated = run_parsed(
        result.kind,
        result.target,
        confirm=confirm,
        execute=execute,
        deferred_origin=deferred_origin,
        summary=permissions._confirmation_summary(command, result),
        require_consent=permissions.classify_permission(command, result)
        == "requires_confirmation",
    )
    if migrated is not None:
        if not execute and migrated.status == "requires_confirmation":
            # The same sentence a dry run has always given. It does not stage
            # an approval: legacy dry runs wrote a pending action as a side
            # effect, which burnin and doctor -- both callers of execute=False
            # -- would have left behind on every run. A dry run creates nothing.
            migrated = replace(
                migrated,
                message=permissions._confirmation_summary(command, result),
                tts_text=permissions._confirmation_summary(command, result),
            )
        elif not execute and result.message:
            # The parser's own sentence ("Opening Notepad."), which is what a
            # dry run has always said, rather than the layer's "Would run ...".
            migrated = replace(
                migrated,
                message=result.message,
                tts_text=result.tts_text or result.message,
            )
        audit.log_attempt(command, migrated)
        return migrated

    if not execute:
        # A dry run describes; it does not stage, ask, or refuse on anyone's
        # behalf.
        dry = permissions._describe_permission(command, result)
        audit.log_attempt(command, dry)
        return dry

    needs_consent = (
        result.permission == "requires_confirmation"
        or permissions.classify_permission(command, result) == "requires_confirmation"
    )
    # Synthetic input is asked for by the action layer, as it runs -- see
    # permissions.with_permission -- so this module does not hold it back here.
    asked_at_the_layer = result.kind == "automation"
    result = permissions.with_permission(
        command, result, confirm=confirm, deferred_origin=deferred_origin
    )
    if not asked_at_the_layer and (
        result.status in {"requires_confirmation", "cancelled"}
        or (needs_consent and result.permission != "allowed")
    ):
        audit.log_attempt(command, result)
        return result

    if result.kind in {"app", "folder", "url", "browser"} and sys.platform != "win32":
        unsupported = LocalActionResult(
            status="unsupported",
            kind=result.kind,
            target=result.target,
            message="Windows local actions are not supported in this environment.",
            tts_text="Windows local actions are not supported here.",
            permission="unsupported",
        )
        audit.audit_decision(command, unsupported, "unsupported")
        audit.log_attempt(command, unsupported)
        return unsupported

    try:
        executed = executor.execute_parsed_action(
            result, confirm=confirm, consented=needs_consent
        )
    except Exception:  # pragma: no cover - defensive edge
        executed = LocalActionResult(
            status="error",
            kind=result.kind,
            target=result.target,
            message="I couldn't complete that local action.",
            tts_text="I could not complete that local action.",
            permission=result.permission,
        )

    audit.audit_decision(command, executed, executed.status)
    audit.log_attempt(command, executed)
    return executed


def _prefer_deterministic_browser_route(command: str) -> bool:
    """Keep explicit visible-browser commands out of generic planner routing."""

    exact = {
        "browser diagnostics",
        "show browser diagnostics",
        "browser status",
        "summarize this webpage",
        "summarise this webpage",
        "summarize current webpage",
        "summarize this web page",
        "summarize this page",
        "summarise this page",
        "read the visible headings",
        "read visible headings",
        "what headings are visible",
        "show links on this page",
        "show page links",
        "what links are visible",
        "read visible links",
        "what buttons are visible",
        "what buttons are visible?",
        "show visible buttons",
        "read visible buttons",
        "download this file",
        "download selected file",
        "download this page file",
    }
    if command in exact:
        return True
    return bool(
        re.fullmatch(parsers._WEB_SEARCH_PATTERN, command)
        or re.fullmatch(r"search google for (.+)", command)
        or re.fullmatch(r"open youtube and search(?: for)? (.+)", command)
        or re.fullmatch(r"fill (?:the )?(.+?) (?:field )?with (.+)", command)
    )


def _route_with_intent_router(command: str) -> LocalActionResult | None:
    """Try the new intent router while preserving legacy fallback behavior."""
    try:
        from grandpa.router import route_local_intent

        return route_local_intent(command)
    except Exception:
        logger.debug(
            "Intent router failed; using legacy local action parser.", exc_info=True
        )
        return None
