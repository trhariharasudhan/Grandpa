"""High-level Project Launcher and Developer Workflow service."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from grandpa.core.config import DEFAULT_CONFIG_DIR
from grandpa.projects.discovery import discover_projects
from grandpa.projects.errors import (
    ProjectNotFoundError,
    ProjectProcessError,
    WorkflowNotConfiguredError,
)
from grandpa.projects.models import Project, ProjectCandidate, WorkflowResult
from grandpa.projects.registry import ProjectRegistry
from grandpa.projects.resolver import resolve_project
from grandpa.projects.runner import ProjectRunner, redact_secrets


class ProjectService:
    def __init__(
        self,
        *,
        registry: ProjectRegistry | None = None,
        runner: ProjectRunner | None = None,
    ) -> None:
        self.registry = registry or ProjectRegistry()
        self.runner = runner or ProjectRunner()

    def bootstrap_grandpa(self) -> Project | None:
        return self.registry.ensure_grandpa()

    def projects(self, *, bootstrap: bool = True) -> list[Project]:
        if bootstrap:
            self.bootstrap_grandpa()
        return self.registry.list()

    def resolve(self, query: str) -> Project:
        return resolve_project(query, self.projects())

    def current_project(self, cwd: Path | None = None) -> Project | None:
        current = (cwd or Path.cwd()).resolve(strict=False)
        matches: list[tuple[int, Project]] = []
        for project in self.projects():
            root = Path(project.root_path).resolve(strict=False)
            if current == root or root in current.parents:
                matches.append((len(root.parts), project))
        matches.sort(key=lambda item: item[0], reverse=True)
        return matches[0][1] if matches else None

    def register(
        self, path: str, *, name: str | None = None, editor: str = "visual studio code"
    ) -> Project:
        return self.registry.register(path, name=name, editor=editor)

    def unregister(self, query: str) -> Project:
        project = self.resolve(query)
        removed = self.registry.unregister(project.id)
        if removed is None:
            raise ProjectNotFoundError(query)
        return removed

    def discover(self, root: str, *, max_depth: int = 3) -> list[ProjectCandidate]:
        return discover_projects(root, max_depth=max_depth)

    def open(self, query: str, *, target: str | None = None) -> str:
        project = self.resolve(query)
        app = (target or project.editor or "visual studio code").casefold().strip()
        if app in {
            "vscode",
            "vs code",
            "visual studio code",
            "code",
            "configured editor",
        }:
            from grandpa.pc_control import LocalActionRequest, run_local_action

            result = run_local_action(
                LocalActionRequest(
                    "open_app", "vscode", {"project_path": project.root_path}
                )
            )
            if not result.ok:
                raise ProjectProcessError(result.message)
            return f"Opening {project.name} in Visual Studio Code."
        if app in {"explorer", "file explorer"}:
            os.startfile(project.root_path)  # type: ignore[attr-defined]  # noqa: S606
            return f"Opening {project.name} in File Explorer."
        raise WorkflowNotConfiguredError(
            f"Opening projects with {target} is not configured safely."
        )

    def run_workflow(
        self, query: str, workflow: str, *, profile: str | None = None
    ) -> WorkflowResult:
        project = self.resolve(query)
        if workflow == "test" and profile:
            command = project.test_profiles.get(profile.casefold())
            workflow_name = f"test:{profile.casefold()}"
        else:
            command = project.commands.get(workflow)
            workflow_name = workflow
        if command is None:
            raise WorkflowNotConfiguredError(
                f"The project does not have a `{workflow_name}` workflow configured."
            )
        return self.runner.run(project, workflow_name, command)

    def status(self, query: str) -> WorkflowResult:
        project = self.resolve(query)
        if project.metadata.get("grandpa_lifecycle"):
            from grandpa.cli.daemon_cmd import _LOG_FILE, _read_pid
            from grandpa.core.config import load_config

            pid = _read_pid()
            config = load_config()
            if pid is None:
                return WorkflowResult("stopped", "Grandpa server is not running.")
            return WorkflowResult(
                "running",
                f"Grandpa server is running. PID: {pid}. URL: http://{config.server.host}:{config.server.port}. Log: {_LOG_FILE}",
                pid=pid,
                log_path=str(_LOG_FILE),
            )
        state = self.runner.process_store.get_owned(project.id)
        if state is None:
            command = project.commands.get("status")
            if command is not None:
                return self.runner.run(project, "status", command)
            return WorkflowResult("stopped", f"{project.name} is not running.")
        return WorkflowResult(
            "running",
            f"{project.name} is running. PID: {state.pid}. Log: {state.log_path}",
            pid=state.pid,
            log_path=state.log_path,
        )

    def lifecycle(self, query: str, action: str) -> WorkflowResult:
        project = self.resolve(query)
        if project.metadata.get("grandpa_lifecycle"):
            return self._grandpa_lifecycle(action)
        if action == "start":
            if self.runner.process_store.get_owned(project.id):
                return WorkflowResult("running", f"{project.name} is already running.")
            return self.run_workflow(project.id, "start")
        if action == "stop":
            return self._stop_owned(project)
        if action == "restart":
            current = self.status(project.id)
            if current.status == "running":
                stopped = self._stop_owned(project)
                if stopped.status != "stopped":
                    return stopped
            return self.run_workflow(project.id, "start")
        raise WorkflowNotConfiguredError(action)

    def logs(self, query: str, *, tail: int = 100) -> tuple[str, str]:
        project = self.resolve(query)
        root = Path(project.root_path).resolve()
        allowed = []
        for value in project.log_paths:
            expanded = Path(os.path.expandvars(os.path.expanduser(value))).resolve(
                strict=False
            )
            config_root = DEFAULT_CONFIG_DIR.resolve(strict=False)
            if (
                expanded == root
                or root in expanded.parents
                or expanded == config_root
                or config_root in expanded.parents
            ):
                allowed.append(expanded)
        generated_logs = sorted(
            self.runner.log_dir.glob(f"{project.id}-*.log"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        allowed.extend(generated_logs)
        existing = [path for path in allowed if path.exists() and path.is_file()]
        if not existing:
            return "No registered project logs exist yet.", str(
                allowed[0]
            ) if allowed else ""
        latest = max(existing, key=lambda path: path.stat().st_mtime)
        lines = latest.read_text(encoding="utf-8", errors="replace").splitlines()[
            -max(1, min(tail, 1000)) :
        ]
        return redact_secrets("\n".join(lines)), str(latest)

    def info(self, query: str) -> dict[str, object]:
        project = self.resolve(query)
        branch = ""
        try:
            branch = subprocess.run(  # noqa: S603
                ["git", "-C", project.root_path, "branch", "--show-current"],
                shell=False,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pass
        workflows = sorted(
            (*project.commands, *(f"test:{name}" for name in project.test_profiles))
        )
        return {
            "project": project,
            "branch": branch,
            "git": (Path(project.root_path) / ".git").exists(),
            "workflows": workflows,
        }

    def _grandpa_lifecycle(self, action: str) -> WorkflowResult:
        from grandpa.cli import daemon_cmd

        if action == "status":
            return self.status("grandpa")
        if action == "restart":
            if self.status("grandpa").status == "running":
                self._invoke_daemon_callback(daemon_cmd.stop, action="stop")
                if self.status("grandpa").status == "running":
                    raise ProjectProcessError(
                        "Grandpa server did not stop cleanly; restart was cancelled."
                    )
            self._invoke_daemon_callback(daemon_cmd.start, action="start")
            return self.status("grandpa")
        command = getattr(daemon_cmd, action, None)
        self._invoke_daemon_callback(command, action=action)
        return self.status("grandpa")

    def _invoke_daemon_callback(self, command: object, *, action: str) -> None:
        callback = getattr(command, "callback", None)
        if callback is None:
            raise WorkflowNotConfiguredError(action)
        try:
            if action == "start":
                callback(
                    host=None,
                    port=None,
                    engine_key=None,
                    model_name=None,
                    agent_name=None,
                )
            else:
                callback()
        except SystemExit as exc:
            result = self.status("grandpa")
            if action == "start" and result.status == "running":
                return
            raise ProjectProcessError(
                f"Grandpa {action} failed with exit code {exc.code}."
            ) from exc

    def _stop_owned(self, project: Project) -> WorkflowResult:
        state = self.runner.process_store.get_owned(project.id)
        if state is None:
            command = project.commands.get("stop")
            if command is not None:
                return self.runner.run(project, "stop", command)
            return WorkflowResult("stopped", f"{project.name} is not running.")
        try:
            import psutil

            process = psutil.Process(state.pid)
            process.terminate()
            process.wait(timeout=10)
        except Exception as exc:
            raise ProjectProcessError(
                f"Could not stop {project.name} gracefully: {exc}"
            ) from exc
        self.runner.process_store.remove(project.id)
        return WorkflowResult("stopped", f"{project.name} stopped.")


__all__ = ["ProjectService"]
