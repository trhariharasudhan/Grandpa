"""Safe Windows foreground window management for Grandpa."""

from __future__ import annotations

import ctypes
import re
import sys
import time
from dataclasses import dataclass
from typing import Literal

WindowAction = Literal["focus", "close", "minimize", "maximize", "restore", "list"]
WindowStatus = Literal[
    "handled",
    "dialog_pending",
    "cancelled",
    "target_lost",
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
    process_id: int = 0
    document_id: str = ""
    document_title: str = ""


@dataclass(frozen=True)
class NotepadDocumentInfo:
    document_id: str
    title: str
    modified: bool
    selected: bool
    tab_index: int


@dataclass(frozen=True)
class DialogControl:
    handle: int
    label: str
    control_id: int = 0
    class_name: str = ""


@dataclass(frozen=True)
class DialogInfo:
    handle: int
    title: str
    process_id: int
    owner_handle: int
    kind: str
    controls: tuple[DialogControl, ...] = ()


@dataclass(frozen=True)
class WindowControlResult:
    status: WindowStatus
    action: WindowAction
    target: str
    message: str
    windows: tuple[WindowInfo, ...] = ()
    dialog: DialogInfo | None = None


@dataclass(frozen=True)
class NotepadDocumentTarget:
    window: WindowInfo
    document: NotepadDocumentInfo


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

        return control_window_info(action, window, target=target)
    except Exception as exc:
        return WindowControlResult(
            "error",
            action,
            target,
            f"I could not control that window: {exc}",
        )


def control_window_info(
    action: WindowAction,
    window: WindowInfo,
    *,
    target: str | None = None,
    close_timeout: float = 1.5,
) -> WindowControlResult:
    """Control one already-resolved HWND without repeating title matching."""

    resolved_target = target or window.app_id or window.title
    if action == "close" and window.app_id == "notepad" and not window.document_id:
        documents = list_notepad_documents(window)
        if len(documents) == 1:
            document = documents[0]
            window = WindowInfo(
                window.handle,
                window.title,
                window.app_id,
                window.process_id,
                document.document_id,
                document.title,
            )
        elif len(documents) > 1:
            return WindowControlResult(
                "target_lost",
                action,
                resolved_target,
                "I found multiple Notepad documents but could not verify the "
                "selected tab. Nothing was closed.",
                (window,),
            )
    if action == "close" and _is_system_critical(window):
        return WindowControlResult(
            "blocked",
            action,
            resolved_target,
            "I blocked this window action for safety.",
            (window,),
        )
    try:
        if action == "close" and window.app_id == "notepad" and window.document_id:
            if not _request_notepad_document_close(window):
                return WindowControlResult(
                    "target_lost",
                    action,
                    resolved_target,
                    "The selected Notepad document changed before it could be closed.",
                    (window,),
                )
        else:
            _apply_action(action, window.handle)
        label = (
            "the active window"
            if resolved_target == "active"
            else _display_target(resolved_target)
        )
        if action == "close":
            if window.document_id:
                outcome, dialog = _wait_for_close_outcome(window, close_timeout)
            else:
                closed, dialog = _wait_for_window_close_or_dialog(
                    window, close_timeout
                )
                outcome = "closed" if closed else "open"
            if dialog is not None:
                return WindowControlResult(
                    "dialog_pending",
                    action,
                    resolved_target,
                    "Notepad has unsaved changes. Save, don't save, or cancel?",
                    (window,),
                    dialog,
                )
            if outcome == "target_lost":
                return WindowControlResult(
                    "target_lost",
                    action,
                    resolved_target,
                    "The selected Notepad document changed during close verification.",
                    (window,),
                )
            if outcome != "closed":
                return WindowControlResult(
                    "error",
                    action,
                    resolved_target,
                    f"{label} did not close. It may be waiting for a save prompt.",
                    (window,),
                )
            message = f"Closed {label}."
        else:
            verb = {
                "focus": "Focused",
                "minimize": "Minimized",
                "maximize": "Maximized",
                "restore": "Restored",
            }[action]
            message = f"{verb} {label}."
        return WindowControlResult(
            "handled",
            action,
            resolved_target,
            message,
            (window,),
        )
    except Exception as exc:
        return WindowControlResult(
            "error",
            action,
            resolved_target,
            f"I could not control that window: {exc}",
            (window,),
        )


def _resolve_window(target: str) -> WindowInfo | WindowControlResult:
    if target == "active":
        handle = _get_foreground_window()
        title = _get_window_title(handle)
        if handle and title:
            return _with_notepad_document(WindowInfo(
                handle=handle,
                title=title,
                process_id=_window_process_id(handle),
            ))
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
    return _with_notepad_document(matches[0])


def _matching_windows(target: str) -> list[WindowInfo]:
    target = target.lower().strip()
    keywords = _APP_TITLE_KEYWORDS.get(target, (target,))
    matches = []
    for window in _list_windows():
        title = window.title.lower()
        if any(keyword in title for keyword in keywords):
            matches.append(
                WindowInfo(
                    window.handle,
                    window.title,
                    target,
                    window.process_id,
                )
            )
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
                windows.append(
                    WindowInfo(hwnd, title, process_id=_window_process_id(hwnd))
                )
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
                windows.append(
                    WindowInfo(
                        int(hwnd),
                        title,
                        process_id=_window_process_id(int(hwnd)),
                    )
                )
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


def _window_process_id(hwnd: int) -> int:
    try:
        process_id = ctypes.c_ulong()
        ctypes.windll.user32.GetWindowThreadProcessId(
            hwnd, ctypes.byref(process_id)
        )
        return int(process_id.value)
    except Exception:
        return 0


def _window_exists(hwnd: int) -> bool:
    try:
        import win32gui  # type: ignore

        return bool(win32gui.IsWindow(hwnd))
    except Exception:
        try:
            return bool(ctypes.windll.user32.IsWindow(hwnd))
        except Exception:
            return False


def _wait_for_window_close_or_dialog(
    window: WindowInfo, timeout: float
) -> tuple[bool, DialogInfo | None]:
    outcome, dialog = _wait_for_close_outcome(window, timeout)
    return outcome == "closed", dialog


def _wait_for_close_outcome(
    window: WindowInfo, timeout: float
) -> tuple[str, DialogInfo | None]:
    deadline = time.monotonic() + max(0.0, timeout)
    while time.monotonic() < deadline:
        dialog = _find_owned_notepad_dialog(window)
        if dialog is not None:
            return "dialog_pending", dialog
        if window.document_id:
            documents = list_notepad_documents(window)
            if not any(
                item.document_id == window.document_id for item in documents
            ):
                return "closed", None
            selected = next((item for item in documents if item.selected), None)
            if selected is not None and selected.document_id != window.document_id:
                return "target_lost", None
        elif not _window_exists(window.handle):
            return "closed", None
        time.sleep(0.05)
    dialog = _find_owned_notepad_dialog(window)
    if dialog is not None:
        return "dialog_pending", dialog
    if window.document_id:
        documents = list_notepad_documents(window)
        if not any(item.document_id == window.document_id for item in documents):
            return "closed", None
        selected = next((item for item in documents if item.selected), None)
        if selected is not None and selected.document_id != window.document_id:
            return "target_lost", None
        return "open", None
    return ("closed", None) if not _window_exists(window.handle) else ("open", None)


def list_notepad_documents(window: WindowInfo) -> tuple[NotepadDocumentInfo, ...]:
    """Read modern Notepad tab identities without accessing document content."""

    if not window.process_id or (
        window.app_id != "notepad" and "notepad" not in window.title.casefold()
    ):
        return ()
    try:
        automation, module = _uia()
        root = automation.ElementFromHandle(window.handle)
        elements = root.FindAll(4, automation.CreateTrueCondition())
        documents: list[NotepadDocumentInfo] = []
        for index in range(int(elements.Length)):
            element = elements.GetElement(index)
            if int(element.CurrentProcessId) != window.process_id:
                continue
            if int(element.CurrentControlType) not in {
                50007,  # UIA_ListItemControlTypeId
                50019,  # UIA_TabItemControlTypeId (Windows 11 Notepad)
            }:
                continue
            if str(element.CurrentClassName or "").casefold() != "listviewitem":
                continue
            name = str(element.CurrentName or "").strip()
            if not name:
                continue
            runtime_id = _uia_runtime_id(element)
            if not runtime_id:
                continue
            modified = bool(
                re.search(r"(?:^|\.\s)modified\.$", name, flags=re.IGNORECASE)
            )
            title = re.sub(
                r"\.\s*(?:unmodified|modified)\.$",
                "",
                name,
                flags=re.IGNORECASE,
            ).strip()
            documents.append(
                NotepadDocumentInfo(
                    runtime_id,
                    title,
                    modified,
                    _uia_is_selected(element, module),
                    len(documents),
                )
            )
        if len(documents) == 1 and not documents[0].selected:
            documents[0] = NotepadDocumentInfo(
                documents[0].document_id,
                documents[0].title,
                documents[0].modified,
                True,
                documents[0].tab_index,
            )
        return tuple(documents)
    except Exception:
        return ()


def snapshot_notepad_documents() -> tuple[NotepadDocumentTarget, ...]:
    targets: list[NotepadDocumentTarget] = []
    for raw in _matching_windows("notepad"):
        window = WindowInfo(
            raw.handle,
            raw.title,
            "notepad",
            raw.process_id,
        )
        for document in list_notepad_documents(window):
            targets.append(NotepadDocumentTarget(window, document))
    return tuple(targets)


def wait_for_new_notepad_document(
    before: tuple[NotepadDocumentTarget, ...],
    timeout: float = 2.5,
) -> NotepadDocumentTarget | None:
    known = {
        (target.window.handle, target.document.document_id)
        for target in before
    }
    deadline = time.monotonic() + max(0.0, timeout)
    while time.monotonic() < deadline:
        current = snapshot_notepad_documents()
        created = [
            target
            for target in current
            if (target.window.handle, target.document.document_id) not in known
        ]
        if len(created) == 1:
            return created[0]
        time.sleep(0.05)
    return None


def create_new_notepad_document() -> tuple[str, NotepadDocumentTarget | None]:
    """Create one verified modern Notepad tab without coordinate-based input."""

    windows = _matching_windows("notepad")
    if not windows:
        return "not_running", None
    if len(windows) != 1:
        return "ambiguous", None
    window = WindowInfo(
        windows[0].handle,
        windows[0].title,
        "notepad",
        windows[0].process_id,
    )
    before = snapshot_notepad_documents()
    _apply_action("focus", window.handle)
    if not _invoke_uia_labeled_control(
        window.handle,
        window.process_id,
        {"add new tab"},
    ):
        return "unsupported", None
    created = wait_for_new_notepad_document(before)
    return ("created", created) if created is not None else ("unverified", None)


def diagnose_notepad_window(window: WindowInfo) -> dict[str, object]:
    """Return read-only identity data for troubleshooting modern Notepad."""

    owned = [
        candidate
        for candidate in _list_windows()
        if candidate.process_id == window.process_id
        and candidate.handle != window.handle
        and (
            _get_owner_window(candidate.handle) == window.handle
            or _get_root_owner(candidate.handle) == window.handle
        )
    ]
    native = _list_dialog_controls(window.handle)
    uia = _list_uia_controls(window.handle, window.process_id)
    dialog = _find_owned_notepad_dialog(window)
    return {
        "window": {
            "title": window.title,
            "hwnd": window.handle,
            "pid": window.process_id,
            "class_name": _get_window_class(window.handle),
        },
        "documents": [
            {
                "id": item.document_id,
                "title": item.title,
                "modified": item.modified,
                "selected": item.selected,
                "tab_index": item.tab_index,
            }
            for item in list_notepad_documents(window)
        ],
        "owned_windows": [
            {
                "title": item.title,
                "hwnd": item.handle,
                "pid": item.process_id,
                "class_name": _get_window_class(item.handle),
            }
            for item in owned
        ],
        "native_controls": [
            {"name": item.label, "type": item.class_name, "hwnd": item.handle}
            for item in native
        ],
        "uia_controls": [
            {"name": item.label, "type": item.class_name, "hwnd": item.handle}
            for item in uia
        ],
        "dialog": (
            {
                "title": dialog.title,
                "kind": dialog.kind,
                "hwnd": dialog.handle,
                "pid": dialog.process_id,
            }
            if dialog is not None
            else None
        ),
    }


def _uia_runtime_id(element: object) -> str:
    try:
        values = element.GetRuntimeId()
        return ".".join(str(int(value)) for value in values)
    except Exception:
        return ""


def _uia_is_selected(element: object, module: object) -> bool:
    try:
        pattern = element.GetCurrentPattern(10010)  # UIA_SelectionItemPatternId
        selected = pattern.QueryInterface(
            module.IUIAutomationSelectionItemPattern
        )
        return bool(selected.CurrentIsSelected)
    except Exception:
        return False


def _with_notepad_document(window: WindowInfo) -> WindowInfo:
    if window.app_id != "notepad" and "notepad" not in window.title.casefold():
        return window
    documents = list_notepad_documents(window)
    active = next((item for item in documents if item.selected), None)
    if active is None:
        return window
    return WindowInfo(
        window.handle,
        window.title,
        window.app_id or "notepad",
        window.process_id,
        active.document_id,
        active.title,
    )


def _request_notepad_document_close(window: WindowInfo) -> bool:
    current = _with_notepad_document(
        WindowInfo(window.handle, window.title, "notepad", window.process_id)
    )
    if current.document_id != window.document_id:
        return False
    _apply_action("focus", window.handle)
    try:
        user32 = ctypes.windll.user32
        user32.keybd_event(0x11, 0, 0, 0)  # Ctrl down
        user32.keybd_event(0x57, 0, 0, 0)  # W down
        user32.keybd_event(0x57, 0, 2, 0)  # W up
        user32.keybd_event(0x11, 0, 2, 0)  # Ctrl up
        return True
    except Exception:
        return False


def _find_owned_notepad_dialog(window: WindowInfo) -> DialogInfo | None:
    if window.app_id != "notepad" or not window.process_id:
        return None
    for candidate in _list_windows():
        if candidate.handle == window.handle:
            continue
        if candidate.process_id != window.process_id:
            continue
        owner = _get_owner_window(candidate.handle)
        if owner != window.handle and _get_root_owner(candidate.handle) != window.handle:
            continue
        controls = tuple(
            _all_dialog_controls(candidate.handle, candidate.process_id)
        )
        kind = _classify_notepad_dialog(
            candidate.title,
            _get_window_class(candidate.handle),
            controls,
        )
        if kind:
            return DialogInfo(
                candidate.handle,
                candidate.title,
                candidate.process_id,
                window.handle,
                kind,
                controls,
            )
    controls = tuple(_all_dialog_controls(window.handle, window.process_id))
    kind = _classify_notepad_dialog(
        window.title,
        _get_window_class(window.handle),
        controls,
    )
    if kind:
        return DialogInfo(
            window.handle,
            window.title,
            window.process_id,
            window.handle,
            kind,
            controls,
        )
    return None


def find_owned_notepad_dialog(window: WindowInfo) -> DialogInfo | None:
    """Return only a recognized modal owned by the exact Notepad HWND/PID."""

    return _find_owned_notepad_dialog(window)


def window_exists(hwnd: int) -> bool:
    return _window_exists(hwnd)


def _classify_notepad_dialog(
    title: str,
    class_name: str,
    controls: tuple[DialogControl, ...],
) -> str:
    labels = {_normalise_control_label(item.label) for item in controls}
    lowered_title = title.casefold()
    if (
        "confirm save as" in lowered_title
        or "replace" in lowered_title
        or {"yes", "no"}.issubset(labels)
    ):
        return "overwrite_confirmation"
    if "save as" in lowered_title or (
        "save" in labels and any("file name" in label for label in labels)
    ):
        return "save_as"
    has_save = "save" in labels
    has_discard = any(
        label in {"don't save", "dont save", "discard", "discard changes"}
        for label in labels
    )
    dialog_class = class_name.casefold() in {"#32770", "dialog"}
    if has_save and has_discard and (
        "notepad" in lowered_title or dialog_class
    ):
        return "notepad_unsaved"
    return ""


def _list_dialog_controls(hwnd: int) -> list[DialogControl]:
    try:
        import win32gui  # type: ignore

        controls: list[DialogControl] = []

        def callback(child: int, _extra: object) -> bool:
            controls.append(
                DialogControl(
                    int(child),
                    win32gui.GetWindowText(child).strip(),
                    int(win32gui.GetDlgCtrlID(child)),
                    win32gui.GetClassName(child),
                )
            )
            return True

        win32gui.EnumChildWindows(hwnd, callback, None)
        return controls
    except Exception:
        return []


def _list_uia_controls(hwnd: int, process_id: int) -> list[DialogControl]:
    try:
        automation, module = _uia()
        root = automation.ElementFromHandle(hwnd)
        elements = root.FindAll(4, automation.CreateTrueCondition())  # descendants
        controls: list[DialogControl] = []
        for index in range(int(elements.Length)):
            element = elements.GetElement(index)
            if int(element.CurrentProcessId) != process_id:
                continue
            label = str(element.CurrentName or "").strip()
            if not label:
                continue
            controls.append(
                DialogControl(
                    int(element.CurrentNativeWindowHandle or 0),
                    label,
                    0,
                    str(element.CurrentClassName or ""),
                )
            )
        return controls
    except Exception:
        return []


def _all_dialog_controls(
    hwnd: int, process_id: int
) -> list[DialogControl]:
    controls = _list_dialog_controls(hwnd)
    seen = {
        (_normalise_control_label(item.label), item.handle)
        for item in controls
    }
    for item in _list_uia_controls(hwnd, process_id):
        key = (_normalise_control_label(item.label), item.handle)
        if key not in seen:
            controls.append(item)
            seen.add(key)
    return controls


def _uia():
    import comtypes.client  # type: ignore

    module = comtypes.client.GetModule("UIAutomationCore.dll")
    unknown = comtypes.client.CreateObject(
        "{FF48DBA4-60EF-4201-AA87-54103EEF594E}"
    )
    return unknown.QueryInterface(module.IUIAutomation), module


def _get_owner_window(hwnd: int) -> int:
    try:
        import win32gui  # type: ignore

        return int(win32gui.GetWindow(hwnd, 4))  # GW_OWNER
    except Exception:
        try:
            return int(ctypes.windll.user32.GetWindow(hwnd, 4))
        except Exception:
            return 0


def _get_root_owner(hwnd: int) -> int:
    try:
        return int(ctypes.windll.user32.GetAncestor(hwnd, 3))  # GA_ROOTOWNER
    except Exception:
        return 0


def _get_window_class(hwnd: int) -> str:
    try:
        import win32gui  # type: ignore

        return str(win32gui.GetClassName(hwnd))
    except Exception:
        return ""


def _normalise_control_label(value: str) -> str:
    return " ".join(value.replace("&", "").casefold().split())


def verify_dialog_identity(
    dialog: DialogInfo,
    window: WindowInfo,
) -> bool:
    if not _window_exists(dialog.handle) or not _window_exists(window.handle):
        return False
    if _window_process_id(dialog.handle) != window.process_id:
        return False
    if dialog.handle != window.handle:
        owner = _get_owner_window(dialog.handle)
        if owner != window.handle and _get_root_owner(dialog.handle) != window.handle:
            return False
    current = _find_owned_notepad_dialog(window)
    return bool(
        current
        and current.handle == dialog.handle
        and current.kind == dialog.kind
    )


def invoke_dialog_choice(
    dialog: DialogInfo,
    window: WindowInfo,
    choice: str,
) -> bool:
    """Invoke a labeled control only after exact owner/PID verification."""

    if not verify_dialog_identity(dialog, window):
        return False
    aliases = {
        "save": {"save"},
        "discard": {"don't save", "dont save", "discard", "discard changes"},
        "cancel": {"cancel"},
        "overwrite": {"yes", "replace", "replace it"},
    }
    wanted = aliases.get(choice, set())
    control = next(
        (
            item
            for item in dialog.controls
            if _normalise_control_label(item.label) in wanted
        ),
        None,
    )
    if control is None:
        return False
    if not control.handle:
        return _invoke_uia_labeled_control(
            dialog.handle,
            dialog.process_id,
            wanted,
        )
    try:
        import win32con  # type: ignore
        import win32gui  # type: ignore

        win32gui.SendMessage(control.handle, win32con.BM_CLICK, 0, 0)
        return True
    except Exception:
        try:
            ctypes.windll.user32.SendMessageW(control.handle, 0x00F5, 0, 0)
            return True
        except Exception:
            return False


def complete_save_as_dialog(
    dialog: DialogInfo,
    window: WindowInfo,
    path: str,
) -> bool:
    """Set a verified Save As filename and invoke its exact Save control."""

    if dialog.kind != "save_as" or not verify_dialog_identity(dialog, window):
        return False
    if not _set_save_as_filename(dialog, path):
        return False
    return invoke_dialog_choice(dialog, window, "save")


def _set_save_as_filename(dialog: DialogInfo, path: str) -> bool:
    native = next(
        (
            control
            for control in dialog.controls
            if control.control_id == 0x047C
            or control.class_name.casefold() == "edit"
        ),
        None,
    )
    if native is not None and native.handle:
        try:
            import win32gui  # type: ignore

            win32gui.SetWindowText(native.handle, path)
            return True
        except Exception:
            try:
                return bool(
                    ctypes.windll.user32.SetWindowTextW(native.handle, path)
                )
            except Exception:
                return False
    try:
        automation, module = _uia()
        root = automation.ElementFromHandle(dialog.handle)
        elements = root.FindAll(4, automation.CreateTrueCondition())
        edits = []
        for index in range(int(elements.Length)):
            element = elements.GetElement(index)
            if int(element.CurrentProcessId) != dialog.process_id:
                continue
            if int(element.CurrentControlType) == 50004:  # UIA_EditControlTypeId
                edits.append(element)
        if len(edits) != 1:
            return False
        pattern = edits[0].GetCurrentPattern(10002)  # UIA_ValuePatternId
        pattern.QueryInterface(module.IUIAutomationValuePattern).SetValue(path)
        return True
    except Exception:
        return False


def _invoke_uia_labeled_control(
    hwnd: int,
    process_id: int,
    labels: set[str],
) -> bool:
    try:
        automation, module = _uia()
        root = automation.ElementFromHandle(hwnd)
        elements = root.FindAll(4, automation.CreateTrueCondition())
        matches = []
        for index in range(int(elements.Length)):
            element = elements.GetElement(index)
            if int(element.CurrentProcessId) != process_id:
                continue
            if int(element.CurrentControlType) != 50000:  # UIA_ButtonControlTypeId
                continue
            if _normalise_control_label(str(element.CurrentName or "")) in labels:
                matches.append(element)
        if len(matches) != 1:
            return False
        pattern = matches[0].GetCurrentPattern(10000)  # UIA_InvokePatternId
        pattern.QueryInterface(module.IUIAutomationInvokePattern).Invoke()
        return True
    except Exception:
        return False


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
    "DialogControl",
    "DialogInfo",
    "NotepadDocumentInfo",
    "NotepadDocumentTarget",
    "WindowControlResult",
    "WindowInfo",
    "control_window",
    "control_window_info",
    "complete_save_as_dialog",
    "create_new_notepad_document",
    "diagnose_notepad_window",
    "find_owned_notepad_dialog",
    "invoke_dialog_choice",
    "list_notepad_documents",
    "snapshot_notepad_documents",
    "list_open_windows",
    "verify_dialog_identity",
    "wait_for_new_notepad_document",
    "window_exists",
]
