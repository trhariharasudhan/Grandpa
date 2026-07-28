"""User-facing running application and window helpers."""

from __future__ import annotations

import csv
import logging
import subprocess
import sys
from collections.abc import Callable, Iterable

from grandpa.apps.models import AppProcessInfo
from grandpa.apps.resolver import canonicalize_app_identity, normalize_app_name
from grandpa.apps.safety import NOISY_EXECUTABLE_TOKENS, is_critical_process

logger = logging.getLogger(__name__)

_PROCESS_DISPLAY_NAMES = {
    "chrome": "Google Chrome",
    "msedge": "Microsoft Edge",
    "firefox": "Mozilla Firefox",
    "code": "Visual Studio Code",
    "spotify": "Spotify",
    "chatgpt": "ChatGPT",
    "windowsterminal": "Windows Terminal",
    "systemsettings": "Windows Settings",
    "xboxpcapp": "Xbox",
    "notepad": "Notepad",
    "explorer": "File Explorer",
}


def list_running_apps(*, limit: int = 50, include_all_processes: bool = False) -> list[AppProcessInfo]:
    """Return grouped visible applications, or raw processes for diagnostics."""

    raw = _psutil_processes(limit=max(limit * 20, 500))
    if raw is None:
        raw = _tasklist_processes(limit=max(limit * 20, 500))
    if include_all_processes:
        return raw[:limit]
    visible_pids = _visible_window_pids() if sys.platform == "win32" else set()
    filtered = [proc for proc in raw if _is_user_process(proc, visible_pids)]
    return _group_processes(filtered)[:limit]


def _psutil_processes(*, limit: int) -> list[AppProcessInfo] | None:
    try:
        import psutil
    except ImportError:
        return None
    apps: list[AppProcessInfo] = []
    for proc in psutil.process_iter(["pid", "name", "exe"]):
        if len(apps) >= limit:
            break
        try:
            info = proc.info
            name = str(info.get("name") or "")
            apps.append(
                AppProcessInfo(
                    pid=int(info.get("pid") or 0),
                    name=name,
                    display_name=_process_display_name(name),
                    executable=str(info.get("exe") or ""),
                )
            )
        except (psutil.Error, OSError, ValueError):
            continue
    return apps


def _tasklist_processes(*, limit: int) -> list[AppProcessInfo]:
    try:
        result = subprocess.run(
            ["tasklist", "/fo", "csv", "/nh"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []
    apps: list[AppProcessInfo] = []
    for row in csv.reader(result.stdout.splitlines()):
        if len(apps) >= limit:
            break
        if len(row) < 2:
            continue
        name = row[0].strip()
        try:
            pid = int(row[1])
        except ValueError:
            pid = 0
        apps.append(AppProcessInfo(pid=pid, name=name, display_name=_process_display_name(name)))
    return apps


def _is_user_process(process: AppProcessInfo, visible_pids: set[int]) -> bool:
    if process.pid <= 0 or not process.name or is_critical_process(process.name):
        return False
    normalized = normalize_app_name(process.name)
    if any(token in normalized for token in NOISY_EXECUTABLE_TOKENS):
        return False
    process_stem = process.name.casefold().removesuffix(".exe")
    if visible_pids and process.pid not in visible_pids and process_stem not in _PROCESS_DISPLAY_NAMES:
        return False
    return bool(process.display_name)


def _group_processes(processes: Iterable[AppProcessInfo]) -> list[AppProcessInfo]:
    grouped: dict[str, AppProcessInfo] = {}
    for process in processes:
        key = canonicalize_app_identity(process.display_name or process.name, process.name)
        if not key:
            continue
        existing = grouped.get(key)
        if existing is None:
            grouped[key] = process
        else:
            grouped[key] = AppProcessInfo(
                pid=existing.pid,
                name=existing.name,
                display_name=existing.display_name,
                executable=existing.executable or process.executable,
                process_count=existing.process_count + process.process_count,
            )
    return sorted(grouped.values(), key=lambda item: item.display_name.casefold())


def _process_display_name(name: str) -> str:
    stem = name.casefold().removesuffix(".exe")
    if stem in _PROCESS_DISPLAY_NAMES:
        return _PROCESS_DISPLAY_NAMES[stem]
    if not stem or is_critical_process(name):
        return ""
    if any(token in stem for token in NOISY_EXECUTABLE_TOKENS):
        return ""
    return name.removesuffix(".exe")


def _visible_window_pids() -> set[int]:
    """Return PIDs owning visible top-level windows; failure means process fallback."""

    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        pids: set[int] = set()
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        @callback_type
        def collect(hwnd, _lparam):
            if user32.IsWindowVisible(hwnd) and user32.GetWindowTextLengthW(hwnd) > 0:
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value:
                    pids.add(int(pid.value))
            return True

        user32.EnumWindows(collect, 0)
        return pids
    except Exception:
        return set()


def find_running_app(name: str, *, processes: list[AppProcessInfo] | None = None) -> AppProcessInfo | None:
    query = normalize_app_name(name)
    for proc in processes if processes is not None else list_running_apps():
        candidates = {normalize_app_name(proc.name), normalize_app_name(proc.display_name)}
        if query in candidates or any(query in candidate for candidate in candidates):
            return proc
    return None


def close_running_app(name: str, *, terminator: Callable[[AppProcessInfo], None] | None = None) -> str:
    process = find_running_app(name)
    if process is None:
        return f"I could not find a running app named {name}."
    if is_critical_process(process.name):
        return "I will not close a critical Windows process."
    if terminator is None:
        try:
            import psutil
        except ImportError:
            return "Process management requires psutil."
        psutil.Process(process.pid).terminate()
    else:
        terminator(process)
    logger.info("Application close requested: %s (%s)", process.name, process.pid)
    return f"Closing {process.display_name or process.name}."


__all__ = ["close_running_app", "find_running_app", "list_running_apps"]
