"""Safe local Windows actions for Grandpa.

Phase 1 intentionally supports only a small allowlist of read-only or
launcher-style actions. It never runs arbitrary shell, PowerShell, or cmd
strings.
"""

from __future__ import annotations

import logging
import os
import platform
import re
import sys
import urllib.parse
import webbrowser
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from grandpa.local_action_approvals import LocalActionApprovalStore

logger = logging.getLogger(__name__)

ActionStatus = Literal[
    "handled",
    "requires_confirmation",
    "blocked",
    "unsupported",
    "no_match",
    "error",
    "cancelled",
]
PermissionStatus = Literal["allowed", "requires_confirmation", "blocked", "unsupported"]
ActionKind = Literal[
    "app",
    "folder",
    "url",
    "time",
    "system_info",
    "screen",
    "screenshot",
    "browser",
    "automation",
    "window",
    "app_lookup",
    "pc_control",
    "agent_plan",
    "blocked",
]

BLOCKED_MESSAGE = "I blocked this action for safety."
CONFIRMATION_PREFIX = "Confirmation required before I run this action."
CANCELLED_MESSAGE = "Cancelled the pending local action."


@dataclass(frozen=True)
class LocalActionResult:
    status: ActionStatus
    kind: ActionKind | None = None
    target: str = ""
    message: str = ""
    tts_text: str = ""
    permission: PermissionStatus | None = None
    pending_action: dict[str, Any] | None = None

    @property
    def should_fallback(self) -> bool:
        return self.status == "no_match"


_APP_ALLOWLIST: dict[str, tuple[str, str]] = {
    "notepad": ("notepad", "Notepad"),
    "calculator": ("calculator", "Calculator"),
    "calc": ("calculator", "Calculator"),
    "chrome": ("chrome", "Chrome"),
    "google chrome": ("chrome", "Chrome"),
    "edge": ("edge", "Microsoft Edge"),
    "microsoft edge": ("edge", "Microsoft Edge"),
    "vs code": ("vscode", "VS Code"),
    "vscode": ("vscode", "VS Code"),
    "visual studio code": ("vscode", "VS Code"),
    "file explorer": ("explorer", "File Explorer"),
    "explorer": ("explorer", "File Explorer"),
    "windows explorer": ("explorer", "File Explorer"),
    "control panel": ("control_panel", "Control Panel"),
    "settings": ("settings", "Settings"),
    "windows settings": ("settings", "Settings"),
    "task manager": ("task_manager", "Task Manager"),
}

_EXACT_SPEECH_CORRECTIONS = {
    "calc-you-later": "calculator",
    "note pad": "notepad",
    "visual studio coat": "vscode",
}


def resolve_fuzzy_app(target: str) -> tuple[str | None, float, str | None]:
    target = target.lower().strip()

    # Check exact allowlist
    if target in _APP_ALLOWLIST:
        app_id, label = _APP_ALLOWLIST[target]
        return app_id, 1.0, label

    # Check exact speech corrections
    if target in _EXACT_SPEECH_CORRECTIONS:
        app_id = _EXACT_SPEECH_CORRECTIONS[target]
        for k, (aid, lbl) in _APP_ALLOWLIST.items():
            if aid == app_id:
                return app_id, 1.0, lbl

    # Check exact inventory match
    try:
        from grandpa.apps.inventory import find_app

        res = find_app(target)
        if res.status == "found" and res.score >= 1.0:
            record = res.matches[0]
            return record.canonical_key, 1.0, record.display_name
    except Exception:
        pass

    # Run SequenceMatcher fuzzy check across all keys in _APP_ALLOWLIST
    from difflib import SequenceMatcher

    best_ratio = 0.0
    best_app_id = None
    best_label = None

    for candidate_key, (app_id, label) in _APP_ALLOWLIST.items():
        ratio = SequenceMatcher(None, target, candidate_key).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_app_id = app_id
            best_label = label

    # Check fuzzy inventory match
    try:
        from grandpa.apps.inventory import find_app

        res = find_app(target)
        if res.status in {"found", "ambiguous"} and res.score > best_ratio:
            record = res.matches[0]
            best_ratio = res.score
            best_app_id = record.canonical_key
            best_label = record.display_name
    except Exception:
        pass

    return best_app_id, best_ratio, best_label


_URL_ALLOWLIST: dict[str, tuple[str, str]] = {
    "youtube": ("https://www.youtube.com", "YouTube"),
    "gmail": ("https://mail.google.com", "Gmail"),
}

_DANGEROUS_PATTERNS = (
    r"\bdelete\b",
    r"\bremove\b.*\bfiles?\b",
    r"\berase\b",
    r"\bwipe\b",
    r"\bformat\b",
    r"\bshutdown\b",
    r"\brestart\b",
    r"\breboot\b",
    r"\blog\s*off\b",
    r"\bsign\s*out\b",
    r"\bregistry\b",
    r"\bregedit\b",
    r"\bpassword\b",
    r"\bcredential",
    r"\boverwrite\b",
    r"\bcommand\s*prompt\b",
    r"\bcmd(?:\.exe)?\b",
    r"\bpowershell\b",
    r"\bterminal\b",
    r"\bmacro\b",
    r"\bautomate\b.*\bloop\b",
    r"\brepeat\b.*\bforever\b",
    r"\bunattended\b",
    r"\bremote\s*control\b",
    r"\bsystem32\b",
    r"\balt\s*\+\s*f4\b",
    r"\bctrl\s*\+\s*x\b",
    r"\bpurchase\b",
    r"\bpayment\b",
    r"\bpay\b",
    r"\bbuy\b",
    r"\bcheckout\b",
    r"\bextract\b.*\bpassword\b",
    r"\bread\b.*\bpassword\b",
    r"\brm\s+-",
    r"\bdel\s+",
)


def handle_local_action(text: str, *, execute: bool = True) -> LocalActionResult:
    """Parse and execute a safe local action if ``text`` asks for one.

    Returns ``no_match`` when the normal assistant pipeline should handle the
    query.
    """
    command = _normalise(text)
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

    confirmation_result = _handle_confirmation_command(command)
    if confirmation_result.status != "no_match":
        return confirmation_result

    if _is_dangerous(command):
        result = LocalActionResult(
            status="blocked",
            kind="blocked",
            target=command,
            message=BLOCKED_MESSAGE,
            tts_text=BLOCKED_MESSAGE,
            permission="blocked",
        )
        _audit_decision(command, result, "blocked")
        _log_attempt(command, result)
        return result

    if _is_safe_desktop_operator_request(command):
        result = _parse_desktop_operator_action(command)
        if result.status != "no_match":
            if result.permission == "requires_confirmation":
                result = _with_permission(command, result)
            _audit_decision(command, result, result.status)
            _log_attempt(command, result)
            return result

    user_skill_result = _parse_user_skill_action(command)
    if user_skill_result.status != "no_match":
        if user_skill_result.permission == "requires_confirmation":
            user_skill_result = _with_permission(command, user_skill_result)
        _audit_decision(command, user_skill_result, user_skill_result.status)
        _log_attempt(command, user_skill_result)
        return user_skill_result

    if execute and not _prefer_deterministic_browser_route(command):
        routed = _route_with_intent_router(command)
        if routed is not None:
            _audit_decision(command, routed, routed.status)
            _log_attempt(command, routed)
            return routed

    result = _parse_safe_action(command)
    if result.status == "no_match":
        return result

    if result.status == "pending_confirmation":
        _log_attempt(command, result)
        return result

    result = _with_permission(command, result)
    if result.status == "requires_confirmation":
        _log_attempt(command, result)
        return result

    if not execute:
        _log_attempt(command, result)
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
        _audit_decision(command, unsupported, "unsupported")
        _log_attempt(command, unsupported)
        return unsupported

    try:
        executed = _execute(result)
    except Exception:  # pragma: no cover - defensive edge
        executed = LocalActionResult(
            status="error",
            kind=result.kind,
            target=result.target,
            message="I couldn't complete that local action.",
            tts_text="I could not complete that local action.",
            permission=result.permission,
        )

    _audit_decision(command, executed, executed.status)
    _log_attempt(command, executed)
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
        re.fullmatch(r"search (?!google for\b)(?!youtube for\b)(.+)", command)
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


