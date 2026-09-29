"""Confine a plain script's writes, the way the test suite confines a test's.

The write guard has only ever existed inside pytest: ``confine_writes`` takes
pytest's ``monkeypatch``, so nothing outside a test could use it. Every machine
change in the last several turns came from the same place -- an ad-hoc probe
script, run outside pytest, importing grandpa before setting ``GRANDPA_HOME``,
and writing into a real ``~/.grandpa``. Five files one turn, a ``server.log``
another.

So the guard is available to any script now, in one line::

    from tests.sandbox import arm

    arm()   # everything this process writes must land in a throwaway directory

``arm`` points ``GRANDPA_HOME``, ``HOME`` and ``USERPROFILE`` at a fresh
temporary directory *before* the guard goes up, so code that resolves a path
from any of them lands inside the sandbox rather than being refused; then it
refuses everything else, loudly, with the same ``ActuationDenied`` the suite
uses.

Is arming automatic? No, and it cannot be from inside Python: a module only runs
when something imports it, and the scripts that caused the damage did not. What
*is* automatic is the refusal to run one unguarded --
``scripts/hooks/require_sandboxed_probe.py`` blocks a python command that
imports grandpa without either arming this or setting GRANDPA_HOME itself. The
arming stays opt-in; forgetting it does not stay possible.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any


class _Patcher:
    """The two methods ``confine_writes`` needs from pytest's monkeypatch.

    Written out rather than depending on pytest, because the whole point is to
    work where pytest is not.
    """

    def __init__(self) -> None:
        self._undo: list[tuple[Any, str, Any]] = []

    def setattr(self, target: Any, name: str, value: Any) -> None:
        self._undo.append((target, name, getattr(target, name)))
        setattr(target, name, value)

    def undo(self) -> None:
        for target, name, original in reversed(self._undo):
            setattr(target, name, original)
        self._undo.clear()


_ARMED: _Patcher | None = None


def armed() -> bool:
    return _ARMED is not None


def arm(*, home: Path | str | None = None) -> Path:
    """Send this process's state into a sandbox and refuse writes outside it.

    Returns the sandbox directory. Safe to call twice; the second call is a
    no-op so a script that arms and then imports something that also arms does
    not end up double-patched.
    """
    global _ARMED
    if _ARMED is not None:
        return Path(os.environ["GRANDPA_HOME"]).parent

    root = Path(home) if home is not None else Path(tempfile.mkdtemp(prefix="probe-"))
    root.mkdir(parents=True, exist_ok=True)
    grandpa_home = root / ".grandpa"
    grandpa_home.mkdir(parents=True, exist_ok=True)

    # Before the guard, so anything resolving these lands inside rather than
    # being refused. HOME and USERPROFILE as well as GRANDPA_HOME, because
    # Path.home() ignores GRANDPA_HOME and several paths still go through it.
    os.environ["GRANDPA_HOME"] = str(grandpa_home)
    os.environ["HOME"] = str(root)
    os.environ["USERPROFILE"] = str(root)

    from tests.write_guard import confine_writes

    patcher = _Patcher()
    confine_writes(patcher)
    _ARMED = patcher
    return root


def disarm() -> None:
    """Put the filesystem back. Rarely needed; a probe usually just exits."""
    global _ARMED
    if _ARMED is not None:
        _ARMED.undo()
        _ARMED = None


__all__ = ["arm", "armed", "disarm"]
