"""Window targeting and verification for safe desktop input."""

from __future__ import annotations

import ctypes
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from grandpa.automation.models import AutomationAction

TERMINAL_MARKERS = (
    "windows terminal",
    "powershell",
    "command prompt",
    "cmd.exe",
    "pwsh.exe",
)


@dataclass(frozen=True)
class WindowIdentity:
    handle: int
    title: str
    process_id: int = 0
    process_name: str = ""
    target: str = ""

    @property
    def label(self) -> str:
        return self.target or self.title


@dataclass(frozen=True)
class WindowVerification:
    ok: bool
    message: str
    expected: WindowIdentity | None = None
    actual: WindowIdentity | None = None


class WindowTargetResolutionError(RuntimeError):
    """A friendly window-resolution failure safe for user-facing output."""


class WindowTargetController:
    """Resolve, focus, and prove foreground identity before desktop input."""

    def __init__(
        self,
        *,
        resolve_func: Callable[[str], WindowIdentity | None] | None = None,
        foreground_func: Callable[[], WindowIdentity | None] | None = None,
        focus_func: Callable[[int], None] | None = None,
        sleep_func: Callable[[float], None] = time.sleep,
        timeout: float = 0.75,
        poll_interval: float = 0.05,
    ) -> None:
        self._resolve = resolve_func or resolve_window
        self._foreground = foreground_func or foreground_window
        self._focus = focus_func or focus_window_handle
        self._sleep = sleep_func
        self.timeout = timeout
        self.poll_interval = poll_interval

    def resolve(self, target: str) -> WindowIdentity | None:
        return self._resolve(target)

    def focus_and_verify(
        self, target: str | WindowIdentity, *, dry_run: bool = False
    ) -> WindowVerification:
        try:
            expected = self._resolve(target) if isinstance(target, str) else target
        except WindowTargetResolutionError as exc:
            return WindowVerification(False, str(exc))
        label = target if isinstance(target, str) else target.label
        if expected is None:
            return WindowVerification(
                False,
                f"{_display_target(str(label))} could not be found. No input was sent.",
            )
        if is_terminal_window(expected):
            return WindowVerification(
                False,
                "Terminal windows are protected from automation input. No input was sent.",
                expected,
            )
        if dry_run:
            return WindowVerification(True, f"Target window resolved: {expected.title}.", expected)

        try:
            self._focus(expected.handle)
        except Exception:
            return WindowVerification(
                False,
                f"{_display_target(expected.label)} is no longer available. No input was sent.",
                expected,
            )
        deadline = time.monotonic() + self.timeout
        actual = self._foreground()
        while not same_window(expected, actual) and time.monotonic() < deadline:
            self._sleep(self.poll_interval)
            actual = self._foreground()
        if same_window(expected, actual):
            return WindowVerification(
                True,
                f"Focused {_display_target(expected.label)}.\nVerified active window: {actual.title}.",
                expected,
                actual,
            )
        actual_label = actual.title if actual is not None else "an unknown window"
        if actual is not None and is_terminal_window(actual):
            return WindowVerification(
                False,
                "Target verification failed.\n"
                f"Expected {_display_target(expected.label)}, but {actual_label} is active.\n"
                "No input was sent.",
                expected,
                actual,
            )
        return WindowVerification(
            False,
            f"{_display_target(expected.label)} could not be confirmed as the active window.\n"
            "No input was sent.",
            expected,
            actual,
        )

    def verify_foreground(self, expected: WindowIdentity) -> WindowVerification:
        """Prove that a previously pinned window still owns the foreground."""

        actual = self._foreground()
        if same_window(expected, actual):
            return WindowVerification(
                True,
                f"Verified active window: {actual.title}.",
                expected,
                actual,
            )
        actual_label = actual.title if actual is not None else "no active window"
        return WindowVerification(
            False,
            "The target window changed during the action. "
            f"Expected {_display_target(expected.label)}, but {actual_label} is active.",
            expected,
            actual,
        )


def window_payload(action: AutomationAction) -> dict[str, object]:
    action_type = {
        "focus": "focus_window",
        "maximize": "maximize_window",
        "minimize": "minimize_window",
        "restore": "restore_window",
    }.get(action.kind)
    if action_type is None:
        raise ValueError(f"Unsupported window action: {action.kind}")
    return {"action_type": action_type, "target": action.target or "active", "args": {}}


def resolve_window(target: str) -> WindowIdentity | None:
    if sys.platform != "win32":
        return None
    from grandpa.windows_window_control import _resolve_window

    result = _resolve_window(target)
    if not hasattr(result, "handle"):
        message = str(getattr(result, "message", "")).strip()
        if message:
            raise WindowTargetResolutionError(message)
        return None
    return _identity(int(result.handle), str(result.title), target)


def foreground_window() -> WindowIdentity | None:
    if sys.platform != "win32":
        return None
    from grandpa.windows_window_control import _get_foreground_window, _get_window_title

    handle = int(_get_foreground_window())
    title = str(_get_window_title(handle))
    return _identity(handle, title) if handle and title else None


def focus_window_handle(handle: int) -> None:
    from grandpa.windows_window_control import _apply_action

    _apply_action("focus", handle)


def same_window(expected: WindowIdentity, actual: WindowIdentity | None) -> bool:
    if actual is None:
        return False
    if expected.handle and expected.handle == actual.handle:
        return True
    if expected.process_id and expected.process_id == actual.process_id:
        if expected.process_name and actual.process_name:
            return (
                expected.process_name.casefold() == actual.process_name.casefold()
                and _normalize_title(expected.title) == _normalize_title(actual.title)
            )
    return False


def is_terminal_window(window: WindowIdentity) -> bool:
    value = f"{window.title} {window.process_name}".casefold()
    return any(marker in value for marker in TERMINAL_MARKERS)


def _identity(handle: int, title: str, target: str = "") -> WindowIdentity:
    process_id = _window_process_id(handle)
    return WindowIdentity(handle, title, process_id, _process_name(process_id), target)


def _window_process_id(handle: int) -> int:
    try:
        process_id = ctypes.c_ulong()
        ctypes.windll.user32.GetWindowThreadProcessId(handle, ctypes.byref(process_id))
        return int(process_id.value)
    except Exception:
        return 0


def _process_name(process_id: int) -> str:
    if not process_id:
        return ""
    try:
        import psutil  # type: ignore

        return str(psutil.Process(process_id).name())
    except Exception:
        pass
    try:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, process_id)
        if not handle:
            return ""
        try:
            size = ctypes.c_ulong(32768)
            buffer = ctypes.create_unicode_buffer(size.value)
            if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                return Path(buffer.value).name
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return ""
    return ""


def _display_target(target: str) -> str:
    value = target.strip()
    if value.casefold() in {"vscode", "vs code", "visual studio code"}:
        return "VS Code"
    return value.replace("_", " ").title()


def _normalize_title(value: str) -> str:
    return " ".join(value.casefold().lstrip("*").split())


__all__ = [
    "WindowIdentity",
    "WindowTargetController",
    "WindowTargetResolutionError",
    "WindowVerification",
    "foreground_window",
    "is_terminal_window",
    "same_window",
    "window_payload",
]
