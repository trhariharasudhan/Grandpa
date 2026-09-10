"""Voice Operator Mode for command-first desktop control."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from grandpa.desktop.applications import names_one_application
from grandpa.pc_control import run_local_action
from grandpa.voice.errors import (
    MicrophoneUnavailableError,
    VoiceDependencyError,
    VoiceError,
    VoiceOutputUnavailableError,
    VoiceRecognitionError,
)
from grandpa.voice.speech_output import SpeechOutputEngine

OperatorStatus = Literal[
    "handled",
    "blocked",
    "target_lost",
    "ambiguous",
    "dialog_pending",
    "cancelled",
    "unsupported",
    "exit",
    "error",
]


@dataclass(frozen=True)
class VoiceOperatorIntent:
    kind: str
    action: str = ""
    target: str = ""
    args: dict[str, Any] | None = None
    requires_confirmation: bool = False
    status: OperatorStatus = "handled"
    message: str = ""


@dataclass(frozen=True)
class VoiceOperatorResult:
    status: OperatorStatus
    message: str
    spoken_text: str
    action: dict[str, Any] | None = None
    requires_confirmation: bool = False


APP_ALIASES = {
    "chrome": "chrome",
    "google chrome": "chrome",
    "edge": "edge",
    "microsoft edge": "edge",
    "vscode": "vscode",
    "vs code": "vscode",
    "visual studio code": "vscode",
    "notepad": "notepad",
    "note pad": "notepad",
    "node pad": "notepad",
    "note bad": "notepad",
    "node bad": "notepad",
    "the pad": "notepad",
    "calculator": "calculator",
    "calc": "calculator",
    "file explorer": "file explorer",
    "explorer": "file explorer",
}
KEY_ALIASES = {
    "enter": "enter",
    "return": "enter",
    "escape": "esc",
    "esc": "esc",
    "tab": "tab",
}
DANGEROUS_PATTERNS = (
    r"\bdelete all\b",
    r"\bformat\b",
    r"\bshutdown\b",
    r"\brestart\b",
    r"\bpowershell\b",
    r"\bcmd\b",
    r"\bshell\b",
    r"\brun command\b",
)
LAUNCH_WORDS = {"start", "launch", "run"}
APP_PHRASE_ALIASES = {
    "google chrome browser": "chrome",
    "chrome browser": "chrome",
    "visual studio code": "vscode",
    "vs code": "vscode",
    "note bad": "notepad",
    "node bad": "notepad",
    "note pad": "notepad",
    "node pad": "notepad",
    "the pad": "notepad",
}


def is_dangerous_command(text: str) -> bool:
    """Whether *text* matches a pattern that must never reach an executor.

    Both the spoken words and their normalised form are checked. Normalisation
    rewrites the launch verbs -- "run" becomes "open" -- so "run command"
    reached this check as "open command" and slipped past the ``run command``
    pattern entirely, ending up as an attempt to launch an application called
    "command". Reading the raw text as well closes that without touching the
    pattern list, and it can only ever add matches, never remove one.
    """
    raw = str(text or "").strip().casefold()
    normalized = normalize_voice_operator_transcript(text)
    return any(
        re.search(pattern, candidate)
        for pattern in DANGEROUS_PATTERNS
        for candidate in (normalized, raw)
        if candidate
    )


def parse_voice_operator_command(
    text: str,
    *,
    has_pending_confirmation: bool | Callable[[], bool] = False,
    has_pending_window_choice: bool | Callable[[], bool] = False,
    has_pending_dialog: bool | Callable[[], bool] = False,
) -> VoiceOperatorIntent:
    raw_command = str(text).strip()
    command = normalize_voice_operator_transcript(text)
    if not command:
        return VoiceOperatorIntent(
            "none", status="unsupported", message="I did not hear a command."
        )
    from grandpa.voice.cli_session import is_exit_phrase

    if (
        is_exit_phrase(raw_command)
        or is_exit_phrase(command)
        or command in {"stop listening", "exit", "quit"}
    ):
        return VoiceOperatorIntent(
            "exit", status="exit", message="Voice Operator Mode stopped."
        )
    if is_dangerous_command(raw_command):
        return VoiceOperatorIntent(
            "blocked", status="blocked", message="I blocked that command for safety."
        )

    # Natural phrasings for actions pc_control already implements. Runs after
    # the safety check so it can never claim a blocked phrase, and before the
    # rest of the chain so a recognised phrase is not first mangled into an
    # application name -- "open google.com" used to resolve to open_app with the
    # target "google com".
    from grandpa.voice.action_phrases import resolve_action_phrase

    phrase_action = resolve_action_phrase(command)
    if phrase_action is not None:
        return VoiceOperatorIntent(
            "local_action",
            phrase_action.action_type,
            phrase_action.target,
            dict(phrase_action.args or {}),
            message=f"Handling {phrase_action.action_type.replace('_', ' ')}.",
        )

    from grandpa.automation import AutomationPlanner

    is_pending_conf = (
        has_pending_confirmation()
        if callable(has_pending_confirmation)
        else bool(has_pending_confirmation)
    )
    is_pending_wc = (
        has_pending_window_choice()
        if callable(has_pending_window_choice)
        else bool(has_pending_window_choice)
    )
    is_pending_dlg = (
        has_pending_dialog()
        if callable(has_pending_dialog)
        else bool(has_pending_dialog)
    )

    if (
        command
        in {
            "yes",
            "confirm",
            "continue",
            "do it",
            "ok",
            "okay",
            "no",
            "cancel",
            "don't",
            "dont",
        }
        and is_pending_conf
    ):
        return VoiceOperatorIntent(
            "screen_automation",
            "confirmation",
            args={"command": command},
            message="Handling automation confirmation.",
        )
    if is_pending_wc:
        return VoiceOperatorIntent(
            "screen_automation",
            "window_choice",
            args={"command": command},
            message="Selecting a window.",
        )
    if is_pending_dlg:
        return VoiceOperatorIntent(
            "screen_automation",
            "dialog_response",
            args={"command": raw_command},
            message="Handling the verified window dialog.",
        )

    automation_action = AutomationPlanner().parse(command)
    if automation_action is not None and automation_action.kind in {
        "move",
        "click",
        "double_click",
        "right_click",
        "middle_click",
        "scroll",
        "drag",
        "locate",
        "highlight",
        "focus",
        "close",
        "type",
        "paste",
        "press",
    }:
        intent_args = {"command": command}
        if automation_action.kind == "type":
            intent_args = {"text": str(automation_action.args.get("text", ""))}
        elif automation_action.kind == "press":
            intent_args = {"keys": list(automation_action.args.get("keys", []))}
        return VoiceOperatorIntent(
            "screen_automation",
            {
                "type": "keyboard_type",
                "press": "keyboard_hotkey",
                "focus": "focus_window",
                "close": "close_window",
            }.get(automation_action.kind, automation_action.kind),
            automation_action.target,
            intent_args,
            automation_action.requires_confirmation,
            message="Handling visible-screen automation.",
        )

    from grandpa.web_search import WebSearchParser

    web_search_action = WebSearchParser().parse(command)
    if web_search_action is not None:
        target = (
            web_search_action.query.text
            if web_search_action.query
            else web_search_action.action
        )
        return VoiceOperatorIntent(
            "web_search",
            web_search_action.action,
            target,
            {"command": command},
            False,
            message="Handling web search command.",
        )

    from grandpa.downloads import DownloadsParser

    downloads_action = DownloadsParser().parse(command)
    if downloads_action is not None:
        return VoiceOperatorIntent(
            "downloads",
            downloads_action.action,
            downloads_action.query or downloads_action.selector,
            {"command": command},
            downloads_action.action in {"delete", "archive", "organize"},
            message="Handling Downloads command.",
        )

    from grandpa.notes import NotesParser

    notes_action = NotesParser().parse(command)
    if notes_action is not None:
        return VoiceOperatorIntent(
            "notes",
            notes_action.action,
            notes_action.query or notes_action.title,
            {"command": command},
            notes_action.action == "delete",
            message="Handling notes command.",
        )

    from grandpa.calendar import CalendarParser

    calendar_action = CalendarParser().parse(command)
    if calendar_action is not None:
        return VoiceOperatorIntent(
            "calendar",
            calendar_action.action,
            calendar_action.query
            or calendar_action.date_range
            or calendar_action.title,
            {"command": command},
            calendar_action.action in {"create", "update", "delete"},
            message="Handling Calendar command.",
        )

    from grandpa.gmail import GmailParser

    gmail_action = GmailParser().parse(command)
    if gmail_action is not None:
        return VoiceOperatorIntent(
            "gmail",
            gmail_action.action,
            gmail_action.query or gmail_action.selector or gmail_action.recipient,
            {"command": command},
            gmail_action.action
            in {"send", "reply", "forward", "archive", "label", "trash"},
            message="Handling Gmail command.",
        )

    # Browser Intelligence Voice Commands
    if command in {
        "what page is this",
        "what page is this?",
        "where am i",
        "current page",
        "what browser page is this",
    }:
        return VoiceOperatorIntent(
            "browser_intelligence", "page", message="Checking active browser page."
        )
    if command in {
        "summarize this page",
        "summarize page",
        "summarize this webpage",
        "summarize current page",
    }:
        return VoiceOperatorIntent(
            "browser_intelligence",
            "summarize",
            message="Summarizing current browser page.",
        )
    match = re.fullmatch(
        r"(?:read|extract)\s+(installation|requirements|pricing|specs|faq|code)\s*(?:steps|section)?",
        command,
    )
    if match:
        sec = match.group(1)
        return VoiceOperatorIntent(
            "browser_intelligence",
            "extract",
            sec,
            {"section": sec},
            message=f"Reading {sec} steps.",
        )
    match = re.fullmatch(r"open\s+official\s+(.+)", command)
    if match:
        tgt = match.group(1).strip()
        return VoiceOperatorIntent(
            "browser_intelligence",
            "open_official",
            tgt,
            {"target": tgt},
            message=f"Opening official {tgt}.",
        )
    match = re.fullmatch(r"compare\s+(.+?)\s+(?:vs|and|with)\s+(.+)", command)
    if match:
        item_a, item_b = match.group(1).strip(), match.group(2).strip()
        return VoiceOperatorIntent(
            "browser_intelligence",
            "compare",
            f"{item_a} vs {item_b}",
            {"item_a": item_a, "item_b": item_b},
            message=f"Comparing {item_a} and {item_b}.",
        )

    # Memory Integration Voice Commands
    from grandpa.memory.service import MemoryService

    memory_route = MemoryService.get_instance().parse_and_route_intent(command)
    if memory_route is not None:
        return VoiceOperatorIntent(
            "memory",
            memory_route.intent.value,
            memory_route.target_key or memory_route.project_name or command,
            {"command": command, "route": memory_route},
            message="Handling memory command.",
        )

    from grandpa.browser_awareness import BrowserAwarenessParser

    awareness_action = BrowserAwarenessParser().parse(command)
    if awareness_action is not None:
        return VoiceOperatorIntent(
            "browser_awareness",
            awareness_action.action,
            awareness_action.query,
            {"command": command},
            message="Reading browser page context.",
        )

    from grandpa.browser import BrowserParser

    browser_action = BrowserParser().parse(command)
    if browser_action is not None:
        return VoiceOperatorIntent(
            "browser_automation",
            browser_action.action,
            browser_action.target or browser_action.provider or browser_action.url,
            {"command": command},
            message="Handling browser command.",
        )

    if command in {"scan my apps", "scan apps", "scan installed apps"}:
        return VoiceOperatorIntent(
            "app_inventory", "scan", message="Scanning installed apps."
        )
    if command in {"what apps do i have", "list apps", "show apps", "list my apps"}:
        return VoiceOperatorIntent(
            "app_inventory", "list", message="Listing installed apps."
        )
    if command.startswith("find app "):
        name = command[len("find app ") :].strip()
        return VoiceOperatorIntent(
            "app_inventory", "find", name, message=f"Finding {name}."
        )

    from grandpa.desktop.automation import DesktopParser

    desktop_action = DesktopParser().parse(command)
    if desktop_action is not None:
        return VoiceOperatorIntent(
            "local_action",
            desktop_action.pc_action_type,
            desktop_action.target,
            desktop_action.args,
            desktop_action.requires_confirmation,
            message=desktop_action.label or desktop_action.target,
        )

    app = _match_app(command, prefixes=("open ",))
    if app:
        return VoiceOperatorIntent(
            "local_action", "open_app", app, message=f"Opening {app}."
        )

    app = _match_app(command, prefixes=("switch to ", "focus "))
    if app:
        return VoiceOperatorIntent(
            "local_action", "focus_window", app, message=f"Focusing {app}."
        )

    window_action = _parse_window_action(command)
    if window_action:
        return VoiceOperatorIntent(
            "local_action",
            window_action,
            "active",
            message=_window_message(window_action),
        )

    # Browser Intelligence Voice Commands
    if command in {
        "what page is this",
        "what page is this?",
        "where am i",
        "current page",
        "what browser page is this",
    }:
        return VoiceOperatorIntent(
            "browser_intelligence", "page", message="Checking active browser page."
        )
    if command in {
        "summarize this page",
        "summarize page",
        "summarize this webpage",
        "summarize current page",
    }:
        return VoiceOperatorIntent(
            "browser_intelligence",
            "summarize",
            message="Summarizing current browser page.",
        )
    match = re.fullmatch(
        r"(?:read|extract)\s+(installation|requirements|pricing|specs|faq|code)\s*(?:steps|section)?",
        command,
    )
    if match:
        sec = match.group(1)
        return VoiceOperatorIntent(
            "browser_intelligence",
            "extract",
            sec,
            {"section": sec},
            message=f"Reading {sec} steps.",
        )
    match = re.fullmatch(r"open\s+official\s+(.+)", command)
    if match:
        tgt = match.group(1).strip()
        return VoiceOperatorIntent(
            "browser_intelligence",
            "open_official",
            tgt,
            {"target": tgt},
            message=f"Opening official {tgt}.",
        )
    match = re.fullmatch(r"compare\s+(.+?)\s+(?:vs|and|with)\s+(.+)", command)
    if match:
        item_a, item_b = match.group(1).strip(), match.group(2).strip()
        return VoiceOperatorIntent(
            "browser_intelligence",
            "compare",
            f"{item_a} vs {item_b}",
            {"item_a": item_a, "item_b": item_b},
            message=f"Comparing {item_a} and {item_b}.",
        )

    if command in {
        "screenshot",
        "take screenshot",
        "capture screen",
        "capture screenshot",
    }:
        return VoiceOperatorIntent(
            "screen", "screenshot", message="Capturing the screen."
        )
    if command in {
        "what is on my screen",
        "what's on my screen",
        "read my screen",
        "describe my screen",
    }:
        return VoiceOperatorIntent("screen", "read", message="Reading the screen.")

    if _looks_like_file_operator_command(command):
        from grandpa.files import FileParser

        file_action = FileParser().parse(command)
        if file_action is not None:
            return VoiceOperatorIntent(
                "file_automation",
                file_action.action,
                file_action.source or file_action.query,
                {"command": command},
                file_action.action == "delete",
                message="Handling file command.",
            )

    if command.startswith("open "):
        target = command[len("open ") :].strip()
        if target and names_one_application(target):
            return VoiceOperatorIntent(
                "local_action", "open_app", target, message=f"Opening {target}."
            )

    if command.startswith("type "):
        value = text.strip()[len("type ") :].strip()
        if not value:
            return VoiceOperatorIntent(
                "none", status="unsupported", message="Tell me what text to type."
            )
        return VoiceOperatorIntent(
            "local_action",
            "keyboard_type",
            "focused app",
            {"text": value},
            message="Typing text.",
        )

    key_match = re.fullmatch(r"press (enter|return|escape|esc|tab)", command)
    if key_match:
        key = KEY_ALIASES[key_match.group(1)]
        return VoiceOperatorIntent(
            "local_action",
            "keyboard_hotkey",
            key,
            {"keys": [key]},
            message=f"Pressing {key}.",
        )

    return VoiceOperatorIntent(
        "none",
        status="unsupported",
        message="I don't know that operator command yet.",
    )


def _looks_like_file_operator_command(command: str) -> bool:
    file_prefixes = (
        "create folder ",
        "create a folder ",
        "make folder ",
        "make a folder ",
        "create file ",
        "create a file ",
        "make file ",
        "make an empty file ",
        "rename ",
        "copy ",
        "duplicate ",
        "move ",
        # Deleting is reached by name as well as by noun phrase: "delete
        # report.pdf" is how people ask, and admitting only "delete file ..."
        # meant the plain form was never routed here at all.
        #
        # This widens what the file layer claims, so phrases meant for another
        # domain ("delete that email") can land here too. Two things already
        # contain that: the notes, calendar and downloads parsers are matched
        # earlier in the chain and keep their own phrases, and no delete ever
        # acts without a confirmation naming the resolved path -- a wrong match
        # ends as a question, not as a deletion.
        #
        # Only the bare verbs are listed. This is a prefix test, so "delete
        # file ..." and "delete the folder ..." are already matched by
        # "delete "; spelling them out again reads like extra coverage while
        # matching nothing new. The same goes for "find ".
        "delete ",
        "remove ",
        "find ",
        "search for ",
        "search files containing ",
        "show recent pdfs",
        "open latest ",
        "open the folder containing ",
        "zip ",
        "compress ",
        "extract ",
        "show properties of ",
        "what is the size of ",
        "when was ",
        "show file type and location ",
    )
    if command.startswith(file_prefixes):
        return True
    if command.startswith("open "):
        target = command[len("open ") :].strip()
        return any(separator in target for separator in ("\\", "/")) or "." in target
    return False


def execute_voice_operator_intent(
    intent: VoiceOperatorIntent,
    *,
    dry_run: bool = False,
    action_runner: Callable[[dict[str, Any]], Any] = run_local_action,
    screen_reader: Callable[..., Any] | None = None,
    automation_service=None,
) -> VoiceOperatorResult:
    if intent.status in {"blocked", "unsupported", "exit"}:
        return VoiceOperatorResult(intent.status, intent.message, intent.message)
    if intent.kind == "screen_automation":
        from grandpa.automation.executor import AutomationExecutor
        from grandpa.automation.service import ScreenAutomationService

        service = automation_service or ScreenAutomationService(
            executor=(
                AutomationExecutor(origin="voice")
                if action_runner is run_local_action
                else AutomationExecutor(runner=action_runner, origin="voice")
            )
        )
        result = service.handle(
            _automation_command_from_intent(intent), dry_run=dry_run
        )
        status: OperatorStatus = (
            "handled"
            if result.status in {"handled", "needs_confirmation"}
            else _coerce_status(result.status)
        )
        return VoiceOperatorResult(
            status,
            result.message,
            result.message,
            {
                "action_type": intent.action,
                "target": intent.target,
                "args": intent.args or {},
                "confirmation_token": result.confirmation_token,
                **result.data,
            },
            requires_confirmation=result.status == "needs_confirmation",
        )
    if intent.kind == "app_inventory":
        return _execute_app_inventory_intent(intent)
    if intent.kind == "web_search":
        from grandpa.web_search import handle_web_search_command

        result = handle_web_search_command(
            str((intent.args or {}).get("command") or intent.target)
        )
        status: OperatorStatus = (
            "handled"
            if result.status in {"handled", "not_configured"}
            else _coerce_status(result.status)
        )
        return VoiceOperatorResult(
            status,
            result.message,
            result.message,
            {
                "action_type": "web_search",
                "target": intent.target,
                "args": intent.args or {},
            },
        )
    if intent.kind == "downloads":
        from grandpa.downloads import handle_downloads_command

        result = handle_downloads_command(
            str((intent.args or {}).get("command") or intent.target)
        )
        status: OperatorStatus = (
            "handled"
            if result.status in {"handled", "needs_confirmation"}
            else _coerce_status(result.status)
        )
        return VoiceOperatorResult(
            status,
            result.message,
            result.message,
            {
                "action_type": "downloads",
                "target": intent.target,
                "args": intent.args or {},
            },
            requires_confirmation=result.requires_confirmation,
        )
    if intent.kind == "notes":
        from grandpa.notes import handle_notes_command

        result = handle_notes_command(
            str((intent.args or {}).get("command") or intent.target)
        )
        status: OperatorStatus = (
            "handled"
            if result.status in {"handled", "needs_confirmation"}
            else _coerce_status(result.status)
        )
        return VoiceOperatorResult(
            status,
            result.message,
            result.message,
            {
                "action_type": "notes",
                "target": intent.target,
                "args": intent.args or {},
            },
            requires_confirmation=result.requires_confirmation,
        )
    if intent.kind == "calendar":
        from grandpa.calendar import handle_calendar_command

        result = handle_calendar_command(
            str((intent.args or {}).get("command") or intent.target)
        )
        status: OperatorStatus = (
            "handled"
            if result.status in {"handled", "needs_confirmation"}
            else _coerce_status(result.status)
        )
        return VoiceOperatorResult(
            status,
            result.message,
            result.message,
            {
                "action_type": "calendar",
                "target": intent.target,
                "args": intent.args or {},
            },
            requires_confirmation=result.requires_confirmation,
        )
    if intent.kind == "gmail":
        from grandpa.gmail import handle_gmail_command

        result = handle_gmail_command(
            str((intent.args or {}).get("command") or intent.target)
        )
        status: OperatorStatus = (
            "handled"
            if result.status in {"handled", "needs_confirmation"}
            else _coerce_status(result.status)
        )
        return VoiceOperatorResult(
            status,
            result.message,
            result.message,
            {
                "action_type": "gmail",
                "target": intent.target,
                "args": intent.args or {},
            },
            requires_confirmation=result.requires_confirmation,
        )
    if intent.kind == "browser_awareness":
        from grandpa.browser_awareness import handle_browser_awareness_command

        result = handle_browser_awareness_command(
            str((intent.args or {}).get("command") or intent.target)
        )
        status: OperatorStatus = (
            "handled" if result.status == "handled" else _coerce_status(result.status)
        )
        return VoiceOperatorResult(
            status,
            result.message,
            result.message,
            {
                "action_type": "browser_awareness",
                "target": intent.target,
                "args": intent.args or {},
            },
        )
    if intent.kind == "browser_automation":
        from grandpa.browser import handle_browser_command

        result = handle_browser_command(
            str((intent.args or {}).get("command") or intent.target),
            origin="voice",
        )
        status: OperatorStatus = (
            "handled" if result.status == "handled" else _coerce_status(result.status)
        )
        return VoiceOperatorResult(
            status,
            result.message,
            result.message,
            {
                "action_type": "browser_automation",
                "target": intent.target,
                "args": intent.args or {},
            },
        )
    if intent.kind == "file_automation":
        from grandpa.composition import build_file_automation

        # Spoken file mutations were reaching shutil and pathlib directly, with
        # no risk tier, approval gate, emergency stop, audit record or
        # verification. Handing the file layer this turn's actuator routes them
        # through the same boundary as every other spoken action.
        #
        # This turn's runner is passed rather than the module default: under
        # test it is a recorder, and process_voice_operator_turn's callers
        # thread it through every other branch here. Composition is
        # request-scoped and configured once, so a turn's runner and provenance
        # cannot leak into the next one.
        automation = build_file_automation(
            mutation_runner=action_runner, origin="voice", dry_run=dry_run
        )
        result = automation.handle(
            str((intent.args or {}).get("command") or intent.target)
        )
        status: OperatorStatus = (
            "handled"
            if result.status in {"handled", "needs_confirmation", "ambiguous"}
            else _coerce_status(result.status)
        )
        return VoiceOperatorResult(
            status,
            result.message,
            result.message,
            {
                "action_type": "file_automation",
                "target": intent.target,
                "args": intent.args or {},
            },
            requires_confirmation=result.requires_confirmation,
        )
    if intent.kind == "browser_intelligence":
        from grandpa.browser_intelligence import (
            LocalPageSummarizer,
            ProductComparisonEngine,
            SmartNavigator,
            extract_section_content,
            format_voice_summary,
            read_current_browser_page,
        )

        page = read_current_browser_page()
        if intent.action == "page":
            msg = f"You are currently on {page.title} at domain {page.domain}."
            return VoiceOperatorResult(
                "handled", msg, msg, {"title": page.title, "domain": page.domain}
            )

        if intent.action == "summarize":
            summarizer = LocalPageSummarizer()
            summary = summarizer.summarize_page(page, summary_type="short")
            spoken = format_voice_summary(summary)
            return VoiceOperatorResult("handled", summary, spoken, {"summary": summary})

        if intent.action == "extract":
            sec = str((intent.args or {}).get("section") or "installation")
            extracted = extract_section_content(page, target_section=sec)
            spoken = format_voice_summary(extracted.text)
            return VoiceOperatorResult(
                "handled", extracted.text, spoken, extracted.to_dict()
            )

        if intent.action == "open_official":
            target = str((intent.args or {}).get("target") or intent.target)
            nav = SmartNavigator()
            nav_res = nav.search_and_open_official(target)
            msg = nav_res.get("message", f"Opened official site for {target}.")
            return VoiceOperatorResult("handled", msg, msg, nav_res)

        if intent.action == "compare":
            item_a = str((intent.args or {}).get("item_a") or "Raspberry Pi 5")
            item_b = str((intent.args or {}).get("item_b") or "Jetson Nano")
            engine = ProductComparisonEngine()
            comparison = engine.compare_items(item_a, item_b)
            spoken = format_voice_summary(comparison.summary)
            return VoiceOperatorResult(
                "handled", comparison.summary, spoken, comparison.to_dict()
            )

    if intent.kind == "memory":
        from grandpa.cli.chat_cmd import _handle_natural_memory_intent

        cmd_text = str((intent.args or {}).get("command") or intent.target)
        msg = _handle_natural_memory_intent(cmd_text)
        if msg:
            from grandpa.browser_intelligence import format_voice_summary

            spoken = format_voice_summary(msg)
            return VoiceOperatorResult(
                "handled", msg, spoken, {"kind": "memory", "command": cmd_text}
            )
        return VoiceOperatorResult("handled", intent.message, intent.message)
    if intent.kind == "screen":
        return _execute_screen_intent(intent, screen_reader=screen_reader)
    if intent.kind != "local_action":
        return VoiceOperatorResult("unsupported", intent.message, intent.message)

    payload = {
        "action_type": intent.action,
        "target": intent.target,
        "args": intent.args or {},
        "dry_run": dry_run,
        "require_approval": intent.requires_confirmation,
        # Provenance for the audit trail (AD-022). Everything reaching here was
        # spoken or typed by the user at the operator prompt.
        "origin": "voice",
    }
    response = action_runner(payload)
    status: OperatorStatus = (
        "handled"
        if getattr(response, "ok", False)
        else _coerce_status(getattr(response, "status", "error"))
    )
    message = str(getattr(response, "message", intent.message))
    return VoiceOperatorResult(
        status=status,
        message=message,
        spoken_text=spoken_text_for_verification(response, message),
        action=payload,
        requires_confirmation=bool(getattr(response, "approval_required", False)),
    )


def spoken_text_for_verification(response: Any, message: str) -> str:
    """Phrase the spoken reply according to what verification actually found.

    ``_apply_verification`` (pc_control) records whether an action was
    confirmed to have taken effect, but until this existed the user heard the
    same sentence either way -- the field was machine-readable and inaudible.
    Someone operating by voice has no screen to check, so "Volume set to 50%"
    has to stop being said when nothing moved.

    Three states, three different things to say:

    ``verified``
        The concise success message, unchanged. It has been confirmed, so there
        is nothing to hedge.
    ``failed``
        Lead with the failure. The underlying message reads "Window maximized.
        However, I could not confirm..." -- accurate, but the first two words
        sound like success, and in speech the opening is what gets heard.
    ``unknown``
        Say that it ran and that confirmation was not available. Not a failure,
        and not a claim of success.

    A response carrying no verification evidence is returned untouched, so
    every existing caller and every action without a verifier keeps its current
    wording. Malformed evidence is treated the same way rather than raising --
    a reporting layer must not be able to break the action path.
    """
    evidence = getattr(response, "evidence", None)
    if not isinstance(evidence, dict):
        return message
    verification = evidence.get("verification")
    if not isinstance(verification, dict):
        return message

    # The three phrasings live with the verification module, so the plan path
    # says the same things about the same three states.
    from grandpa.desktop.control.verification import verification_sentence

    return verification_sentence(
        str(verification.get("status") or "").strip().lower(),
        str(verification.get("detail") or ""),
        message,
    )


@dataclass(frozen=True)
class VoiceOperatorTurnResponse:
    """Structured result returned by the single-turn Voice Operator processor."""

    text: str
    status: OperatorStatus = "handled"
    spoken_text: str = ""
    action: dict[str, Any] | None = None
    requires_confirmation: bool = False
    exit_requested: bool = False


@dataclass
class VoiceOperatorResponder:
    """Single-turn processor for Voice Operator commands implementing Responder protocol."""

    dry_run: bool = False
    action_runner: Callable[[dict[str, Any]], Any] = run_local_action
    screen_reader: Callable[..., Any] | None = None
    automation_service: Any = None
    debug: bool = False
    debug_output: Callable[[str], None] | None = None

    def __post_init__(self) -> None:
        if self.automation_service is None:
            from grandpa.automation.executor import AutomationExecutor
            from grandpa.automation.service import ScreenAutomationService

            self.automation_service = ScreenAutomationService(
                executor=AutomationExecutor(runner=self.action_runner, origin="voice")
            )

    def handle_user_input(self, text: str) -> VoiceOperatorTurnResponse:
        return process_voice_operator_turn(
            text,
            dry_run=self.dry_run,
            action_runner=self.action_runner,
            screen_reader=self.screen_reader,
            automation_service=self.automation_service,
            debug=self.debug,
            debug_output=self.debug_output,
        )


def process_voice_operator_turn(
    text: str,
    *,
    dry_run: bool = False,
    action_runner: Callable[[dict[str, Any]], Any] = run_local_action,
    screen_reader: Callable[..., Any] | None = None,
    automation_service: Any = None,
    debug: bool = False,
    debug_output: Callable[[str], None] | None = None,
) -> VoiceOperatorTurnResponse:
    """Execute one recognized phrase through the Voice Operator router and return the result."""

    if automation_service is None:
        from grandpa.automation.executor import AutomationExecutor
        from grandpa.automation.service import ScreenAutomationService

        automation_service = ScreenAutomationService(
            executor=AutomationExecutor(runner=action_runner, origin="voice")
        )

    raw_text = str(text or "").strip()
    normalized_text = normalize_voice_operator_transcript(raw_text)
    if debug and debug_output:
        debug_output(f"Raw transcript: {raw_text}")
        debug_output(f"Normalized transcript: {normalized_text}")

    if not normalized_text:
        return VoiceOperatorTurnResponse(
            text="I did not hear a command.",
            status="unsupported",
            spoken_text="I did not hear a command.",
        )

    from grandpa.voice.cli_session import is_exit_phrase

    if (
        is_exit_phrase(raw_text)
        or is_exit_phrase(normalized_text)
        or normalized_text in {"stop listening", "exit", "quit"}
    ):
        return VoiceOperatorTurnResponse(
            text="Voice Operator Mode stopped.",
            status="exit",
            spoken_text="Voice Operator Mode stopped.",
            exit_requested=True,
        )

    def _is_pending(fn_or_val: Any) -> bool:
        if fn_or_val is None:
            return False
        if callable(fn_or_val):
            try:
                return bool(fn_or_val())
            except TypeError:
                return False
        return bool(fn_or_val)

    has_pending = (
        _is_pending(getattr(automation_service, "has_pending_confirmation", None))
        or _is_pending(getattr(automation_service, "has_pending_window_choice", None))
        or _is_pending(getattr(automation_service, "has_pending_dialog", None))
    )
    if has_pending:
        intent = parse_voice_operator_command(
            normalized_text,
            has_pending_confirmation=automation_service.has_pending_confirmation,
            has_pending_window_choice=automation_service.has_pending_window_choice,
            has_pending_dialog=automation_service.has_pending_dialog,
        )
        result = execute_voice_operator_intent(
            intent,
            dry_run=dry_run,
            action_runner=action_runner,
            screen_reader=screen_reader,
            automation_service=automation_service,
        )
        return VoiceOperatorTurnResponse(
            text=result.message,
            status=result.status,
            spoken_text=result.spoken_text,
            action=result.action,
            requires_confirmation=result.requires_confirmation,
            exit_requested=(result.status == "exit"),
        )

    # Resolution order is: multi-step planner, then deterministic device
    # commands, then conversational classification.
    #
    # The executive planner stays first because it claims only genuine
    # multi-step goals -- planner/routing.py:38 returns None for anything that
    # decomposes to fewer than two steps -- so it cannot swallow a single
    # device command, and putting the device parser ahead of it would steal
    # goals like "open chrome and search for fastapi" that it handles properly.
    #
    # classify_intent then moves *after* the device parser. It matches greeting
    # words anywhere in an utterance, so while it ran first "type hello world",
    # "type hi there", "open hello.txt" and "search for hello.txt" were all
    # classified GREETING and answered with a chat reply while no actuator ran
    # at all -- the user heard something friendly and nothing happened.
    #
    # parse_voice_operator_command is the discriminator: every conversational
    # phrase ("hello", "thanks", "how are you", "what time is it") parses to
    # kind == "none", while device commands parse to a concrete kind. Safety is
    # unaffected -- DANGEROUS_PATTERNS still yields kind == "blocked" here, and
    # execute_voice_operator_intent short-circuits blocked/unsupported/exit at
    # its top -- so this reorders resolution without widening what may run.
    # Safety comes before every resolver, including the planner.
    #
    # The dangerous-command check lives inside parse_voice_operator_command,
    # which the turn only reaches once the planner has declined -- so a phrase
    # the planner *claimed* was executed without the check ever running. That
    # is not hypothetical: "open cmd and search for fastapi" decomposes to a
    # four-step plan whose first step launches cmd.
    #
    # The check is made on the raw words. Normalisation rewrites the launch
    # verbs, turning "run command" into "open command", and the parser is
    # handed the normalised text below -- so by the time it runs its own check
    # the dangerous phrasing is already gone. Blocking here is the only place
    # that still sees what the user actually said.
    #
    # The response itself is the parser's, so there is one blocked message and
    # one blocked status in the codebase, not a second copy living here.
    if is_dangerous_command(raw_text):
        blocked = parse_voice_operator_command(raw_text)
        result = execute_voice_operator_intent(
            blocked,
            dry_run=dry_run,
            action_runner=action_runner,
            screen_reader=screen_reader,
            automation_service=automation_service,
        )
        return VoiceOperatorTurnResponse(
            text=result.message,
            status=result.status,
            spoken_text=result.spoken_text,
        )

    from grandpa.planner.routing import handle_executive_goal

    planned = handle_executive_goal(
        normalized_text,
        automation_service=automation_service,
        source="voice_operator",
        # The plan's own steps end at the same actuator this turn was given,
        # and are attributed to the person who spoke (AD-022) rather than
        # appearing in the audit trail as anonymous direct calls.
        action_runner=action_runner,
        origin="voice",
    )
    if planned is not None:
        return VoiceOperatorTurnResponse(
            text=planned,
            status="handled",
            spoken_text=planned,
        )

    intent = parse_voice_operator_command(
        normalized_text,
        has_pending_confirmation=automation_service.has_pending_confirmation,
        has_pending_window_choice=automation_service.has_pending_window_choice,
        has_pending_dialog=automation_service.has_pending_dialog,
    )
    if intent.kind != "none":
        result = execute_voice_operator_intent(
            intent,
            dry_run=dry_run,
            action_runner=action_runner,
            screen_reader=screen_reader,
            automation_service=automation_service,
        )
        return VoiceOperatorTurnResponse(
            text=result.message,
            status=result.status,
            spoken_text=result.spoken_text,
            action=result.action,
            requires_confirmation=result.requires_confirmation,
            exit_requested=(result.status == "exit"),
        )

    # Unified assistant routing
    from grandpa.agent.context import classify_intent
    from grandpa.agent.models import AgentIntent

    intent_type = classify_intent(normalized_text)

    if intent_type in (
        AgentIntent.GREETING,
        AgentIntent.TIME_QUERY,
        AgentIntent.PROJECT,
        AgentIntent.ROADMAP,
        AgentIntent.SPRINT,
        AgentIntent.AGENT,
        AgentIntent.PLANNER,
    ):
        from grandpa.agent.runtime import AgentRuntime

        runtime = AgentRuntime()
        res = runtime.run(normalized_text)
        exit_requested = intent_type == AgentIntent.STOP_CANCEL or normalized_text in {
            "stop listening",
            "exit",
            "quit",
        }
        return VoiceOperatorTurnResponse(
            text=res.message,
            status="handled",
            spoken_text=res.message,
            exit_requested=exit_requested,
        )

    # Nothing claimed this: not the planner, not the device parser, not
    # conversational routing. Run the already-parsed intent so the caller still
    # gets the operator's own "I don't know that command" reply, not silence.
    result = execute_voice_operator_intent(
        intent,
        dry_run=dry_run,
        action_runner=action_runner,
        screen_reader=screen_reader,
        automation_service=automation_service,
    )
    return VoiceOperatorTurnResponse(
        text=result.message,
        status=result.status,
        spoken_text=result.spoken_text,
        action=result.action,
        requires_confirmation=result.requires_confirmation,
        exit_requested=(result.status == "exit"),
    )


def build_voice_operator_session(
    *,
    model: str | None = None,
    language: str | None = None,
    device: str | None = None,
    microphone: int | None = None,
    device_name: str | None = None,
    no_tts: bool = False,
    wake_word: bool = False,
    wake_phrases: tuple[str, ...] | None = None,
    wake_response_enabled: bool = True,
    duration_seconds: float | None = None,
    dry_run: bool = False,
    action_runner: Callable[[dict[str, Any]], Any] | None = None,
    automation_service: Any | None = None,
    screen_reader: Callable[..., Any] | None = None,
    output: Callable[[str], None] = print,
    quiet: bool = False,
    verbose: bool = False,
    screen_reader_mode: bool = False,
    debug: bool = False,
    microphone_capture: Any | None = None,
    transcriber: Any | None = None,
    speaker: Any | None = None,
) -> Any:
    """Construct a continuous VoiceSession wired to VoiceOperatorResponder."""

    from grandpa.voice.cli_session import build_voice_session

    responder = VoiceOperatorResponder(
        dry_run=dry_run,
        action_runner=action_runner or run_local_action,
        screen_reader=screen_reader,
        automation_service=automation_service,
        debug=debug,
        debug_output=output if debug else None,
    )
    return build_voice_session(
        model=model,
        language=language,
        device=device,
        microphone=microphone,
        no_tts=no_tts,
        wake_word=wake_word,
        wake_phrases=wake_phrases,
        wake_response_enabled=wake_response_enabled,
        output=output,
        quiet=quiet,
        verbose=verbose,
        screen_reader=screen_reader_mode,
        responder=responder,
        microphone_capture=microphone_capture,
        transcriber=transcriber,
        speaker=speaker,
        phrase_duration_limit=duration_seconds,
        debug=debug,
    )


def run_voice_operator_loop(
    *,
    input_func: Callable[[str], str] | None = None,
    output_func: Callable[[str], None] = print,
    listen_func: Callable[[], str] | None = None,
    action_runner: Callable[[dict[str, Any]], Any] | None = None,
    speech_output: SpeechOutputEngine | None = None,
    dry_run: bool = False,
    prefer_voice: bool | None = None,
    duration_seconds: float = 4.0,
    device: int | None = None,
    device_name: str | None = None,
    debug: bool = False,
    no_tts: bool = False,
    screen_reader: bool = False,
    automation_service: Any | None = None,
    session: Any | None = None,
) -> int:
    """Run command-first Voice Operator mode with hands-free or typed interaction."""

    if session is not None:
        return session.run()

    if prefer_voice is False:
        return _run_typed_operator_loop(
            input_func=input_func or input,
            output_func=output_func,
            action_runner=action_runner,
            automation_service=automation_service,
            speech_output=speech_output,
            dry_run=dry_run,
            debug=debug,
            no_tts=no_tts,
        )

    if listen_func is not None or (input_func is not None and input_func is not input):
        return _run_simulated_or_custom_operator_loop(
            input_func=input_func,
            output_func=output_func,
            listen_func=listen_func,
            action_runner=action_runner,
            speech_output=speech_output,
            dry_run=dry_run,
            duration_seconds=duration_seconds,
            device=device,
            device_name=device_name,
            debug=debug,
            no_tts=no_tts,
            automation_service=automation_service,
        )

    no_speech_out = no_tts or (speech_output is not None and not speech_output.enabled)
    voice_session = build_voice_operator_session(
        device=None,
        microphone=device,
        device_name=device_name,
        no_tts=no_speech_out,
        duration_seconds=duration_seconds,
        dry_run=dry_run,
        action_runner=action_runner,
        automation_service=automation_service,
        output=output_func,
        debug=debug,
        screen_reader_mode=screen_reader,
    )
    return voice_session.run()


def _run_typed_operator_loop(
    *,
    input_func: Callable[[str], str],
    output_func: Callable[[str], None],
    action_runner: Callable[[dict[str, Any]], Any] | None,
    automation_service: Any | None,
    speech_output: SpeechOutputEngine | None,
    dry_run: bool,
    debug: bool,
    no_tts: bool,
) -> int:
    output_func("Voice Operator Mode started")
    output_func("Type a command. Say 'stop listening' or type 'quit' to exit.")
    speaker = speech_output or (None if no_tts else SpeechOutputEngine())
    responder = VoiceOperatorResponder(
        dry_run=dry_run,
        action_runner=action_runner or run_local_action,
        automation_service=automation_service,
        debug=debug,
        debug_output=output_func if debug else None,
    )

    while True:
        try:
            text = input_func("> ")
            if text is None:
                raise EOFError
            if not text.strip():
                continue
        except (EOFError, KeyboardInterrupt):
            output_func("Voice Operator Mode stopped.")
            return 0

        normalized = normalize_voice_operator_transcript(text)
        if debug:
            output_func(f"Raw transcript: {text}")
            output_func(f"Normalized transcript: {normalized}")
        output_func(f"Understood: {normalized}")

        res = responder.handle_user_input(text)
        output_func(res.text)
        if speaker and speaker.enabled and not no_tts:
            _speak_best_effort(speaker, res.spoken_text or res.text, dry_run=dry_run)
        if res.exit_requested or res.status == "exit":
            return 0


def _run_simulated_or_custom_operator_loop(
    *,
    input_func: Callable[[str], str] | None,
    output_func: Callable[[str], None],
    listen_func: Callable[[], str] | None,
    action_runner: Callable[[dict[str, Any]], Any] | None,
    speech_output: SpeechOutputEngine | None,
    dry_run: bool,
    duration_seconds: float,
    device: int | None,
    device_name: str | None,
    debug: bool,
    no_tts: bool,
    automation_service: Any | None,
) -> int:
    output_func("Voice Operator Mode started")
    output_func(
        "Press Enter to record, or type a command. Say 'stop listening' to exit."
    )
    prompt_input = input_func or input
    use_voice = True
    listener = listen_func or (
        lambda: _listen_once(
            duration_seconds=duration_seconds,
            device=device,
            device_name=device_name,
            debug_output=output_func if debug else None,
            warning_output=output_func,
        )
    )
    speaker = speech_output or (None if no_tts else SpeechOutputEngine())
    responder = VoiceOperatorResponder(
        dry_run=dry_run,
        action_runner=action_runner or run_local_action,
        automation_service=automation_service,
        debug=debug,
        debug_output=output_func if debug else None,
    )

    while True:
        try:
            if use_voice:
                trigger = prompt_input("Press Enter to record, or type command: ")
                if trigger is None:
                    raise EOFError
                if trigger.strip():
                    text = trigger
                else:
                    output_func(f"Recording for {duration_seconds:g} seconds...")
                    try:
                        text = listener()
                    except VoiceRecognitionError as exc:
                        output_func(str(exc))
                        output_func(
                            "You can press Enter to try again, or type a command."
                        )
                        continue
                    except (VoiceDependencyError, MicrophoneUnavailableError) as exc:
                        output_func(str(exc))
                        output_func("Falling back to typed input.")
                        use_voice = False
                        text = prompt_input("> ")
                    except VoiceError as exc:
                        output_func(str(exc))
                        output_func("Falling back to typed input.")
                        use_voice = False
                        text = prompt_input("> ")
                if not text.strip():
                    output_func(
                        "No command heard. Press Enter to record, or type a command."
                    )
                    continue
            else:
                text = prompt_input("> ")
                if text is None:
                    raise EOFError
                if not text.strip():
                    continue
        except (EOFError, KeyboardInterrupt):
            output_func("Voice Operator Mode stopped")
            return 0

        normalized = normalize_voice_operator_transcript(text)
        if debug:
            output_func(f"Raw transcript: {text}")
            output_func(f"Normalized transcript: {normalized}")
        output_func(f"Understood: {normalized}")

        res = responder.handle_user_input(text)
        output_func(res.text)
        if speaker and speaker.enabled and not no_tts:
            _speak_best_effort(speaker, res.spoken_text or res.text, dry_run=dry_run)
        if res.exit_requested or res.status == "exit":
            return 0


def _execute_screen_intent(
    intent: VoiceOperatorIntent,
    *,
    screen_reader: Callable[..., Any] | None,
) -> VoiceOperatorResult:
    if screen_reader is None:
        from grandpa.screen_awareness import describe_screen

        screen_reader = describe_screen
    context = screen_reader(include_ocr=intent.action == "read")
    message = str(getattr(context, "message", "") or "I could not inspect the screen.")
    return VoiceOperatorResult("handled", message, message)


def _automation_command_from_intent(intent: VoiceOperatorIntent) -> str:
    args = intent.args or {}
    if args.get("command"):
        return str(args["command"])
    if intent.action == "keyboard_type":
        return f"type {args.get('text', '')}".strip()
    if intent.action == "keyboard_hotkey":
        keys = args.get("keys", [])
        return f"press {'+'.join(str(key) for key in keys)}"
    if intent.action == "focus_window":
        return f"focus {intent.target}"
    return intent.target


def _execute_app_inventory_intent(intent: VoiceOperatorIntent) -> VoiceOperatorResult:
    from grandpa.apps.inventory import find_app, list_apps, scan_app_inventory

    if intent.action == "scan":
        apps = scan_app_inventory()
        message = f"Scanned {len(apps)} apps."
        return VoiceOperatorResult("handled", message, message)
    if intent.action == "list":
        apps = list_apps()
        if not apps:
            message = "No app inventory found. Run scan my apps first."
        else:
            names = ", ".join(app.display_name for app in apps[:20])
            suffix = f" and {len(apps) - 20} more" if len(apps) > 20 else ""
            message = f"Installed apps: {names}{suffix}."
        return VoiceOperatorResult("handled", message, message)
    if intent.action == "find":
        result = find_app(intent.target)
        return VoiceOperatorResult(
            "handled" if result.status == "found" else "unsupported",
            result.message,
            result.message,
        )
    return VoiceOperatorResult(
        "unsupported",
        "I don't know that app inventory command yet.",
        "I don't know that app inventory command yet.",
    )


def _listen_once(
    *,
    duration_seconds: float = 4.0,
    device: int | None = None,
    device_name: str | None = None,
    debug_output: Callable[[str], None] | None = None,
    warning_output: Callable[[str], None] | None = None,
) -> str:
    from grandpa.jarvis.voice_input import (
        SoundDeviceMicrophoneRecorder,
        listen_for_jarvis_command,
    )

    recorder = SoundDeviceMicrophoneRecorder(
        duration_seconds=duration_seconds, device=device, device_name=device_name
    )
    try:
        return listen_for_jarvis_command(recorder=recorder).transcript
    finally:
        if (
            warning_output
            and recorder.last_diagnostics
            and recorder.last_diagnostics.warning
        ):
            warning_output(f"Audio warning: {recorder.last_diagnostics.warning}")
        if debug_output and recorder.last_diagnostics:
            diagnostics = recorder.last_diagnostics
            debug_output(f"Requested device: {diagnostics.requested_device_id}")
            debug_output(f"Requested device name: {diagnostics.requested_device_name}")
            debug_output(f"Actual device: {diagnostics.selected_device_id}")
            debug_output(f"Audio device name: {diagnostics.device_name}")
            debug_output(f"Audio channels: {diagnostics.channels}")
            debug_output(f"Audio sample rate: {diagnostics.sample_rate}")
            debug_output(f"Audio RMS level: {diagnostics.rms_level:.1f}")
            debug_output(f"Audio captured frames: {diagnostics.captured_frame_count}")


def _speak_best_effort(
    speech_output: SpeechOutputEngine, text: str, *, dry_run: bool
) -> None:
    try:
        speech_output.speak(text, interrupt=True, dry_run=dry_run)
    except VoiceOutputUnavailableError:
        return


def _match_app(command: str, *, prefixes: tuple[str, ...]) -> str | None:
    """The application named after one of *prefixes*, or None.

    "open chrome and go to gmail" used to yield the application name "chrome
    and go to gmail". Nothing resolves to that, so the turn reported a
    successful launch and no window appeared. A phrase joined by a clause word
    is several instructions, not one application, and this refuses it -- the
    same refusal ``planner/decomposer.py`` makes, kept in step with it.
    """
    for prefix in prefixes:
        if command.startswith(prefix):
            raw = command[len(prefix) :].strip()
            if raw not in APP_ALIASES and not names_one_application(raw):
                return None
            return APP_ALIASES.get(raw, raw)
    return None


def _parse_window_action(command: str) -> str | None:
    target_words = ("this window", "active window", "current window", "window")
    mapping = {
        "close": "close_window",
        "minimize": "minimize_window",
        "maximise": "maximize_window",
        "maximize": "maximize_window",
        "restore": "restore_window",
    }
    for verb, action in mapping.items():
        if any(command == f"{verb} {target}" for target in target_words):
            return action
    return None


def _window_message(action: str) -> str:
    labels = {
        "close_window": "Closing the active window.",
        "minimize_window": "Minimizing the active window.",
        "maximize_window": "Maximizing the active window.",
        "restore_window": "Restoring the active window.",
    }
    return labels[action]


def _coerce_status(status: str) -> OperatorStatus:
    if status in {
        "ambiguous",
        "blocked",
        "cancelled",
        "dialog_pending",
        "target_lost",
        "unsupported",
    }:
        return status
    if status == "approval_required":
        return "handled"
    return "error"


def _normalise(text: str) -> str:
    value = text.strip().lower()
    value = re.sub(r"[?!.,;:]+", " ", value)
    return re.sub(r"\s+", " ", value)


_VOCATIVE_PREFIX_PATTERNS = (
    re.compile(
        r"^(hey|okay|ok|hi|hello)\s+grandpa\s*,?\s*please\s*,?\s*", re.IGNORECASE
    ),
    re.compile(r"^grandpa\s*,?\s*please\s*,?\s*", re.IGNORECASE),
    re.compile(r"^please\s*,?\s*grandpa\s*,?\s*", re.IGNORECASE),
    re.compile(r"^(hey|okay|ok|hi|hello)\s+grandpa\s*,?\s*", re.IGNORECASE),
    re.compile(r"^grandpa\s*,?\s*", re.IGNORECASE),
)


def _strip_vocative_prefix_raw(text: str) -> str:
    result = text.strip()
    for pattern in _VOCATIVE_PREFIX_PATTERNS:
        match = pattern.match(result)
        if match:
            return result[match.end() :].strip()
    return result


def normalize_voice_operator_transcript(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""

    # Strip optional leading conversational vocative prefix ("Grandpa, ", "Hey Grandpa, ", etc.)
    stripped = _strip_vocative_prefix_raw(raw)

    # For typing commands, preserve exact case and text payload
    if stripped.lower().startswith("type "):
        typed_payload = stripped[5:].strip()
        return f"type {typed_payload}".strip()

    command = _normalise(stripped)
    if not command:
        return ""

    words = command.split()
    deduped_words: list[str] = []
    for word in words:
        if not deduped_words or deduped_words[-1] != word:
            deduped_words.append(word)
    command = " ".join(deduped_words)

    words = command.split()
    if words and words[0] in LAUNCH_WORDS:
        words[0] = "open"
        command = " ".join(words)

    if command.startswith("open "):
        target = command[len("open ") :].strip()
        target_words = target.split()
        while target_words and target_words[0] == "open":
            target_words.pop(0)
        target = _normalize_app_phrase(" ".join(target_words))
        return f"open {target}".strip()

    return _normalize_app_phrase(command)


def _normalize_app_phrase(value: str) -> str:
    result = value
    for phrase, replacement in sorted(
        APP_PHRASE_ALIASES.items(), key=lambda item: len(item[0]), reverse=True
    ):
        result = re.sub(rf"\b{re.escape(phrase)}\b", replacement, result)
    return re.sub(r"\s+", " ", result).strip()


__all__ = [
    "VoiceOperatorIntent",
    "VoiceOperatorResponder",
    "VoiceOperatorResult",
    "VoiceOperatorTurnResponse",
    "build_voice_operator_session",
    "execute_voice_operator_intent",
    "normalize_voice_operator_transcript",
    "parse_voice_operator_command",
    "process_voice_operator_turn",
    "spoken_text_for_verification",
    "run_voice_operator_loop",
]
