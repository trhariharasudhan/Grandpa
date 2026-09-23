"""The skills that ship inside the package.

Eighteen manifests live in ``grandpa/skills/data/``. Until now nothing could
reach them: ``skill list`` reported "No skills installed" on a clean install,
because the search path was ``./skills`` and ``~/.grandpa/skills/`` and never
the packaged directory.

They are read-only on purpose. A user can shadow one by putting a skill of the
same name in their own directory -- discovery is first-seen-wins and the
bundled root is searched last -- but they cannot edit or delete what shipped
with the product, any more than they can edit a module in site-packages. The
refusal is explicit here rather than left to the fact that the manifests happen
to be flat files that ``find_installed_paths`` does not match.
"""

from __future__ import annotations

from pathlib import Path

BUNDLED_DIR = Path(__file__).resolve().parent / "data"
"""Where the packaged manifests live."""

PROVENANCE = "bundled"
"""What every manifest in that directory must declare.

``SkillManager.discover()`` will not load a manifest that does not say who
wrote it, and "bundled" is the value that means "reviewed in the repository
like any other code". A manifest added to that directory without it does not
load -- so the requirement is a test
(``tests/skills/test_bundled_skills.py``), not a convention.
"""


def bundled_dir() -> Path:
    return BUNDLED_DIR


def is_bundled(path: Path) -> bool:
    """Whether ``path`` is one of the packaged manifests."""
    try:
        return path.resolve().is_relative_to(BUNDLED_DIR)
    except (OSError, ValueError):
        return False


def bundled_names() -> frozenset[str]:
    """The names a user may not create, edit or delete."""
    if not BUNDLED_DIR.exists():
        return frozenset()
    return frozenset(path.stem for path in BUNDLED_DIR.glob("*.toml"))


def refuse_write(name: str) -> str | None:
    """Why ``name`` may not be written, or None when it may."""
    if name in bundled_names():
        return (
            f"{name!r} ships with Grandpa and cannot be created, edited or "
            f"deleted. To replace it, put a skill of the same name in "
            f"~/.grandpa/skills/ -- your own copy is found first."
        )
    return None


__all__ = [
    "BUNDLED_DIR",
    "PROVENANCE",
    "bundled_dir",
    "bundled_names",
    "is_bundled",
    "refuse_write",
]
