"""The filesystem is confined during a test, and this is what says so.

The actuation guard covers the implementations the catalogue names. It does
not cover the filesystem, which is how a mutation run that removed
``FileWriteTool``'s path guard wrote ``x`` over a real
``~/.ssh/authorized_keys`` and a real ``~/.grandpa/config.toml``: the tool is
not a catalogued action, and the test asserting its refusal named real
absolute paths.

tests/write_guard.py confines every Python-level write to the test's own
scratch space. This file is the check on that confinement -- the equivalent of
test_default_deny_actuation.py for writes rather than actions.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from tests.actuation_guard import ActuationDenied
from tests.write_guard import (
    OS_FUNCTIONS,
    PATH_METHODS,
    SHUTIL_SOURCE_AND_DEST,
    allowed_roots,
    is_allowed,
    is_write_guarded,
)


def _outside() -> Path:
    """A path a test has no business writing to, on any machine.

    Under the user's home but outside every allowed root -- the same shape as
    the two files that were damaged.
    """
    return Path.home() / ".grandpa-write-guard-probe" / "must-not-exist.txt"


def test_a_write_under_the_home_directory_raises() -> None:
    """The exact shape of the damage: Path.write_text to a real location."""
    target = _outside()

    with pytest.raises(ActuationDenied, match="outside the test's own scratch space"):
        target.write_text("x", encoding="utf-8")

    assert not target.exists()


def test_open_in_a_writing_mode_raises() -> None:
    target = _outside()

    for mode in ("w", "a", "x", "r+"):
        with pytest.raises(ActuationDenied):
            open(target, mode)

    assert not target.exists()


def test_reading_is_not_affected() -> None:
    """Confinement is about writes. A read of a real path still works."""
    readable = Path(__file__)

    assert readable.read_text(encoding="utf-8").startswith('"""')
    with open(readable, encoding="utf-8") as handle:
        assert handle.readline()


def test_the_removers_and_movers_raise() -> None:
    target = _outside()

    with pytest.raises(ActuationDenied):
        os.remove(target)
    with pytest.raises(ActuationDenied):
        os.makedirs(target.parent)
    with pytest.raises(ActuationDenied):
        shutil.rmtree(target.parent)
    with pytest.raises(ActuationDenied):
        shutil.copy(__file__, target)

    assert not target.parent.exists()


def test_the_scratch_space_itself_still_works(tmp_path: Path) -> None:
    """A confinement that refused everything would be a different bug."""
    target = tmp_path / "sub" / "notes.txt"
    target.parent.mkdir(parents=True)
    target.write_text("hello", encoding="utf-8")

    assert target.read_text(encoding="utf-8") == "hello"
    shutil.copy(target, tmp_path / "copy.txt")
    os.remove(tmp_path / "copy.txt")


def test_grandpa_home_counts_when_a_test_sets_it(monkeypatch, tmp_path: Path) -> None:
    """Tests point the app's stores at a scratch directory; that must work."""
    home = tmp_path / "grandpa-home"
    home.mkdir()
    monkeypatch.setenv("GRANDPA_HOME", str(home))

    (home / "store.db").write_text("x", encoding="utf-8")

    assert is_allowed(home / "store.db")


def test_an_unset_grandpa_home_is_not_a_permission(monkeypatch) -> None:
    """Unset means the real ~/.grandpa, which is one of the damaged files."""
    monkeypatch.delenv("GRANDPA_HOME", raising=False)

    assert not is_allowed(Path.home() / ".grandpa" / "config.toml")


def test_every_write_entry_point_is_guarded() -> None:
    """The guard is only as good as the list of functions it replaced."""
    import builtins
    import io
    import pathlib

    live: list[str] = []
    if not is_write_guarded(builtins, "open"):
        live.append("builtins.open")
    if not is_write_guarded(io, "open"):
        live.append("io.open")
    for name in PATH_METHODS:
        if hasattr(pathlib.Path, name) and not is_write_guarded(pathlib.Path, name):
            live.append(f"Path.{name}")
    for name in OS_FUNCTIONS:
        if hasattr(os, name) and not is_write_guarded(os, name):
            live.append(f"os.{name}")
    for name in (*SHUTIL_SOURCE_AND_DEST, "rmtree"):
        if hasattr(shutil, name) and not is_write_guarded(shutil, name):
            live.append(f"shutil.{name}")

    assert live == [], f"these write entry points are live in a test: {live}"


def test_the_allowed_roots_are_not_empty_or_everything() -> None:
    roots = allowed_roots()

    assert roots, "an empty root list would deny even tmp_path"
    assert not any(str(root) in {"/", "C:\\", "C:/"} for root in roots)
    assert not is_allowed(Path.home()), "the home directory itself is not a root"


@pytest.mark.real_actions(
    reason="checks that the marker really restores the real filesystem; writes "
    "one file under tmp_path and removes it"
)
def test_the_marker_gives_the_real_filesystem_back(tmp_path: Path) -> None:
    import builtins

    assert not is_write_guarded(builtins, "open")
    probe = tmp_path / "real.txt"
    probe.write_text("real", encoding="utf-8")
    assert probe.read_text(encoding="utf-8") == "real"