def approve_pending_action(action_id: str | None = None) -> LocalActionResult:
    store = LocalActionApprovalStore()
    pending = store.get_pending(action_id) if action_id else store.latest_pending()
    if not pending:
        return LocalActionResult(
            status="unsupported",
            kind="blocked",
            target=action_id or "",
            message="There is no pending local action to approve.",
            tts_text="There is no pending action.",
            permission="unsupported",
        )
    if pending["status"] != "pending":
        return LocalActionResult(
            status="unsupported",
            kind=pending["kind"],
            target=pending["target"],
            message="That pending local action is no longer available.",
            tts_text="That pending action is no longer available.",
            permission="unsupported",
            pending_action=_pending_metadata(pending),
        )
    store.mark(pending["id"], "approved")
    result = LocalActionResult(
        status="handled",
        kind=pending["kind"],
        target=pending["target"],
        message=pending["message"],
        tts_text=pending["tts_text"],
        permission="allowed",
        pending_action=_pending_metadata(pending),
    )
    if result.kind in {"app", "folder", "url", "browser"} and sys.platform != "win32":
        result = LocalActionResult(
            status="unsupported",
            kind=result.kind,
            target=result.target,
            message="Windows local actions are not supported in this environment.",
            tts_text="Windows local actions are not supported here.",
            permission="unsupported",
            pending_action=_pending_metadata(pending),
        )
    else:
        try:
            executed = _execute(result)
            result = LocalActionResult(
                status=executed.status,
                kind=executed.kind,
                target=executed.target,
                message=executed.message,
                tts_text=executed.tts_text,
                permission="allowed",
                pending_action=_pending_metadata(pending),
            )
        except Exception:  # pragma: no cover - defensive edge
            result = LocalActionResult(
                status="error",
                kind=pending["kind"],
                target=pending["target"],
                message="I couldn't complete that local action.",
                tts_text="I could not complete that local action.",
                permission="allowed",
                pending_action=_pending_metadata(pending),
            )
    _log_attempt(pending["source_text"], result)
    return result


def deny_pending_action(action_id: str | None = None) -> LocalActionResult:
    store = LocalActionApprovalStore()
    pending = store.get_pending(action_id) if action_id else store.latest_pending()
    if not pending:
        return LocalActionResult(
            status="unsupported",
            kind="blocked",
            target=action_id or "",
            message="There is no pending local action to cancel.",
            tts_text="There is no pending action.",
            permission="unsupported",
        )
    store.mark(pending["id"], "denied")
    result = LocalActionResult(
        status="cancelled",
        kind=pending["kind"],
        target=pending["target"],
        message=CANCELLED_MESSAGE,
        tts_text=CANCELLED_MESSAGE,
        permission="requires_confirmation",
        pending_action=_pending_metadata(pending),
    )
    _log_attempt(pending["source_text"], result)
    return result


def _handle_confirmation_command(command: str) -> LocalActionResult:
    if command in {"yes", "confirm", "approve", "run it", "do it"}:
        return approve_pending_action()
    if command in {"no", "cancel", "deny", "stop", "don't", "do not"}:
        return deny_pending_action()
    return LocalActionResult(status="no_match")


def _with_permission(command: str, result: LocalActionResult) -> LocalActionResult:
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
        _audit_decision(command, blocked, "blocked")
        return blocked

    pending = LocalActionApprovalStore().create_pending(
        source_text=command,
        kind=result.kind or "",
        target=result.target,
        message=result.message,
        tts_text=result.tts_text,
    )
    message = _confirmation_message(command, result, pending["id"])
    return LocalActionResult(
        status="requires_confirmation",
        kind=result.kind,
        target=result.target,
        message=message,
        tts_text="Please confirm this local action.",
        permission="requires_confirmation",
        pending_action=_pending_metadata(pending),
    )


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
    return _APP_ALLOWLIST.get(raw, (raw, raw.title()))[1]


def classify_permission(command: str, result: LocalActionResult) -> PermissionStatus:
    if result.kind == "automation":
        return "requires_confirmation"
    if result.kind == "window" and result.target == "close|task_manager":
        return "blocked"
    if result.kind == "window" and result.target.startswith("close|"):
        return "requires_confirmation"
    if result.kind == "folder" and not _is_known_safe_folder(result.target):
        return "requires_confirmation"
    if result.kind == "url" and not _is_known_safe_url(result.target):
        return "requires_confirmation"
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


def _pending_metadata(pending: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": pending["id"],
        "status": pending["status"],
        "kind": pending["kind"],
        "target": pending["target"],
        "source_text": pending["source_text"],
        "expires_at": pending["expires_at"],
    }


def _audit_decision(command: str, result: LocalActionResult, decision: str) -> None:
    try:
        LocalActionApprovalStore().audit(
            action_id=(result.pending_action or {}).get("id"),
            decision=decision,
            source_text=command,
            kind=result.kind,
            target=result.target,
            detail={"permission": result.permission, "status": result.status},
        )
    except Exception:
        logger.debug("Failed to audit local action decision", exc_info=True)


def _is_known_safe_url(url: str) -> bool:
    return url in {value[0] for value in _URL_ALLOWLIST.values()}


def _is_known_safe_folder(path: str) -> bool:
    return path in {str(Path.home() / "Downloads"), str(Path("D:\\"))}


