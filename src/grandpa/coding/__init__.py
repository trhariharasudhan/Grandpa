"""Read-only local project inspection for Grandpa Coding Agent v1."""

from grandpa.coding.architecture_analysis import analyze_architecture
from grandpa.coding.code_summary import summarize_module, summarize_project, summarize_repository
from grandpa.coding.dependency_analysis import analyze_dependencies
from grandpa.coding.diagnostics import coding_diagnostics
from grandpa.coding.project_scanner import detect_project, scan_projects
from grandpa.coding.repository_analysis import analyze_repository

__all__ = [
    "analyze_architecture",
    "analyze_dependencies",
    "analyze_repository",
    "coding_diagnostics",
    "detect_project",
    "scan_projects",
    "summarize_module",
    "summarize_project",
    "summarize_repository",
]
