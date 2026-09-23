"""Grandpa's own state does not land wherever the process was started.

``RUNTIME_DIR``, ``DEFAULT_USER_SKILLS_DB`` and ``DEFAULT_OPERATOR_DB`` were
relative paths. Start the CLI from one directory and the server from another
and they were different installations that could not see each other's data --
and a test suite run from the project root wrote a ``runtime/`` tree into the
repository. A ``user_skills.db`` left there was later picked up by a test that
believed it was reading an isolated store, and failed on a skill nobody in
that run had created.

They are rooted under ``GRANDPA_HOME`` now. This pins that, and pins it by
scanning for the shape rather than by listing the three that were wrong, so a
fourth added later is caught the day it appears.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "grandpa"

# Module-level names that hold a path a store or a log defaults to.
SUSPICIOUS_NAME = ("_DIR", "_PATH", "_DB", "_LOG", "_FILE")


def _default_path_constants() -> list[tuple[Path, str, str]]:
    """Every module-level constant whose name says it holds a path."""
    found: list[tuple[Path, str, str]] = []
    for path in sorted(SRC.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - not this test's business
            continue
        for node in tree.body:
            targets = []
            if isinstance(node, ast.Assign):
                targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                targets = [node.target.id]
            for name in targets:
                if name.isupper() and name.endswith(SUSPICIOUS_NAME):
                    found.append((path, name, ast.unparse(node.value)))
    return found


def test_the_scan_finds_something() -> None:
    """An empty scan would make the assertion below vacuous."""
    assert len(_default_path_constants()) >= 10


def test_no_default_path_constant_is_a_bare_relative_literal() -> None:
    """``Path("runtime")`` and friends: rooted nowhere, so rooted at the cwd."""
    offenders = [
        f"{path.relative_to(SRC).as_posix()}: {name} = {value}"
        for path, name, value in _default_path_constants()
        if 'Path("' in value
        and "DEFAULT_CONFIG_DIR" not in value
        and "runtime_path" not in value
        and "runtime_dir" not in value
        and "home()" not in value
        and "__file__" not in value
        and '"~' not in value
        and not any(
            value.startswith(prefix) for prefix in ('Path("/', "Path(os.", "Path(str(")
        )
    ]

    assert offenders == [], (
        "these default to a path relative to the working directory, so the "
        f"state they name lands wherever the process was started: {offenders}"
    )


@pytest.mark.parametrize(
    "dotted,attribute",
    [
        ("grandpa.pc_control", "RUNTIME_DIR"),
        ("grandpa.pc_control", "AUDIT_LOG_PATH"),
        ("grandpa.skill_builder.storage", "DEFAULT_USER_SKILLS_DB"),
        ("grandpa.desktop.operator", "DEFAULT_OPERATOR_DB"),
    ],
)
def test_the_three_that_were_wrong_are_absolute(dotted: str, attribute: str) -> None:
    import importlib

    value = getattr(importlib.import_module(dotted), attribute)

    assert value.is_absolute(), f"{dotted}.{attribute} is {value}"


def test_they_follow_grandpa_home(monkeypatch, tmp_path: Path) -> None:
    """Not merely absolute -- absolute *under the configured home*."""
    monkeypatch.setenv("GRANDPA_HOME", str(tmp_path))
    monkeypatch.delenv("GRANDPA_RUNTIME_DIR", raising=False)

    from grandpa.runtime_paths import runtime_dir, runtime_path

    assert runtime_dir() == tmp_path / "runtime"
    assert runtime_path("skills", "user_skills.db").is_relative_to(tmp_path)


def test_state_left_at_the_old_location_is_reported_not_moved(tmp_path: Path) -> None:
    """A person with data in an old ./runtime is told, not migrated silently.

    Copying it would have to guess which ``./runtime`` is the real one when the
    app has been started from several directories; deleting it is not a
    decision a path module makes. So it stays, and it is findable.
    """
    from grandpa.runtime_paths import legacy_state

    legacy = tmp_path / "runtime" / "skills"
    legacy.mkdir(parents=True)
    (legacy / "user_skills.db").write_bytes(b"old")

    found = legacy_state(cwd=tmp_path)

    assert [p.name for p in found] == ["user_skills.db"]
    assert (legacy / "user_skills.db").exists(), "it must not have been moved"
    assert (legacy / "user_skills.db").read_bytes() == b"old"


def test_nothing_is_reported_when_there_is_no_old_location(tmp_path: Path) -> None:
    from grandpa.runtime_paths import legacy_state

    assert legacy_state(cwd=tmp_path) == []


def test_the_environment_can_still_override(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("GRANDPA_RUNTIME_DIR", str(tmp_path / "elsewhere"))

    from grandpa.runtime_paths import runtime_dir

    assert runtime_dir() == tmp_path / "elsewhere"
    assert os.environ["GRANDPA_RUNTIME_DIR"]
