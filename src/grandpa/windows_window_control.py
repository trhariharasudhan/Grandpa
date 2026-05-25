"""Safe Windows foreground window management for Grandpa."""

from __future__ import annotations

import ctypes
import sys
from dataclasses import dataclass
from typing import Literal


WindowAction = Literal["focus", "close", "minimize", "maximize", "restore", "list"]
WindowStatus = Literal[
    "handled",
    "blocked",
    "unsupported",
    "not_found",
    "multiple_matches",
    "error",
]

_APP_TITLE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "notepad": ("notepad",),
    "chrome": ("chrome",),
    "edge": ("edge", "microsoft edge"),
    "vscode": ("visual studio code", "vs code", "code"),
    "explorer": ("file explorer", "explorer"),
    "calculator": ("calculator",),
    "settings": ("settings",),
    "control_panel": ("control panel",),
    "task_manager": ("task manager",),
}

_SYSTEM_CRITICAL_KEYWORDS = (
    "task manager",
    "windows security",
    "registry editor",
    "administrator:",
    "command prompt",
    "powershell",
    "terminal",
)


@dataclass(frozen=True)
class WindowInfo:
    handle: int
    title: str
    app_id: str = ""


@dataclass(frozen=True)
class WindowControlResult:
    status: WindowStatus
    action: WindowAction
    target: str
    message: str
    windows: tuple[WindowInfo, ...] = ()


def list_open_windows() -> WindowControlResult:
    if sys.platform != "win32":
        return WindowControlResult(
            "unsupported",
            "list",
            "windows",
            "Window control is only supported on Windows desktop.",
        )
    windows = tuple(_list_windows())
    if not windows:
        return WindowControlResult(
            "not_found",
            "list",
            "windows",
            "I could not find any visible application windows.",
        )
    lines = ["Open windows:"]
    for window in windows[:20]:
        lines.append(f"- {window.title}")
    if len(windows) > 20:
        lines.append(f"- ...and {len(windows) - 20} more")
    return WindowControlResult("handled", "list", "windows", "\n".join(lines), windows)


def control_window(action: WindowAction, target: str = "active") -> WindowControlResult:
    if sys.platform != "win32":
        return WindowControlResult(
            "unsupported",
            action,
            target,
            "Window control is only supported on Windows desktop.",
        )

    if action == "list":
        return list_open_windows()

    try:
        window = _resolve_window(target)
        if isinstance(window, WindowControlResult):
            return window

        if action == "close" and _is_system_critical(window):
            return WindowControlResult(
                "blocked",
                action,
                target,
                "I blocked this window action for safety.",
                (window,),
            )

        _apply_action(action, window.handle)
        label = "the active window" if target == "active" else _display_target(target)
        verb = {
            "focus": "Focused",
            "close": "Asked to close",
            "minimize": "Minimized",
            "maximize": "Maximized",
            "restore": "Restored",
        }[action]
        return WindowControlResult(
            "handled",
            action,
            target,
            f"{verb} {label}.",
            (window,),
        )
    except Exception as exc:
        return WindowControlResult(
            "error",
            action,
            target,
            f"I could not control that window: {exc}",
        )


def _resolve_window(target: str) -> WindowInfo | WindowControlResult:
    if target == "active":
        handle = _get_foreground_window()
        title = _get_window_title(handle)
        if handle and title:
            return WindowInfo(handle=handle, title=title)
        return WindowControlResult(
            "not_found",
            "focus",
            target,
            "I could not find the active window.",
        )

    matches = _matching_windows(target)
    if not matches:
        return WindowControlResult(
            "not_found",
            "focus",
            target,
            f"I could not find an open {_display_target(target)} window.",
        )
    if len(matches) > 1:
        titles = "\n".join(f"- {window.title}" for window in matches[:5])
        return WindowControlResult(
            "multiple_matches",
            "focus",
            target,
            f"I found multiple {_display_target(target)} windows. Please clarify:\n{titles}",
            tuple(matches),
        )
    return matches[0]


def _matching_windows(target: str) -> list[WindowInfo]:
    target = target.lower().strip()
    keywords = _APP_TITLE_KEYWORDS.get(target, (target,))
    matches = []
    for window in _list_windows():
        title = window.title.lower()
        if any(keyword in title for keyword in keywords):
            matches.append(WindowInfo(window.handle, window.title, target))
    return matches


def _list_windows() -> list[WindowInfo]:
    try:
        return _list_windows_pywin32()
    except Exception:
        return _list_windows_ctypes()


def _list_windows_pywin32() -> list[WindowInfo]:
    import win32gui  # type: ignore

    windows: list[WindowInfo] = []

    def callback(hwnd: int, _extra: object) -> bool:
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd).strip()
            if title:
                windows.append(WindowInfo(hwnd, title))
        return True

    win32gui.EnumWindows(callback, None)
    return windows


def _list_windows_ctypes() -> list[WindowInfo]:
    user32 = ctypes.windll.user32
    windows: list[WindowInfo] = []

    enum_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def callback(hwnd: int, _lparam: int) -> bool:
        if user32.IsWindowVisible(hwnd):
            title = _get_window_title(hwnd)
            if title:
                windows.append(WindowInfo(int(hwnd), title))
        return True

    user32.EnumWindows(enum_proc(callback), 0)
    return windows


def _get_foreground_window() -> int:
    try:
        import win32gui  # type: ignore

        return int(win32gui.GetForegroundWindow())
    except Exception:
        return int(ctypes.windll.user32.GetForegroundWindow())


def _get_window_title(hwnd: int) -> str:
    if not hwnd:
        return ""
    try:
        import win32gui  # type: ignore

        return win32gui.GetWindowText(hwnd).strip()
    except Exception:
        user32 = ctypes.windll.user32
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return ""
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        return buffer.value.strip()


def _apply_action(action: WindowAction, hwnd: int) -> None:
    try:
        import win32con  # type: ignore
        import win32gui  # type: ignore

        if action == "focus":
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(hwnd)
        elif action == "minimize":
            win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)
        elif action == "maximize":
            win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)
        elif action == "restore":
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        elif action == "close":
            win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
        return
    except Exception:
        pass

    user32 = ctypes.windll.user32
    if action == "focus":
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        user32.SetForegroundWindow(hwnd)
    elif action == "minimize":
        user32.ShowWindow(hwnd, 6)  # SW_MINIMIZE
    elif action == "maximize":
        user32.ShowWindow(hwnd, 3)  # SW_MAXIMIZE
    elif action == "restore":
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    elif action == "close":
        user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE


def _is_system_critical(window: WindowInfo) -> bool:
    title = window.title.lower()
    return any(keyword in title for keyword in _SYSTEM_CRITICAL_KEYWORDS)


def _display_target(target: str) -> str:
    if target == "vscode":
        return "VS Code"
    return target.replace("_", " ").title()


__all__ = [
    "WindowControlResult",
    "WindowInfo",
    "control_window",
    "list_open_windows",
]
