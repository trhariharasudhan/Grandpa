"""Read-only desktop awareness helpers for Grandpa PC control.

This module keeps OS probing local and conservative. It never captures screen
pixels, reads hidden windows, or stores clipboard contents; clipboard history is
metadata-only so audit/debug views do not leak user data.
"""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from grandpa.core.config import DEFAULT_CONFIG_DIR

DEFAULT_CLIPBOARD_HISTORY_DB = DEFAULT_CONFIG_DIR / "pc_control_clipboard_history.db"
PROTECTED_WINDOW_KEYWORDS = (
    "windows security",
    "credential",
    "password",
    "sign in",
    "login",
    "bank",
    "payment",
    "checkout",
    "administrator:",
    "registry editor",
)


@dataclass(frozen=True)
class MonitorInfo:
    id: str
    left: int
    top: int
    width: int
    height: int
    primary: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProcessInfo:
    pid: int | None
    name: str
    title: str = ""
    executable: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DesktopContextResult:
    supported: bool
    message: str
    evidence: dict[str, Any]


def get_clipboard_history_db_path() -> Path:
    configured = os.environ.get("GRANDPA_CLIPBOARD_HISTORY_DB")
    if configured:
        return Path(configured)
    return DEFAULT_CLIPBOARD_HISTORY_DB


def list_monitors() -> DesktopContextResult:
    if sys.platform == "win32":
        monitors = _list_monitors_win32()
        if monitors:
            return DesktopContextResult(
                True,
                f"Detected {len(monitors)} monitor(s).",
                {
                    "monitors": [monitor.to_dict() for monitor in monitors],
                    "count": len(monitors),
                },
            )

    fallback = _list_primary_monitor_pyautogui()
    if fallback:
        return DesktopContextResult(
            True,
            "Detected the primary monitor.",
            {"monitors": [fallback.to_dict()], "count": 1, "fallback": "pyautogui"},
        )
    return DesktopContextResult(
        False,
        "Monitor detection is not supported in this environment.",
        {"monitors": [], "count": 0},
    )


def get_active_process() -> DesktopContextResult:
    if sys.platform != "win32":
        return DesktopContextResult(
            False, "Active process detection is only supported on Windows desktop.", {}
        )
    try:
        import ctypes

        user32 = ctypes.windll.user32
        hwnd = int(user32.GetForegroundWindow())
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        title = _window_title(hwnd)
        info = _process_info_from_pid(int(pid.value), title)
        return DesktopContextResult(
            True,
            f"Active process: {info.name or 'unknown'}.",
            {"process": info.to_dict()},
        )
    except Exception as exc:
        return DesktopContextResult(
            False,
            "I could not read the active process.",
            {"error": exc.__class__.__name__},
        )


def list_processes(limit: int = 50) -> DesktopContextResult:
    try:
        import psutil  # type: ignore
    except Exception:
        return DesktopContextResult(
            False, "Process listing needs psutil installed.", {"processes": []}
        )
    processes: list[dict[str, Any]] = []
    for proc in psutil.process_iter(["pid", "name", "exe"]):
        try:
            info = proc.info
            name = str(info.get("name") or "")
            if not name:
                continue
            processes.append(
                {
                    "pid": int(info.get("pid") or 0),
                    "name": name,
                    "executable": _safe_executable(str(info.get("exe") or "")),
                }
            )
        except Exception:
            continue
        if len(processes) >= max(1, min(limit, 200)):
            break
    return DesktopContextResult(
        True,
        f"Found {len(processes)} running process(es).",
        {"processes": processes, "count": len(processes)},
    )


