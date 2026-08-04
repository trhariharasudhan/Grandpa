"""Window targeting and verification for safe desktop input."""

from __future__ import annotations

import ctypes
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

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
    document_id: str = ""
    document_title: str = ""

    @property
    def label(self) -> str:
        return self.target or self.title


@dataclass(frozen=True)
class WindowVerification:
    ok: bool
    message: str
    expected: WindowIdentity | None = None
    actual: WindowIdentity | None = None
    candidates: tuple[WindowIdentity, ...] = ()


@dataclass(frozen=True)
class DialogControlIdentity:
    handle: int
    label: str
    control_id: int = 0
    class_name: str = ""


@dataclass(frozen=True)
class DialogIdentity:
    handle: int
    title: str
    process_id: int
    owner_handle: int
    kind: str
    controls: tuple[DialogControlIdentity, ...] = ()


@dataclass(frozen=True)
class WindowCloseResult:
    status: str
    message: str
    window: WindowIdentity
    dialog: DialogIdentity | None = None

    @property
    def ok(self) -> bool:
        return self.status in {"closed", "cancelled"}


class WindowTargetResolutionError(RuntimeError):
    """A friendly window-resolution failure safe for user-facing output."""

    def __init__(
        self,
        message: str,
        *,
        candidates: tuple[WindowIdentity, ...] = (),
    ) -> None:
        super().__init__(message)
        self.candidates = candidates