def _normalise(text: str) -> str:
    cmd = text.strip().lower()
    cmd = re.sub(r"[?!.,\s]+$", "", cmd)
    cmd = re.sub(r"\s+", " ", cmd)

    # Map switch to / switch / focus on -> focus
    cmd = re.sub(r"\bswitch\s+to\b", "focus", cmd)
    cmd = re.sub(r"\bswitch\b", "focus", cmd)
    cmd = re.sub(r"\bfocus\s+on\b", "focus", cmd)

    # Strip leading fillers
    fillers = [
        r"^please\s+",
        r"^can\s+you\s+",
        r"^could\s+you\s+",
        r"^would\s+you\s+",
        r"^okay\s*",
        r"^ok\s*",
        r"^hey\s+grandpa\s+",
        r"^grandpa\s+",
    ]
    for pattern in fillers:
        cmd = re.sub(pattern, "", cmd).strip()

    # Normalize trailing UI suffixes and map bring to front
    match = re.match(
        r"^(focus|minimize|maximize|restore|close|open|launch|start|show|bring\s+to\s+front|bring\s+to\s+foreground)\s+(.+)$",
        cmd,
    )
    if match:
        action = match.group(1)
        target = match.group(2).strip()
        # Strip articles
        target = re.sub(r"^(the|my|a|an)\s+", "", target).strip()
        # Strip trailing UI suffixes
        suffixes = [
            r"\s+screen$",
            r"\s+window$",
            r"\s+app$",
            r"\s+application$",
            r"\s+program$",
        ]
        for pattern in suffixes:
            target = re.sub(pattern, "", target).strip()
        if action in {"bring to front", "bring to foreground"}:
            action = "focus"
        cmd = f"{action} {target}"

    bring_match = re.match(r"^bring\s+(.+?)\s+to\s+(?:front|foreground)$", cmd)
    if bring_match:
        target = bring_match.group(1).strip()
        target = re.sub(r"^(the|my|a|an)\s+", "", target).strip()
        suffixes = [
            r"\s+screen$",
            r"\s+window$",
            r"\s+app$",
            r"\s+application$",
            r"\s+program$",
        ]
        for pattern in suffixes:
            target = re.sub(pattern, "", target).strip()
        cmd = f"focus {target}"

    return cmd


def _is_dangerous(command: str) -> bool:
    if _is_safe_desktop_operator_request(command):
        return False
    return any(re.search(pattern, command) for pattern in _DANGEROUS_PATTERNS)


def _parse_safe_action(command: str) -> LocalActionResult:
    # Parse Chrome Profile Selection command
    profile_match = re.search(
        r"(?:select|click|choose|open chrome using|use)(?:\s+my|\s+the)?\s+([a-zA-Z0-9\s]+?)(?:\s+chrome)?\s+profile",
        command,
    )
    if profile_match:
        profile_name = profile_match.group(1).strip()
        # Capitalize words to look like a canonical profile name (e.g. Hari Hara Sudhan)
        profile_name = " ".join(w.capitalize() for w in profile_name.split())
        return LocalActionResult(
            status="handled",
            kind="chrome_profile",
            target=profile_name,
            message=f"Selecting Chrome profile {profile_name}.",
            tts_text=f"Selecting Chrome profile {profile_name}.",
        )

    action_result = _route_with_action_modules(command)
    if action_result is not None:
        return action_result

    operator_result = _parse_desktop_operator_action(command)
    if operator_result.status != "no_match":
        return operator_result

    window_result = _parse_window_action(command)
    if window_result.status != "no_match":
        return window_result

    browser_result = _parse_browser_action(command)
    if browser_result.status != "no_match":
        return browser_result

    screen_result = _parse_screen_action(command)
    if screen_result.status != "no_match":
        return screen_result

    automation_result = _parse_automation_action(command)
    if automation_result.status != "no_match":
        return automation_result

    pc_control_result = _parse_pc_control_action(command)
    if pc_control_result.status != "no_match":
        return pc_control_result

    agent_plan_result = _parse_agent_plan_action(command)
    if agent_plan_result.status != "no_match":
        return agent_plan_result

    if command in {"what time is it", "what's the time", "time", "current time"}:
        now = datetime.now().strftime("%I:%M %p").lstrip("0")
        message = f"It is {now}."
        return LocalActionResult(
            status="handled",
            kind="time",
            target="local_time",
            message=message,
            tts_text=message,
        )

    if command in {
        "show system info",
        "system info",
        "show basic system info",
        "what is my system info",
    }:
        message = _system_info_message()
        return LocalActionResult(
            status="handled",
            kind="system_info",
            target="system_info",
            message=message,
            tts_text="Here is your basic system info.",
        )

    if command in {"find installed apps", "list installed apps", "show installed apps"}:
        return LocalActionResult(
            status="handled",
            kind="app_lookup",
            target="installed_apps",
            message="Finding installed apps.",
            tts_text="Finding installed apps.",
        )

    app_location_match = re.fullmatch(r"where is (.+?) installed", command)
    if app_location_match:
        app_name = app_location_match.group(1).strip()
        return LocalActionResult(
            status="handled",
            kind="app_lookup",
            target=app_name,
            message=f"Finding where {app_name} is installed.",
            tts_text=f"Finding {app_name}.",
        )

    open_target = _strip_open_prefix(command)
    if open_target is None:
        return LocalActionResult(status="no_match")

    if open_target in _URL_ALLOWLIST:
        url, label = _URL_ALLOWLIST[open_target]
        return LocalActionResult(
            status="handled",
            kind="url",
            target=url,
            message=f"Opening {label}.",
            tts_text=f"Opening {label}.",
        )

    folder = _folder_for(open_target)
    if folder is not None:
        return LocalActionResult(
            status="handled",
            kind="folder",
            target=str(folder),
            message=f"Opening {open_target.title()}.",
            tts_text=f"Opening {open_target.title()}.",
        )

    unknown_folder = _unknown_folder_path(open_target)
    if unknown_folder is not None:
        return LocalActionResult(
            status="handled",
            kind="folder",
            target=str(unknown_folder),
            message=f"Opening {unknown_folder}.",
            tts_text="Opening that folder.",
        )

    app_id, confidence, label = resolve_fuzzy_app(open_target)
    if confidence >= 1.0:
        return LocalActionResult(
            status="handled",
            kind="app",
            target=app_id,
            message=f"Opening {label}.",
            tts_text=f"Opening {label}.",
        )
    elif confidence >= 0.8:
        return LocalActionResult(
            status="pending_confirmation",
            kind="app",
            target=app_id,
            message=f"Did you mean {label}?",
            tts_text=f"Did you mean {label}?",
            permission="pending",
            pending_action={"command": f"open {app_id}", "canonical_name": label},
        )

    if open_target.startswith(("http://", "https://")):
        return LocalActionResult(
            status="handled",
            kind="url",
            target=open_target,
            message=f"Opening {open_target}.",
            tts_text="Opening that website.",
        )

    return LocalActionResult(status="no_match")


def _is_safe_desktop_operator_request(command: str) -> bool:
    return bool(
        re.fullmatch(r"open terminal in (vs\s*code|vscode|visual studio code)", command)
        or command
        in {
            "summarize current desktop state",
            "detect active app and suggest actions",
            "desktop operator diagnostics",
            "operator diagnostics",
        }
    )


