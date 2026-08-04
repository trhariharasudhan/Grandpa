"""Deterministic project and module summaries."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from grandpa.coding.architecture_analysis import analyze_architecture
from grandpa.coding.dependency_analysis import analyze_dependencies
from grandpa.coding.project_scanner import ROOT
from grandpa.coding.repository_analysis import analyze_repository


def summarize_project(path: str | Path | None = None) -> dict[str, Any]:
    root = Path(path or ROOT).resolve()
    repo = analyze_repository(root)
    architecture = analyze_architecture(root)
    dependencies = analyze_dependencies(root)
    types = ", ".join(repo["project"].get("types", [])) or "unknown"
    top_language = (
        repo["language_breakdown"][0]["language"]
        if repo["language_breakdown"]
        else "unknown"
    )
    summary = (
        f"{root.name} is a {types} project. It contains {repo['file_count']} tracked source/document files, "
        f"{repo['module_count']} code module(s), {repo['test_count']} test file(s), and "
        f"{dependencies['dependency_count']} declared dependenc(ies). The largest detected language group is {top_language}."
    )
    return {
        "project": repo["project"],
        "summary": summary,
        "repository": repo,
        "architecture": architecture,
        "dependencies": dependencies,
        "read_only": True,
    }


def summarize_repository(path: str | Path | None = None) -> dict[str, Any]:
    return summarize_project(path)


def summarize_module(module_path: str | Path) -> dict[str, Any]:
    path = Path(module_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Module path does not exist: {path}")
    if path.is_dir():
        files = [item for item in path.rglob("*") if item.is_file()]
        summary = f"{path.name} is a directory with {len(files)} file(s)."
        return {
            "path": str(path),
            "type": "directory",
            "file_count": len(files),
            "summary": summary,
            "read_only": True,
        }
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    summary = (
        f"{path.name} is a {path.suffix or 'plain'} file with {len(lines)} line(s)."
    )
    return {
        "path": str(path),
        "type": "file",
        "line_count": len(lines),
        "summary": summary,
        "read_only": True,
    }


__all__ = ["summarize_module", "summarize_project", "summarize_repository"]
