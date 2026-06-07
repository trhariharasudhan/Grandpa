"""Low-risk workflow local-action handlers."""

from __future__ import annotations

HANDLERS = {"workflow status", "workflow diagnostics", "show workflow status"}


def try_handle(command: str):
    from grandpa.local_actions import LocalActionResult

    if command not in HANDLERS:
        return None
    return LocalActionResult(
        status="handled",
        kind="pc_control",
        target="workflow_status|workflows",
        message="Checking workflow status.",
        tts_text="Checking workflow status.",
    )
