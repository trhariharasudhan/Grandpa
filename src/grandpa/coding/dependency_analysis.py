"""Read-only dependency manifest inspection."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Any

from grandpa.coding.project_scanner import ROOT


def analyze_dependencies(path: str | Path | None = None) -> dict[str, Any]:
    root = Path(path or ROOT).resolve()
    manifests: list[dict[str, Any]] = []
    for filename, parser in (
        ("pyproject.toml", _parse_pyproject),
        ("requirements.txt", _parse_requirements),
        ("package.json", _parse_package_json),
        ("Cargo.toml", _parse_cargo),
        ("pubspec.yaml", _parse_pubspec),
    ):
        manifest = root / filename
        if manifest.exists():
            manifests.append(parser(manifest))
    return {
        "path": str(root),
        "manifests": manifests,
        "manifest_count": len(manifests),
        "dependency_count": sum(len(item.get("dependencies", [])) for item in manifests),
        "read_only": True,
    }


def _parse_pyproject(path: Path) -> dict[str, Any]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    deps = list(data.get("project", {}).get("dependencies", []) or [])
    optional = data.get("project", {}).get("optional-dependencies", {}) or {}
    for group, values in optional.items():
        deps.extend(f"{item} [{group}]" for item in values or [])
    poetry = data.get("tool", {}).get("poetry", {}).get("dependencies", {}) or {}
    deps.extend(name for name in poetry if name.lower() != "python")
    return _manifest(path, "python", deps)


def _parse_requirements(path: Path) -> dict[str, Any]:
    deps = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        clean = line.strip()
        if clean and not clean.startswith("#") and not clean.startswith("-"):
            deps.append(clean)
    return _manifest(path, "python", deps)


def _parse_package_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    deps = []
    for section in ("dependencies", "devDependencies", "optionalDependencies"):
        deps.extend(f"{name}@{version}" for name, version in (data.get(section) or {}).items())
    return _manifest(path, "node", deps)


def _parse_cargo(path: Path) -> dict[str, Any]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    deps = []
    for section in ("dependencies", "dev-dependencies", "build-dependencies"):
        deps.extend((data.get(section) or {}).keys())
    return _manifest(path, "rust", deps)


def _parse_pubspec(path: Path) -> dict[str, Any]:
    deps = []
    in_deps = False
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if re.match(r"^(dependencies|dev_dependencies):\s*$", line):
            in_deps = True
            continue
        if in_deps and line and not line.startswith(" "):
            in_deps = False
        if in_deps:
            match = re.match(r"^\s{2}([A-Za-z0-9_]+):", line)
            if match and match.group(1) != "flutter":
                deps.append(match.group(1))
    return _manifest(path, "flutter", deps)


def _manifest(path: Path, ecosystem: str, dependencies: list[str]) -> dict[str, Any]:
    unique = []
    seen = set()
    for dep in dependencies:
        key = dep.lower()
        if key not in seen:
            unique.append(dep)
            seen.add(key)
    return {
        "path": str(path),
        "file": path.name,
        "ecosystem": ecosystem,
        "dependencies": unique,
        "dependency_count": len(unique),
    }


__all__ = ["analyze_dependencies"]
