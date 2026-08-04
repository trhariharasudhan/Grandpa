"""Read-only repository metrics for Grandpa Coding Agent."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from grandpa.coding.project_scanner import IGNORED_DIRS, ROOT, detect_project

LANGUAGE_EXTENSIONS = {
    ".py": "Python",
    ".ts": "TypeScript",
    ".tsx": "TypeScript React",
    ".js": "JavaScript",
    ".jsx": "JavaScript React",
    ".rs": "Rust",
    ".dart": "Dart",
    ".md": "Markdown",
    ".json": "JSON",
    ".toml": "TOML",
    ".yml": "YAML",
    ".yaml": "YAML",
    ".css": "CSS",
    ".html": "HTML",
}


def analyze_repository(path: str | Path | None = None) -> dict[str, Any]:
    root = Path(path or ROOT).resolve()
    files = list(_iter_files(root))
    language_counts: Counter[str] = Counter()
    language_bytes: Counter[str] = Counter()
    test_count = 0
    module_count = 0
    total_bytes = 0
    for file in files:
        size = _size(file)
        total_bytes += size
        language = LANGUAGE_EXTENSIONS.get(file.suffix.lower(), "Other")
        language_counts[language] += 1
        language_bytes[language] += size
        rel = file.relative_to(root)
        parts = {part.lower() for part in rel.parts}
        if (
            "tests" in parts
            or file.name.startswith("test_")
            or file.name.endswith(".test.ts")
            or file.name.endswith(".spec.ts")
        ):
            test_count += 1
        if file.suffix.lower() in {".py", ".ts", ".tsx", ".js", ".rs", ".dart"}:
            module_count += 1
    dependency_count = _dependency_count(root)
    return {
        "project": detect_project(root),
        "repository_size_bytes": total_bytes,
        "file_count": len(files),
        "module_count": module_count,
        "test_count": test_count,
        "dependency_count": dependency_count,
        "language_breakdown": [
            {"language": language, "files": count, "bytes": language_bytes[language]}
            for language, count in language_counts.most_common()
        ],
        "read_only": True,
    }


def _iter_files(root: Path):
    for path in root.rglob("*"):
        if any(part in IGNORED_DIRS for part in path.parts):
            continue
        if path.is_file():
            yield path


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _dependency_count(root: Path) -> int:
    try:
        from grandpa.coding.dependency_analysis import analyze_dependencies

        data = analyze_dependencies(root)
        return sum(
            len(item.get("dependencies", [])) for item in data.get("manifests", [])
        )
    except Exception:
        return 0


__all__ = ["LANGUAGE_EXTENSIONS", "analyze_repository"]
