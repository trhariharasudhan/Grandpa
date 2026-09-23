"""No test writes outside its own scratch space unless it says so.

The actuation guard replaces every implementation the *catalogue* names. It
does not replace the filesystem, and it never claimed to -- which left a gap
big enough to damage a real machine:

``FileWriteTool`` is a tool, not a catalogued action, so nothing replaced it.
Its guard was the only thing keeping it inside the user's own folders, and a
mutation run deliberately removed that guard to prove the refusal was real.
The test asserting the refusal named real absolute paths, so the moment the
guard came off, ``path.write_text("x")`` landed on the real
``~/.ssh/authorized_keys`` and ``~/.grandpa/config.toml``.

Fixing the one test would leave the gap: any other test that names an absolute
path, and any future mutation of any other write guard, has the same reach. So
the filesystem is confined instead, at the lowest level a Python caller can
reach it -- ``open`` in a writing mode, the ``pathlib`` mutators, the ``os``
removers and movers, and ``shutil``'s copy and delete helpers.

Allowed destinations
--------------------
* anything under the system temp directory, which is where ``tmp_path``,
  ``tmp_path_factory`` and ``tempfile.mkdtemp()`` all live;
* anything under ``GRANDPA_HOME`` **when a test has set it**, which is how
  tests point the app's own stores at a scratch directory. An unset
  ``GRANDPA_HOME`` is not a permission: unset means the real ``~/.grandpa``,
  which is one of the two things that got damaged;
* ``__pycache__`` directories, so importing a module can still write bytecode;
* the tool caches at the repository root (``.pytest_cache``, ``.ruff_cache``,
  coverage data), which the test runner itself maintains;
* the null device.

Everything else raises :class:`~tests.actuation_guard.ActuationDenied`, the
same ``BaseException`` the actuation guard uses, for the same reason: a broad
``except Exception`` must not be able to swallow it.

A test that really must write elsewhere opts out the existing way::

    @pytest.mark.real_actions(reason="writes into the repo's own runtime dir")

What this does not cover
------------------------
Writes that never pass through Python -- sqlite3's C implementation opening a
database file, a subprocess writing on its own -- are invisible here. Those
reach the disk through ``subprocess.Popen`` and the catalogued
implementations, which the actuation guard already denies.
"""

from __future__ import annotations

import builtins
import functools
import io
import os
import pathlib
import shutil
import tempfile
from pathlib import Path
from typing import Any

from tests.actuation_guard import MARKER, ActuationDenied

_WRITING_MODES = frozenset("wax+")


SESSION_HOME = os.environ.get("GRANDPA_HOME")
"""The suite's own scratch home, as conftest set it before collection.

Module-level constants like ``pc_control.AUDIT_LOG_PATH`` resolve ``GRANDPA_HOME``
once, at import. A test that re-points the variable at its own ``tmp_path`` does
not move those constants, so a write through one of them still lands in the
session home -- which is a scratch directory the suite created, and has to stay
allowed for the whole run rather than only while it is the current value.
"""


@functools.lru_cache(maxsize=8)
def _roots_for(home: str | None) -> tuple[Path, ...]:
    roots = [Path(tempfile.gettempdir())]
    if home:
        roots.append(Path(home))
    if SESSION_HOME and SESSION_HOME != home:
        roots.append(Path(SESSION_HOME))
    repository = Path(__file__).resolve().parents[1]
    roots.extend(
        [
            repository / ".pytest_cache",
            repository / ".ruff_cache",
            repository / "htmlcov",
        ]
    )
    return tuple(_normalise(root) for root in roots)


def allowed_roots() -> tuple[Path, ...]:
    """Where a test may write.

    ``GRANDPA_HOME`` is read at call time, not at setup: a test sets it inside
    its own body, and a snapshot taken when the fixture ran would miss that.
    The resolved roots are cached per value of that variable, because this runs
    on every filesystem call in the suite and ``Path.resolve()`` hits the disk.
    """
    return _roots_for(os.environ.get("GRANDPA_HOME"))


@functools.lru_cache(maxsize=4096)
def _normalise_str(text: str) -> Path:
    try:
        return Path(text).expanduser().resolve(strict=False)
    except (TypeError, ValueError, OSError):
        return Path(text)


def _normalise(path: Any) -> Path:
    try:
        return _normalise_str(os.fspath(path))
    except TypeError:
        return Path(str(path))


