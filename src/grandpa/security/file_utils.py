"""Secure file and directory creation helpers.

All Grandpa data files under ``~/.grandpa/`` should be created
through these helpers to ensure consistent, restrictive permissions.
"""

from __future__ import annotations

import os
from pathlib import Path


def secure_mkdir(path: Path, mode: int = 0o700) -> Path:
    """Create a directory with restrictive permissions.

    Creates parent directories as needed, then sets *mode* on the
    target directory (even if it already exists).
    """
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, mode)
    except PermissionError:
        # Windows can deny chmod on user-profile directories even when the
        # directory is readable/writable by the current user. Treat that as a
        # platform permission limitation, not a config-load failure.
        pass
    return path


def secure_create(path: Path, mode: int = 0o600) -> Path:
    """Ensure a file exists with restrictive permissions.

    Creates the parent directory with ``0o700`` if needed, touches the
    file if it doesn't exist, and sets *mode* on it.
    """
    secure_mkdir(path.parent, mode=0o700)
    if not path.exists():
        path.touch()
    try:
        os.chmod(path, mode)
    except PermissionError:
        pass
    return path
