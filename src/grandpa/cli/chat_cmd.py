"""``Grandpa chat`` — interactive multi-turn chat REPL."""

from __future__ import annotations

import logging
import re
import subprocess
import sys
import threading
from pathlib import Path
from typing import List, Optional

import click
from rich.console import Console
from rich.markdown import Markdown

from grandpa.cli._tool_names import resolve_tool_names
from grandpa.cli.input_ui import read_chat_input, select_from_list
from grandpa.cli.slash_commands import command_help_text, unknown_command_message
from grandpa.cli.theme import (
    help_commands_text,
    help_examples_text,
    help_modules_text,
    help_shortcuts_text,
    render_assistant_response,
    render_chat_home,
    render_help,
    render_user_message,
)
from grandpa.core.config import load_config
from grandpa.core.types import Message, Role
from grandpa.engine._base import (
    EngineConnectionError,
    EngineModelLoadError,
    EngineModelNotFoundError,
)
from grandpa.response_cleanup import (
    GENERATION_ERROR_MESSAGE,
    clean_assistant_response,
    clean_error_message,
)

logger = logging.getLogger(__name__)

_THINKING_FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")

NATURAL_MEMORY_LIST_INTENTS = {
    "show my memories",
    "list my memories",
    "show memories",
    "list memories",
}

NATURAL_MEMORY_ALL_INTENTS = {
    "show all memories",
    "list all memories",
}

NATURAL_MEMORY_RECALL_INTENTS = {
    "what do you remember",
    "what do you remember about me",
    "what do you know about me",
}

NATURAL_REMINDER_LIST_INTENTS = {
    "do i have any reminders",
    "list my reminders",
    "show me my reminders",
    "show my reminders",
    "what are my reminders",
    "what reminder do i have",
    "show reminders",
    "list reminders",
    "what reminders do i have",
}


def _read_input(prompt: str = "> ") -> Optional[str]:
    """Read user input with graceful EOF handling."""
    try:
        return input(prompt)
    except (EOFError, KeyboardInterrupt):
        return None


def _engine_unavailable_message(engine_name: str, exc: EngineConnectionError) -> str:
    text = str(exc)
    if engine_name == "ollama" or "ollama" in text.lower():
        return (
            "Ollama is not available.\n"
            "Start it with: ollama serve\n"
            "Verify it with: ollama list\n"
            "Then retry the command."
        )
    return f"Inference engine '{engine_name}' is not available. {text}"


def _model_not_found_message(engine_name: str, exc: EngineModelNotFoundError) -> str:
    model = exc.model
    if engine_name == "ollama":
        return f'Ollama is running, but model "{model}" is not installed.'
    return f'Inference engine "{engine_name}" does not have model "{model}" installed.'


def _model_pull_guidance(model: str) -> str:
    return (
        f"Install it with: ollama pull {model}\n"
        "Verify it with: ollama list\n"
        "Then retry the command."
    )


def _generation_log_path() -> Path:
    return Path.home() / ".grandpa" / "server.log"


def _log_generation_exception(exc: BaseException) -> None:
    log_path = _generation_log_path()
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(log_path, encoding="utf-8")
        handler.setLevel(logging.ERROR)
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        diagnostic_logger = logging.getLogger(f"{__name__}.generation")
        diagnostic_logger.propagate = False
        diagnostic_logger.addHandler(handler)
        try:
            diagnostic_logger.error(
                "Chat generation failed",
                exc_info=(type(exc), exc, exc.__traceback__),
            )
        finally:
            diagnostic_logger.removeHandler(handler)
            handler.close()
    except Exception:
        logger.debug("Failed to write chat generation diagnostics", exc_info=True)


def _model_load_failure_message(exc: EngineModelLoadError) -> str:
    if exc.low_memory:
        return str(exc)
    return clean_error_message(
        exc,
        fallback=f"Ollama could not load {exc.model}. Check `ollama serve` and try again.",
    )


class ThinkingAnimation:
    """Small terminal-only spinner for blocking response generation."""

    def __init__(self, console: Console, *, interval: float = 0.1) -> None:
        self._console = console
        self._interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._enabled = bool(getattr(console, "is_terminal", False))

    def start(self) -> None:
        if not self._enabled or self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run,
            name="grandpa-thinking-animation",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        if not self._thread:
            return
        self._stop.set()
        self._thread.join(timeout=1.0)
        self._clear_line()
        self._thread = None

    def _run(self) -> None:
        index = 0
        while not self._stop.is_set():
            frame = _THINKING_FRAMES[index % len(_THINKING_FRAMES)]
            self._write(f"\r{frame} Thinking...")
            index += 1
            self._stop.wait(self._interval)

    def _clear_line(self) -> None:
        self._write("\r\033[2K")

    def _write(self, text: str) -> None:
        file = self._console.file
        file.write(text)
        file.flush()


def _get_ollama_models() -> list[str]:
    result = subprocess.run(
        ["ollama", "list"],
        capture_output=True,
        text=True,
        check=False,
    )

    models = []
    for line in result.stdout.splitlines()[1:]:
        parts = line.split()
        if parts:
            models.append(parts[0])

    return models


def _create_one_shot_reminder(text: str, *, store=None) -> str | None:
    from grandpa.reminder_parser import ReminderParseError, parse_reminder_phrase
    from grandpa.reminders import ReminderStore

    try:
        parsed = parse_reminder_phrase(text)
    except ReminderParseError:
        return None
    reminder_store = store or ReminderStore()
    reminder = reminder_store.create(
        parsed.message,
        parsed.due_at,
        source={
            "cli": "grandpa chat",
            "input": text,
            "matched_expression": parsed.matched_expression,
        },
    )
    return f"Reminder created: {reminder.message} at {reminder.due_at.isoformat()}."


