"""Application aliases for high-level desktop automation."""

from __future__ import annotations

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


__all__ = ["APP_ALIASES", "resolve_application"]
