"""Low-risk screen and visual diagnostic local-action handlers."""

from __future__ import annotations

HANDLERS: dict[str, str] = {
    "screen diagnostics": "screen_diagnostics",
    "show screen diagnostics": "screen_diagnostics",
    "screen awareness diagnostics": "screen_diagnostics",
    "visual diagnostics": "visual_diagnostics",
    "visual targeting diagnostics": "visual_diagnostics",
    "show visual diagnostics": "visual_diagnostics",
    "visual automation diagnostics": "visual_diagnostics",
}


def try_handle(command: str):
    from grandpa.local_actions import LocalActionResult

    target = HANDLERS.get(command)
    if target is None:
        return None
    visual = target == "visual_diagnostics"
    return LocalActionResult(
        status="handled",
        kind="screen",
        target=target,
        message="Checking visual targeting diagnostics." if visual else "Checking screen-awareness diagnostics.",
        tts_text="Checking visual diagnostics." if visual else "Checking screen diagnostics.",
    )
