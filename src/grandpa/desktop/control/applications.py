"""Application launching and detection service for PC control."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

SAFE_APP_ALIASES = {
    "notepad": "notepad",
    "calculator": "calculator",
    "calc": "calculator",
    "chrome": "chrome",
    "edge": "edge",
    "vscode": "vscode",
    "vs code": "vscode",
    "visual studio code": "vscode",
    "file explorer": "explorer",
    "explorer": "explorer",
    "terminal": "terminal",
    "windows terminal": "terminal",
    "task manager": "task_manager",
}


@dataclass(frozen=True)
class ApplicationControlService:
    """Resolve and launch allowlisted Windows applications."""

    name: str = "applications"

    def app_id(self, name: str) -> str | None:
        return SAFE_APP_ALIASES.get(name.strip().lower())

    def execute(self, request: Any, action: str):
        from grandpa.pc_control import LocalActionResponse

        app_id = self.app_id(request.target)
        if not app_id:
            return LocalActionResponse(
                False,
                None,
                "blocked",
                "Unknown app is not in Grandpa's safe app allowlist.",
                False,
                "BLOCKED",
                error="blocked_by_policy",
            )
        from grandpa.windows_app_resolver import launch_app, resolve_app

        resolution = resolve_app(app_id)
        evidence = {"app_id": app_id, "resolution": resolution.to_dict()}
        if resolution.status not in {"found", "available"}:
            return LocalActionResponse(
                ok=False,
                action_id=None,
                status="unsupported" if resolution.status == "unsupported" else "failed",
                message=resolution.message,
                approval_required=False,
                risk_level="LOW",
                evidence=evidence,
                error=resolution.status,
            )
        if action == "detect_app":
            return LocalActionResponse(True, None, "completed", resolution.message, False, "LOW", evidence)
        launch = launch_app(app_id)
        evidence["launch"] = launch.to_dict()
        ok = launch.status == "found"
        return LocalActionResponse(
            ok=ok,
            action_id=None,
            status="completed" if ok else "failed",
            message=launch.message,
            approval_required=False,
            risk_level="LOW",
            evidence=evidence,
            error=None if ok else launch.status,
        )

    def diagnostics(self) -> dict[str, Any]:
        return {
            "service": self.name,
            "ready": True,
            "risk_levels": {"open_app": "LOW", "detect_app": "LOW"},
            "allowlisted_apps": sorted(set(SAFE_APP_ALIASES.values())),
            "dependencies": ["grandpa.windows_app_resolver"],
        }


__all__ = ["ApplicationControlService", "SAFE_APP_ALIASES"]
