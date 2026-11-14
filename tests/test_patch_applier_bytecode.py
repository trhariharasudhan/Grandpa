"""A patched source file is never verified against its stale bytecode.

``test_agent_execution_v2``'s calculator fixtures failed intermittently on
windows-latest (and 2 runs in 6 on Linux): the patch ``a - b`` -> ``a + b``
keeps the file's size, the diagnose run had compiled it in the same second,
and Python's mtime+size check reused the old ``.pyc``. The verification run
then reported a correct patch as failed.
"""

from __future__ import annotations

import os
import py_compile
from pathlib import Path

from grandpa.agent.execution.patch_applier import (
    drop_stale_bytecode,
    rollback_applied_backups,
)


def _compiled(source: Path) -> list[Path]:
    return sorted((source.parent / "__pycache__").glob(f"{source.stem}.*.pyc"))


def test_rewriting_drops_only_that_files_bytecode(tmp_path: Path) -> None:
    target = tmp_path / "calculator.py"
    other = tmp_path / "other.py"
    target.write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    other.write_text("X = 1\n", encoding="utf-8")
    py_compile.compile(str(target))
    py_compile.compile(str(other))
    stamp = target.stat()

    # The same-size, same-second rewrite that made the cache look current.
    target.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    os.utime(target, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    assert target.stat().st_size == stamp.st_size
    assert _compiled(target)

    drop_stale_bytecode(str(target))

    assert _compiled(target) == []
    assert _compiled(other), "an unrelated module's cache must be left alone"


def test_non_python_and_uncompiled_files_are_ignored(tmp_path: Path) -> None:
    text = tmp_path / "notes.txt"
    text.write_text("x", encoding="utf-8")
    drop_stale_bytecode(str(text))
    fresh = tmp_path / "fresh.py"
    fresh.write_text("Y = 2\n", encoding="utf-8")
    drop_stale_bytecode(str(fresh))  # no __pycache__ yet: nothing to do


def test_rollback_also_drops_the_patched_bytecode(tmp_path: Path) -> None:
    target = tmp_path / "calculator.py"
    backup = tmp_path / "calculator.py.bak"
    backup.write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    target.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    py_compile.compile(str(target))
    assert _compiled(target)

    rollback_applied_backups([(str(target), str(backup))])

    assert "a - b" in target.read_text(encoding="utf-8")
    assert _compiled(target) == []
