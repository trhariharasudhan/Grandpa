"""Where Grandpa keeps its own state.

Three stores defaulted to a *relative* path -- ``Path("runtime")`` and two
databases under it -- so the audit log, the desktop operator's history and the
user's saved skills landed wherever the process happened to be started from.
Run the CLI from one directory and the app from another and they are different
installations that cannot see each other's data.

It also made a test able to write into the repository: a suite run from the
project root left a ``runtime/skills/user_skills.db`` behind, and a later run
picked up the skill saved in it and failed on it, because the store the test
thought was isolated was the same file every time.

State now lives under ``GRANDPA_HOME`` (``~/.grandpa`` unless the environment
says otherwise), which is where the rest of Grandpa's data already is.

Existing state at the old location
----------------------------------
It is **left where it is, and reported** -- not migrated and not orphaned in
silence. :func:`legacy_state` finds it and ``grandpa doctor`` prints it, so a
person who has data in an old ``./runtime`` directory is told the path, told
that nothing is reading it any more, and can move it themselves. Copying it
automatically would guess which of several ``./runtime`` directories is the
real one when a person has started the app from more than one place, and
deleting it is not a decision a path-resolution module gets to make.
"""

from __future__ import annotations

import os
from pathlib import Path

LEGACY_RUNTIME_DIR = Path("runtime")
"""What these paths used to be, relative to the working directory."""


def grandpa_home() -> Path:
    """The configured home. Read every call: tests move it per test."""
    from grandpa.core.config import DEFAULT_CONFIG_DIR

    override = os.environ.get("GRANDPA_HOME")
    return Path(override).expanduser() if override else DEFAULT_CONFIG_DIR


def runtime_dir() -> Path:
    """The root for Grandpa's own runtime state."""
    override = os.environ.get("GRANDPA_RUNTIME_DIR")
    if override:
        return Path(override).expanduser()
    return grandpa_home() / "runtime"


def runtime_path(*parts: str) -> Path:
    return runtime_dir().joinpath(*parts)


def legacy_state(cwd: Path | None = None) -> list[Path]:
    """Files under a relative ``./runtime`` that nothing reads any more.

    Returned so the doctor can say what was found. Nothing here moves or
    deletes them.
    """
    base = (cwd or Path.cwd()) / LEGACY_RUNTIME_DIR
    if not base.exists() or base.resolve() == runtime_dir().resolve():
        return []
    return sorted(path for path in base.rglob("*") if path.is_file())


__all__ = [
    "LEGACY_RUNTIME_DIR",
    "grandpa_home",
    "legacy_state",
    "runtime_dir",
    "runtime_path",
]