def is_allowed(target: Any) -> bool:
    """Whether a write to ``target`` is inside a test's own scratch space.

    An ``int`` is a file descriptor, not a path: ``open(fd, "w")`` is how
    ``tempfile`` and atomic-write helpers hand an already-opened file to the
    text layer. Whatever produced the descriptor was itself checked, and
    refusing here leaks it -- which is how the first version of this guard left
    a temp file open and turned an atomic config write into WinError 32.
    """
    if isinstance(target, int):
        return True
    try:
        resolved = _normalise(target)
    except Exception:  # noqa: BLE001 - an unparseable path is not a write we allow
        return False
    name = resolved.name.lower()
    if name in {"nul", "null", "devnull"} or str(resolved).lower().endswith(
        "/dev/null"
    ):
        return True
    if "__pycache__" in resolved.parts:
        return True
    if name.startswith(".coverage"):
        return True
    # normcase, not ==: Windows is case-insensitive, and Path.resolve() does
    # not normalise case, so C:\Users\x\.Grandpa and C:\Users\x\.grandpa are
    # the same directory but compare unequal. That is a real code path -- the
    # security setup builds the home from a differently-cased literal.
    target = os.path.normcase(str(resolved))
    for root in allowed_roots():
        root_text = os.path.normcase(str(root))
        if target == root_text or target.startswith(root_text + os.sep):
            return True
    return False


def _refuse(target: Any, call: str) -> ActuationDenied:
    roots = "\n    ".join(str(root) for root in allowed_roots())
    return ActuationDenied(
        f"{call} tried to write outside the test's own scratch space:\n"
        f"    {_normalise(target)}\n"
        f"Allowed roots:\n    {roots}\n"
        f"Nothing writes to a real location by default. If this test needs to, "
        f"mark it:\n"
        f'    @pytest.mark.{MARKER}(reason="why, and what it writes")'
    )


def _guard_path_method(name: str, original: Any):
    def guarded(self: Path, *args: Any, **kwargs: Any) -> Any:
        if not is_allowed(self):
            raise _refuse(self, f"Path.{name}")
        return original(self, *args, **kwargs)

    guarded.__write_guarded__ = f"Path.{name}"  # type: ignore[attr-defined]
    return guarded


def _guard_target_function(module_label: str, name: str, original: Any, index: int = 0):
    def guarded(*args: Any, **kwargs: Any) -> Any:
        target = args[index] if len(args) > index else None
        if target is not None and not is_allowed(target):
            raise _refuse(target, f"{module_label}.{name}")
        return original(*args, **kwargs)

    guarded.__write_guarded__ = f"{module_label}.{name}"  # type: ignore[attr-defined]
    return guarded


def _guard_open(original: Any, label: str):
    def guarded(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        if _WRITING_MODES & set(str(mode)) and not is_allowed(file):
            raise _refuse(file, label)
        return original(file, mode, *args, **kwargs)

    guarded.__write_guarded__ = label  # type: ignore[attr-defined]
    return guarded


PATH_METHODS = (
    "write_text",
    "write_bytes",
    "mkdir",
    "touch",
    "unlink",
    "rmdir",
    "rename",
    "replace",
    "symlink_to",
    "chmod",
)

OS_FUNCTIONS = (
    "remove",
    "unlink",
    "rmdir",
    "removedirs",
    "makedirs",
    "mkdir",
    "truncate",
)
OS_TWO_ARG = ("rename", "replace", "link", "symlink")
SHUTIL_SOURCE_AND_DEST = ("copy", "copy2", "copyfile", "copytree", "move")


def confine_writes(monkeypatch) -> int:
    """Confine every Python-level write to the test's own scratch space."""
    replaced = 0

    monkeypatch.setattr(builtins, "open", _guard_open(builtins.open, "open"))
    monkeypatch.setattr(io, "open", _guard_open(io.open, "io.open"))
    replaced += 2

    for name in PATH_METHODS:
        original = getattr(pathlib.Path, name, None)
        if original is None:
            continue
        monkeypatch.setattr(pathlib.Path, name, _guard_path_method(name, original))
        replaced += 1

    for name in OS_FUNCTIONS:
        original = getattr(os, name, None)
        if original is None:
            continue
        monkeypatch.setattr(os, name, _guard_target_function("os", name, original))
        replaced += 1

    for name in OS_TWO_ARG:
        original = getattr(os, name, None)
        if original is None:
            continue
        # The destination is what gets created, so index 1.
        monkeypatch.setattr(os, name, _guard_target_function("os", name, original, 1))
        replaced += 1

    for name in SHUTIL_SOURCE_AND_DEST:
        original = getattr(shutil, name, None)
        if original is None:
            continue
        monkeypatch.setattr(
            shutil, name, _guard_target_function("shutil", name, original, 1)
        )
        replaced += 1

    monkeypatch.setattr(
        shutil, "rmtree", _guard_target_function("shutil", "rmtree", shutil.rmtree)
    )
    replaced += 1
    return replaced


def is_write_guarded(owner: object, attribute: str) -> bool:
    return bool(getattr(getattr(owner, attribute, None), "__write_guarded__", None))


__all__ = [
    "OS_FUNCTIONS",
    "OS_TWO_ARG",
    "PATH_METHODS",
    "SHUTIL_SOURCE_AND_DEST",
    "allowed_roots",
    "confine_writes",
    "is_allowed",
    "is_write_guarded",
]
