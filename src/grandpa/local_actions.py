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
import subprocess
import sys
import urllib.parse
import webbrowser
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

ActionStatus = Literal["handled", "blocked", "unsupported", "no_match", "error"]
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
    "blocked",
]

BLOCKED_MESSAGE = "I blocked this action for safety."


@dataclass(frozen=True)
class LocalActionResult:
    status: ActionStatus
    kind: ActionKind | None = None
    target: str = ""
    message: str = ""
    tts_text: str = ""

    @property
    def should_fallback(self) -> bool:
        return self.status == "no_match"


_APP_ALLOWLIST: dict[str, tuple[str, str]] = {
    "notepad": ("notepad.exe", "Notepad"),
    "calculator": ("calc.exe", "Calculator"),
    "calc": ("calc.exe", "Calculator"),
    "chrome": ("chrome.exe", "Chrome"),
    "google chrome": ("chrome.exe", "Chrome"),
    "edge": ("msedge.exe", "Microsoft Edge"),
    "microsoft edge": ("msedge.exe", "Microsoft Edge"),
    "vs code": ("code", "VS Code"),
    "vscode": ("code", "VS Code"),
    "visual studio code": ("code", "VS Code"),
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

    if _is_dangerous(command):
        result = LocalActionResult(
            status="blocked",
            kind="blocked",
            target=command,
            message=BLOCKED_MESSAGE,
            tts_text=BLOCKED_MESSAGE,
        )
        _log_attempt(command, result)
        return result

    result = _parse_safe_action(command)
    if result.status == "no_match":
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
        )
        _log_attempt(command, unsupported)
        return unsupported

    try:
        executed = _execute(result)
    except Exception as exc:  # pragma: no cover - defensive edge
        executed = LocalActionResult(
            status="error",
            kind=result.kind,
            target=result.target,
            message=f"I could not complete that local action: {exc}",
            tts_text="I could not complete that local action.",
        )

    _log_attempt(command, executed)
    return executed


def _normalise(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[?!.\s]+$", "", text)
    text = re.sub(r"\s+", " ", text)
    return text


def _is_dangerous(command: str) -> bool:
    return any(re.search(pattern, command) for pattern in _DANGEROUS_PATTERNS)


def _parse_safe_action(command: str) -> LocalActionResult:
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

    if open_target in _APP_ALLOWLIST:
        executable, label = _APP_ALLOWLIST[open_target]
        return LocalActionResult(
            status="handled",
            kind="app",
            target=executable,
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

    if result.kind == "app":
        subprocess.Popen([result.target], shell=False)  # noqa: S603
        return result

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
        if result.kind in {"time", "system_info", "screen", "screenshot", "automation"}:
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


__all__ = ["BLOCKED_MESSAGE", "LocalActionResult", "handle_local_action"]