def _parse_desktop_operator_action(command: str) -> LocalActionResult:
    if not _is_safe_desktop_operator_request(command):
        return LocalActionResult(status="no_match")
    try:
        from grandpa.desktop.operator import (
            active_app_actions,
            build_ui_navigation_plan,
            operator_diagnostics,
        )

        if command in {"desktop operator diagnostics", "operator diagnostics"}:
            diagnostics = operator_diagnostics()
            message = (
                "Desktop operator is ready with "
                f"{diagnostics.get('profile_count', 0)} app profile(s), bounded retries, and approval-gated risky actions."
            )
            return LocalActionResult(
                status="handled",
                kind="pc_control",
                target="desktop_operator|diagnostics",
                message=message,
                tts_text=message,
            )
        if command == "detect active app and suggest actions":
            actions = active_app_actions()
            suggestions = (
                ", ".join(actions.get("suggested_actions") or [])
                or "no app-specific suggestions"
            )
            message = f"Active app: {actions.get('active_app', 'unknown')}. Suggested actions: {suggestions}."
            return LocalActionResult(
                status="handled",
                kind="pc_control",
                target="desktop_operator|active_app",
                message=message,
                tts_text=message,
            )

        plan = build_ui_navigation_plan(command)
        task = plan.get("task", {})
        summary = str(task.get("result_summary") or "Prepared a desktop operator plan.")
        target = f"desktop_operator|{task.get('task_id', 'planned')}"
        if task.get("status") == "waiting_approval":
            return LocalActionResult(
                status="handled",
                kind="pc_control",
                target=target,
                message=summary,
                tts_text="Confirmation required for this desktop operator plan.",
                permission="requires_confirmation",
                pending_action={"operator_task": task},
            )
        if task.get("status") == "blocked":
            return LocalActionResult(
                status="blocked",
                kind="blocked",
                target=target,
                message=summary,
                tts_text=summary,
                permission="blocked",
            )
        return LocalActionResult(
            status="handled",
            kind="pc_control",
            target=target,
            message=summary,
            tts_text=summary,
        )
    except Exception as exc:
        logger.debug("Desktop operator routing failed: %s", exc, exc_info=True)
        return LocalActionResult(
            status="error",
            kind="pc_control",
            target="desktop_operator",
            message="Desktop operator is unavailable right now.",
            tts_text="Desktop operator is unavailable right now.",
        )


def _parse_user_skill_action(command: str) -> LocalActionResult:
    try:
        from grandpa.skill_builder import (
            create_user_skill,
            list_user_skills,
            run_user_skill,
        )

        if re.fullmatch(r"(list|show) (custom|user) skills", command):
            skills = list_user_skills(limit=20)["skills"]
            if not skills:
                message = "No custom user skills saved yet."
            else:
                names = ", ".join(skill["name"] for skill in skills[:8])
                message = f"Custom skills: {names}."
            return LocalActionResult(
                status="handled",
                kind="pc_control",
                target="user_skills|list",
                message=message,
                tts_text=message,
            )

        if re.match(
            r"^(create a skill called|remember this workflow|save this automation)",
            command,
        ):
            created = create_user_skill({"request": command})
            skill = created["skill"]
            message = f"Saved user skill '{skill['name']}' with {len(skill['workflow_steps'])} declarative step(s)."
            return LocalActionResult(
                status="handled",
                kind="pc_control",
                target=f"user_skill|{skill['skill_id']}",
                message=message,
                tts_text=message,
            )

        for skill in list_user_skills(limit=500)["skills"]:
            triggers = {
                str(item).strip().lower() for item in skill.get("trigger_phrases", [])
            }
            if (
                command in triggers
                or command == str(skill.get("name", "")).strip().lower()
            ):
                result = run_user_skill(
                    skill["skill_id"], params={"user_request": command}
                )
                return LocalActionResult(
                    status="handled"
                    if result["ok"]
                    else (
                        "requires_confirmation"
                        if result["status"] == "approval_required"
                        else "error"
                    ),
                    kind="pc_control",
                    target=f"user_skill|{skill['skill_id']}",
                    message=result["message"],
                    tts_text=result["message"],
                    permission="requires_confirmation"
                    if result["status"] == "approval_required"
                    else None,
                )
    except Exception as exc:
        logger.debug("User skill routing failed: %s", exc, exc_info=True)
        return LocalActionResult(status="no_match")
    return LocalActionResult(status="no_match")


def _route_with_action_modules(command: str) -> LocalActionResult | None:
    """Try decomposed low-risk action handlers before legacy parser branches."""
    try:
        from grandpa.actions import route_action

        return route_action(command)
    except Exception:
        logger.debug("Action module router failed; using legacy parser.", exc_info=True)
        return None


def _parse_pc_control_action(command: str) -> LocalActionResult:
    mapping = {
        "list monitors": ("list_monitors", "monitors"),
        "show monitors": ("list_monitors", "monitors"),
        "detect monitors": ("list_monitors", "monitors"),
        "what monitors are connected": ("list_monitors", "monitors"),
        "what process is active": ("active_process", "active"),
        "what app is active": ("active_process", "active"),
        "show active process": ("active_process", "active"),
        "list processes": ("list_processes", "processes"),
        "show running processes": ("list_processes", "processes"),
        "desktop summary": ("desktop_summary", "desktop"),
        "summarize desktop": ("desktop_summary", "desktop"),
        "pc control diagnostics": ("pc_diagnostics", "diagnostics"),
        "show pc diagnostics": ("pc_diagnostics", "diagnostics"),
        "inspect clipboard": ("clipboard_inspect", "clipboard"),
        "clipboard history": ("clipboard_history", "clipboard"),
        "show clipboard history": ("clipboard_history", "clipboard"),
    }
    if command not in mapping:
        return LocalActionResult(status="no_match")
    action_type, target = mapping[command]
    return LocalActionResult(
        status="handled",
        kind="pc_control",
        target=f"{action_type}|{target}",
        message="Checking PC control context.",
        tts_text="Checking PC control context.",
    )


def _parse_agent_plan_action(command: str) -> LocalActionResult:
    if any(
        phrase in command
        for phrase in (
            "set up my coding workspace",
            "setup my coding workspace",
            "start my coding workspace",
            "research python tutorials and summarize",
            "research python tutorials and summarise",
            "organize my downloads folder",
            "organise my downloads folder",
            "check grandpa readiness and report issues",
            "summarize current webpage and save notes",
            "summarise current webpage and save notes",
        )
    ):
        return LocalActionResult(
            status="handled",
            kind="agent_plan",
            target=command,
            message="Building a safe local execution plan.",
            tts_text="Building a safe local execution plan.",
        )
    return LocalActionResult(status="no_match")


