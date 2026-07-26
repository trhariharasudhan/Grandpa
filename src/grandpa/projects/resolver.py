"""Deterministic registered-project resolution."""

from __future__ import annotations

import difflib
import re
from pathlib import Path

from grandpa.projects.errors import AmbiguousProjectError, ProjectNotFoundError
from grandpa.projects.models import Project


def normalize_project_name(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.casefold()).split())


def resolve_project(query: str, projects: list[Project]) -> Project:
    target = normalize_project_name(query)
    if not target:
        raise ProjectNotFoundError("Tell me which registered project to use.")

    def names(project: Project) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                normalize_project_name(item)
                for item in (
                    project.id,
                    project.name,
                    Path(project.root_path).name,
                    *project.aliases,
                )
                if item
            )
        )

    exact = [project for project in projects if target in names(project)]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise _ambiguous(exact)

    starts = [
        project
        for project in projects
        if any(name.startswith(target) for name in names(project))
    ]
    if len(starts) == 1:
        return starts[0]
    if len(starts) > 1:
        raise _ambiguous(starts)

    scored: list[tuple[float, Project]] = []
    for project in projects:
        score = max(
            difflib.SequenceMatcher(a=target, b=name).ratio() for name in names(project)
        )
        if score >= 0.72:
            scored.append((score, project))
    scored.sort(key=lambda item: item[0], reverse=True)
    if not scored:
        raise ProjectNotFoundError(
            f"I could not find a registered project named {query}. Use `grandpa projects list` to see available projects."
        )
    best = scored[0][0]
    close = [project for score, project in scored if best - score < 0.06]
    if len(close) > 1:
        raise _ambiguous(close)
    return close[0]


def _ambiguous(projects: list[Project]) -> AmbiguousProjectError:
    choices = "\n".join(f"- {project.name}" for project in projects[:8])
    return AmbiguousProjectError(
        f"I found multiple projects:\n{choices}\n\nPlease specify which project."
    )


__all__ = ["normalize_project_name", "resolve_project"]
