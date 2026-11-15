"""Ending a running process by name or PID -- the ``process_kill`` action.

Closing a window (``close_app``) asks an application to quit and lets it ask
about unsaved work. This ends the process outright, which is why it is HIGH
risk and confirmed by the action layer before this module is ever called.

The confirmation is the user's consent, not a safety check, so this module
refuses on its own, whatever was approved:

* **system-critical processes** -- the names in
  :data:`grandpa.apps.safety.CRITICAL_PROCESS_NAMES` plus
  :data:`KILL_REFUSED_NAMES`, matched with or without ``.exe``; and PIDs 0-4,
  which are the kernel's on Windows;
* **Grandpa itself** -- this process and every ancestor of it (the terminal,
  the daemon), so "kill python" cannot end the conversation asking for it;
* **ambiguity** -- a name matches executables exactly (``chrome`` is
  ``chrome.exe``), never by substring, so "kill code" cannot reach
  ``vscode-helper.exe``.

Every PID of an exactly-matching executable is ended: "kill chrome" means all
of Chrome. Each gets a polite terminate first and a forced kill only if it is
still alive after :data:`GRACE_SECONDS`.

The psutil calls sit behind :func:`kill_process`; :func:`plan_kill` and
:func:`execute_plan` take the process table and the terminator as arguments,
which is how the tests drive them without touching a real process.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from grandpa.action_layer.model import ActionResult
from grandpa.apps.safety import is_critical_process

logger = logging.getLogger(__name__)

GRACE_SECONDS = 3.0

KILL_REFUSED_NAMES = frozenset(
    {
        # Beyond the launcher's critical list: ending these breaks security,
        # sign-in or the shell session rather than one application.
        "lsaiso.exe",
        "msmpeng.exe",
        "nissrv.exe",
        "securityhealthservice.exe",
        "sihost.exe",
        "spoolsv.exe",
        "taskhostw.exe",
        "audiodg.exe",
        "ctfmon.exe",
        "memory compression",
        "secure system",
    }
)

_KERNEL_PIDS = frozenset({0, 4})


@dataclass(frozen=True, slots=True)
class RunningProcess:
    pid: int
    name: str


@dataclass(frozen=True, slots=True)
class KillPlan:
    targets: tuple[RunningProcess, ...] = ()
    refusal: str = ""


def _norm(name: str) -> str:
    return name.strip().casefold()


def _with_exe(name: str) -> set[str]:
    value = _norm(name)
    if not value:
        return set()
    return {value, value[:-4]} if value.endswith(".exe") else {value, f"{value}.exe"}


def is_kill_refused(name: str) -> bool:
    """Is this process name one Grandpa will never end?"""
    return any(
        is_critical_process(candidate) or candidate in KILL_REFUSED_NAMES
        for candidate in _with_exe(name)
    )


def plan_kill(
    *,
    name: str = "",
    pid: int | None = None,
    processes: Iterable[RunningProcess],
    protected_pids: Iterable[int] = (),
) -> KillPlan:
    """Decide what would be ended, or why nothing will be. Changes nothing."""
    name = str(name or "").strip()
    if bool(name) == (pid is not None):
        return KillPlan(refusal="Tell me either a process name or a PID, not both.")

    table = list(processes)
    protected = set(protected_pids)

    if pid is not None:
        pid = int(pid)
        if pid in _KERNEL_PIDS:
            return KillPlan(refusal="I will not end a Windows system process.")
        matches = [proc for proc in table if proc.pid == pid]
        if not matches:
            return KillPlan(refusal=f"No running process has PID {pid}.")
    else:
        wanted = _with_exe(name)
        matches = [proc for proc in table if _norm(proc.name) in wanted]
        if not matches:
            return KillPlan(refusal=f"I could not find a running process named {name}.")

    for proc in matches:
        if proc.pid in _KERNEL_PIDS or is_kill_refused(proc.name):
            return KillPlan(
                refusal=f"I will not end {proc.name}: it is a Windows system process."
            )
        if proc.pid in protected:
            return KillPlan(
                refusal=f"I will not end {proc.name} (PID {proc.pid}): "
                "Grandpa is running inside it."
            )
    return KillPlan(targets=tuple(sorted(matches, key=lambda proc: proc.pid)))


def execute_plan(
    plan: KillPlan,
    terminate: Callable[[Sequence[RunningProcess]], Sequence[RunningProcess]],
) -> ActionResult:
    """End the plan's targets. ``terminate`` returns the ones it could not end."""
    if plan.refusal:
        return ActionResult.failed(plan.refusal, plan.refusal)
    survivors = list(terminate(plan.targets))
    ended = [proc for proc in plan.targets if proc not in survivors]
    label = plan.targets[0].name
    pids = [proc.pid for proc in ended]
    logger.info("process_kill ended %s pids=%s survivors=%s", label, pids, survivors)
    if survivors:
        message = (
            f"I ended {len(ended)} of {len(plan.targets)} {label} processes; "
            f"{len(survivors)} refused (access denied or still running)."
        )
        return ActionResult.failed(
            message, message, ended=pids, survivors=[p.pid for p in survivors]
        )
    noun = "process" if len(ended) == 1 else f"{len(ended)} processes"
    return ActionResult.ok(f"Ended {label} ({noun}).", ended=pids)


# --- the real process table, through psutil ---------------------------------


def _snapshot() -> list[RunningProcess]:
    import psutil

    table: list[RunningProcess] = []
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            table.append(RunningProcess(int(proc.info["pid"]), str(proc.info["name"])))
        except (psutil.Error, KeyError, TypeError, ValueError):
            continue
    return table


def _grandpa_pids() -> set[int]:
    import psutil

    pids = {os.getpid()}
    try:
        pids.update(parent.pid for parent in psutil.Process().parents())
    except psutil.Error:
        pids.add(os.getppid())
    return pids


def _psutil_terminate(targets: Sequence[RunningProcess]) -> list[RunningProcess]:
    import psutil

    handles: dict[int, psutil.Process] = {}
    survivors: list[RunningProcess] = []
    for target in targets:
        try:
            handle = psutil.Process(target.pid)
            # A PID can be reused between the snapshot and now.
            if _norm(handle.name()) != _norm(target.name):
                continue
            handle.terminate()
            handles[target.pid] = handle
        except psutil.NoSuchProcess:
            continue
        except psutil.Error:
            survivors.append(target)
    _gone, alive = psutil.wait_procs(list(handles.values()), timeout=GRACE_SECONDS)
    for handle in alive:
        try:
            handle.kill()
        except psutil.NoSuchProcess:
            continue
        except psutil.Error:
            survivors.extend(t for t in targets if t.pid == handle.pid)
    return survivors


def kill_process(name: str = "", pid: int | None = None) -> ActionResult:
    """End a running process. The action layer has already confirmed."""
    try:
        import psutil  # noqa: F401
    except ImportError:
        return ActionResult.failed("Ending a process requires psutil.")
    plan = plan_kill(
        name=name, pid=pid, processes=_snapshot(), protected_pids=_grandpa_pids()
    )
    return execute_plan(plan, _psutil_terminate)


__all__ = [
    "GRACE_SECONDS",
    "KILL_REFUSED_NAMES",
    "KillPlan",
    "RunningProcess",
    "execute_plan",
    "is_kill_refused",
    "kill_process",
    "plan_kill",
]