def _parse_automation_action(command: str) -> LocalActionResult:
    match = re.fullmatch(r"type (.+?) in (notepad)", command)
    if match:
        text = match.group(1).strip()
        app = match.group(2).strip()
        return LocalActionResult(
            status="handled",
            kind="automation",
            target=f"focus|{app}||type|{text}",
            message=f'Typing "{text}" in {app.title()}.',
            tts_text=f"Typing that in {app.title()}.",
        )

    match = re.fullmatch(r"type (.+)", command)
    if match:
        text = match.group(1).strip()
        return LocalActionResult(
            status="handled",
            kind="automation",
            target=f"type|{text}",
            message=f'Typing "{text}".',
            tts_text="Typing that.",
        )

    press_map = {
        "press enter": ("press|enter", "Pressed enter."),
        "press tab": ("press|tab", "Pressed tab."),
        "press escape": ("press|escape", "Pressed escape."),
        "press esc": ("press|escape", "Pressed escape."),
    }
    if command in press_map:
        target, message = press_map[command]
        return LocalActionResult(
            status="handled",
            kind="automation",
            target=target,
            message=message,
            tts_text=message,
        )

    if command in {"scroll down", "scroll up"}:
        direction = "down" if command.endswith("down") else "up"
        message = f"Scrolled {direction}."
        return LocalActionResult(
            status="handled",
            kind="automation",
            target=f"scroll|{direction}",
            message=message,
            tts_text=message,
        )

    if command in {"copy selected text", "copy selection"}:
        return LocalActionResult(
            status="handled",
            kind="automation",
            target="hotkey|ctrl+c",
            message="Copied the selected text.",
            tts_text="Copied the selected text.",
        )

    if command == "paste":
        return LocalActionResult(
            status="handled",
            kind="automation",
            target="hotkey|ctrl+v",
            message="Pasted from the clipboard.",
            tts_text="Pasted from the clipboard.",
        )

    if command == "switch window":
        return LocalActionResult(
            status="handled",
            kind="automation",
            target="hotkey|alt+tab",
            message="Switched window.",
            tts_text="Switched window.",
        )

    if command == "focus chrome":
        return LocalActionResult(
            status="handled",
            kind="automation",
            target="focus|chrome",
            message="Trying to focus Chrome.",
            tts_text="Trying to focus Chrome.",
        )

    if command == "click the center of the screen":
        return LocalActionResult(
            status="handled",
            kind="automation",
            target="click_center",
            message="Clicked the center of the screen.",
            tts_text="Clicked the center of the screen.",
        )

    if command == "move mouse to center":
        return LocalActionResult(
            status="handled",
            kind="automation",
            target="move_center",
            message="Moved the mouse to the center of the screen.",
            tts_text="Moved the mouse to the center.",
        )

    if command == "click the highlighted button":
        return LocalActionResult(
            status="handled",
            kind="automation",
            target="click_highlighted",
            message="Clicking highlighted buttons is not enabled yet.",
            tts_text="Highlighted button clicking is not enabled yet.",
        )

    return LocalActionResult(status="no_match")


def _parse_window_action(command: str) -> LocalActionResult:
    if command in {"list open windows", "what windows are open", "show open windows"}:
        return LocalActionResult(
            status="handled",
            kind="window",
            target="list|windows",
            message="Checking open windows.",
            tts_text="Checking open windows.",
        )

    # First check for active window actions
    match = re.fullmatch(r"(minimize|maximize|restore|close) active window", command)
    if match:
        action = match.group(1)
        return LocalActionResult(
            status="handled",
            kind="window",
            target=f"{action}|active",
            message=_window_pending_message(action, "active"),
            tts_text=_window_tts(action, "active"),
        )

    # General window target action
    match = re.fullmatch(r"(focus|minimize|maximize|restore|close)\s+(.+)", command)
    if match:
        action = match.group(1)
        raw_target = match.group(2).strip()
        if raw_target != "active" and raw_target != "active window":
            app_id, confidence, label = resolve_fuzzy_app(raw_target)
            if confidence >= 1.0:
                return LocalActionResult(
                    status="handled",
                    kind="window",
                    target=f"{action}|{app_id}",
                    message=_window_pending_message(action, app_id),
                    tts_text=_window_tts(action, app_id),
                )
            elif confidence >= 0.8:
                return LocalActionResult(
                    status="pending_confirmation",
                    kind="window",
                    target=f"{action}|{app_id}",
                    message=f"Did you mean {label}?",
                    tts_text=f"Did you mean {label}?",
                    permission="pending",
                    pending_action={
                        "command": f"{action} {app_id}",
                        "canonical_name": label,
                    },
                )
            else:
                return LocalActionResult(status="no_match")

    return LocalActionResult(status="no_match")


def _window_app_id(target: str) -> str:
    if target in {"vs code", "visual studio code"}:
        return "vscode"
    if target == "file explorer":
        return "explorer"
    if target == "control panel":
        return "control_panel"
    if target == "task manager":
        return "task_manager"
    return target


def _window_pending_message(action: str, target: str) -> str:
    label = "the active window" if target == "active" else _window_label(target)
    if action == "close":
        return f"Close {label}."
    return f"{action.title()} {label}."


def _window_tts(action: str, target: str) -> str:
    label = "the active window" if target == "active" else _window_label(target)
    if action == "close":
        return f"Close {label}."
    return f"{action.title()} {label}."


def _window_label(target: str) -> str:
    if target == "vscode":
        return "VS Code"
    return target.title()


def _parse_screen_action(command: str) -> LocalActionResult:
    if command in {
        "take a screenshot",
        "screenshot",
        "capture screen",
        "capture screenshot",
    }:
        return LocalActionResult(
            status="handled",
            kind="screenshot",
            target="screen",
            message="Taking a screenshot.",
            tts_text="Taking a screenshot.",
        )

    if command in {
        "screen diagnostics",
        "show screen diagnostics",
        "visual diagnostics",
        "visual targeting diagnostics",
        "show visual diagnostics",
        "visual automation diagnostics",
        "screen awareness diagnostics",
    }:
        return LocalActionResult(
            status="handled",
            kind="screen",
            target="visual_diagnostics"
            if "visual" in command
            else "screen_diagnostics",
            message="Checking visual targeting diagnostics."
            if "visual" in command
            else "Checking screen-awareness diagnostics.",
            tts_text="Checking visual diagnostics."
            if "visual" in command
            else "Checking screen diagnostics.",
        )

    if command in {
        "what window is open",
        "what window is open right now",
        "what app is open",
        "what browser tab am i on",
        "what tab am i on",
    }:
        return LocalActionResult(
            status="handled",
            kind="screen",
            target="active_window",
            message="Checking the active window.",
            tts_text="Checking the active window.",
        )

    if command in {
        "what is on my screen",
        "read my screen",
        "analyze my screen",
        "describe my screen",
        "screen analysis",
        "what's on my screen",
        "read this error message",
        "read the error message",
        "summarize this page",
        "summarise this page",
        "analyze current screen",
        "analyse current screen",
    }:
        return LocalActionResult(
            status="handled",
            kind="screen",
            target="screen_context",
            message="Analyzing the current screen.",
            tts_text="Analyzing the current screen.",
        )

    return LocalActionResult(status="no_match")


