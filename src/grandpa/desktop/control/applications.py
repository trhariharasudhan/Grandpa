"""Application launching and detection service for PC control."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
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
        from grandpa.pc_control import LocalActionResponse, _is_protected_path

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

        launch_args: list[str] = []
        project_path = str(request.args.get("project_path") or "").strip()
        if project_path:
            if app_id != "vscode":
                return LocalActionResponse(
                    ok=False,
                    action_id=None,
                    status="blocked",
                    message="I blocked that app launch because project folders are only supported for VS Code.",
                    approval_required=False,
                    risk_level="BLOCKED",
                    evidence=evidence,
                    error="unsupported_project_app",
                )
            project = Path(project_path).expanduser().resolve(strict=False)
            evidence["project_path"] = str(project)
            if not project.exists() or not project.is_dir():
                return LocalActionResponse(
                    ok=False,
                    action_id=None,
                    status="blocked",
                    message="I blocked that app launch because the project path is not a valid folder.",
                    approval_required=False,
                    risk_level="BLOCKED",
                    evidence=evidence,
                    error="invalid_project_path",
                )
            if _is_protected_path(project):
                return LocalActionResponse(
                    ok=False,
                    action_id=None,
                    status="blocked",
                    message="I blocked that app launch because the project path is protected.",
                    approval_required=False,
                    risk_level="BLOCKED",
                    evidence=evidence,
                    error="protected_project_path",
                )
            launch_args.append(str(project))

        launch = launch_app(app_id, args=launch_args)
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