def _handle_memory_slash_command(command: str, *, store=None) -> str | None:
    if not command.startswith("/memory"):
        return None
    from grandpa.memory_context import MemoryStore

    memory_store = store or MemoryStore()
    parts = command.split(maxsplit=2)
    if len(parts) == 1:
        return (
            "Memory commands:\n"
            "- /memory list\n"
            "- /memory all\n"
            "- /memory search <query>\n"
            "- /memory search <query> --all\n"
            "- /memory forget <query or id>\n"
            "You can also say: remember my name is Hari"
        )
    action = parts[1].lower()
    argument = parts[2].strip() if len(parts) > 2 else ""
    if action == "list":
        return _format_user_memories(memory_store.list_memories())
    if action == "all":
        return _format_memories(memory_store.list_memories())
    if action == "search":
        if not argument:
            return "Usage: /memory search <query>"
        include_internal = _strip_all_flag(argument)
        results = memory_store.search_memories(include_internal[0])
        results = _filter_memory_search_results(include_internal[0], results)
        if not include_internal[1]:
            results = _user_facing_memories(results)
        return _format_memories(results, heading="Matching memories:")
    if action == "forget":
        if not argument:
            return "Usage: /memory forget <query or id>"
        removed = memory_store.forget(argument)
        if removed:
            noun = "memory" if removed == 1 else "memories"
            return f"Forgot {removed} {noun}."
        return "No matching memory found."
    return "Unknown memory command. Try /memory for help."


def _handle_reminders_slash_command(command: str, *, store=None) -> str | None:
    if not command.startswith("/reminders"):
        return None
    from grandpa.reminders import ReminderStore

    reminder_store = store or ReminderStore()
    parts = command.split(maxsplit=2)
    if len(parts) == 1:
        return (
            "Reminder commands:\n"
            "- /reminders list\n"
            "- /reminders all\n"
            "- /reminders cancel <id>\n"
            "You can also say: remind me in 30 minutes to drink water"
        )
    action = parts[1].lower()
    argument = parts[2].strip() if len(parts) > 2 else ""
    if action == "list":
        return _format_reminders(
            reminder_store.list(status="pending"), empty="No pending reminders found."
        )
    if action == "all":
        return _format_reminders(reminder_store.list(), empty="No reminders found.")
    if action == "cancel":
        if not argument:
            return "Usage: /reminders cancel <id>"
        reminder = reminder_store.cancel(argument)
        if reminder is None:
            return "Reminder not found."
        if reminder.status == "cancelled":
            return "Reminder cancelled."
        return f"Reminder is already {reminder.status}."
    return "Unknown reminder command. Try /reminders for help."


def _handle_files_slash_command(command: str) -> str | None:
    if not command.startswith("/files"):
        return None
    parts = command.split(maxsplit=2)
    if len(parts) == 1 or (len(parts) > 1 and parts[1].lower() == "help"):
        return (
            "File commands:\n"
            "- /files search <query>\n"
            "- /files recent\n"
            "- /files create-folder <name>\n"
            "- /files create-file <name>\n"
            "- /files rename <source> <destination>\n"
            "- /files copy <source> <destination>\n"
            "- /files move <source> <destination>\n"
            "- /files delete <path>\n"
            "- /files open <path>\n"
            "- /files zip <path>\n"
            "- /files extract <archive>\n"
            "- /files info <path>"
        )
    action = parts[1].lower()
    argument = parts[2].strip() if len(parts) > 2 else ""
    if action == "recent":
        from grandpa.file_assistant import handle_file_command

        return handle_file_command("show recent files").message
    command_text = _files_slash_to_natural(action, argument)
    if command_text is None:
        return "Unknown file command. Try /files help."
    from grandpa.file_assistant import handle_file_command

    return handle_file_command(command_text).message


def _files_slash_to_natural(action: str, argument: str) -> str | None:
    if action == "search" and argument:
        return f"find {argument}"
    if action == "create-folder" and argument:
        return f"create folder {argument}"
    if action == "create-file" and argument:
        return f"create file {argument}"
    if action in {"rename", "copy", "move"} and argument:
        parts = argument.split(maxsplit=1)
        if len(parts) != 2:
            return None
        return f"{action} {parts[0]} to {parts[1]}"
    if action == "delete" and argument:
        return f"delete {argument}"
    if action == "open" and argument:
        return f"open {argument}"
    if action == "zip" and argument:
        return f"zip {argument}"
    if action == "extract" and argument:
        return f"extract {argument}"
    if action == "info" and argument:
        return f"show properties of {argument}"
    return None


def _handle_browser_slash_command(command: str) -> str | None:
    if not command.startswith("/browser"):
        return None
    parts = command.split(maxsplit=3)
    if len(parts) == 1 or (len(parts) > 1 and parts[1].lower() == "help"):
        return (
            "Browser commands:\n"
            "- /browser open <url or site>\n"
            "- /browser search <query>\n"
            "- /browser search google <query>\n"
            "- /browser search youtube <query>\n"
            "- /browser search github <query>\n"
            "- /browser new-tab\n"
            "- /browser close-tab\n"
            "- /browser refresh\n"
            "- /browser back\n"
            "- /browser forward\n"
            "- /browser history\n"
            "- /browser downloads\n"
            "- /browser bookmarks\n"
            "- /browser current\n"
            "- /browser title\n"
            "- /browser url\n"
            "- /browser read\n"
            "- /browser summarize\n"
            "- /browser find <text>\n"
            "- /browser links\n"
            "- /browser tabs"
        )
    awareness_text = _browser_slash_to_awareness(command)
    if awareness_text is not None:
        from grandpa.browser_awareness import handle_browser_awareness_command

        return handle_browser_awareness_command(awareness_text).message
    automation_text = _browser_slash_to_natural(command)
    if automation_text is None:
        return "Unknown browser command. Try /browser help."
    from grandpa.browser import handle_browser_command

    return handle_browser_command(automation_text).message


def _browser_slash_to_awareness(command: str) -> str | None:
    parts = command.split(maxsplit=2)
    action = parts[1].lower() if len(parts) > 1 else ""
    mapping = {
        "current": "what page am i on",
        "title": "what is the title of this page",
        "url": "show the current url",
        "read": "read this page",
        "summarize": "summarize this page",
        "links": "list the links on this page",
        "tabs": "what tabs are open",
        "selected": "read selected text",
    }
    if action == "find" and len(parts) >= 3 and parts[2].strip():
        return f"find text {parts[2].strip()} on this page"
    return mapping.get(action)


def _browser_slash_to_natural(command: str) -> str | None:
    parts = command.split(maxsplit=3)
    action = parts[1].lower() if len(parts) > 1 else ""
    if action == "open" and len(parts) >= 3:
        return f"open {command.split(maxsplit=2)[2]}"
    if action == "search":
        if len(parts) == 3:
            return f"search google for {parts[2]}"
        if len(parts) >= 4 and parts[2].lower() in {
            "google",
            "youtube",
            "github",
            "stackoverflow",
            "stack-overflow",
        }:
            provider = (
                "stack overflow"
                if parts[2].lower() in {"stackoverflow", "stack-overflow"}
                else parts[2].lower()
            )
            return f"search {provider} for {parts[3]}"
        if len(parts) >= 3:
            return f"search google for {command.split(maxsplit=2)[2]}"
    mapping = {
        "new-tab": "open a new tab",
        "close-tab": "close current tab",
        "refresh": "refresh page",
        "back": "go back",
        "forward": "go forward",
        "history": "open browser history",
        "downloads": "open browser downloads",
        "bookmarks": "open browser bookmarks",
        "settings": "open browser settings",
    }
    return mapping.get(action)


