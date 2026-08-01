"""Workspace and path safety validator for Agent Execution Engine V2."""

from __future__ import annotations

import os
from pathlib import Path

from grandpa.agent.execution.models import WorkspaceContext


def resolve_and_verify_workspace(path_str: str) -> WorkspaceContext:
    """Resolve and verify that the given path is a safe project root."""
    try:
        raw_path = Path(path_str).expanduser().absolute()
        resolved_path = raw_path.resolve()
    except Exception as exc:
        return WorkspaceContext(
            root_path=path_str,
            is_safe=False,
            reason=f"Failed to resolve path: {exc}",
        )

    # 1. Canonicalize and check existence
    if not resolved_path.exists():
        return WorkspaceContext(
            root_path=str(resolved_path),
            is_safe=False,
            reason="Workspace path does not exist.",
        )

    if not resolved_path.is_dir():
        return WorkspaceContext(
            root_path=str(resolved_path),
            is_safe=False,
            reason="Workspace path is not a directory.",
        )

    # 2. Reject sensitive system directories
    system_dirs = {
        "c:\\windows", "c:\\program files", "c:\\program files (x86)",
        "/usr/bin", "/bin", "/sbin", "/etc", "/var", "/lib", "/sys", "/proc"
    }
    path_lower = str(resolved_path).lower()
    for sys_dir in system_dirs:
        if path_lower.startswith(sys_dir):
            return WorkspaceContext(
                root_path=str(resolved_path),
                is_safe=False,
                reason=f"Access denied: System directory '{sys_dir}' is blocked.",
            )

    # 3. Enforce approved workspace scope
    # Approved locations: D:\\Grandpa, or any folder under system temp directory
    temp_dir = Path(os.environ.get("TEMP", os.environ.get("TMP", "/tmp"))).resolve()
    is_in_temp = is_subpath(resolved_path, temp_dir)
    is_in_grandpa = is_subpath(resolved_path, Path("D:\\Grandpa"))

    # 4. Reject user profile secrets directories (unless inside temp directory)
    if not is_in_temp:
        user_secret_patterns = [
            "\\.ssh", "\\.aws", "\\.gemini", "\\.config", "appdata", "local settings"
        ]
        import re
        for pattern in user_secret_patterns:
            if re.search(pattern, path_lower):
                return WorkspaceContext(
                    root_path=str(resolved_path),
                    is_safe=False,
                    reason=f"Access denied: Sensitive user path matching '{pattern}' is blocked.",
                )

    if not (is_in_grandpa or is_in_temp or str(resolved_path) == "D:\\Grandpa"):
        return WorkspaceContext(
            root_path=str(resolved_path),
            is_safe=False,
            reason="Workspace path is outside approved repository and temporary directories.",
        )

    # Read current branch to verify repo state
    branch = None
    try:
        import subprocess
        res = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(resolved_path),
            capture_output=True,
            text=True,
            timeout=3,
        )
        if res.returncode == 0:
            branch = res.stdout.strip()
    except Exception:
        pass

    return WorkspaceContext(
        root_path=str(resolved_path),
        is_safe=True,
        active_branch=branch,
    )


def is_subpath(child: Path, parent: Path) -> bool:
    """Check if child path is safely nested under parent path, preventing traversal."""
    try:
        child_res = child.resolve()
        parent_res = parent.resolve()
        return parent_res in child_res.parents or child_res == parent_res
    except Exception:
        return False
