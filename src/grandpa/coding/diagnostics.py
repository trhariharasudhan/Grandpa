"""Diagnostics for Grandpa Coding Agent v1."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from grandpa.coding.architecture_analysis import analyze_architecture
from grandpa.coding.dependency_analysis import analyze_dependencies
from grandpa.coding.project_scanner import ROOT, scan_projects
from grandpa.coding.repository_analysis import analyze_repository


def coding_diagnostics(path: str | Path | None = None) -> dict[str, Any]:
    root = Path(path or ROOT).resolve()
    projects = scan_projects(root)
    dependencies = analyze_dependencies(root)
    architecture = analyze_architecture(root)
    repository = analyze_repository(root)
    return {
        "status": "ready",
        "root": str(root),
        "project_count": projects["count"],
        "dependency_manifest_count": dependencies["manifest_count"],
        "dependency_count": dependencies["dependency_count"],
        "present_layers": architecture["present_layers"],
        "file_count": repository["file_count"],
        "module_count": repository["module_count"],
        "test_count": repository["test_count"],
        "capabilities": {
            "detect_git_repositories": True,
            "detect_python_projects": True,
            "detect_node_projects": True,
            "detect_rust_projects": True,
            "dependency_analysis": True,
            "architecture_analysis": True,
            "code_execution": False,
            "code_modification": False,
        },
        "safety": {
            "read_only": True,
            "executes_code": False,
            "modifies_repositories": False,
        },
        "read_only": True,
    }


__all__ = ["coding_diagnostics"]
