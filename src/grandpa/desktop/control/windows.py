"""Window management service for PC control."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class WindowControlService:
    """Focus, minimize, maximize, restore, close, and list visible windows."""

    name: str = "windows"

    def execute_alias(self, request: Any, action: str):
        from grandpa.pc_control import LocalActionRequest

        return self.execute(
            LocalActionRequest(f"{action}_window", request.target, request.args),
            f"{action}_window",
        )

    def execute(self, request: Any, action: str):
        from grandpa.pc_control import LocalActionResponse
        from grandpa.windows_window_control import control_window, list_open_windows

        if action == "list_windows":
            result = list_open_windows()
        else:
            verb = action.removesuffix("_window")
            result = control_window(verb, request.target or "active")
        ok = result.status == "handled"
        status = "completed" if ok else "failed"
        if result.status == "unsupported":
            status = "unsupported"
        if result.status == "blocked":
            status = "blocked"
        return LocalActionResponse(
            ok=ok,
            action_id=None,
            status=status,
            message=result.message,
            approval_required=False,
            risk_level="LOW" if action == "list_windows" else "MEDIUM",
            evidence={
                "window_status": result.status,
                "windows": [w.title for w in getattr(result, "windows", ())],
            },
            error=None if ok else result.status,
        )

    def diagnostics(self) -> dict[str, Any]:
        return {
            "service": self.name,
            "ready": True,
            "risk_levels": {
                "list_windows": "LOW",
                "focus_window": "MEDIUM",
                "minimize_window": "MEDIUM",
                "maximize_window": "MEDIUM",
                "restore_window": "MEDIUM",
                "close_window": "MEDIUM",
                "close_app": "MEDIUM",
            },
            "dependencies": ["grandpa.windows_window_control"],
        }


__all__ = ["WindowControlService"]
