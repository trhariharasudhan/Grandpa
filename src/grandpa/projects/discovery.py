"""Bounded, non-executing project discovery."""

from __future__ import annotations

from pathlib import Path

from grandpa.projects.errors import InvalidProjectPathError
from grandpa.projects.models import ProjectCandidate

PROJECT_MARKERS = {
    "pyproject.toml": "python",
    "requirements.txt": "python",
    "package.json": "javascript",
    "Cargo.toml": "rust",
    "go.mod": "go",
    "pom.xml": "java",
    "build.gradle": "java",
    "pubspec.yaml": "flutter",
    "docker-compose.yml": "docker",
    "compose.yaml": "docker",
}
IGNORED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "target",
    "dist",
    "build",
    "site",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
}
PROTECTED_NAMES = {
    "windows",
    "program files",
    "program files (x86)",
    "$recycle.bin",
    "system volume information",
}


def detect_project_type(path: Path) -> str:
    found = [
        kind for marker, kind in PROJECT_MARKERS.items() if (path / marker).exists()
    ]
    if not found:
        return "git" if (path / ".git").exists() else "unknown"
    unique = list(dict.fromkeys(found))
    return "/".join(unique)


def discover_projects(
    root: str | Path, *, max_depth: int = 3
) -> list[ProjectCandidate]:
    base = Path(root).expanduser().resolve(strict=False)
    if not base.exists() or not base.is_dir():
        raise InvalidProjectPathError(f"Discovery root does not exist: {base}")
    candidates: list[ProjectCandidate] = []

    def visit(directory: Path, depth: int) -> None:
        if (
            directory.name.casefold() in PROTECTED_NAMES
            or directory.name.casefold() in IGNORED_DIRS
        ):
            return
        project_type = detect_project_type(directory)
        if project_type != "unknown":
            candidates.append(ProjectCandidate(str(directory), project_type))
            return
        if depth >= max_depth:
            return
        try:
            children = sorted(
                (item for item in directory.iterdir() if item.is_dir()),
                key=lambda item: item.name.casefold(),
            )
        except OSError:
            return
        for child in children:
            visit(child, depth + 1)

    visit(base, 0)
    return candidates


__all__ = [
    "IGNORED_DIRS",
    "PROJECT_MARKERS",
    "detect_project_type",
    "discover_projects",
]