def _handle_gmail_slash_command(command: str) -> str | None:
    if not command.startswith("/gmail"):
        return None
    parts = command.split(maxsplit=2)
    if len(parts) == 1 or (len(parts) > 1 and parts[1].lower() == "help"):
        return (
            "Gmail commands:\n"
            "- /gmail setup\n"
            "- /gmail status\n"
            "- /gmail inbox\n"
            "- /gmail unread\n"
            "- /gmail search <query>\n"
            "- /gmail read <selector>\n"
            "- /gmail summarize <selector>\n"
            "- /gmail labels\n"
            "- /gmail trash\n"
            "- /gmail archive"
        )
    command_text = _gmail_slash_to_natural(command)
    if command_text is None:
        return "Unknown Gmail command. Try /gmail help."
    from grandpa.gmail import handle_gmail_command

    return handle_gmail_command(command_text).message


def _gmail_slash_to_natural(command: str) -> str | None:
    parts = command.split(maxsplit=2)
    action = parts[1].lower() if len(parts) > 1 else ""
    argument = parts[2].strip() if len(parts) > 2 else ""
    mapping = {
        "setup": "gmail setup",
        "status": "gmail status",
        "disconnect": "gmail disconnect",
        "inbox": "show inbox",
        "unread": "show unread emails",
        "labels": "show gmail labels",
        "trash": "move this email to trash",
        "archive": "archive this email",
        "send": "send the draft",
        "reply": "reply to this email",
        "forward": "forward this email",
    }
    if action == "search" and argument:
        return f"search gmail for {argument}"
    if action == "read":
        return (
            "read latest email"
            if not argument
            else f"read the latest email from {argument}"
        )
    if action == "summarize":
        return "summarize latest email" if not argument else f"summarize {argument}"
    if action == "draft" and argument:
        return f"draft an email to {argument}"
    return mapping.get(action)


def _handle_calendar_slash_command(command: str) -> str | None:
    if not command.startswith("/calendar"):
        return None
    parts = command.split(maxsplit=2)
    if len(parts) == 1 or (len(parts) > 1 and parts[1].lower() == "help"):
        return (
            "Calendar commands:\n"
            "- /calendar setup\n"
            "- /calendar status\n"
            "- /calendar today\n"
            "- /calendar tomorrow\n"
            "- /calendar week\n"
            "- /calendar upcoming\n"
            "- /calendar free\n"
            "- /calendar create <details>\n"
            "- /calendar update <details>\n"
            "- /calendar delete <details>"
        )
    command_text = _calendar_slash_to_natural(command)
    if command_text is None:
        return "Unknown Calendar command. Try /calendar help."
    from grandpa.calendar import handle_calendar_command

    return handle_calendar_command(command_text).message


def _calendar_slash_to_natural(command: str) -> str | None:
    parts = command.split(maxsplit=2)
    action = parts[1].lower() if len(parts) > 1 else ""
    argument = parts[2].strip() if len(parts) > 2 else ""
    mapping = {
        "setup": "calendar setup",
        "status": "calendar status",
        "disconnect": "calendar disconnect",
        "today": "calendar today",
        "tomorrow": "calendar tomorrow",
        "week": "calendar week",
        "upcoming": "calendar upcoming",
        "free": "show free time",
    }
    if action == "free" and argument:
        return f"show free time {argument}"
    if action == "search" and argument:
        return f"search calendar for {argument}"
    if action == "create":
        return "create a meeting" if not argument else f"create a meeting {argument}"
    if action == "update":
        return "move my meeting" if not argument else f"move my meeting to {argument}"
    if action == "delete":
        return "cancel meeting" if not argument else f"cancel meeting {argument}"
    return mapping.get(action)


def _handle_notes_slash_command(command: str) -> str | None:
    if not command.startswith("/notes"):
        return None
    parts = command.split(maxsplit=2)
    if len(parts) == 1 or (len(parts) > 1 and parts[1].lower() == "help"):
        return (
            "Notes commands:\n"
            "- /notes list\n"
            "- /notes recent\n"
            "- /notes search <query>\n"
            "- /notes open <name>\n"
            "- /notes create <name>\n"
            "- /notes append <name> <text>\n"
            "- /notes rename <old> to <new>\n"
            "- /notes delete <name>\n"
            "- /notes archive <name>\n"
            "- /notes restore <name>\n"
            "- /notes pin <name>\n"
            "- /notes unpin <name>"
        )
    command_text = _notes_slash_to_natural(command)
    if command_text is None:
        return "Unknown Notes command. Try /notes help."
    from grandpa.notes import handle_notes_command

    return handle_notes_command(command_text).message


def _notes_slash_to_natural(command: str) -> str | None:
    parts = command.split(maxsplit=2)
    action = parts[1].lower() if len(parts) > 1 else ""
    argument = parts[2].strip() if len(parts) > 2 else ""
    mapping = {
        "list": "show my notes",
        "recent": "list recent notes",
    }
    if action == "search" and argument:
        return f"search notes for {argument}"
    if action == "open" and argument:
        return f"open my note {argument}"
    if action == "create" and argument:
        return f"create a note called {argument}"
    if action == "append" and argument:
        return f"notes append {argument}"
    if action == "rename" and argument:
        return f"rename note {argument}"
    if action in {"delete", "archive", "restore", "pin", "unpin"} and argument:
        return f"{action} note {argument}"
    return mapping.get(action)


def _handle_downloads_slash_command(command: str) -> str | None:
    if not command.startswith("/downloads"):
        return None
    parts = command.split(maxsplit=2)
    if len(parts) == 1 or (len(parts) > 1 and parts[1].lower() == "help"):
        return (
            "Downloads commands:\n"
            "- /downloads recent\n"
            "- /downloads today\n"
            "- /downloads latest\n"
            "- /downloads search <query>\n"
            "- /downloads large\n"
            "- /downloads incomplete\n"
            "- /downloads organize\n"
            "- /downloads move <selector> <destination>\n"
            "- /downloads archive <selector>\n"
            "- /downloads delete <selector>\n"
            "- /downloads duplicates\n"
            "- /downloads info <selector>"
        )
    command_text = _downloads_slash_to_natural(command)
    if command_text is None:
        return "Unknown Downloads command. Try /downloads help."
    from grandpa.downloads import handle_downloads_command

    return handle_downloads_command(command_text).message


