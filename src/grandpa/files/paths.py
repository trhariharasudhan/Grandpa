"""Safe path resolution for Grandpa file automation."""

from __future__ import annotations

import os
from pathlib import Path

MAX_SEARCH_RESULTS = 20

#: Hard ceilings on how much of a safe root a single search may traverse.
#:
#: ``MAX_SEARCH_RESULTS`` bounds how many *matches* are collected, but nothing
#: bounded how many entries were *examined*: a query matching nothing walked
#: every safe root to completion. ``safe_roots()`` includes the whole user
#: profile, so a filename that does not exist froze the caller -- measured at
#: over 20 seconds before being killed, with the stack pinned inside ``_walk``.
#: That is reached from file-argument validation, so dry runs hung too.
#:
#: The shape follows ``apps/scanner.py`` (``MAX_DISCOVERED_APPS``,
#: ``MAX_PROGRAM_FILES_CANDIDATES``): an in-loop cap on entries examined, plus a
#: depth limit so one deep branch cannot consume the whole budget. Hitting
#: either ceiling ends traversal of that root and moves to the next. Neither
#: widens access -- traversal still starts only from ``safe_roots()``.
MAX_SEARCH_ENTRIES = 20000
MAX_SEARCH_DEPTH = 6

SKIP_DIR_NAMES = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "__pycache__",
    "node_modules",
    "target",
    "dist",
    "build",
    ".pytest_cache",
    ".ruff_cache",
}


def user_folder_aliases() -> dict[str, Path]:
    home = Path.home()
    return {
        "home": home,
        "desktop": home / "Desktop",
        "desktop folder": home / "Desktop",
        "documents": home / "Documents",
        "documents folder": home / "Documents",
        "downloads": home / "Downloads",
        "downloads folder": home / "Downloads",
        "pictures": home / "Pictures",
        "pictures folder": home / "Pictures",
        "music": home / "Music",
        "music folder": home / "Music",
        "videos": home / "Videos",
        "videos folder": home / "Videos",
        "project": Path.cwd(),
        "grandpa project": Path("D:/Grandpa")
        if Path("D:/Grandpa").exists()
        else Path.cwd(),
    }


def safe_roots(extra_roots: tuple[Path, ...] = ()) -> tuple[Path, ...]:
    env_roots = tuple(
        Path(item)
        for item in os.getenv("GRANDPA_FILE_SAFE_ROOTS", "").split(os.pathsep)
        if item
    )
    roots = (
        Path.cwd(),
        Path.home(),
        Path.home() / "Desktop",
        Path.home() / "Documents",
        Path.home() / "Downloads",
        Path.home() / "Pictures",
        Path.home() / "Music",
        Path.home() / "Videos",
        Path("D:/Grandpa"),
        Path("D:/Projects"),
        *env_roots,
        *extra_roots,
    )
    return _dedupe_existing_or_plausible(roots)


def resolve_alias(value: str) -> Path | None:
    return user_folder_aliases().get(_clean_alias(value))


def resolve_destination(value: str, *, roots: tuple[Path, ...] = ()) -> Path:
    alias = resolve_alias(value)
    if alias is not None:
        return alias.resolve(strict=False)
    return resolve_path(value, roots=roots)


def resolve_path(value: str, *, roots: tuple[Path, ...] = ()) -> Path:
    raw = str(value or "").strip().strip('"')
    if not raw:
        raise ValueError("path is required")
    alias = resolve_alias(raw)
    if alias is not None:
        return alias.resolve(strict=False)
    candidate = Path(raw).expanduser()
    if candidate.is_absolute():
        return candidate.resolve(strict=False)
    base = (roots or safe_roots())[0]
    return (base / candidate).resolve(strict=False)


def find_matches(
    query: str, *, roots: tuple[Path, ...] = (), limit: int = MAX_SEARCH_RESULTS
) -> list[Path]:
    needle = str(query or "").strip().strip('"').casefold()
    if not needle:
        return []
    found: list[Path] = []
    for root in roots or safe_roots():
        if not root.exists():
            continue
        if root.is_file():
            candidates = [root]
        else:
            candidates = _walk(root)
        for path in candidates:
            try:
                if _matches_query(path, needle):
                    found.append(path.resolve(strict=False))
                    if len(found) >= limit:
                        return _sort_matches(found)
            except OSError:
                continue
    return _sort_matches(found)


def latest_by_suffix(
    suffixes: set[str], *, roots: tuple[Path, ...] = ()
) -> Path | None:
    matches: list[Path] = []
    for root in roots or safe_roots():
        if not root.exists():
            continue
        for path in _walk(root):
            try:
                if path.suffix.casefold() in suffixes:
                    matches.append(path.resolve(strict=False))
            except OSError:
                continue
    if not matches:
        return None
    return max(matches, key=lambda path: path.stat().st_mtime)


def describe_path(path: Path) -> str:
    return f"`{path}`"


def _walk(
    root: Path,
    *,
    max_entries: int = MAX_SEARCH_ENTRIES,
    max_depth: int = MAX_SEARCH_DEPTH,
):
    """Yield entries under *root*, bounded by entry count and directory depth.

    Traversal stops once ``max_entries`` entries have been yielded or a branch
    reaches ``max_depth``, whichever comes first. Without these ceilings a query
    that matches nothing walks the entire safe root -- see the note on
    ``MAX_SEARCH_ENTRIES``.
    """
    root_depth = len(root.parts)
    yielded = 0
    for current, dirs, names in os.walk(root):
        current_path = Path(current)
        depth = len(current_path.parts) - root_depth
        if depth >= max_depth:
            # Do not descend further; the entries already at this level are
            # still reported below.
            dirs[:] = []
        else:
            dirs[:] = [
                name
                for name in dirs
                if name.casefold() not in SKIP_DIR_NAMES and not name.startswith(".")
            ]
        for name in names:
            yield current_path / name
            yielded += 1
            if yielded >= max_entries:
                return
        for name in dirs:
            yield current_path / name
            yielded += 1
            if yielded >= max_entries:
                return


def _matches_query(path: Path, needle: str) -> bool:
    haystack = f"{path.name} {path.suffix}".casefold()
    if needle in haystack:
        return True
    terms = [term for term in needle.split() if term]
    return bool(terms) and all(term in haystack for term in terms)


def _sort_matches(paths: list[Path]) -> list[Path]:
    return sorted(paths, key=lambda path: (path.name.casefold(), str(path).casefold()))


def _clean_alias(value: str) -> str:
    return " ".join(str(value).strip().casefold().split())


def _dedupe_existing_or_plausible(paths: tuple[Path, ...]) -> tuple[Path, ...]:
    seen: set[str] = set()
    result: list[Path] = []
    for path in paths:
        key = str(path.expanduser().resolve(strict=False)).casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(path.expanduser().resolve(strict=False))
    return tuple(result)


__all__ = [
    "MAX_SEARCH_RESULTS",
    "describe_path",
    "find_matches",
    "latest_by_suffix",
    "resolve_alias",
    "resolve_destination",
    "resolve_path",
    "safe_roots",
    "user_folder_aliases",
]
