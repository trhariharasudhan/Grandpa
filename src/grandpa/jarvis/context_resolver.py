"""Safe local context resolution for Jarvis commands.

The resolver only searches a small set of user-approved folders and avoids
system, credential, and browser-profile locations.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROTECTED_PATH_MARKERS = {
    ".ssh",
    "$recycle.bin",
    "application data",
    "cookies",
    "credentials",
    "default",
    "local state",
    "login data",
    "program files",
    "program files (x86)",
    "system volume information",
    "users\\all users",
    "windows",
}


@dataclass(frozen=True)
class ResolvedProject:
    name: str
    path: Path
    source_root: Path


class SafeContextResolver:
    """Resolve local project/context names inside approved folders only."""

    def __init__(self, roots: list[Path] | None = None) -> None:
        self.roots = roots or default_approved_roots()

    def approved_roots(self) -> list[Path]:
        roots: list[Path] = []
        seen: set[str] = set()
        for root in self.roots:
            resolved = root.expanduser().resolve(strict=False)
            key = _path_key(resolved)
            if key in seen or not resolved.exists() or is_protected_path(resolved):
                continue
            seen.add(key)
            roots.append(resolved)
        return roots

    def resolve_project(self, name: str) -> ResolvedProject | None:
        wanted = _normalise_name(name)
        if not wanted:
            return None

        for root in self.approved_roots():
            if _normalise_name(root.name) == wanted and _looks_like_project(root):
                return ResolvedProject(root.name, root, root)

            for child in _safe_children(root):
                if _normalise_name(child.name) == wanted and _looks_like_project(child):
                    return ResolvedProject(child.name, child, root)
        return None


def default_approved_roots() -> list[Path]:
    home = Path.home()
    roots = [
        Path.cwd(),
        home,
        home / "Desktop",
        home / "Documents",
        home / "Downloads",
    ]
    for raw in (r"D:\Grandpa", r"D:\Projects"):
        path = Path(raw)
        if path.exists():
            roots.append(path)
    return roots


def is_protected_path(path: Path) -> bool:
    resolved = path.expanduser().resolve(strict=False)
    lowered = str(resolved).lower().replace("/", "\\")
    if lowered.startswith(("c:\\windows", "c:\\program files")):
        return True
    parts = {part.lower() for part in resolved.parts}
    if parts & PROTECTED_PATH_MARKERS:
        return True
    browser_markers = (
        "\\appdata\\local\\google\\chrome\\user data",
        "\\appdata\\local\\microsoft\\edge\\user data",
        "\\appdata\\roaming\\mozilla\\firefox\\profiles",
    )
    return any(marker in lowered for marker in browser_markers)


def _safe_children(root: Path) -> list[Path]:
    if is_protected_path(root):
        return []
    try:
        children = [child for child in root.iterdir() if child.is_dir()]
    except OSError:
        return []
    return [child for child in children if not is_protected_path(child)]


def _looks_like_project(path: Path) -> bool:
    if not path.is_dir() or is_protected_path(path):
        return False
    markers = (
        ".git",
        "pyproject.toml",
        "package.json",
        "Cargo.toml",
        "README.md",
        "src",
    )
    return any((path / marker).exists() for marker in markers)


def _normalise_name(value: str) -> str:
    cleaned = value.strip().lower()
    for suffix in (" project", " repo", " repository", " folder"):
        if cleaned.endswith(suffix):
            cleaned = cleaned[: -len(suffix)]
    return " ".join(cleaned.replace("_", " ").replace("-", " ").split())


def _path_key(path: Path) -> str:
    return os.path.normcase(str(path))
