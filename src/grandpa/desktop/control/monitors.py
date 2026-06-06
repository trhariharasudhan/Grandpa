"""Monitor awareness service for PC control."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MonitorControlService:
    """List and inspect monitor metadata without changing display settings."""

    name: str = "monitors"

    def execute(self, request: Any, action: str):
        from grandpa.desktop_context import list_monitors
        from grandpa.pc_control import LocalActionResponse

        result = list_monitors()
        monitors = result.evidence.get("monitors", [])
        if action == "monitor_info" and request.target:
            target = str(request.target).lower().strip()
            monitors = [
                monitor for monitor in monitors
                if target in {str(monitor.get("id", "")).lower(), "primary" if monitor.get("primary") else ""}
            ]
        ok = result.supported and (action == "list_monitors" or bool(monitors))
        message = result.message if action == "list_monitors" else (
            f"Found monitor {request.target}." if monitors else f"I could not find monitor {request.target}."
        )
        return LocalActionResponse(
            ok=ok,
            action_id=None,
            status="completed" if ok else ("unsupported" if not result.supported else "failed"),
            message=message,
            approval_required=False,
            risk_level="LOW",
            evidence={**result.evidence, "monitors": monitors},
            error=None if ok else ("unsupported" if not result.supported else "monitor_not_found"),
        )

    def diagnostics(self) -> dict[str, Any]:
        try:
            from grandpa.desktop_context import list_monitors

            result = list_monitors()
            return {
                "service": self.name,
                "ready": bool(result.supported),
                "risk_levels": {"list_monitors": "LOW", "monitor_info": "LOW"},
                "dependencies": ["grandpa.desktop_context"],
                "count": result.evidence.get("count", 0),
                "supported": result.supported,
            }
        except Exception as exc:
            return {"service": self.name, "ready": False, "error": exc.__class__.__name__}


__all__ = ["MonitorControlService"]
