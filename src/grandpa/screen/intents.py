"""Shared screen-intent parsing for chat and voice."""

from __future__ import annotations

import re

from grandpa.screen.errors import ScreenError
from grandpa.screen.models import ScreenCommandResult
from grandpa.screen.service import ScreenVisionService


def handle_screen_command(
    text: str, *, service: ScreenVisionService | None = None
) -> ScreenCommandResult:
    normalized = " ".join(re.sub(r"[^a-z0-9]+", " ", text.casefold()).split())
    if not normalized:
        return ScreenCommandResult("no_match", "")
    action = _match_action(normalized)
    if action is None:
        return ScreenCommandResult("no_match", "")
    manager = service or ScreenVisionService()
    try:
        if action == "capture":
            return manager.capture()
        if action == "save":
            return manager.capture(save=True)
        if action == "describe":
            return manager.describe()
        if action == "read":
            return manager.read()
        if action == "error":
            return manager.error()
        if action == "active":
            return manager.active()
        if action == "windows":
            return manager.windows()
    except ScreenError as exc:
        return ScreenCommandResult("error", str(exc), str(exc), "screen")
    return ScreenCommandResult("no_match", "")


def _match_action(normalized: str) -> str | None:
    command_groups = {
        "capture": {
            "take a screenshot",
            "take screenshot",
            "capture screen",
            "capture screenshot",
            "screenshot",
        },
        "save": {
            "save the current screenshot",
            "save current screenshot",
            "take a screenshot and save it",
            "capture and save screenshot",
        },
        "describe": {
            "what is on my screen",
            "what s on my screen",
            "describe this screen",
            "describe my screen",
            "summarize my screen",
            "summarise my screen",
        },
        "read": {
            "read the active window",
            "read active window",
            "read the visible text",
            "read visible text",
            "read my screen",
            "read the screen",
        },
        "error": {
            "read this error",
            "read this error message",
            "what error is on my screen",
            "explain the visible error",
        },
        "active": {
            "what application is active",
            "which application is active",
            "what window is active",
            "what is the active window",
            "what window is open",
            "show active window",
        },
        "windows": {
            "list open windows",
            "list my open windows",
            "show open windows",
            "what windows are open",
        },
    }
    return next(
        (action for action, phrases in command_groups.items() if normalized in phrases),
        None,
    )


__all__ = ["handle_screen_command"]
