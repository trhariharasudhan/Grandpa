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

_URL_ALLOWLIST: dict[str, tuple[str, str]] = {
    "youtube": ("https://www.youtube.com", "YouTube"),
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

    result = _parse_safe_action(command)
    if result.status == "no_match":
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
    permission = classify_permission(command, result)
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
    text = text.strip().lower()
    text = re.sub(r"[?!.\s]+$", "", text)
    text = re.sub(r"\s+", " ", text)
    return text


def _is_dangerous(command: str) -> bool:
    return any(re.search(pattern, command) for pattern in _DANGEROUS_PATTERNS)


def _parse_safe_action(command: str) -> LocalActionResult:
    window_result = _parse_window_action(command)
    if window_result.status != "no_match":
        return window_result

    screen_result = _parse_screen_action(command)
    if screen_result.status != "no_match":
        return screen_result

    browser_result = _parse_browser_action(command)
    if browser_result.status != "no_match":
        return browser_result

    automation_result = _parse_automation_action(command)
    if automation_result.status != "no_match":
        return automation_result

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

    if open_target in _APP_ALLOWLIST:
        app_id, label = _APP_ALLOWLIST[open_target]
        return LocalActionResult(
            status="handled",
            kind="app",
            target=app_id,
            message=f"Opening {label}.",
            tts_text=f"Opening {label}.",
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


def _parse_automation_action(command: str) -> LocalActionResult:
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

    match = re.fullmatch(
        r"(focus|minimize|maximize|restore|close) "
        r"(notepad|chrome|edge|vs code|vscode|visual studio code|calculator|"
        r"file explorer|explorer|settings|control panel|task manager)",
        command,
    )
    if match:
        action = match.group(1)
        target = _window_app_id(match.group(2))
        return LocalActionResult(
            status="handled",
            kind="window",
            target=f"{action}|{target}",
            message=_window_pending_message(action, target),
            tts_text=_window_tts(action, target),
        )

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

    match = re.fullmatch(r"open youtube and search for (.+)", command)
    if match:
        query = match.group(1).strip()
        url = (
            "https://www.youtube.com/results?search_query="
            + urllib.parse.quote_plus(query)
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
        url = (
            "https://www.youtube.com/results?search_query="
            + urllib.parse.quote_plus(query)
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
    for prefix in ("open ", "launch ", "start "):
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
        from grandpa.screen_awareness import describe_screen, get_active_window_info

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

    if result.kind == "app":
        from grandpa.windows_app_resolver import launch_app

        launched = launch_app(result.target)
        if launched.status == "found":
            return LocalActionResult(
                status="handled",
                kind="app",
                target=launched.launch_target,
                message=f"Opening {launched.display_name}.",
                tts_text=f"Opening {launched.display_name}.",
            )
        status = "unsupported" if launched.status == "unsupported" else "error"
        return LocalActionResult(
            status=status,
            kind="app",
            target=result.target,
            message=launched.message,
            tts_text=launched.message,
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
        if result.target == "about:blank":
            webbrowser.open_new_tab(result.target)
        else:
            webbrowser.open(result.target)
        return result

    return result


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


__all__ = [
    "BLOCKED_MESSAGE",
    "LocalActionResult",
    "approve_pending_action",
    "classify_permission",
    "deny_pending_action",
    "handle_local_action",
]
