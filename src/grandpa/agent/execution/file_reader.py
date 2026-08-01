"""Bounded and safe file reading helper for Agent Execution Engine V2."""

from __future__ import annotations

import re
from pathlib import Path

from grandpa.agent.execution.workspace import is_subpath

# Sensitive files patterns
SENSITIVE_PATTERNS = [
    r"\.env$", r"\.env\.", r"key", r"token", r"secret", r"vault", r"auth",
    r"\.git", r"\.pytest_cache", r"\.ruff_cache", r"\.venv", r"__pycache__"
]


def is_sensitive_path(path_str: str) -> bool:
    """Verify if the path string matches patterns for credentials, tokens, or system configurations."""
    p_lower = path_str.lower().replace("\\", "/")
    for pattern in SENSITIVE_PATTERNS:
        if re.search(pattern, p_lower):
            return True
    return False


def read_file_safe(file_path: str, workspace_root: str, max_lines: int = 200, max_bytes: int = 50000) -> str:
    """Safely read text file content, returning bounded line strings."""
    try:
        p = Path(file_path).resolve()
        root = Path(workspace_root).resolve()
    except Exception as exc:
        return f"Error resolving file path: {exc}"

    # 1. Traversal check
    if not is_subpath(p, root):
        return f"Access Denied: Path traversal detected. '{file_path}' is outside workspace '{workspace_root}'."

    # 2. Sensitivity pattern check
    if is_sensitive_path(str(p)):
        return f"Access Denied: File '{file_path}' matches sensitive path patterns."

    if not p.exists():
        return f"Error: File '{file_path}' does not exist."

    if not p.is_file():
        return f"Error: Path '{file_path}' is not a file."

    # 3. Size check
    try:
        size = p.stat().st_size
        if size > max_bytes:
            return f"Error: File size ({size} bytes) exceeds limit of {max_bytes} bytes."
    except OSError as exc:
        return f"Error checking file size: {exc}"

    # 4. Binary check
    try:
        with open(p, "rb") as f:
            chunk = f.read(1024)
            if b"\x00" in chunk:
                return "Error: Binary file reading is blocked."
    except Exception as exc:
        return f"Error checking binary file: {exc}"

    # 5. Read lines safely
    try:
        lines = []
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            for idx, line in enumerate(f, 1):
                if idx > max_lines:
                    lines.append(f"[Truncated: Exceeded limit of {max_lines} lines]")
                    break
                lines.append(line)
        return "".join(lines)
    except Exception as exc:
        return f"Error reading file content: {exc}"
