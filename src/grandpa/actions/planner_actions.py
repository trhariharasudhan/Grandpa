"""Low-risk planner diagnostic local-action handlers."""

from __future__ import annotations

HANDLERS = {"planner diagnostics", "show planner diagnostics"}


def try_handle(command: str):
    from grandpa.local_actions import LocalActionResult

    if command not in HANDLERS:
        return None
    return LocalActionResult(
        status="handled",
        kind="pc_control",
        target="runtime_skill|planner.diagnostics",
        message="Checking planner diagnostics.",
        tts_text="Checking planner diagnostics.",
    )
