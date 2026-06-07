"""Low-risk desktop local-action handlers."""

from __future__ import annotations

HANDLERS: dict[str, tuple[str, str]] = {
    "list monitors": ("list_monitors", "monitors"),
    "show monitors": ("list_monitors", "monitors"),
    "detect monitors": ("list_monitors", "monitors"),
    "what monitors are connected": ("list_monitors", "monitors"),
    "desktop summary": ("desktop_summary", "desktop"),
    "summarize desktop": ("desktop_summary", "desktop"),
    "pc control diagnostics": ("pc_diagnostics", "diagnostics"),
    "show pc diagnostics": ("pc_diagnostics", "diagnostics"),
    "clipboard history": ("clipboard_history", "clipboard"),
    "show clipboard history": ("clipboard_history", "clipboard"),
}


def try_handle(command: str):
    from grandpa.local_actions import LocalActionResult

    item = HANDLERS.get(command)
    if item is None:
        return None
    action_type, target = item
    return LocalActionResult(
        status="handled",
        kind="pc_control",
        target=f"{action_type}|{target}",
        message="Checking PC control context.",
        tts_text="Checking PC control context.",
    )
