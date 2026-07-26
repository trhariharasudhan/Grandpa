"""Shared natural-language project intent adapter for chat and voice."""

from __future__ import annotations

import re

from grandpa.projects.errors import ProjectError
from grandpa.projects.models import ProjectCommandResult
from grandpa.projects.service import ProjectService


def handle_project_command(
    text: str, *, service: ProjectService | None = None
) -> ProjectCommandResult:
    normalized = " ".join(re.sub(r"[^a-zA-Z0-9]+", " ", text).casefold().split())
    if not normalized:
        return ProjectCommandResult("no_match", "")
    manager = service or ProjectService()

    if normalized in {
        "list my projects",
        "show my projects",
        "list projects",
        "what projects do i have",
    }:
        projects = manager.projects()
        if not projects:
            return ProjectCommandResult(
                "handled", "No projects are registered yet.", "list"
            )
        lines = [
            "Registered projects:",
            *(f"- {project.name} ({project.root_path})" for project in projects),
        ]
        return ProjectCommandResult("handled", "\n".join(lines), "list")

    match = re.fullmatch(
        r"(?:open|launch) (.+?)(?: project)?(?: in (?:vs code|vscode|visual studio code))?",
        normalized,
    )
    if match and (
        "project" in normalized
        or _looks_like_registered_project(match.group(1), manager)
    ):
        return _execute(
            manager, "open", match.group(1), lambda: manager.open(match.group(1))
        )

    match = re.fullmatch(
        r"(?:start|run) (?:the )?(.+?)(?: server| project)?", normalized
    )
    if match and "test" not in normalized:
        return _execute(
            manager,
            "start",
            match.group(1),
            lambda: manager.lifecycle(match.group(1), "start"),
        )

    match = re.fullmatch(
        r"(?:check|show|what is) (?:the )?(.+?)(?: server| project)? status", normalized
    )
    if match:
        return _execute(
            manager, "status", match.group(1), lambda: manager.status(match.group(1))
        )
    match = re.fullmatch(r"(?:check|show) (.+?) server status", normalized)
    if match:
        return _execute(
            manager, "status", match.group(1), lambda: manager.status(match.group(1))
        )

    match = re.fullmatch(
        r"(?:run|start) only (voice|chat|apps?|app manager) tests for (.+)",
        normalized,
    )
    if match:
        profile = "apps" if match.group(1).startswith("app") else match.group(1)
        return _execute(
            manager,
            "test",
            match.group(2),
            lambda: manager.run_workflow(match.group(2), "test", profile=profile),
        )

    match = re.fullmatch(
        r"(?:run|start) only (?:the )?(voice|chat|apps?|app manager) tests",
        normalized,
    )
    if match:
        current = manager.current_project()
        if current is None:
            return ProjectCommandResult(
                "error",
                "Tell me which project should run that test profile.",
                "test",
            )
        profile = "apps" if match.group(1).startswith("app") else match.group(1)
        return _execute(
            manager,
            "test",
            current.id,
            lambda: manager.run_workflow(current.id, "test", profile=profile),
        )

    match = re.fullmatch(
        r"(?:run|start) (?:only )?(.+?) (voice|chat|apps?) tests", normalized
    )
    if match:
        profile = "apps" if match.group(2).startswith("app") else match.group(2)
        return _execute(
            manager,
            "test",
            match.group(1),
            lambda: manager.run_workflow(match.group(1), "test", profile=profile),
        )
    match = re.fullmatch(r"run tests for (.+)", normalized) or re.fullmatch(
        r"run (.+?) tests", normalized
    )
    if match:
        return _execute(
            manager,
            "test",
            match.group(1),
            lambda: manager.run_workflow(match.group(1), "test"),
        )

    match = re.fullmatch(r"(?:show|read|open) (.+?)(?: project)? logs?", normalized)
    if match:

        def read_logs() -> str:
            content, path = manager.logs(match.group(1))
            return f"{content}\nLog: {path}" if path else content

        return _execute(manager, "logs", match.group(1), read_logs)

    match = re.fullmatch(
        r"(?:show|describe) (.+?) project(?: information| info)?", normalized
    )
    if match:
        return _execute(
            manager,
            "show",
            match.group(1),
            lambda: _format_info(manager.info(match.group(1))),
        )

    match = re.fullmatch(
        r"(?:stop|restart) (?:the )?(.+?)(?: server| project)?", normalized
    )
    if match:
        action = normalized.split()[0]
        try:
            project = manager.resolve(match.group(1))
        except ProjectError as exc:
            return ProjectCommandResult("error", str(exc), action)
        return ProjectCommandResult(
            "needs_confirmation",
            f"Confirmation is required to {action} {project.name}. Use `grandpa projects {action} {project.id}`.",
            action,
            project.id,
        )
    return ProjectCommandResult("no_match", "")


def _looks_like_registered_project(query: str, service: ProjectService) -> bool:
    try:
        service.resolve(query)
        return True
    except ProjectError:
        return False


def _execute(
    service: ProjectService, action: str, query: str, operation
) -> ProjectCommandResult:
    try:
        value = operation()
        message = value.message if hasattr(value, "message") else str(value)
        project_id = service.resolve(query).id
        status = (
            "handled"
            if getattr(value, "status", "completed") not in {"failed", "error"}
            else "error"
        )
        return ProjectCommandResult(status, message, action, project_id)
    except ProjectError as exc:
        return ProjectCommandResult("error", str(exc), action)


def _format_info(info: dict[str, object]) -> str:
    project = info["project"]
    lines = [
        f"Project: {project.name}",
        f"Path: {project.root_path}",
        f"Type: {project.project_type}",
        f"Editor: {project.editor}",
        f"Git repository: {'Yes' if info['git'] else 'No'}",
        f"Branch: {info['branch'] or project.default_branch or 'Unknown'}",
        "Registered workflows:",
        *(f"- {name}" for name in info["workflows"]),
    ]
    return "\n".join(lines)


__all__ = ["handle_project_command"]
