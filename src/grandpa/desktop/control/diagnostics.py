"""Desktop context and PC-control diagnostics service."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def system_info_message() -> str:
    """What kind of computer this is, and nothing about who uses it.

    Moved here from a private helper in ``local_actions`` so that the question
    has one answer. Deliberately the narrow one: platform, architecture,
    processor and Python version. The neighbouring diagnostics actions --
    list_processes in particular -- disclose the username, full paths and every
    running executable, which is far more than someone asking "system info"
    expects to hand over.
    """
    import platform

    return "\n".join(
        [
            "Basic system info:",
            f"- OS: {platform.platform()}",
            f"- Machine: {platform.machine() or 'unknown'}",
            f"- Processor: {platform.processor() or 'unknown'}",
            f"- Python: {platform.python_version()}",
        ]
    )


@dataclass(frozen=True)
class DesktopDiagnosticsService:
    """Read-only desktop context and readiness diagnostics."""

    name: str = "diagnostics"

    def execute(self, request: Any, action: str):
        from grandpa.pc_control import LocalActionResponse as _Response

        if action == "system_info":
            return _Response(
                True,
                None,
                "completed",
                system_info_message(),
                False,
                "LOW",
                {"disclosure": "platform only"},
            )
        from grandpa.desktop_context import (
            desktop_session_summary,
            get_active_process,
            list_processes,
            pc_control_diagnostics,
        )
        from grandpa.pc_control import LocalActionResponse

        if action == "active_process":
            result = get_active_process()
        elif action == "list_processes":
            result = list_processes(int(request.args.get("limit", 50)))
        elif action == "desktop_summary":
            result = desktop_session_summary()
        else:
            diagnostics = pc_control_diagnostics()
            return LocalActionResponse(
                ok=True,
                action_id=None,
                status="completed",
                message="PC control diagnostics are ready.",
                approval_required=False,
                risk_level="LOW",
                evidence=diagnostics,
            )
        return LocalActionResponse(
            ok=result.supported,
            action_id=None,
            status="completed" if result.supported else "unsupported",
            message=result.message,
            approval_required=False,
            risk_level="LOW",
            evidence=result.evidence,
            error=None if result.supported else "unsupported",
        )

    def diagnostics(self) -> dict[str, Any]:
        try:
            from grandpa.desktop_context import pc_control_diagnostics

            info = pc_control_diagnostics()
            return {
                "service": self.name,
                "ready": True,
                "risk_levels": {
                    "system_info": "LOW",
                    "active_process": "LOW",
                    "list_processes": "LOW",
                    "desktop_summary": "LOW",
                    "pc_diagnostics": "LOW",
                },
                "support": info,
            }
        except Exception as exc:
            return {
                "service": self.name,
                "ready": False,
                "error": exc.__class__.__name__,
            }


__all__ = ["DesktopDiagnosticsService", "system_info_message"]
