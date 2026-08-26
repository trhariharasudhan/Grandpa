"""Detect how Grandpa was installed, to decide whether it can self-update.

Grandpa has no published distribution. The PyPI name ``grandpa`` belongs to
an unrelated project (``grandpa`` 0.6.3, "Bizerba AI Team"), so
``pip install --upgrade grandpa`` and ``uv tool upgrade grandpa`` would pull a
third party's package over the user's environment. Neither command is ever
produced by this module.

The only supported install today is the documented one: a git checkout with an
editable install (``git clone`` + ``uv sync``). That upgrades from the user's
own remote, so it is safe and stays enabled.

Every other install shape reports ``upgrade_command = ""`` and an
``unsupported_reason``. Callers must check :attr:`InstallInfo.can_upgrade`
before running anything.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import grandpa

#: Why non-checkout installs cannot self-update. Referenced in the CLI output.
NO_DISTRIBUTION_REASON = (
    "Grandpa has no published package. The name 'grandpa' on PyPI belongs to "
    "an unrelated project, so upgrading through pip or uv would install "
    "someone else's software. Update by pulling the git checkout instead: "
    "https://github.com/trhariharasudhan/Grandpa"
)


@dataclass(frozen=True)
class InstallInfo:
    """How Grandpa was installed, and whether it can upgrade itself."""

    kind: str  # "pypi" | "uv-tool" | "editable-git" | "unknown"
    upgrade_command: str  # "" when no verified upgrade path exists
    repo_root: Optional[Path] = None  # only set for editable-git
    unsupported_reason: str = ""

    @property
    def can_upgrade(self) -> bool:
        """True only when a verified upgrade command is available."""
        return bool(self.upgrade_command)


def detect_install() -> InstallInfo:
    """Return an :class:`InstallInfo` for the running interpreter.

    Cheap: just walks the parent directories of ``grandpa.__file__``
    once and checks for marker directories. No subprocess calls.
    """
    try:
        pkg_file = Path(grandpa.__file__).resolve()
    except Exception:
        return InstallInfo(
            kind="unknown",
            upgrade_command="",
            unsupported_reason=NO_DISTRIBUTION_REASON,
        )

    parts = [p.lower() for p in pkg_file.parts]

    if "uv" in parts and "tools" in parts:
        return InstallInfo(
            kind="uv-tool",
            upgrade_command="",
            unsupported_reason=NO_DISTRIBUTION_REASON,
        )

    # Editable install: a ``.git`` dir within a few parents of the
    # package source. Walk up at most ~8 levels — enough for typical
    # ``<repo>/src/grandpa/__init__.py`` layouts plus headroom, but
    # not so deep we wander into home or root.
    candidate = pkg_file.parent
    for _ in range(8):
        if (candidate / ".git").exists() and (candidate / "pyproject.toml").exists():
            return InstallInfo(
                kind="editable-git",
                upgrade_command=f"cd {candidate} && git pull && uv sync",
                repo_root=candidate,
            )
        if candidate.parent == candidate:
            break
        candidate = candidate.parent

    if "site-packages" in parts:
        return InstallInfo(
            kind="pypi",
            upgrade_command="",
            unsupported_reason=NO_DISTRIBUTION_REASON,
        )

    return InstallInfo(
        kind="unknown",
        upgrade_command="",
        unsupported_reason=NO_DISTRIBUTION_REASON,
    )