def _parse_browser_action(command: str) -> LocalActionResult:
    if command in {
        "what page am i on",
        "what webpage am i on",
        "what browser page am i on",
    }:
        return LocalActionResult(
            status="handled",
            kind="browser",
            target="context|active",
            message="Checking the active browser page.",
            tts_text="Checking the active browser page.",
        )

    if command in {
        "what tabs are open",
        "what browser tabs are open",
        "list browser tabs",
    }:
        return LocalActionResult(
            status="handled",
            kind="browser",
            target="tabs|recent",
            message="Checking recent browser tabs.",
            tts_text="Checking recent browser tabs.",
        )

    if command in {"browser diagnostics", "show browser diagnostics", "browser status"}:
        return LocalActionResult(
            status="handled",
            kind="browser",
            target="diagnostics|browser",
            message="Checking browser diagnostics.",
            tts_text="Checking browser diagnostics.",
        )

    if command in {
        "play video",
        "pause video",
        "play youtube",
        "pause youtube",
        "mute video",
        "unmute video",
    }:
        action = command.replace("youtube", "video")
        return LocalActionResult(
            status="handled",
            kind="browser",
            target=f"media|{action}",
            message=f"{action.title()}.",
            tts_text=f"{action.title()}.",
        )

    fill_match = re.fullmatch(r"fill (?:the )?(.+?) (?:field )?with (.+)", command)
    if fill_match:
        field = fill_match.group(1).strip()
        value = fill_match.group(2).strip()
        return LocalActionResult(
            status="handled",
            kind="browser",
            target=f"form_fill|{field}={value}",
            message=f"Fill {field}.",
            tts_text=f"Fill {field}.",
        )

    if command in {
        "download this file",
        "download selected file",
        "download this page file",
    }:
        return LocalActionResult(
            status="handled",
            kind="browser",
            target="download|visible selection",
            message="Prepare browser download.",
            tts_text="Prepare browser download.",
        )

    task_match = re.fullmatch(r"(?:remember|continue|track) browser task (.+)", command)
    if task_match:
        return LocalActionResult(
            status="handled",
            kind="browser",
            target=f"task|{task_match.group(1).strip()}",
            message="Recording browser task context.",
            tts_text="Recording browser task context.",
        )

    if command in {
        "summarize this webpage",
        "summarise this webpage",
        "summarize current webpage",
        "summarize this web page",
        "summarize this page",
        "summarise this page",
    }:
        return LocalActionResult(
            status="handled",
            kind="browser",
            target="summary|visible",
            message="Summarizing the visible webpage.",
            tts_text="Summarizing the visible webpage.",
        )

    if command in {
        "read the visible headings",
        "read visible headings",
        "what headings are visible",
    }:
        return LocalActionResult(
            status="handled",
            kind="browser",
            target="headings|visible",
            message="Reading visible browser headings.",
            tts_text="Reading visible browser headings.",
        )

    if command in {
        "show links on this page",
        "show page links",
        "what links are visible",
        "read visible links",
    }:
        return LocalActionResult(
            status="handled",
            kind="browser",
            target="links|visible",
            message="Reading visible browser links.",
            tts_text="Reading visible browser links.",
        )

    if command in {
        "what buttons are visible",
        "what buttons are visible?",
        "show visible buttons",
        "read visible buttons",
    }:
        return LocalActionResult(
            status="handled",
            kind="browser",
            target="buttons|visible",
            message="Reading visible browser buttons.",
            tts_text="Reading visible browser buttons.",
        )

    if command in {
        "focus the search box",
        "focus search box",
        "focus the browser search box",
    }:
        return LocalActionResult(
            status="handled",
            kind="browser",
            target="focus_search|visible",
            message="Focusing the visible browser search box.",
            tts_text="Focusing the visible browser search box.",
        )

    if command in {"click the first video", "click first video"}:
        return LocalActionResult(
            status="handled",
            kind="browser",
            target="click|first video",
            message="Clicking the first visible video.",
            tts_text="Clicking the first visible video.",
        )

    if command in {"browser back", "go back", "back in browser"}:
        return LocalActionResult(
            status="handled",
            kind="browser",
            target="back|visible",
            message="Going back in the visible browser.",
            tts_text="Going back in the visible browser.",
        )

    if command in {"browser forward", "go forward", "forward in browser"}:
        return LocalActionResult(
            status="handled",
            kind="browser",
            target="forward|visible",
            message="Going forward in the visible browser.",
            tts_text="Going forward in the visible browser.",
        )

    if command in {"reload browser", "reload page", "refresh page"}:
        return LocalActionResult(
            status="handled",
            kind="browser",
            target="reload|visible",
            message="Reloading the visible browser page.",
            tts_text="Reloading the visible browser page.",
        )

    match = re.fullmatch(r"search google for (.+)", command)
    if match:
        query = match.group(1).strip()
        url = "https://www.google.com/search?q=" + urllib.parse.quote_plus(query)
        return LocalActionResult(
            status="handled",
            kind="browser",
            target=url,
            message=f"Searching Google for {query}.",
            tts_text=f"Searching Google for {query}.",
        )

    match = re.fullmatch(r"search (?!google for\b)(?!youtube for\b)(.+)", command)
    if match:
        query = match.group(1).strip()
        url = "https://www.google.com/search?q=" + urllib.parse.quote_plus(query)
        return LocalActionResult(
            status="handled",
            kind="browser",
            target=url,
            message=f"Searching Google for {query}.",
            tts_text=f"Searching Google for {query}.",
        )

    match = re.fullmatch(r"open youtube and search for (.+)", command)
    if match:
        query = match.group(1).strip()
        url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(
            query
        )
        return LocalActionResult(
            status="handled",
            kind="browser",
            target=url,
            message=f"Opening YouTube and searching for {query}.",
            tts_text=f"Opening YouTube and searching for {query}.",
        )

    match = re.fullmatch(r"open youtube and search (.+)", command)
    if match:
        query = match.group(1).strip()
        url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(
            query
        )
        return LocalActionResult(
            status="handled",
            kind="browser",
            target=url,
            message=f"Opening YouTube and searching for {query}.",
            tts_text=f"Opening YouTube and searching for {query}.",
        )

    if command in {"open a new tab", "new tab", "open new tab"}:
        return LocalActionResult(
            status="handled",
            kind="browser",
            target="about:blank",
            message="Opening a new browser tab.",
            tts_text="Opening a new browser tab.",
        )

    return LocalActionResult(status="no_match")


def _strip_open_prefix(command: str) -> str | None:
    for prefix in ("open my ", "open ", "launch ", "start ", "show my ", "show "):
        if command.startswith(prefix):
            return command[len(prefix) :].strip()
    return None


def _unknown_folder_path(target: str) -> Path | None:
    if re.match(r"^[a-z]:[\\/]", target, re.I):
        return Path(target)
    if target.startswith(("~\\", "~/")):
        return Path.home() / target[2:]
    return None


def _folder_for(target: str) -> Path | None:
    if target in {"downloads", "downloads folder", "download folder"}:
        return Path.home() / "Downloads"
    if target in {"d drive", "d:", "d drive folder", "d folder"}:
        return Path("D:\\")
    return None


def _system_info_message() -> str:
    lines = [
        "Basic system info:",
        f"- OS: {platform.platform()}",
        f"- Machine: {platform.machine() or 'unknown'}",
        f"- Processor: {platform.processor() or 'unknown'}",
        f"- Python: {platform.python_version()}",
    ]
    return "\n".join(lines)


