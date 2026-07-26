"""Read-only project discovery for local software repositories."""

from __future__ import annotations

from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
IGNORED_DIRS = {
    ".git",
    ".venv",
    ".venv311",
    ".uv-cache",
    ".pytest_cache",
    ".ruff_cache",
    "node_modules",
    "target",
    "build",
    "dist",
    "site",
    "__pycache__",
}


def scan_projects(root: str | Path | None = None, *, max_depth: int = 2) -> dict[str, Any]:
    """Detect software projects under ``root`` without executing anything."""
    base = _safe_root(root)
    projects: list[dict[str, Any]] = []
    seen: set[Path] = set()
    for path in _candidate_dirs(base, max_depth=max_depth):
        detected = detect_project(path)
        if detected["is_project"] and path not in seen:
            projects.append(detected)
            seen.add(path)
    projects.sort(key=lambda item: (0 if item["path"] == str(base) else 1, item["name"].lower()))
    return {
        "root": str(base),
        "projects": projects,
        "count": len(projects),
        "read_only": True,
    }


def detect_project(path: str | Path | None = None) -> dict[str, Any]:
    project = _safe_root(path)
    markers = {
        "git": project / ".git",
        "python": project / "pyproject.toml",
        "requirements": project / "requirements.txt",
        "node": project / "package.json",
        "rust": project / "Cargo.toml",
    }
    types: list[str] = []
    if markers["git"].exists():
        types.append("git")
    if markers["python"].exists() or markers["requirements"].exists():
        types.append("python")
    if markers["node"].exists():
        types.append("node")
    if markers["rust"].exists():
        types.append("rust")
    return {
        "name": project.name,
        "path": str(project),
        "is_project": bool(types),
        "types": types,
        "markers": {name: str(marker) for name, marker in markers.items() if marker.exists()},
        "read_only": True,
    }


def _candidate_dirs(root: Path, *, max_depth: int) -> list[Path]:
    candidates = [root]

    def walk(path: Path, depth: int) -> None:
        if depth >= max_depth:
            return
        try:
            children = [item for item in path.iterdir() if item.is_dir() and item.name not in IGNORED_DIRS]
        except OSError:
            return
        for child in children:
            candidates.append(child)
            walk(child, depth + 1)

    walk(root, 0)
    return candidates


def _safe_root(path: str | Path | None) -> Path:
    candidate = Path(path or ROOT).resolve()
    if not candidate.exists():
        raise FileNotFoundError(f"Project path does not exist: {candidate}")
    if candidate.is_file():
        candidate = candidate.parent
    return candidate


__all__ = ["IGNORED_DIRS", "ROOT", "detect_project", "scan_projects"]