class WindowTargetController:
    """Resolve, focus, and prove foreground identity before desktop input."""

    def __init__(
        self,
        *,
        resolve_func: Callable[[str], WindowIdentity | None] | None = None,
        foreground_func: Callable[[], WindowIdentity | None] | None = None,
        focus_func: Callable[[int], None] | None = None,
        close_func: Callable[[WindowIdentity], object] | None = None,
        dialog_choice_func: (
            Callable[[DialogIdentity, WindowIdentity, str], bool] | None
        ) = None,
        dialog_detect_func: (
            Callable[[WindowIdentity], DialogIdentity | None] | None
        ) = None,
        save_as_func: (
            Callable[[DialogIdentity, WindowIdentity, str], bool] | None
        ) = None,
        exists_func: Callable[[int], bool] | None = None,
        document_exists_func: Callable[[WindowIdentity], bool] | None = None,
        ready_func: Callable[[WindowIdentity], bool] | None = None,
        control_sequence_func: (
            Callable[[int, int, tuple[str, ...]], bool] | None
        ) = None,
        control_available_func: (
            Callable[[int, int, tuple[str, ...]], bool] | None
        ) = None,
        control_text_func: (
            Callable[[int, int, tuple[str, ...]], dict[str, str]] | None
        ) = None,
        sleep_func: Callable[[float], None] = time.sleep,
        timeout: float = 1.5,
        poll_interval: float = 0.05,
    ) -> None:
        self._resolve = resolve_func or resolve_window
        self._foreground = foreground_func or foreground_window
        self._focus = focus_func or focus_window_handle
        self._close = close_func or close_window_identity
        self._dialog_choice = dialog_choice_func or invoke_window_dialog_choice
        self._dialog_detect = dialog_detect_func or detect_window_dialog
        self._save_as = save_as_func or complete_window_save_as
        self._exists = exists_func or window_handle_exists
        self._document_exists = document_exists_func or window_document_exists
        self._ready = ready_func or window_identity_ready
        self._control_sequence = control_sequence_func or invoke_window_control_sequence
        self._control_available = control_available_func or window_controls_available
        self._control_text = control_text_func or read_window_control_texts
        self._sleep = sleep_func
        self.timeout = timeout
        self.poll_interval = poll_interval

    def resolve(self, target: str) -> WindowIdentity | None:
        return self._resolve(target)

    def candidates(self, target: str) -> tuple[WindowIdentity, ...]:
        """Return every safely resolved candidate without selecting an ambiguity."""

        try:
            resolved = self._resolve(target)
        except WindowTargetResolutionError as exc:
            return exc.candidates
        return (resolved,) if resolved is not None else ()

    def is_ready(self, target: WindowIdentity) -> bool:
        """Check that a resolved top-level window is still usable."""

        try:
            return bool(self._ready(target))
        except Exception:
            return False

    def invoke_controls(
        self, target: WindowIdentity, automation_ids: tuple[str, ...]
    ) -> bool:
        """Invoke exact UIA controls only inside the pinned window process."""

        try:
            return bool(
                self._control_sequence(
                    target.handle,
                    target.process_id,
                    automation_ids,
                )
            )
        except Exception:
            return False

    def controls_available(
        self, target: WindowIdentity, automation_ids: tuple[str, ...]
    ) -> bool:
        try:
            return bool(
                self._control_available(
                    target.handle,
                    target.process_id,
                    automation_ids,
                )
            )
        except Exception:
            return False

    def read_controls(
        self, target: WindowIdentity, automation_ids: tuple[str, ...]
    ) -> dict[str, str]:
        try:
            return dict(
                self._control_text(
                    target.handle,
                    target.process_id,
                    automation_ids,
                )
            )
        except Exception:
            return {}

    def focus_and_verify(
        self, target: str | WindowIdentity, *, dry_run: bool = False
    ) -> WindowVerification:
        try:
            expected = self._resolve(target) if isinstance(target, str) else target
        except WindowTargetResolutionError as exc:
            return WindowVerification(False, str(exc), candidates=exc.candidates)
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
            return WindowVerification(
                True, f"Target window resolved: {expected.title}.", expected
            )

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

    def close_and_verify(
        self, expected: WindowIdentity, *, dry_run: bool = False
    ) -> WindowCloseResult:
        """Close one pinned HWND and only succeed after Windows removes it."""

        if is_terminal_window(expected):
            return WindowCloseResult(
                "failed",
                "Terminal windows are protected from automation close actions.",
                expected,
            )
        if dry_run:
            return WindowCloseResult(
                "confirmation_required",
                f"Would close {_display_target(expected.label)} after confirmation.",
                expected,
            )
        result = self._close(expected)
        status = str(getattr(result, "status", ""))
        dialog = _dialog_identity(getattr(result, "dialog", None))
        if status == "handled":
            close_status = "closed"
        elif status == "dialog_pending" and dialog is not None:
            close_status = "dialog_pending"
        elif status == "target_lost":
            close_status = "target_lost"
        else:
            close_status = "failed"
        return WindowCloseResult(
            close_status,
            str(getattr(result, "message", "") or "The window did not close."),
            expected,
            dialog,
        )

    def respond_to_dialog(
        self,
        expected: WindowIdentity,
        dialog: DialogIdentity,
        choice: str,
    ) -> WindowCloseResult:
        if (
            dialog.process_id != expected.process_id
            or dialog.owner_handle != expected.handle
        ):
            return WindowCloseResult(
                "failed",
                "The pending dialog no longer belongs to the selected window. Nothing was clicked.",
                expected,
            )
        if not self._dialog_choice(dialog, expected, choice):
            return WindowCloseResult(
                "failed",
                "The verified dialog action was unavailable. Nothing was clicked.",
                expected,
            )
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            target_exists = self._target_exists(expected)
            if choice in {"discard", "overwrite"} and not target_exists:
                message = (
                    "Saved and closed Notepad."
                    if choice == "overwrite"
                    else "Closed Notepad without saving."
                )
                return WindowCloseResult("closed", message, expected)
            current = self._dialog_detect(expected)
            if choice == "cancel" and current is None and target_exists:
                return WindowCloseResult(
                    "cancelled",
                    "Close cancelled. Notepad remains open.",
                    expected,
                )
            if choice == "save":
                if not target_exists:
                    return WindowCloseResult(
                        "closed", "Saved and closed Notepad.", expected
                    )
                if current is not None and current.kind == "save_as":
                    return WindowCloseResult(
                        "save_as_pending",
                        "A Save As dialog is open. What filename or path should I use?",
                        expected,
                        current,
                    )
            self._sleep(self.poll_interval)
        return WindowCloseResult(
            "failed",
            "The dialog action timed out, so I could not verify the result.",
            expected,
            self._dialog_detect(expected),
        )

    def _target_exists(self, expected: WindowIdentity) -> bool:
        if expected.document_id:
            return self._document_exists(expected)
        return self._exists(expected.handle)

    def save_as_and_verify(
        self,
        expected: WindowIdentity,
        dialog: DialogIdentity,
        path: str,
        *,
        allow_overwrite: bool = False,
    ) -> WindowCloseResult:
        if dialog.kind != "save_as":
            return WindowCloseResult(
                "failed",
                "The pending dialog is not a verified Save As dialog.",
                expected,
            )
        if (
            dialog.process_id != expected.process_id
            or dialog.owner_handle != expected.handle
        ):
            return WindowCloseResult(
                "failed",
                "The Save As dialog no longer belongs to the selected window.",
                expected,
            )
        if not self._save_as(dialog, expected, path):
            return WindowCloseResult(
                "failed",
                "I could not set the filename in the verified Save As dialog.",
                expected,
            )
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            if not self._target_exists(expected):
                return WindowCloseResult(
                    "closed", "Saved and closed Notepad.", expected
                )
            current = self._dialog_detect(expected)
            if current is not None and current.kind == "overwrite_confirmation":
                if not allow_overwrite:
                    return WindowCloseResult(
                        "overwrite_pending",
                        f"{path} already exists. Overwrite it? Yes / No",
                        expected,
                        current,
                    )
                if not self._dialog_choice(current, expected, "overwrite"):
                    return WindowCloseResult(
                        "failed",
                        "The verified overwrite confirmation could not be invoked.",
                        expected,
                        current,
                    )
            self._sleep(self.poll_interval)
        return WindowCloseResult(
            "failed",
            "The Save As action timed out, so I could not verify that Notepad closed.",
            expected,
            self._dialog_detect(expected),
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
        candidates = tuple(
            _identity(
                int(window.handle),
                str(window.title),
                target,
                process_id=int(getattr(window, "process_id", 0)),
            )
            for window in getattr(result, "windows", ())
        )
        if message:
            raise WindowTargetResolutionError(message, candidates=candidates)
        return None
    return _identity(
        int(result.handle),
        str(result.title),
        target,
        process_id=int(getattr(result, "process_id", 0)),
        document_id=str(getattr(result, "document_id", "")),
        document_title=str(getattr(result, "document_title", "")),
    )


def foreground_window() -> WindowIdentity | None:
    if sys.platform != "win32":
        return None
    from grandpa.windows_window_control import _get_foreground_window, _get_window_title

    handle = int(_get_foreground_window())
    title = str(_get_window_title(handle))
    return _identity(handle, title) if handle and title else None


def focus_window_handle(handle: int) -> None:
    """Bring one verified HWND forward using a bounded Windows-native handoff."""

    from grandpa.windows_window_control import _apply_action

    _apply_action("focus", handle)
    if sys.platform != "win32":
        return

    user32 = ctypes.windll.user32
    foreground = int(user32.GetForegroundWindow())
    if foreground == int(handle):
        return

    current_thread = int(ctypes.windll.kernel32.GetCurrentThreadId())
    foreground_thread = int(user32.GetWindowThreadProcessId(foreground, None))
    attached = False
    try:
        if foreground_thread and foreground_thread != current_thread:
            attached = bool(
                user32.AttachThreadInput(current_thread, foreground_thread, True)
            )
        user32.ShowWindow(int(handle), 9)  # SW_RESTORE
        user32.BringWindowToTop(int(handle))
        user32.SetForegroundWindow(int(handle))
    finally:
        if attached:
            user32.AttachThreadInput(current_thread, foreground_thread, False)


def close_window_identity(window: WindowIdentity) -> object:
    from grandpa.windows_window_control import WindowInfo, control_window_info

    return control_window_info(
        "close",
        WindowInfo(
            window.handle,
            window.title,
            window.target,
            window.process_id,
            window.document_id,
            window.document_title,
        ),
        target=window.target or window.title,
    )


def invoke_window_control_sequence(
    handle: int,
    process_id: int,
    automation_ids: tuple[str, ...],
) -> bool:
    from grandpa.windows_window_control import invoke_uia_controls_by_id

    return invoke_uia_controls_by_id(handle, process_id, automation_ids)


def window_controls_available(
    handle: int,
    process_id: int,
    automation_ids: tuple[str, ...],
) -> bool:
    from grandpa.windows_window_control import uia_controls_available_by_id

    return uia_controls_available_by_id(handle, process_id, automation_ids)


def read_window_control_texts(
    handle: int,
    process_id: int,
    automation_ids: tuple[str, ...],
) -> dict[str, str]:
    from grandpa.windows_window_control import read_uia_control_names_by_id

    return read_uia_control_names_by_id(handle, process_id, automation_ids)


def detect_window_dialog(window: WindowIdentity) -> DialogIdentity | None:
    from grandpa.windows_window_control import (
        WindowInfo,
        find_owned_notepad_dialog,
    )

    return _dialog_identity(
        find_owned_notepad_dialog(
            WindowInfo(
                window.handle,
                window.title,
                window.target,
                window.process_id,
                window.document_id,
                window.document_title,
            )
        )
    )


def invoke_window_dialog_choice(
    dialog: DialogIdentity,
    window: WindowIdentity,
    choice: str,
) -> bool:
    from grandpa.windows_window_control import (
        DialogControl,
        DialogInfo,
        WindowInfo,
        invoke_dialog_choice,
    )

    return invoke_dialog_choice(
        DialogInfo(
            dialog.handle,
            dialog.title,
            dialog.process_id,
            dialog.owner_handle,
            dialog.kind,
            tuple(
                DialogControl(
                    item.handle,
                    item.label,
                    item.control_id,
                    item.class_name,
                )
                for item in dialog.controls
            ),
        ),
        WindowInfo(
            window.handle,
            window.title,
            window.target,
            window.process_id,
            window.document_id,
            window.document_title,
        ),
        choice,
    )


def complete_window_save_as(
    dialog: DialogIdentity,
    window: WindowIdentity,
    path: str,
) -> bool:
    from grandpa.windows_window_control import (
        DialogControl,
        DialogInfo,
        WindowInfo,
        complete_save_as_dialog,
    )

    return complete_save_as_dialog(
        DialogInfo(
            dialog.handle,
            dialog.title,
            dialog.process_id,
            dialog.owner_handle,
            dialog.kind,
            tuple(
                DialogControl(
                    item.handle,
                    item.label,
                    item.control_id,
                    item.class_name,
                )
                for item in dialog.controls
            ),
        ),
        WindowInfo(
            window.handle,
            window.title,
            window.target,
            window.process_id,
            window.document_id,
            window.document_title,
        ),
        path,
    )


def window_handle_exists(handle: int) -> bool:
    from grandpa.windows_window_control import window_exists

    return window_exists(handle)


def window_document_exists(window: WindowIdentity) -> bool:
    if not window.document_id:
        return window_handle_exists(window.handle)
    from grandpa.windows_window_control import WindowInfo, list_notepad_documents

    documents = list_notepad_documents(
        WindowInfo(
            window.handle,
            window.title,
            window.target,
            window.process_id,
            window.document_id,
            window.document_title,
        )
    )
    return any(item.document_id == window.document_id for item in documents)


def window_identity_ready(window: WindowIdentity) -> bool:
    """Return whether a visible target HWND is available for safe automation."""

    if not window_handle_exists(window.handle):
        return False
    if sys.platform != "win32":
        return True
    try:
        user32 = ctypes.windll.user32
        return bool(user32.IsWindowVisible(window.handle)) and bool(
            user32.IsWindowEnabled(window.handle)
        )
    except Exception:
        return False


def same_window(expected: WindowIdentity, actual: WindowIdentity | None) -> bool:
    if actual is None:
        return False
    if expected.handle and expected.handle == actual.handle:
        return not expected.document_id or expected.document_id == actual.document_id
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


def _identity(
    handle: int,
    title: str,
    target: str = "",
    *,
    process_id: int = 0,
    document_id: str = "",
    document_title: str = "",
) -> WindowIdentity:
    process_id = process_id or _window_process_id(handle)
    if not document_id and (
        target.casefold() == "notepad" or "notepad" in title.casefold()
    ):
        try:
            from grandpa.windows_window_control import (
                WindowInfo,
                list_notepad_documents,
            )

            documents = list_notepad_documents(
                WindowInfo(handle, title, "notepad", process_id)
            )
            active = next((item for item in documents if item.selected), None)
            if active is not None:
                document_id = active.document_id
                document_title = active.title
        except Exception:
            pass
    return WindowIdentity(
        handle,
        title,
        process_id,
        _process_name(process_id),
        target,
        document_id,
        document_title,
    )


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
            if kernel32.QueryFullProcessImageNameW(
                handle, 0, buffer, ctypes.byref(size)
            ):
                return Path(buffer.value).name
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return ""
    return ""


def _dialog_identity(value: Any) -> DialogIdentity | None:
    if value is None:
        return None
    return DialogIdentity(
        int(value.handle),
        str(value.title),
        int(value.process_id),
        int(value.owner_handle),
        str(value.kind),
        tuple(
            DialogControlIdentity(
                int(control.handle),
                str(control.label),
                int(getattr(control, "control_id", 0)),
                str(getattr(control, "class_name", "")),
            )
            for control in getattr(value, "controls", ())
        ),
    )


def _display_target(target: str) -> str:
    value = target.strip()
    if value.casefold() in {"vscode", "vs code", "visual studio code"}:
        return "VS Code"
    return value.replace("_", " ").title()


def _normalize_title(value: str) -> str:
    return " ".join(value.casefold().lstrip("*").split())


__all__ = [
    "WindowIdentity",
    "DialogControlIdentity",
    "DialogIdentity",
    "WindowCloseResult",
    "WindowTargetController",
    "WindowTargetResolutionError",
    "WindowVerification",
    "foreground_window",
    "close_window_identity",
    "complete_window_save_as",
    "detect_window_dialog",
    "is_terminal_window",
    "same_window",
    "invoke_window_dialog_choice",
    "invoke_window_control_sequence",
    "window_handle_exists",
    "window_identity_ready",
    "window_controls_available",
    "read_window_control_texts",
    "window_payload",
]
