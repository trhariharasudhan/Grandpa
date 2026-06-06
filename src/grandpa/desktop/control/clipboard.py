"""Clipboard service for PC control."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ClipboardControlService:
    """Read, write, clear, inspect, and list metadata-only clipboard history."""

    name: str = "clipboard"

    def execute(self, request: Any, action: str):
        import pyperclip

        from grandpa.desktop_context import (
            inspect_clipboard_text,
            read_clipboard_history,
            record_clipboard_metadata,
        )
        from grandpa.pc_control import LocalActionResponse

        if action == "clipboard_read":
            text = pyperclip.paste()
            metadata = record_clipboard_metadata(text, source="read")
            return LocalActionResponse(True, None, "completed", "Clipboard read.", False, "LOW", {"clipboard_text": text, **metadata})
        if action == "clipboard_write":
            text = str(request.args.get("content", request.target))
            pyperclip.copy(text)
            metadata = record_clipboard_metadata(text, source="write")
            return LocalActionResponse(True, None, "completed", "Clipboard updated.", False, "LOW", metadata)
        if action == "clipboard_inspect":
            text = pyperclip.paste()
            metadata = inspect_clipboard_text(text)
            record_clipboard_metadata(text, source="inspect")
            return LocalActionResponse(True, None, "completed", "Clipboard inspected.", False, "LOW", metadata)
        if action == "clipboard_history":
            result = read_clipboard_history(int(request.args.get("limit", 20)))
            return LocalActionResponse(
                result.supported,
                None,
                "completed" if result.supported else "failed",
                result.message,
                False,
                "LOW",
                result.evidence,
                None if result.supported else "clipboard_history_unavailable",
            )
        pyperclip.copy("")
        metadata = record_clipboard_metadata("", source="clear")
        return LocalActionResponse(True, None, "completed", "Clipboard cleared.", False, "LOW", {"cleared": True, **metadata})

    def diagnostics(self) -> dict[str, Any]:
        try:
            import pyperclip  # noqa: F401

            pyperclip_available = True
        except Exception:
            pyperclip_available = False
        return {
            "service": self.name,
            "ready": pyperclip_available,
            "risk_levels": {
                "clipboard_read": "LOW",
                "clipboard_write": "LOW",
                "clipboard_clear": "LOW",
                "clipboard_inspect": "LOW",
                "clipboard_history": "LOW",
            },
            "dependencies": {"pyperclip": pyperclip_available, "metadata_only_history": True},
            "safety": {"audit_content_redacted": True, "history_metadata_only": True},
        }


__all__ = ["ClipboardControlService"]