def _downloads_slash_to_natural(command: str) -> str | None:
    parts = command.split(maxsplit=2)
    action = parts[1].lower() if len(parts) > 1 else ""
    argument = parts[2].strip() if len(parts) > 2 else ""
    mapping = {
        "recent": "show recent downloads",
        "today": "show downloads from today",
        "latest": "open latest download",
        "large": "show large downloads",
        "incomplete": "show incomplete downloads",
        "organize": "organize my downloads folder",
        "duplicates": "show duplicate downloads",
    }
    if action == "search" and argument:
        return f"find downloaded {argument}"
    if action == "info" and argument:
        return f"downloads info {argument}"
    if action == "archive" and argument:
        return f"downloads archive {argument}"
    if action == "delete" and argument:
        return f"downloads delete {argument}"
    if action == "move" and argument:
        return f"downloads move {argument}"
    return mapping.get(action)


def _handle_search_slash_command(command: str) -> str | None:
    if not command.startswith("/search"):
        return None
    parts = command.split(maxsplit=2)
    if len(parts) == 1 or (len(parts) > 1 and parts[1].lower() == "help"):
        return (
            "Search commands:\n"
            "- /search web <query>\n"
            "- /search news <query>\n"
            "- /search official <query>\n"
            "- /search recent <query>\n"
            "- /search sources\n"
            "- /search clear-cache"
        )
    command_text = _search_slash_to_natural(command)
    if command_text is None:
        return "Unknown Search command. Try /search help."
    from grandpa.web_search import handle_web_search_command

    return handle_web_search_command(command_text).message


def _search_slash_to_natural(command: str) -> str | None:
    parts = command.split(maxsplit=2)
    action = parts[1].lower() if len(parts) > 1 else ""
    argument = parts[2].strip() if len(parts) > 2 else ""
    if action == "web" and argument:
        return f"search the web for {argument}"
    if action == "news" and argument:
        return f"search news for {argument}"
    if action == "official" and argument:
        return f"search official docs for {argument}"
    if action == "recent" and argument:
        return f"find recent articles from the last week about {argument}"
    if action == "sources":
        return "show sources"
    if action == "clear-cache":
        return "clear web search cache"
    return None


def _handle_apps_slash_command(command: str) -> str | None:
    if not command.startswith("/apps"):
        return None
    parts = command.split(maxsplit=2)
    if len(parts) == 1 or (len(parts) > 1 and parts[1].lower() == "help"):
        return (
            "Application commands:\n"
            "- /apps scan\n"
            "- /apps refresh\n"
            "- /apps list\n"
            "- /apps search <name>\n"
            "- /apps find <name>\n"
            "- /apps running\n"
            "- /apps open <name>"
        )
    action = parts[1].lower()
    argument = parts[2].strip() if len(parts) > 2 else ""
    from grandpa.desktop.automation import handle_desktop_command

    if action in {"scan", "refresh"}:
        return handle_desktop_command("refresh application database").message
    if action == "list":
        return handle_desktop_command("list installed applications").message
    if action == "running":
        return handle_desktop_command("what apps are running").message
    if action in {"search", "find"} and argument:
        return handle_desktop_command(f"search applications for {argument}").message
    if action == "open" and argument:
        return handle_desktop_command(f"open {argument}").message
    return "Unknown applications command. Try /apps help."


def _handle_module_slash_command(command: str) -> str | None:
    command_name = command.split(maxsplit=1)[0].lower()
    return command_help_text(command_name)


def _handle_help_slash_command(command: str) -> str | None:
    parts = command.lower().split(maxsplit=1)
    if parts[0] != "/help":
        return None
    if len(parts) == 1:
        return None
    topic = parts[1].strip()
    if topic == "commands":
        return help_commands_text()
    if topic == "examples":
        return help_examples_text()
    if topic == "modules":
        return help_modules_text()
    if topic == "shortcuts":
        return help_shortcuts_text()
    return "Unknown help topic. Try /help commands, /help examples, /help modules, or /help shortcuts."


def _unknown_slash_command_message(command: str) -> str:
    return unknown_command_message(command)


def _handle_natural_assistant_intent(
    text: str,
    *,
    memory_store=None,
    reminder_store=None,
    spoken: bool = False,
    automation_service=None,
) -> str | None:
    from grandpa.automation import WindowsCommandPipeline

    pipeline_result = WindowsCommandPipeline(
        automation_service=automation_service,
        source="chat",
    ).handle(text, spoken=spoken)
    if not pipeline_result.should_fallback:
        return pipeline_result.message
    from grandpa.projects import handle_project_command

    project_result = handle_project_command(text)
    if not project_result.should_fallback:
        return project_result.message
    memory_message = _handle_natural_memory_intent(text, store=memory_store)
    if memory_message is not None:
        return memory_message
    return _handle_natural_reminder_intent(text, store=reminder_store)


def _handle_natural_memory_intent(text: str, *, store=None) -> str | None:
    normalized = _normalize_local_intent(text)
    if normalized in NATURAL_MEMORY_ALL_INTENTS:
        from grandpa.memory_context import MemoryStore

        memory_store = store or MemoryStore()
        return _format_memories(memory_store.list_memories())
    if normalized in NATURAL_MEMORY_LIST_INTENTS:
        from grandpa.memory_context import MemoryStore

        memory_store = store or MemoryStore()
        return _format_user_memories(memory_store.list_memories())
    if normalized in NATURAL_MEMORY_RECALL_INTENTS:
        from grandpa.memory_context import MemoryStore, handle_memory_command

        memory_store = store or MemoryStore()
        result = handle_memory_command(text, store=memory_store)
        return (
            result.message
            if not result.should_fallback
            else _format_memories(memory_store.list_memories())
        )
    return None


