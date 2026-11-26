"""Open the app or the orb as its own process, and keep one of each.

The desktop app (``grandpa app``) and the orb (``grandpa avatar``) are separate
programs: each can open the other, and closing one never closes the other.
That holds because the other one is started *detached* -- its own process
group, no console, no handles shared with the one that started it -- so it
does not end with its parent, a console window, or Ctrl+C.

Each running copy writes its process id to ``<grandpa home>/run/<name>.pid``; a
second launch of the same one is refused while that process is alive, so a
double click never stacks up two orbs.

Only these two fixed commands can be launched; nothing from the page or the
chat reaches the command line.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

#: What may be launched, and the command line each one runs.
PROGRAMS: dict[str, tuple[str, ...]] = {
    "app": ("-m", "grandpa", "app"),
    "avatar": ("-m", "grandpa", "orb"),  # the orb ring (pid file keeps its old name)
}


def run_dir() -> Path:
    from grandpa.runtime_paths import grandpa_home

    return grandpa_home() / "run"


def _pid_file(name: str) -> Path:
    if name not in PROGRAMS:
        raise ValueError(f"unknown program: {name!r}")
    return run_dir() / f"{name}.pid"


def running_pid(name: str) -> int | None:
    """The process id of the running ``name``, or None when it isn't running."""
    try:
        pid = int(_pid_file(name).read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return None
    if pid == os.getpid():
        return pid
    try:
        import psutil

        process = psutil.Process(pid)
        if not process.is_running() or process.status() == psutil.STATUS_ZOMBIE:
            return None
        # A recycled id belongs to some other program: only a Python running
        # this very command counts.
        if "grandpa" not in " ".join(process.cmdline()).lower():
            return None
    except Exception:  # noqa: BLE001 - gone, or not ours to inspect
        return None
    return pid


def claim(name: str) -> bool:
    """Record this process as the running ``name``. False if another one is."""
    other = running_pid(name)
    if other is not None and other != os.getpid():
        return False
    path = _pid_file(name)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(os.getpid()), encoding="ascii")
    except OSError:
        pass  # can't record it: still run, just without the duplicate check
    return True


def release(name: str) -> None:
    """Forget this process as the running ``name`` (on exit)."""
    path = _pid_file(name)
    try:
        if path.read_text(encoding="ascii").strip() == str(os.getpid()):
            path.unlink()
    except OSError:
        pass


def detached_flags() -> int:
    """Windows creation flags for a process that outlives its parent."""
    if sys.platform != "win32":
        return 0
    return (
        getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
        | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
        | getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0x01000000)
    )


def launch(name: str, *, popen=subprocess.Popen) -> str:
    """Start ``name`` on its own. Returns ``"started"`` or ``"running"``.

    Raises ValueError for anything but the two known programs, and OSError
    when the process could not be started.
    """
    if name not in PROGRAMS:
        raise ValueError(f"unknown program: {name!r}")
    if running_pid(name) is not None:
        return "running"
    kwargs: dict = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
        "cwd": os.getcwd(),  # same folder as this one: same config, same files
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = detached_flags()
    else:
        kwargs["start_new_session"] = True
    try:
        popen([sys.executable, *PROGRAMS[name]], **kwargs)
    except OSError:
        if sys.platform != "win32":
            raise
        # Some job objects refuse to let a child break away; detached is enough.
        kwargs["creationflags"] &= ~0x01000000
        popen([sys.executable, *PROGRAMS[name]], **kwargs)
    return "started"


__all__ = [
    "PROGRAMS",
    "claim",
    "detached_flags",
    "launch",
    "release",
    "run_dir",
    "running_pid",
]