def inspect_clipboard_text(text: str) -> dict[str, Any]:
    text = text or ""
    lowered = text.lower()
    content_type = "empty"
    if text.strip():
        if re.match(r"^https?://", text.strip(), re.I):
            content_type = "url"
        elif re.match(r"^[a-z]:[\\/]", text.strip(), re.I) or text.strip().startswith(
            ("~/", "~\\")
        ):
            content_type = "path"
        elif re.search(r"[\w.+-]+@[\w.-]+\.[a-z]{2,}", text, re.I):
            content_type = "email"
        elif any(
            token in lowered
            for token in ("def ", "class ", "function ", "import ", "const ", "=>")
        ):
            content_type = "code"
        else:
            content_type = "plain_text"
    sensitive = bool(
        re.search(
            r"(password|secret|token|api[_ -]?key|bearer\s+[a-z0-9._-]+|sk-[a-z0-9])",
            lowered,
            re.I,
        )
    )
    digest = (
        hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:16]
        if text
        else ""
    )
    return {
        "content_type": content_type,
        "characters": len(text),
        "lines": len(text.splitlines()) if text else 0,
        "words": len(re.findall(r"\S+", text)),
        "sha256_16": digest,
        "sensitive": sensitive,
    }


def record_clipboard_metadata(text: str, *, source: str) -> dict[str, Any]:
    metadata = inspect_clipboard_text(text)
    path = get_clipboard_history_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path, timeout=10) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS clipboard_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                source TEXT NOT NULL,
                content_type TEXT NOT NULL,
                characters INTEGER NOT NULL,
                lines INTEGER NOT NULL,
                words INTEGER NOT NULL,
                sha256_16 TEXT NOT NULL,
                sensitive INTEGER NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO clipboard_history (
                timestamp, source, content_type, characters, lines, words, sha256_16, sensitive
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                time.time(),
                source,
                metadata["content_type"],
                metadata["characters"],
                metadata["lines"],
                metadata["words"],
                metadata["sha256_16"],
                int(metadata["sensitive"]),
            ),
        )
    return metadata


def read_clipboard_history(limit: int = 20) -> DesktopContextResult:
    path = get_clipboard_history_db_path()
    if not path.exists():
        return DesktopContextResult(
            True,
            "Clipboard history is empty.",
            {"items": [], "count": 0, "metadata_only": True},
        )
    safe_limit = max(1, min(int(limit or 20), 100))
    try:
        with sqlite3.connect(path, timeout=10) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT timestamp, source, content_type, characters, lines, words, sha256_16, sensitive
                FROM clipboard_history
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
    except sqlite3.Error as exc:
        return DesktopContextResult(
            False,
            "Clipboard history database is unavailable.",
            {"error": exc.__class__.__name__},
        )
    items = [
        {
            "timestamp": float(row["timestamp"]),
            "source": str(row["source"]),
            "content_type": str(row["content_type"]),
            "characters": int(row["characters"]),
            "lines": int(row["lines"]),
            "words": int(row["words"]),
            "sha256_16": str(row["sha256_16"]),
            "sensitive": bool(row["sensitive"]),
        }
        for row in rows
    ]
    return DesktopContextResult(
        True,
        f"Loaded {len(items)} clipboard metadata item(s).",
        {"items": items, "count": len(items), "metadata_only": True},
    )


def active_window_is_protected() -> bool:
    result = get_active_process()
    process = result.evidence.get("process", {}) if result.supported else {}
    title = str(process.get("title", "")).lower()
    name = str(process.get("name", "")).lower()
    haystack = f"{title} {name}"
    return any(keyword in haystack for keyword in PROTECTED_WINDOW_KEYWORDS)


def desktop_session_summary() -> DesktopContextResult:
    monitors = list_monitors()
    active = get_active_process()
    processes = list_processes(limit=20)
    evidence = {
        "monitors": monitors.evidence,
        "active_process": active.evidence.get("process"),
        "process_count": processes.evidence.get("count", 0),
        "supported": {
            "monitors": monitors.supported,
            "active_process": active.supported,
            "processes": processes.supported,
        },
    }
    parts = [
        monitors.message,
        active.message,
        processes.message,
    ]
    return DesktopContextResult(
        any(item.supported for item in (monitors, active, processes)),
        " ".join(parts),
        evidence,
    )


