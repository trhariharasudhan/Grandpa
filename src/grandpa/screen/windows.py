"""Read-only Windows monitor and top-level-window inspection."""

from __future__ import annotations

import ctypes
import logging
import sys

from grandpa.screen.errors import ActiveWindowUnavailableError
from grandpa.screen.models import MonitorInfo, WindowInfo

logger = logging.getLogger(__name__)

_IGNORED_TITLES = {
    "program manager",
    "windows input experience",
    "microsoft text input application",
    "default ime",
}
_IGNORED_CLASSES = {"Progman", "WorkerW", "Shell_TrayWnd", "DV2ControlHost"}
WS_EX_TOOLWINDOW = 0x00000080


def list_monitors() -> list[MonitorInfo]:
    """Return physical monitor bounds, including negative coordinates."""
    if sys.platform != "win32":
        return _fallback_primary_monitor()
    try:
        import win32api  # type: ignore

        records: list[MonitorInfo] = []
        for index, handle in enumerate(win32api.EnumDisplayMonitors(), 1):
            monitor_handle = handle[0]
            info = win32api.GetMonitorInfo(monitor_handle)
            left, top, right, bottom = info["Monitor"]
            records.append(
                MonitorInfo(
                    index=index,
                    left=int(left),
                    top=int(top),
                    width=int(right - left),
                    height=int(bottom - top),
                    is_primary=bool(info.get("Flags", 0) & 1),
                    name=str(info.get("Device", "")),
                )
            )
        if records:
            return records
    except Exception as exc:
        logger.debug("pywin32 monitor enumeration unavailable: %s", exc)
    return _fallback_primary_monitor()


def virtual_desktop_bounds(
    monitors: list[MonitorInfo] | None = None,
) -> tuple[int, int, int, int]:
    records = monitors or list_monitors()
    if not records:
        return (0, 0, 0, 0)
    return (
        min(item.left for item in records),
        min(item.top for item in records),
        max(item.left + item.width for item in records),
        max(item.top + item.height for item in records),
    )


def get_active_window() -> WindowInfo:
    if sys.platform != "win32":
        raise ActiveWindowUnavailableError(
            "Active-window inspection is available only on Windows desktop."
        )
    try:
        import win32gui  # type: ignore

        hwnd = int(win32gui.GetForegroundWindow())
        if not hwnd:
            raise ActiveWindowUnavailableError(
                "The active window could not be detected."
            )
        return _window_info(hwnd)
    except ActiveWindowUnavailableError:
        raise
    except Exception as exc:
        raise ActiveWindowUnavailableError(
            "The active window could not be inspected."
        ) from exc


def list_windows(
    *, visible_only: bool = True, include_all: bool = False
) -> list[WindowInfo]:
    if sys.platform != "win32":
        return []
    try:
        import win32gui  # type: ignore

        records: list[WindowInfo] = []

        def callback(hwnd: int, _extra: object) -> bool:
            try:
                visible = bool(win32gui.IsWindowVisible(hwnd))
                if visible_only and not visible:
                    return True
                title = win32gui.GetWindowText(hwnd).strip()
                bounds = tuple(int(value) for value in win32gui.GetWindowRect(hwnd))
                class_name = win32gui.GetClassName(hwnd)
                exstyle = int(win32gui.GetWindowLong(hwnd, -20))
                if not _is_user_facing_window(
                    title=title,
                    class_name=class_name,
                    exstyle=exstyle,
                    bounds=bounds,
                    include_all=include_all,
                ):
                    return True
                records.append(
                    _window_info(hwnd, title=title, bounds=bounds, visible=visible)
                )
            except Exception:
                pass
            return True

        win32gui.EnumWindows(callback, None)
    except Exception as exc:
        logger.debug("Window enumeration unavailable: %s", exc)
        return []

    return _deduplicate_windows(records)


def _is_user_facing_window(
    *,
    title: str,
    class_name: str,
    exstyle: int,
    bounds: tuple[int, int, int, int],
    include_all: bool,
) -> bool:
    if include_all:
        return True
    width = max(0, bounds[2] - bounds[0])
    height = max(0, bounds[3] - bounds[1])
    return bool(
        title
        and title.casefold() not in _IGNORED_TITLES
        and class_name not in _IGNORED_CLASSES
        and not exstyle & WS_EX_TOOLWINDOW
        and width > 1
        and height > 1
    )


def _deduplicate_windows(records: list[WindowInfo]) -> list[WindowInfo]:
    deduplicated: list[WindowInfo] = []
    seen: set[str] = set()
    for item in records:
        key = item.title.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduplicated.append(item)
    return deduplicated


def _window_info(
    hwnd: int,
    *,
    title: str | None = None,
    bounds: tuple[int, int, int, int] | None = None,
    visible: bool | None = None,
) -> WindowInfo:
    import win32gui  # type: ignore
    import win32process  # type: ignore

    title = title if title is not None else win32gui.GetWindowText(hwnd).strip()
    bounds = (
        bounds
        if bounds is not None
        else tuple(int(value) for value in win32gui.GetWindowRect(hwnd))
    )
    visible = bool(win32gui.IsWindowVisible(hwnd)) if visible is None else visible
    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    process_name = ""
    executable = ""
    try:
        import psutil

        process = psutil.Process(pid)
        process_name = process.name()
        executable = process.exe()
    except Exception:
        pass
    return WindowInfo(
        title=title or "Unknown window",
        process_name=process_name,
        pid=int(pid),
        executable_path=executable,
        bounds=bounds,
        is_visible=visible,
        is_minimized=bool(win32gui.IsIconic(hwnd)),
        monitor_index=_monitor_index_for_bounds(bounds),
        handle=int(hwnd),
    )


def _monitor_index_for_bounds(bounds: tuple[int, int, int, int]) -> int:
    center_x = (bounds[0] + bounds[2]) // 2
    center_y = (bounds[1] + bounds[3]) // 2
    for monitor in list_monitors():
        if (
            monitor.left <= center_x < monitor.left + monitor.width
            and monitor.top <= center_y < monitor.top + monitor.height
        ):
            return monitor.index
    return 0


def _fallback_primary_monitor() -> list[MonitorInfo]:
    try:
        if sys.platform == "win32":
            user32 = ctypes.windll.user32  # type: ignore[attr-defined]
            return [
                MonitorInfo(
                    1,
                    0,
                    0,
                    int(user32.GetSystemMetrics(0)),
                    int(user32.GetSystemMetrics(1)),
                    True,
                    "Primary",
                )
            ]
        from PIL import ImageGrab

        image = ImageGrab.grab()
        return [MonitorInfo(1, 0, 0, image.width, image.height, True, "Primary")]
    except Exception:
        return []


__all__ = [
    "get_active_window",
    "list_monitors",
    "list_windows",
    "virtual_desktop_bounds",
]
