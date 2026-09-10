"""Application aliases for high-level desktop automation."""

from __future__ import annotations

import re

#: Words that begin a new clause rather than continue an application name.
#: A spoken goal is a sequence of clauses, so text containing one of these is
#: several instructions and not one application: "chrome and go to gmail" is
#: two things to do, not a program by that name.
#:
#: Word boundaries keep ordinary names intact -- "command prompt" contains the
#: letters of "and" but not the word.
_CLAUSE_WORDS = re.compile(r"\b(?:and|then|go to|navigate to)\b")

APP_ALIASES: dict[str, tuple[str, str]] = {
    "chrome": ("chrome", "Chrome"),
    "google chrome": ("chrome", "Chrome"),
    "edge": ("edge", "Microsoft Edge"),
    "microsoft edge": ("edge", "Microsoft Edge"),
    "firefox": ("firefox", "Firefox"),
    "mozilla firefox": ("firefox", "Firefox"),
    "vs code": ("vscode", "VS Code"),
    "vscode": ("vscode", "VS Code"),
    "visual studio code": ("vscode", "VS Code"),
    "code": ("vscode", "VS Code"),
    "notepad": ("notepad", "Notepad"),
    "calculator": ("calculator", "Calculator"),
    "calc": ("calculator", "Calculator"),
    "paint": ("paint", "Paint"),
    "mspaint": ("paint", "Paint"),
    "task manager": ("task_manager", "Task Manager"),
    "file explorer": ("explorer", "File Explorer"),
    "explorer": ("explorer", "File Explorer"),
    "control panel": ("control_panel", "Control Panel"),
    "settings": ("settings", "Settings"),
    "windows settings": ("settings", "Settings"),
}


def resolve_application(value: str) -> tuple[str, str] | None:
    """Resolve a natural app name to a safe app id and display label."""

    return APP_ALIASES.get(value.strip().casefold())


def names_one_application(value: str) -> bool:
    """Whether *value* could be a single application name.

    False for clause-joined text. Parsers that took the whole tail of "open
    chrome and go to gmail" produced an application named "chrome and go to
    gmail"; nothing resolves to that, so the user was told their command
    succeeded and no window appeared. Refusing sends the phrase on to a
    resolver that can handle several clauses, and if none can, the operator
    says it does not know the command -- which is the truth.
    """
    name = value.strip()
    return bool(name) and _CLAUSE_WORDS.search(name) is None


__all__ = ["APP_ALIASES", "names_one_application", "resolve_application"]
