"""A7: the avatar's performance gate -- at most 20% iGPU and 300 MB of RAM.

The avatar shares a Ryzen 5 7520U's integrated GPU and 16 GB with Ollama. If
the window costs more than its budget while Ollama is generating, Grandpa
should get out of the way: the 3D character goes and only the ring stays
(``AvatarController.ring_only``), for the rest of the run.

What is measured is the **window**, not Grandpa's brain:

* **RAM**: the WebView2 processes the window started (``msedgewebview2.exe``,
  children of this process), by their private memory (USS) where the OS gives
  it, otherwise their working set (RSS, which over-counts shared pages). The
  Python process is not counted: it also holds the speech and chat models,
  which are not the avatar's cost.
* **GPU**: the "GPU Engine" 3D utilisation of those same processes, from the
  Windows performance counters. Sampled every :data:`SAMPLE_SECONDS` by one
  short PowerShell call; off Windows it is not measured.

One sample over budget is not enough: :data:`STRIKES` in a row are, so a
single slow frame while a model loads does not cost Captain his grandpa.
A sample that could not be read counts neither way.
"""

from __future__ import annotations

import logging
import subprocess
import sys
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

GPU_BUDGET_PCT = 20.0
RAM_BUDGET_MB = 300.0
SAMPLE_SECONDS = 10.0
STRIKES = 3
WEBVIEW_NAMES = ("msedgewebview2",)
"""Process names (lower case, no extension) that are the window's."""

_GPU_COUNTER = r"\GPU Engine(*engtype_3D)\Utilization Percentage"
_GPU_SCRIPT = (
    f"(Get-Counter '{_GPU_COUNTER}' -ErrorAction SilentlyContinue).CounterSamples"
    " | ForEach-Object { $_.InstanceName + '=' + $_.CookedValue }"
)
_MIB = 1024 * 1024


@dataclass(frozen=True)
class Budget:
    gpu_pct: float = GPU_BUDGET_PCT
    ram_mb: float = RAM_BUDGET_MB


@dataclass(frozen=True)
class Sample:
    """One reading. ``None`` means "could not be measured", not zero."""

    ram_mb: float | None = None
    gpu_pct: float | None = None

    def over(self, budget: Budget) -> list[str]:
        reasons = []
        if self.gpu_pct is not None and self.gpu_pct > budget.gpu_pct:
            reasons.append(f"GPU {self.gpu_pct:.0f}% > {budget.gpu_pct:.0f}%")
        if self.ram_mb is not None and self.ram_mb > budget.ram_mb:
            reasons.append(f"RAM {self.ram_mb:.0f} MB > {budget.ram_mb:.0f} MB")
        return reasons

    @property
    def measured(self) -> bool:
        return self.ram_mb is not None or self.gpu_pct is not None

    def describe(self) -> str:
        ram = "n/a" if self.ram_mb is None else f"{self.ram_mb:.0f} MB"
        gpu = "n/a" if self.gpu_pct is None else f"{self.gpu_pct:.1f}%"
        return f"avatar window: RAM {ram}, GPU {gpu}"


# --- reading the window -----------------------------------------------------------


def window_processes(*, psutil_module: Any = None, pid: int | None = None) -> list:
    """The WebView2 processes this process started (any depth)."""
    if psutil_module is None:
        import psutil as psutil_module
    try:
        me = psutil_module.Process(pid) if pid is not None else psutil_module.Process()
        children = me.children(recursive=True)
    except Exception:  # noqa: BLE001 - gone or denied: nothing to measure
        return []
    found = []
    for child in children:
        try:
            name = (child.name() or "").lower()
        except Exception:  # noqa: BLE001
            continue
        if name.removesuffix(".exe") in WEBVIEW_NAMES:
            found.append(child)
    return found


def ram_mb(processes: Iterable[Any]) -> float | None:
    """Private memory of ``processes`` in MiB; ``None`` if none could be read."""
    total = 0
    read = False
    for proc in processes:
        try:
            try:
                total += proc.memory_full_info().uss
            except Exception:  # noqa: BLE001 - USS needs more rights; RSS does not
                total += proc.memory_info().rss
            read = True
        except Exception:  # noqa: BLE001 - exited or denied
            continue
    return total / _MIB if read else None


