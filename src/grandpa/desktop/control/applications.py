"""Application launching and detection service for PC control."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

SAFE_APP_ALIASES = {
    "notepad": "notepad",
    "note pad": "notepad",
    "node pad": "notepad",
    "note bad": "notepad",
    "node bad": "notepad",
    "the pad": "notepad",
    "calculator": "calculator",
    "calc": "calculator",
    "chrome": "chrome",
    "firefox": "firefox",
    "mozilla firefox": "firefox",
    "edge": "edge",
    "vscode": "vscode",
    "vs code": "vscode",
    "visual studio code": "vscode",
    "code": "vscode",
    "paint": "paint",
    "mspaint": "paint",
    "file explorer": "explorer",
    "explorer": "explorer",
    "terminal": "terminal",
    "windows terminal": "terminal",
    "task manager": "task_manager",
    "control panel": "control_panel",
    "settings": "settings",
    "windows settings": "settings",
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
            return self._execute_inventory_app(request, action)
        from grandpa.windows_app_resolver import launch_app, resolve_app

        resolution = resolve_app(app_id)
        new_instance = bool(request.args.get("new_instance"))
        evidence = {
            "app_id": app_id,
            "new_instance": new_instance,
            "resolution": resolution.to_dict(),
        }
        if resolution.status not in {"found", "available"}:
            return LocalActionResponse(
                ok=False,
                action_id=None,
                status="unsupported"
                if resolution.status == "unsupported"
                else "failed",
                message=resolution.message,
                approval_required=False,
                risk_level="LOW",
                evidence=evidence,
                error=resolution.status,
            )
        if action == "detect_app":
            return LocalActionResponse(
                True, None, "completed", resolution.message, False, "LOW", evidence
            )

        notepad_before = ()
        if app_id == "notepad":
            from grandpa.windows_window_control import (
                create_new_notepad_document,
                snapshot_notepad_documents,
            )

            notepad_before = snapshot_notepad_documents()
            if new_instance and notepad_before:
                creation_status, created = create_new_notepad_document()
                evidence["notepad_creation_status"] = creation_status
                if created is not None:
                    evidence["launch_target"] = _notepad_target_evidence(created)
                    return LocalActionResponse(
                        True,
                        None,
                        "completed",
                        "Opened a new Notepad document.",
                        False,
                        "LOW",
                        evidence,
                    )
                message = {
                    "ambiguous": (
                        "I found multiple Notepad windows and did not choose one "
                        "arbitrarily. Focus the intended window and try again."
                    ),
                    "unsupported": (
                        "This Notepad version does not expose a verified Add New Tab control."
                    ),
                    "unverified": (
                        "Notepad accepted the new-document request, but the new tab "
                        "could not be verified."
                    ),
                }.get(creation_status, "A new Notepad document could not be verified.")
                return LocalActionResponse(
                    False,
                    None,
                    "failed",
                    message,
                    False,
                    "LOW",
                    evidence,
                    error=creation_status,
                )

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
        response_status = "completed" if ok else "failed"
        message = launch.message
        if ok and app_id == "notepad":
            from grandpa.windows_window_control import wait_for_new_notepad_document

            created = wait_for_new_notepad_document(notepad_before)
            if created is not None:
                evidence["launch_target"] = _notepad_target_evidence(created)
                message = "Opened and verified a new Notepad document."
            else:
                ok = False
                message = (
                    "Notepad launched, but I could not distinguish a new document "
                    "from the existing tabs."
                )
                evidence["notepad_creation_status"] = "unverified"
                response_status = "partial_success"
        if ok and new_instance and app_id != "notepad":
            message = f"Opening another {resolution.display_name} window."
        return LocalActionResponse(
            ok=ok,
            action_id=None,
            status=response_status,
            message=message,
            approval_required=False,
            risk_level="LOW",
            evidence=evidence,
            error=None if ok else launch.status,
        )

    def _execute_inventory_app(self, request: Any, action: str):
        from grandpa.apps.inventory import find_app, launch_inventory_app
        from grandpa.pc_control import LocalActionResponse

        if action == "detect_app":
            result = find_app(request.target)
            ok = result.status == "found"
            return LocalActionResponse(
                ok=ok,
                action_id=None,
                status="completed"
                if ok
                else ("unsupported" if result.status == "missing" else "blocked"),
                message=result.message,
                approval_required=False,
                risk_level="LOW" if ok else "BLOCKED",
                evidence={"matches": [match.to_dict() for match in result.matches]},
                error=None if ok else result.status,
            )

        result = find_app(request.target)
        if result.status == "missing":
            return LocalActionResponse(
                False,
                None,
                "blocked",
                result.message,
                False,
                "BLOCKED",
                evidence={},
                error="missing_app",
            )
        if result.status == "ambiguous":
            return LocalActionResponse(
                False,
                None,
                "approval_required",
                result.message,
                True,
                "MEDIUM",
                evidence={"matches": [match.to_dict() for match in result.matches]},
                error="ambiguous_app",
            )
        record = result.matches[0]
        canonical_app_id = SAFE_APP_ALIASES.get(
            record.display_name.strip().lower()
        ) or SAFE_APP_ALIASES.get(record.name.strip().lower())
        if canonical_app_id:
            from grandpa.windows_app_resolver import resolve_app

            resolution = resolve_app(canonical_app_id)
            if resolution.status in {"found", "available"}:
                from dataclasses import replace

                try:
                    req = replace(request, target=canonical_app_id)
                except Exception:
                    req = request
                return self.execute(req, action)

        target_path = Path(record.path)
        if not target_path.exists():
            import shutil

            which_path = shutil.which(record.path)
            if which_path:
                target_path = Path(which_path)
            else:
                return LocalActionResponse(
                    False,
                    None,
                    "failed",
                    f"I found {record.display_name}, but its executable path does not exist on disk: {record.path}",
                    False,
                    "LOW",
                    evidence={"app": record.to_dict()},
                    error="missing_executable",
                )

        try:
            message = launch_inventory_app(record)
        except ValueError:
            return LocalActionResponse(
                False,
                None,
                "blocked",
                "I blocked that app launch because the target is not a safe executable or shortcut.",
                False,
                "BLOCKED",
                evidence={"app": record.to_dict()},
                error="dangerous_launch_target",
            )
        except OSError as exc:
            return LocalActionResponse(
                False,
                None,
                "failed",
                f"I found {record.display_name}, but Windows could not launch it: {exc}",
                False,
                "LOW",
                evidence={"app": record.to_dict()},
                error="launch_failed",
            )
        return LocalActionResponse(
            True,
            None,
            "completed",
            message,
            False,
            "LOW",
            evidence={"app": record.to_dict()},
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


def _notepad_target_evidence(target: Any) -> dict[str, Any]:
    return {
        "window_handle": target.window.handle,
        "process_id": target.window.process_id,
        "window_title": target.window.title,
        "document_id": target.document.document_id,
        "document_title": target.document.title,
    }