def _handle_natural_reminder_intent(text: str, *, store=None) -> str | None:
    normalized = _normalize_local_intent(text)
    if _is_natural_reminder_list_intent(normalized):
        from grandpa.reminders import ReminderStore

        reminder_store = store or ReminderStore()
        return _format_reminders(
            reminder_store.list(status="pending"),
            empty=(
                "No pending reminders found. You can create one with: "
                "remind me in 30 minutes to drink water"
            ),
        )
    cancel_match = re.match(r"^(cancel|delete|remove)\s+reminder\s+(.+)$", normalized)
    if cancel_match:
        from grandpa.reminders import ReminderStore

        reminder_store = store or ReminderStore()
        reminder_id = cancel_match.group(2).strip()
        reminder = reminder_store.cancel(reminder_id)
        if reminder is None:
            return "Reminder not found. Use /reminders list to see reminder IDs."
        if reminder.status == "cancelled":
            return "Reminder cancelled."
        return f"Reminder is already {reminder.status}."
    return None


def _is_natural_reminder_list_intent(normalized: str) -> bool:
    if normalized in NATURAL_REMINDER_LIST_INTENTS:
        return True
    return bool(
        re.fullmatch(r"(show|list)\s+(me\s+)?(my\s+)?reminders", normalized)
        or re.fullmatch(r"what\s+reminders?\s+do\s+i\s+have", normalized)
        or re.fullmatch(r"what\s+are\s+my\s+reminders", normalized)
        or re.fullmatch(r"do\s+i\s+have\s+any\s+reminders", normalized)
    )


def _format_memories(items: list[dict], *, heading: str = "Saved memories:") -> str:
    if not items:
        return "No memories found."
    lines = [heading]
    for item in items[:20]:
        lines.append(
            f"- #{item['id']} {item['category']}/{item['key']}: {item['value']}"
        )
    return "\n".join(lines)


def _format_user_memories(items: list[dict]) -> str:
    visible = _user_facing_memories(items)
    if not visible:
        return (
            "No user-facing memories found.\n"
            "Use /memory all to show internal memories.\n"
            "You can save one with: remember my name is Hari"
        )
    grouped: dict[str, list[dict]] = {
        "Personal": [],
        "Projects": [],
        "Tools & Preferences": [],
        "Other": [],
    }
    for item in visible[:15]:
        grouped[_memory_group(item)].append(item)
    lines = ["Saved memories:"]
    for heading, group_items in grouped.items():
        if not group_items:
            continue
        lines.append("")
        lines.append(heading)
        for item in group_items:
            lines.append(f"- {_friendly_memory_line(item)}")
    lines.append("")
    lines.append("Use /memory all to show internal memories.")
    return "\n".join(lines)


def _user_facing_memories(items: list[dict]) -> list[dict]:
    visible = [item for item in items if _is_user_facing_memory(item)]
    deduped: list[dict] = []
    seen: set[str] = set()
    for item in visible:
        fingerprint = _memory_fingerprint(item)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        deduped.append(item)
    return deduped


def _filter_memory_search_results(query: str, items: list[dict]) -> list[dict]:
    query_terms = _memory_search_terms(query)
    if not query_terms:
        return []
    return [item for item in items if _memory_matches_query_terms(item, query_terms)]


def _memory_matches_query_terms(item: dict, query_terms: list[str]) -> bool:
    candidate = _normalize_memory_text(
        " ".join(
            str(item.get(field) or "")
            for field in ("category", "key", "value", "source")
        )
    )
    if not candidate:
        return False
    phrase = " ".join(query_terms)
    if len(query_terms) > 1 and phrase in candidate:
        return True
    candidate_terms = set(candidate.split())
    return all(term in candidate_terms for term in query_terms)


def _memory_search_terms(query: str) -> list[str]:
    return _normalize_memory_text(query).split()


def _is_user_facing_memory(item: dict) -> bool:
    category = str(item.get("category") or "").lower()
    key = str(item.get("key") or "").lower()
    source = str(item.get("source") or "").lower()
    value = str(item.get("value") or "").lower()
    internal_haystack = f"{category} {key} {value} {source}"
    if category in {"work_context", "diagnostics"}:
        return False
    internal_markers = (
        "agent_goal",
        "burn_in",
        "burn in",
        "diagnostics",
        "multi_agent",
        "diagnostic",
        "readiness",
        "browser",
        "planner",
        "generated",
        "test marker",
        "validation marker",
        "work_context",
    )
    return not any(marker in internal_haystack for marker in internal_markers)


def _memory_fingerprint(item: dict) -> str:
    value = _normalize_memory_text(str(item.get("value") or ""))
    if value:
        return f"{_memory_group(item)}:{value}"
    return f"{_memory_group(item)}:{_normalize_memory_text(str(item.get('key') or ''))}"


