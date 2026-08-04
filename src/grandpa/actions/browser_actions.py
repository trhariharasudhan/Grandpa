"""Low-risk browser local-action handlers."""

from __future__ import annotations

HANDLERS: dict[str, tuple[str, str, str]] = {
    "browser diagnostics": (
        "diagnostics|browser",
        "Checking browser diagnostics.",
        "Checking browser diagnostics.",
    ),
    "show browser diagnostics": (
        "diagnostics|browser",
        "Checking browser diagnostics.",
        "Checking browser diagnostics.",
    ),
    "browser status": (
        "diagnostics|browser",
        "Checking browser diagnostics.",
        "Checking browser diagnostics.",
    ),
}


def try_handle(command: str):
    from grandpa.local_actions import LocalActionResult

    item = HANDLERS.get(command)
    if item is None:
        return None
    target, message, tts = item
    return LocalActionResult(
        status="handled",
        kind="browser",
        target=target,
        message=message,
        tts_text=tts,
    )