def parse_gpu_counters(text: str, pids: Iterable[int]) -> float | None:
    """Sum the 3D utilisation of ``pids`` from ``InstanceName=value`` lines."""
    wanted = {f"pid_{pid}_" for pid in pids}
    if not wanted:
        return None
    total = 0.0
    seen = False
    for line in text.splitlines():
        name, sep, value = line.strip().rpartition("=")
        if not sep:
            continue
        if not any(name.lower().startswith(prefix) for prefix in wanted):
            continue
        try:
            total += float(value.replace(",", "."))
        except ValueError:
            continue
        seen = True
    return total if seen else 0.0 if text.strip() else None


def gpu_pct(
    pids: Iterable[int],
    *,
    run: Callable[..., Any] = subprocess.run,
    platform: str = sys.platform,
    timeout: float = 8.0,
) -> float | None:
    """3D GPU use of ``pids`` in percent, Windows only; ``None`` if unknown."""
    pids = list(pids)
    if platform != "win32" or not pids:
        return None
    kwargs: dict[str, Any] = {}
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if flags:
        kwargs["creationflags"] = flags
    try:
        done = run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", _GPU_SCRIPT],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            **kwargs,
        )
    except Exception:  # noqa: BLE001 - no PowerShell, timeout: unknown
        return None
    if getattr(done, "returncode", 1) != 0:
        return None
    return parse_gpu_counters(getattr(done, "stdout", "") or "", pids)


def sample_window(*, psutil_module: Any = None, run: Any = None) -> Sample:
    """One reading of the window's RAM and GPU."""
    procs = window_processes(psutil_module=psutil_module)
    pids = []
    for proc in procs:
        try:
            pids.append(int(proc.pid))
        except Exception:  # noqa: BLE001
            continue
    gpu = gpu_pct(pids, run=run) if run is not None else gpu_pct(pids)
    return Sample(ram_mb=ram_mb(procs), gpu_pct=gpu)


# --- the watch --------------------------------------------------------------------


class BudgetWatch:
    """Samples every ``interval`` s; after ``strikes`` over-budget samples in a
    row calls ``on_over(reasons)`` once, then stops."""

    def __init__(
        self,
        sample: Callable[[], Sample],
        on_over: Callable[[list[str]], Any],
        *,
        on_sample: Callable[[Sample], Any] | None = None,
        budget: Budget = Budget(),
        strikes: int = STRIKES,
        interval: float = SAMPLE_SECONDS,
    ) -> None:
        self._sample = sample
        self._on_over = on_over
        self._on_sample = on_sample
        self.budget = budget
        self.strikes = max(1, strikes)
        self.interval = interval
        self.count = 0
        self.fired = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def check(self, sample: Sample) -> bool:
        """Count one sample. True when this one tipped it over (fires once)."""
        if self.fired:
            return False
        if self._on_sample is not None:
            try:
                self._on_sample(sample)
            except Exception:  # noqa: BLE001 - a log line must not stop the watch
                pass
        if not sample.measured:
            return False
        reasons = sample.over(self.budget)
        if not reasons:
            self.count = 0
            return False
        self.count += 1
        if self.count < self.strikes:
            return False
        self.fired = True
        try:
            self._on_over(reasons)
        except Exception:  # noqa: BLE001
            logger.exception("avatar fallback failed")
        return True

    def step(self) -> bool:
        try:
            sample = self._sample()
        except Exception:  # noqa: BLE001 - an unreadable sample counts neither way
            logger.debug("avatar budget sample failed", exc_info=True)
            sample = Sample()
        return self.check(sample)

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            self.step()
            if self.fired:
                return

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run, name="grandpa-avatar-budget", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()


__all__ = [
    "GPU_BUDGET_PCT",
    "RAM_BUDGET_MB",
    "SAMPLE_SECONDS",
    "STRIKES",
    "Budget",
    "BudgetWatch",
    "Sample",
    "gpu_pct",
    "parse_gpu_counters",
    "ram_mb",
    "sample_window",
    "window_processes",
]