def _execute(result: LocalActionResult) -> LocalActionResult:
    if result.kind == "time" or result.kind == "system_info":
        return result

    registry_result = _execute_runtime_skill(result)
    if registry_result is not None:
        return registry_result

    if result.kind == "app_lookup":
        from grandpa.windows_app_resolver import describe_app, list_installed_apps

        if result.target == "installed_apps":
            apps = list_installed_apps()
            if apps and all(app["status"] == "unsupported" for app in apps):
                return LocalActionResult(
                    status="unsupported",
                    kind="app_lookup",
                    target=result.target,
                    message="Windows app discovery is only supported on Windows desktop.",
                    tts_text="Windows app discovery is only supported on Windows desktop.",
                )
            lines = ["Installed app resolver:"]
            for app in apps:
                status = app["status"]
                target = app["launch_target"] or app["message"]
                lines.append(f"- {app['display_name']}: {status} ({target})")
            return LocalActionResult(
                status="handled",
                kind="app_lookup",
                target=result.target,
                message="\n".join(lines),
                tts_text="Here are the installed app results.",
            )

        message = describe_app(result.target)
        status = "unsupported" if "only supported on Windows" in message else "handled"
        return LocalActionResult(
            status=status,
            kind="app_lookup",
            target=result.target,
            message=message,
            tts_text=message,
        )

    if result.kind == "screen":
        from grandpa.screen_awareness import (
            describe_screen,
            get_active_window_info,
            screen_diagnostics,
        )

        if result.target == "active_window":
            info = get_active_window_info()
            if info.supported:
                title = info.window_title or "Unknown window"
                app = f" ({info.app_name})" if info.app_name else ""
                message = f"The active window is: {title}{app}."
                return LocalActionResult(
                    status="handled",
                    kind="screen",
                    target=result.target,
                    message=message,
                    tts_text=message,
                )
            return LocalActionResult(
                status="unsupported",
                kind="screen",
                target=result.target,
                message=info.message,
                tts_text=info.message,
            )

        if result.target == "screen_diagnostics":
            diagnostics = screen_diagnostics()
            screenshot = diagnostics.get("screenshot", {})
            ocr = diagnostics.get("ocr", {})
            active = diagnostics.get("active_window", {})
            message = (
                "Screen awareness diagnostics:\n"
                f"- Platform: {diagnostics.get('platform')}\n"
                f"- Active window: {'ready' if active.get('supported') else 'unavailable'}\n"
                f"- Screenshot backends: {', '.join(screenshot.get('backends') or []) or 'none'}\n"
                f"- OCR backend: {ocr.get('backend') or 'unavailable'}\n"
                f"- Visible windows: {diagnostics.get('visible_window_count', 0)}\n"
                "- Local only: yes"
            )
            return LocalActionResult(
                status="handled" if diagnostics.get("supported") else "unsupported",
                kind="screen",
                target=result.target,
                message=message,
                tts_text="Screen diagnostics are ready.",
            )

        info = describe_screen(include_ocr=True)
        return LocalActionResult(
            status="handled" if info.supported else "unsupported",
            kind="screen",
            target=result.target,
            message=info.message,
            tts_text="Here is what I can see on the screen.",
        )

    if result.kind == "screenshot":
        from grandpa.screen_awareness import capture_screenshot

        info = capture_screenshot()
        return LocalActionResult(
            status="handled" if info.supported else "unsupported",
            kind="screenshot",
            target=info.screenshot_path or result.target,
            message=info.message,
            tts_text="Screenshot captured." if info.supported else info.message,
        )

    if result.kind == "automation":
        from grandpa.desktop_automation import execute_automation

        automation = execute_automation(result.target)
        return LocalActionResult(
            status=automation.status,
            kind="automation",
            target=result.target,
            message=automation.message,
            tts_text=automation.tts_text or automation.message,
        )

    if result.kind == "window":
        from grandpa.windows_window_control import control_window, list_open_windows

        action, _, target = result.target.partition("|")
        if action == "list":
            window_result = list_open_windows()
        else:
            window_result = control_window(action, target or "active")
        status = {
            "handled": "handled",
            "blocked": "blocked",
            "unsupported": "unsupported",
            "not_found": "handled",
            "multiple_matches": "handled",
            "error": "error",
        }.get(window_result.status, "error")
        return LocalActionResult(
            status=status,
            kind="window",
            target=result.target,
            message=window_result.message,
            tts_text=window_result.message,
            permission=result.permission,
        )

    if result.kind == "pc_control":
        from grandpa.pc_control import run_local_action

        action_type, _, target = result.target.partition("|")
        response = run_local_action({"action_type": action_type, "target": target})
        return LocalActionResult(
            status="handled"
            if response.ok
            else response.status
            if response.status in {"blocked", "unsupported"}
            else "error",
            kind="pc_control",
            target=result.target,
            message=response.message,
            tts_text=response.message,
            permission=result.permission,
        )

    if result.kind == "agent_plan":
        from grandpa.agents.goal_mode import create_goal

        goal = create_goal(result.target, execute=True)
        analysis = goal.plan
        lines = [
            f"Agent plan goal {goal.status}: {analysis.get('intent', 'local goal')}.",
            f"- Phase: {goal.current_phase}",
            f"- Confidence: {float(analysis.get('confidence', 0.0)):.0%}",
            f"- Risk: {analysis.get('estimated_risk', 'LOW')}",
            f"- Skills: {', '.join(analysis.get('required_skills', [])) or 'none'}",
            f"- Actions taken: {len(goal.actions_taken)}",
        ]
        if goal.approvals_needed:
            lines.append(
                f"- Approval needed: {', '.join(item.get('step_id', '') for item in goal.approvals_needed)}"
            )
        if goal.result_summary:
            lines.append(goal.result_summary)
        else:
            lines.append(
                str(
                    analysis.get(
                        "reasoning_summary", "Grandpa prepared a safe local goal plan."
                    )
                )
            )
        return LocalActionResult(
            status="handled"
            if goal.status not in {"failed", "cancelled"}
            else "unsupported",
            kind="agent_plan",
            target=goal.goal_id,
            message="\n".join(lines),
            tts_text="I processed the autonomous goal safely.",
            permission=result.permission,
        )

    if result.kind == "app":
        from grandpa.windows_app_resolver import launch_app

        launched = launch_app(result.target)
        if launched.status == "found":
            return LocalActionResult(
                status="handled",
                kind="app",
                target=launched.launch_target,
                message=f"{launched.display_name} opened.",
                tts_text=f"{launched.display_name} opened.",
            )
        status = "unsupported" if launched.status == "unsupported" else "error"
        return LocalActionResult(
            status=status,
            kind="app",
            target=result.target,
            message=launched.message,
            tts_text=launched.message,
        )

    if result.kind == "chrome_profile":
        msg = run_chrome_profile_selection(result.target)
        status = "handled" if "selected" in msg or "opened" in msg else "error"
        if "Which Chrome profile do you mean" in msg:
            status = "ambiguous"
        return LocalActionResult(
            status=status,
            kind="chrome_profile",
            target=result.target,
            message=msg,
            tts_text=msg,
        )

    if result.kind == "folder":
        path = Path(result.target)
        if not path.exists():
            return LocalActionResult(
                status="error",
                kind="folder",
                target=result.target,
                message=f"I could not find {result.target}.",
                tts_text="I could not find that folder.",
            )
        os.startfile(path)  # type: ignore[attr-defined]  # noqa: S606
        return result

    if result.kind == "url":
        webbrowser.open(result.target)
        return result

    if result.kind == "browser":
        from grandpa.browser_control import execute_browser_action

        if "|" in result.target:
            action, _, target = result.target.partition("|")
            browser_result = execute_browser_action(action, target)
        elif result.target == "about:blank":
            browser_result = execute_browser_action("new_tab", result.target)
        elif "youtube.com/results" in result.target:
            parsed = urllib.parse.urlparse(result.target)
            query = urllib.parse.parse_qs(parsed.query).get("search_query", [""])[0]
            browser_result = execute_browser_action("youtube_search", query)
        elif "google.com/search" in result.target:
            parsed = urllib.parse.urlparse(result.target)
            query = urllib.parse.parse_qs(parsed.query).get("q", [""])[0]
            browser_result = execute_browser_action("search", query)
        else:
            browser_result = execute_browser_action("open", result.target)
        return LocalActionResult(
            status=browser_result.status,
            kind="browser",
            target=result.target,
            message=browser_result.message,
            tts_text=browser_result.message,
            permission=result.permission,
        )

    return result