def _normalize_memory_text(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def _memory_group(item: dict) -> str:
    category = str(item.get("category") or "")
    key = str(item.get("key") or "")
    key_lower = key.lower()
    if category == "project" or "project" in key:
        return "Projects"
    if (
        category in {"preferences", "apps_tools"}
        or key_lower.startswith("uses")
        or key_lower.startswith("preferred")
    ):
        return "Tools & Preferences"
    if category == "people" or key in {"name", "my_name"}:
        return "Personal"
    return "Other"


def _friendly_memory_line(item: dict) -> str:
    key = str(item.get("key") or "").replace("_", " ")
    value = str(item.get("value") or "")
    if key:
        return f"{key}: {value}"
    return value


def _strip_all_flag(argument: str) -> tuple[str, bool]:
    parts = argument.split()
    filtered = [part for part in parts if part != "--all"]
    return " ".join(filtered).strip(), len(filtered) != len(parts)


def _format_reminders(items: list, *, empty: str) -> str:
    if not items:
        return empty
    lines = ["Reminders:"]
    for reminder in items[:20]:
        lines.append(
            f"- {reminder.id} [{reminder.status}] {reminder.message} at {reminder.due_at.isoformat()}"
        )
    return "\n".join(lines)


def _normalize_local_intent(text: str) -> str:
    return " ".join(text.lower().strip(" ?!.").split())


@click.command()
@click.option("-e", "--engine", "engine_key", default=None, help="Engine backend.")
@click.option("-m", "--model", "model_name", default=None, help="Model to use.")
@click.option("-a", "--agent", "agent_name", default=None, help="Agent type.")
@click.option("--tools", default=None, help="Comma-separated tool names.")
@click.option("--system", "system_prompt", default=None, help="Custom system prompt.")
def chat(
    engine_key: str | None,
    model_name: str | None,
    agent_name: str | None,
    tools: str | None,
    system_prompt: str | None,
) -> None:
    """Start an interactive multi-turn chat session.

    Commands during chat:
      /quit, /exit  — end session
      /clear        — clear conversation history
      /model        — show current model
      /help         — show available commands
      /history      — show conversation history
    """
    console = Console(stderr=True)

    config = load_config()

    # Resolve engine
    from grandpa.engine import get_engine
    from grandpa.intelligence import register_builtin_models

    register_builtin_models()

    resolved = get_engine(config, engine_key)
    if resolved is None:
        console.print("[red]No inference engine available.[/red]")
        sys.exit(1)

    engine_name, engine = resolved
    model = model_name or config.intelligence.default_model
    if not model:
        from grandpa.engine import discover_engines, discover_models

        all_engines = discover_engines(config)
        all_models = discover_models(all_engines)
        engine_models = all_models.get(engine_name, [])
        if engine_models:
            model = engine_models[0]
        else:
            console.print("[red]No model available.[/red]")
            sys.exit(1)

    # Resolve agent (optional)
    agent = None
    agent_key = agent_name or config.agent.default_agent
    if agent_key and agent_key != "none":
        try:
            from grandpa.agents import load_builtin_agents

            load_builtin_agents()
            from grandpa.core.events import EventBus
            from grandpa.core.registry import AgentRegistry

            if AgentRegistry.contains(agent_key):
                agent_cls = AgentRegistry.get(agent_key)
                kwargs: dict = {"bus": EventBus()}

                if getattr(agent_cls, "accepts_tools", False):
                    tool_names_list = resolve_tool_names(
                        tools,
                        getattr(config.tools, "enabled", None),
                        getattr(config.agent, "tools", None),
                    )
                    if tool_names_list:
                        from grandpa.tools import load_builtin_tools

                        load_builtin_tools()
                        from grandpa.core.registry import ToolRegistry
                        from grandpa.tools._stubs import BaseTool

                        tool_instances = []
                        for tname in tool_names_list:
                            if ToolRegistry.contains(tname):
                                tcls = ToolRegistry.get(tname)
                                if isinstance(tcls, type) and issubclass(
                                    tcls, BaseTool
                                ):
                                    tool_instances.append(tcls())
                                elif isinstance(tcls, BaseTool):
                                    tool_instances.append(tcls)
                        if tool_instances:
                            kwargs["tools"] = tool_instances
                    kwargs["max_turns"] = config.agent.max_turns

                    def _confirm(prompt: str) -> bool:
                        console.print(
                            f"[yellow]Confirm:[/yellow] {prompt} [y/N] ",
                            end="",
                        )
                        ans = input().strip().lower()
                        return ans in ("y", "yes")

                    kwargs["interactive"] = True
                    kwargs["confirm_callback"] = _confirm
                agent = agent_cls(engine, model, **kwargs)
        except Exception as exc:
            console.print(f"[yellow]Agent '{agent_key}' failed: {exc}[/yellow]")

    # Print banner
    console.print()

    render_chat_home(
        console=console,
        engine=engine_name,
        model=model,
        agent=agent_key or "direct",
    )

    console.print()

    from grandpa.cli._bg_state import get_status

    # Completion-notification dispatcher (fires once per task per session)
    from grandpa.cli._chat_notifications import NotificationDispatcher

    _notifications = NotificationDispatcher(get_status())

    # Conversation state
    history: List[Message] = []
    if system_prompt:
        history.append(Message(role=Role.SYSTEM, content=system_prompt))
    from grandpa.automation import ScreenAutomationService

    automation_service = ScreenAutomationService()

    # REPL loop
    while True:
        for note in _notifications.diff(get_status()):
            console.print(f"[dim cyan]{note}[/dim cyan]")

        user_input = read_chat_input()

        if user_input is None:
            console.print("\n[dim]Goodbye![/dim]")
            break

        user_input = user_input.strip()
        if not user_input:
            continue

        render_user_message(console, user_input)
        console.print()

        # Handle slash commands
        cmd = user_input.lower()
        if cmd == "/":
            continue
        if cmd in ("/quit", "/exit", "/q"):
            console.print("[dim]Goodbye![/dim]")
            break
        elif cmd == "/clear":
            history = []
            if system_prompt:
                history.append(Message(role=Role.SYSTEM, content=system_prompt))
            console.print("[dim]History cleared.[/dim]")
            continue
        elif cmd == "/model" or cmd.startswith("/model "):
            requested_model = (
                user_input.split(maxsplit=1)[1].strip()
                if len(user_input.split(maxsplit=1)) > 1
                else ""
            )
            if requested_model:
                model = requested_model
                console.print(f"[green]✓[/green] Model changed to [cyan]{model}[/cyan]")
                continue

            models = _get_ollama_models()

            if not models:
                console.print("[red]No Ollama models found.[/red]")
                continue

            selected = select_from_list("Select Model", models)

            if selected:
                model = selected
                console.print(f"[green]✓[/green] Model changed to [cyan]{model}[/cyan]")

            continue
        elif cmd == "/help":
            render_help(console)
            continue
        elif cmd.startswith("/help "):
            console.print(
                _handle_help_slash_command(user_input) or "Unknown help topic."
            )
            continue
        elif cmd == "/history":
            if not history:
                console.print("[dim]No history yet.[/dim]")
            else:
                for msg in history:
                    role_str = msg.role if isinstance(msg.role, str) else msg.role.value
                    role = role_str.upper()
                    console.print(f"[bold]{role}:[/bold] {msg.content[:200]}")
            continue
        elif cmd.startswith("/memory"):
            console.print(
                _handle_memory_slash_command(user_input) or "Unknown memory command."
            )
            continue
        elif cmd.startswith("/reminders"):
            console.print(
                _handle_reminders_slash_command(user_input)
                or "Unknown reminder command."
            )
            continue
        elif cmd.startswith("/notes"):
            console.print(
                _handle_notes_slash_command(user_input) or "Unknown Notes command."
            )
            continue
        elif cmd.startswith("/downloads"):
            console.print(
                _handle_downloads_slash_command(user_input)
                or "Unknown Downloads command."
            )
            continue
        elif cmd.startswith("/search"):
            console.print(
                _handle_search_slash_command(user_input) or "Unknown Search command."
            )
            continue
        elif cmd.startswith("/apps"):
            console.print(
                _handle_apps_slash_command(user_input)
                or "Unknown applications command."
            )
            continue
        elif cmd.startswith("/files"):
            console.print(
                _handle_files_slash_command(user_input) or "Unknown file command."
            )
            continue
        elif cmd.startswith("/browser"):
            console.print(
                _handle_browser_slash_command(user_input) or "Unknown browser command."
            )
            continue
        elif cmd.startswith("/gmail"):
            console.print(
                _handle_gmail_slash_command(user_input) or "Unknown Gmail command."
            )
            continue
        elif cmd.startswith("/calendar"):
            console.print(
                _handle_calendar_slash_command(user_input)
                or "Unknown Calendar command."
            )
            continue
        elif cmd.startswith("/"):
            module_help = _handle_module_slash_command(user_input)
            if module_help is not None:
                console.print(module_help)
            else:
                console.print(_unknown_slash_command_message(user_input))
            continue

        from grandpa.core_ai_brain import (
            build_brain_context,
            process_user_message,
            record_assistant_outcome,
        )
        from grandpa.memory_context import handle_memory_command, remember_conversation

        remember_conversation("user", user_input)
        brain_analysis = process_user_message(user_input)
        effective_user_input = brain_analysis.effective_text

        natural_intent_message = _handle_natural_assistant_intent(
            effective_user_input,
            automation_service=automation_service,
        )
        if natural_intent_message is not None:
            history.append(Message(role=Role.USER, content=user_input))
            history.append(Message(role=Role.ASSISTANT, content=natural_intent_message))
            remember_conversation("assistant", natural_intent_message)
            record_assistant_outcome(
                brain_analysis,
                assistant_text=natural_intent_message,
                kind="local",
                target=None,
                status="handled",
            )
            console.print()
            console.print(Markdown(natural_intent_message))
            console.print()
            continue

        reminder_message = _create_one_shot_reminder(effective_user_input)
        if reminder_message is not None:
            history.append(Message(role=Role.USER, content=user_input))
            history.append(Message(role=Role.ASSISTANT, content=reminder_message))
            remember_conversation("assistant", reminder_message)
            record_assistant_outcome(
                brain_analysis,
                assistant_text=reminder_message,
                kind="reminder",
                target=None,
                status="handled",
            )
            console.print()
            console.print(Markdown(reminder_message))
            console.print()
            continue

        from grandpa.notes import handle_notes_command

        notes_action = handle_notes_command(effective_user_input)
        if not notes_action.should_fallback:
            history.append(Message(role=Role.USER, content=user_input))
            history.append(Message(role=Role.ASSISTANT, content=notes_action.message))
            remember_conversation("assistant", notes_action.message)
            record_assistant_outcome(
                brain_analysis,
                assistant_text=notes_action.message,
                kind="notes",
                target=notes_action.action.query if notes_action.action else None,
                status=notes_action.status,
            )
            console.print()
            console.print(Markdown(notes_action.message))
            console.print()
            continue

        from grandpa.downloads import handle_downloads_command

        downloads_action = handle_downloads_command(effective_user_input)
        if not downloads_action.should_fallback:
            history.append(Message(role=Role.USER, content=user_input))
            history.append(
                Message(role=Role.ASSISTANT, content=downloads_action.message)
            )
            remember_conversation("assistant", downloads_action.message)
            record_assistant_outcome(
                brain_analysis,
                assistant_text=downloads_action.message,
                kind="downloads",
                target=downloads_action.action.query
                if downloads_action.action
                else None,
                status=downloads_action.status,
            )
            console.print()
            console.print(Markdown(downloads_action.message))
            console.print()
            continue

        from grandpa.web_search import handle_web_search_command

        web_search_action = handle_web_search_command(effective_user_input)
        if not web_search_action.should_fallback:
            history.append(Message(role=Role.USER, content=user_input))
            history.append(
                Message(role=Role.ASSISTANT, content=web_search_action.message)
            )
            remember_conversation("assistant", web_search_action.message)
            record_assistant_outcome(
                brain_analysis,
                assistant_text=web_search_action.message,
                kind="web_search",
                target=web_search_action.action.query.text
                if web_search_action.action and web_search_action.action.query
                else None,
                status=web_search_action.status,
            )
            console.print()
            console.print(Markdown(web_search_action.message))
            console.print()
            continue

        memory_result = handle_memory_command(effective_user_input)
        if not memory_result.should_fallback:
            history.append(Message(role=Role.USER, content=user_input))
            history.append(Message(role=Role.ASSISTANT, content=memory_result.message))
            remember_conversation("assistant", memory_result.message)
            record_assistant_outcome(
                brain_analysis,
                assistant_text=memory_result.message,
                kind=memory_result.kind,
                target=memory_result.target,
                status=memory_result.status,
            )
            console.print()
            console.print(Markdown(memory_result.message))
            console.print()
            continue

        from grandpa.calendar import handle_calendar_command

        calendar_action = handle_calendar_command(effective_user_input)
        if not calendar_action.should_fallback:
            history.append(Message(role=Role.USER, content=user_input))
            history.append(
                Message(role=Role.ASSISTANT, content=calendar_action.message)
            )
            remember_conversation("assistant", calendar_action.message)
            record_assistant_outcome(
                brain_analysis,
                assistant_text=calendar_action.message,
                kind="calendar",
                target=calendar_action.action.query if calendar_action.action else None,
                status=calendar_action.status,
            )
            console.print()
            console.print(Markdown(calendar_action.message))
            console.print()
            continue

        from grandpa.gmail import handle_gmail_command

        gmail_action = handle_gmail_command(effective_user_input)
        if not gmail_action.should_fallback:
            history.append(Message(role=Role.USER, content=user_input))
            history.append(Message(role=Role.ASSISTANT, content=gmail_action.message))
            remember_conversation("assistant", gmail_action.message)
            record_assistant_outcome(
                brain_analysis,
                assistant_text=gmail_action.message,
                kind="gmail",
                target=gmail_action.action.query if gmail_action.action else None,
                status=gmail_action.status,
            )
            console.print()
            console.print(Markdown(gmail_action.message))
            console.print()
            continue

        from grandpa.browser_awareness import handle_browser_awareness_command

        browser_awareness = handle_browser_awareness_command(effective_user_input)
        if not browser_awareness.should_fallback:
            history.append(Message(role=Role.USER, content=user_input))
            history.append(
                Message(role=Role.ASSISTANT, content=browser_awareness.message)
            )
            remember_conversation("assistant", browser_awareness.message)
            record_assistant_outcome(
                brain_analysis,
                assistant_text=browser_awareness.message,
                kind="browser_awareness",
                target=browser_awareness.snapshot.url
                if browser_awareness.snapshot
                else None,
                status=browser_awareness.status,
            )
            console.print()
            console.print(Markdown(browser_awareness.message))
            console.print()
            continue

        from grandpa.browser import handle_browser_command

        browser_action = handle_browser_command(effective_user_input)
        if not browser_action.should_fallback:
            history.append(Message(role=Role.USER, content=user_input))
            history.append(Message(role=Role.ASSISTANT, content=browser_action.message))
            remember_conversation("assistant", browser_action.message)
            record_assistant_outcome(
                brain_analysis,
                assistant_text=browser_action.message,
                kind="browser",
                target=browser_action.url
                or (browser_action.action.target if browser_action.action else None),
                status=browser_action.status,
            )
            console.print()
            console.print(Markdown(browser_action.message))
            console.print()
            continue

        from grandpa.desktop.automation import handle_desktop_command

        desktop_action = handle_desktop_command(effective_user_input)
        if not desktop_action.should_fallback:
            history.append(Message(role=Role.USER, content=user_input))
            history.append(Message(role=Role.ASSISTANT, content=desktop_action.message))
            remember_conversation("assistant", desktop_action.message)
            record_assistant_outcome(
                brain_analysis,
                assistant_text=desktop_action.message,
                kind="desktop",
                target=desktop_action.action.target if desktop_action.action else None,
                status=desktop_action.status,
            )
            console.print()
            console.print(Markdown(desktop_action.message))
            console.print()
            continue

        from grandpa.local_actions import handle_local_action

        local_action = handle_local_action(effective_user_input)
        if not local_action.should_fallback:
            history.append(Message(role=Role.USER, content=user_input))
            history.append(Message(role=Role.ASSISTANT, content=local_action.message))
            remember_conversation("assistant", local_action.message)
            record_assistant_outcome(
                brain_analysis,
                assistant_text=local_action.message,
                kind=local_action.kind,
                target=local_action.target,
                status=local_action.status,
            )
            console.print()
            console.print(Markdown(local_action.message))
            console.print()
            continue

        from grandpa.file_assistant import handle_file_command

        file_action = handle_file_command(effective_user_input)
        if not file_action.should_fallback:
            history.append(Message(role=Role.USER, content=user_input))
            history.append(Message(role=Role.ASSISTANT, content=file_action.message))
            remember_conversation("assistant", file_action.message)
            record_assistant_outcome(
                brain_analysis,
                assistant_text=file_action.message,
                kind=getattr(file_action, "kind", "file"),
                target=getattr(file_action, "target", None),
                status=file_action.status,
            )
            console.print()
            console.print(Markdown(file_action.message))
            console.print()
            continue

        from grandpa.task_scheduler import handle_scheduler_command

        scheduler_action = handle_scheduler_command(effective_user_input)
        if not scheduler_action.should_fallback:
            history.append(Message(role=Role.USER, content=user_input))
            history.append(
                Message(role=Role.ASSISTANT, content=scheduler_action.message)
            )
            remember_conversation("assistant", scheduler_action.message)
            record_assistant_outcome(
                brain_analysis,
                assistant_text=scheduler_action.message,
                kind=getattr(scheduler_action, "kind", "routine"),
                target=getattr(scheduler_action, "target", None),
                status=scheduler_action.status,
            )
            console.print()
            console.print(Markdown(scheduler_action.message))
            console.print()
            continue

        # Add user message
        history.append(Message(role=Role.USER, content=effective_user_input))

        # Generate response
        try:
            model_history = [
                Message(role=Role.SYSTEM, content=build_brain_context(brain_analysis)),
                *history,
            ]
            thinking = ThinkingAnimation(console)
            thinking.start()
            try:
                if agent is not None:
                    response = agent.run(effective_user_input)
                    content = (
                        response.content
                        if hasattr(response, "content")
                        else str(response)
                    )
                else:
                    result = engine.generate(model_history, model=model)
                    content = (
                        result.get("content", "")
                        if isinstance(result, dict)
                        else str(result)
                    )
            finally:
                thinking.stop()
            content = clean_assistant_response(content)
            remember_conversation("assistant", content)
            record_assistant_outcome(
                brain_analysis,
                assistant_text=content,
                kind="assistant",
                target=None,
                status="handled",
            )

            history.append(Message(role=Role.ASSISTANT, content=content))
            render_assistant_response(console, Markdown(content))
            console.print()
        except EngineModelNotFoundError as exc:
            console.print(
                f"\n[red]{_model_not_found_message(engine_name, exc)}[/red]\n"
            )
            if engine_name == "ollama":
                model_to_pull = exc.model
                if not click.confirm(f'Pull "{model_to_pull}" now?', default=False):
                    console.print(
                        f"\n[yellow]{_model_pull_guidance(model_to_pull)}[/yellow]\n"
                    )
                    raise click.exceptions.Exit(code=1) from exc
                console.print(
                    f'\n[cyan]Pulling "{model_to_pull}" from Ollama...[/cyan]'
                )
                try:
                    engine.pull_model(model_to_pull)
                except EngineConnectionError as pull_exc:
                    console.print(
                        f"\n[red]{_engine_unavailable_message(engine_name, pull_exc)}[/red]\n"
                    )
                    raise click.exceptions.Exit(code=1) from pull_exc
                console.print(
                    f'[green]Model "{model_to_pull}" was installed. '
                    "Please rerun the chat command.[/green]"
                )
                raise click.exceptions.Exit(code=1) from exc
            raise click.exceptions.Exit(code=1) from exc
        except EngineConnectionError as exc:
            _log_generation_exception(exc)
            console.print(
                f"\n[red]{_engine_unavailable_message(engine_name, exc)}[/red]\n"
            )
            raise click.exceptions.Exit(code=1) from exc
        except EngineModelLoadError as exc:
            _log_generation_exception(exc)
            console.print(f"\n[red]{_model_load_failure_message(exc)}[/red]\n")
            raise click.exceptions.Exit(code=1) from exc
        except KeyboardInterrupt:
            console.print("\n[dim]Generation interrupted.[/dim]")
        except Exception as exc:
            _log_generation_exception(exc)
            cause = clean_error_message(exc, fallback=GENERATION_ERROR_MESSAGE)
            console.print(f"\n[red]{cause}[/red]\n")
        finally:
            pass


__all__ = ["chat"]
