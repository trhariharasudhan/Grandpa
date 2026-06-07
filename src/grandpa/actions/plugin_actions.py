"""Low-risk plugin and skill diagnostic local-action handlers."""

from __future__ import annotations

HANDLERS: dict[str, tuple[str, str]] = {
    "skills diagnostics": ("skills.diagnostics", "Checking skills diagnostics."),
    "skill diagnostics": ("skills.diagnostics", "Checking skills diagnostics."),
    "plugin diagnostics": ("plugins.diagnostics", "Checking plugin diagnostics."),
    "plugins diagnostics": ("plugins.diagnostics", "Checking plugin diagnostics."),
}


def try_handle(command: str):
    from grandpa.local_actions import LocalActionResult

    item = HANDLERS.get(command)
    if item is None:
        return None
    target, message = item
    return LocalActionResult(
        status="handled",
        kind="pc_control",
        target=f"runtime_skill|{target}",
        message=message,
        tts_text=message,
    )