def pc_control_diagnostics() -> dict[str, Any]:
    monitors = list_monitors()
    active = get_active_process()
    processes = list_processes(limit=5)
    clipboard_db = get_clipboard_history_db_path()
    try:
        import pyautogui  # noqa: F401

        pyautogui_available = True
    except Exception:
        pyautogui_available = False
    try:
        import pyperclip  # noqa: F401

        pyperclip_available = True
    except Exception:
        pyperclip_available = False
    return {
        "monitors": {
            "supported": monitors.supported,
            "count": monitors.evidence.get("count", 0),
        },
        "active_process": {
            "supported": active.supported,
            "process": active.evidence.get("process"),
        },
        "processes": {
            "supported": processes.supported,
            "count": processes.evidence.get("count", 0),
        },
        "automation": {
            "pyautogui": pyautogui_available,
            "failsafe": True,
            "visible_screen_only": True,
        },
        "clipboard": {
            "pyperclip": pyperclip_available,
            "history_db": str(clipboard_db),
            "metadata_only": True,
            "exists": clipboard_db.exists(),
        },
        "platform": sys.platform,
    }


def _list_primary_monitor_pyautogui() -> MonitorInfo | None:
    try:
        import pyautogui  # type: ignore

        width, height = pyautogui.size()
        return MonitorInfo("primary", 0, 0, int(width), int(height), True)
    except Exception:
        return None


def _list_monitors_win32() -> list[MonitorInfo]:
    try:
        import ctypes
        from ctypes import wintypes

        monitors: list[MonitorInfo] = []
        user32 = ctypes.windll.user32

        class RECT(ctypes.Structure):
            _fields_ = [
                ("left", wintypes.LONG),
                ("top", wintypes.LONG),
                ("right", wintypes.LONG),
                ("bottom", wintypes.LONG),
            ]

        callback_type = ctypes.WINFUNCTYPE(
            ctypes.c_int,
            wintypes.HMONITOR,
            wintypes.HDC,
            ctypes.POINTER(RECT),
            wintypes.LPARAM,
        )

        primary_left = (
            user32.GetSystemMetrics(76) if hasattr(user32, "GetSystemMetrics") else 0
        )
        primary_top = (
            user32.GetSystemMetrics(77) if hasattr(user32, "GetSystemMetrics") else 0
        )

        def callback(_monitor: int, _hdc: int, rect: Any, _data: int) -> int:
            box = rect.contents
            idx = len(monitors) + 1
            left = int(box.left)
            top = int(box.top)
            monitors.append(
                MonitorInfo(
                    id=f"monitor-{idx}",
                    left=left,
                    top=top,
                    width=int(box.right - box.left),
                    height=int(box.bottom - box.top),
                    primary=left == primary_left and top == primary_top,
                )
            )
            return 1

        user32.EnumDisplayMonitors(0, 0, callback_type(callback), 0)
        if monitors and not any(m.primary for m in monitors):
            monitors[0] = MonitorInfo(**{**monitors[0].to_dict(), "primary": True})
        return monitors
    except Exception:
        return []


def _window_title(hwnd: int) -> str:
    try:
        import win32gui  # type: ignore

        return win32gui.GetWindowText(hwnd).strip()
    except Exception:
        try:
            import ctypes

            user32 = ctypes.windll.user32
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return ""
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            return buffer.value.strip()
        except Exception:
            return ""


def _process_info_from_pid(pid: int, title: str) -> ProcessInfo:
    try:
        import psutil  # type: ignore

        proc = psutil.Process(pid)
        return ProcessInfo(
            pid=pid,
            name=proc.name(),
            title=title,
            executable=_safe_executable(proc.exe()),
        )
    except Exception:
        return ProcessInfo(pid=pid, name="", title=title, executable="")


def _safe_executable(path: str) -> str:
    if not path:
        return ""
    try:
        return str(Path(path))
    except Exception:
        return ""


__all__ = [
    "DesktopContextResult",
    "MonitorInfo",
    "ProcessInfo",
    "active_window_is_protected",
    "desktop_session_summary",
    "get_active_process",
    "get_clipboard_history_db_path",
    "inspect_clipboard_text",
    "list_monitors",
    "list_processes",
    "pc_control_diagnostics",
    "read_clipboard_history",
    "record_clipboard_metadata",
]