def _execute_runtime_skill(result: LocalActionResult) -> LocalActionResult | None:
    """Delegate migrated read-only actions to the runtime skill registry."""
    skill_name = ""
    params: dict[str, Any] = {}
    if result.kind == "pc_control":
        action_type, _, target = result.target.partition("|")
        skill_name = {
            "desktop_summary": "desktop.summary",
            "list_monitors": "desktop.monitors",
            "pc_diagnostics": "desktop.diagnostics",
            "workflow_status": "automation.workflow_status",
            "runtime_skill": target,
        }.get(action_type, "")
        params = {"target": target}
    elif result.kind == "browser" and result.target == "diagnostics|browser":
        skill_name = "browser.diagnostics"
    elif result.kind == "screen" and result.target in {
        "screen_diagnostics",
        "visual_diagnostics",
    }:
        skill_name = (
            "vision.visual_diagnostics"
            if result.target == "visual_diagnostics"
            else "vision.screen_diagnostics"
        )

    if not skill_name:
        return None

    try:
        from grandpa.skills.registry import (
            ensure_default_skills_registered,
            execute_skill,
        )
        from grandpa.skills.runtime import SkillExecutionContext

        ensure_default_skills_registered()
        skill_result = execute_skill(
            skill_name,
            params,
            SkillExecutionContext(
                user_request=result.message,
                source="local_actions",
                dry_run=False,
            ),
        )
    except Exception:
        logger.debug(
            "Runtime skill delegation failed for %s", skill_name, exc_info=True
        )
        return None

    status: ActionStatus = (
        "handled"
        if skill_result.ok
        else (
            "unsupported"
            if skill_result.status == "unsupported"
            else "blocked"
            if skill_result.status == "blocked"
            else "error"
        )
    )
    return LocalActionResult(
        status=status,
        kind=result.kind,
        target=result.target,
        message=skill_result.message,
        tts_text=skill_result.message,
        permission=result.permission,
    )


def _log_attempt(command: str, result: LocalActionResult) -> None:
    logger.info(
        "local_action_attempt command=%r status=%s kind=%s target=%r",
        command,
        result.status,
        result.kind,
        result.target,
    )
    try:
        from grandpa.memory_context import record_activity

        action = "blocked" if result.status == "blocked" else "open"
        if result.kind in {
            "time",
            "system_info",
            "screen",
            "screenshot",
            "automation",
            "window",
            "pc_control",
        }:
            action = result.kind
        record_activity(
            result.kind if result.kind != "blocked" else "safety",
            action,
            result.target,
            command,
            result.status,
        )
    except Exception:
        logger.debug("Failed to record local action activity", exc_info=True)


def run_chrome_profile_selection(profile_name: str) -> str:
    """Detect and select the requested Chrome profile from the 'Who's using Chrome?' screen."""
    if sys.platform != "win32":
        return "Chrome profile selection is only supported on Windows."

    import time
    from difflib import SequenceMatcher

    from grandpa.windows_window_control import _list_windows, control_window

    # 1. Find the Chrome profile chooser window
    chooser_window = None
    for w in _list_windows():
        w_title = w.title.lower() if w.title else ""
        if "who's using chrome" in w_title or "whos using chrome" in w_title:
            chooser_window = w
            break

    if not chooser_window:
        return "I could not find the Chrome profile chooser window."

    # 2. Focus it
    try:
        control_window("focus", chooser_window.title)
    except Exception:
        pass

    # Give a tiny fraction of a second to settle
    time.sleep(0.2)

    # 3. Build vision graph
    try:
        from grandpa.vision.service import VisionEngine

        engine = VisionEngine()
        inspect_res = engine.inspect(active_window=True)
        graph = inspect_res.graph
    except Exception as exc:
        return f"Could not inspect the screen to find Chrome profiles: {exc}"

    if not graph or not graph.nodes:
        return "No visible elements were found in the Chrome window."

    # 4. Find matching profile cards
    matches = []
    seen_labels = set()
    for node in graph.nodes:
        if not node.visible:
            continue
        label = node.label.strip()
        if not label:
            continue
        if label.lower() in {
            "who's using chrome?",
            "browse as guest",
            "guest",
            "add",
            "close",
            "minimize",
            "maximize",
            "add profile",
            "customize your chrome profile",
            "who's using chrome",
        }:
            continue

        ratio = SequenceMatcher(None, profile_name.lower(), label.lower()).ratio()
        if ratio >= 0.85 or profile_name.lower() in label.lower():
            if label not in seen_labels:
                seen_labels.add(label)
                matches.append((node, ratio, label))

    if not matches:
        return f"I could not find a Chrome profile named {profile_name}."

    if len(matches) > 1:
        # Check if they are distinct names
        return "Which Chrome profile do you mean?"

    # 5. Click the single matching profile card
    node, ratio, matched_label = matches[0]
    x, y = node.bounds.center

    try:
        from grandpa.automation.service import get_automation_service

        service = get_automation_service()
        service.handle(f"click at {x} {y}", target_window=chooser_window.title)
    except Exception as exc:
        return f"Failed to automate click on the profile card: {exc}"

    # 6. Verify selection success by waiting for chooser to close or browser window to open
    start_time = time.time()
    while time.time() - start_time < 5.0:
        # Check if chooser disappeared
        chooser_exists = False
        browser_exists = False
        for w in _list_windows():
            w_title = w.title.lower() if w.title else ""
            if "who's using chrome" in w_title or "whos using chrome" in w_title:
                chooser_exists = True
            elif "chrome" in w_title or "google chrome" in w_title:
                browser_exists = True

        if not chooser_exists or browser_exists:
            return f"Chrome profile {matched_label} selected."
        time.sleep(0.2)

    return "I found the profile card, but clicking it did not open Chrome."


__all__ = [
    "BLOCKED_MESSAGE",
    "LocalActionResult",
    "approve_pending_action",
    "classify_permission",
    "deny_pending_action",
    "handle_local_action",
]
