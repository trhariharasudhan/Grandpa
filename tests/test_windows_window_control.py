from __future__ import annotations

import pytest

from grandpa import local_actions, windows_window_control
from grandpa.local_action_approvals import LocalActionApprovalStore
from grandpa.local_actions import handle_local_action
from grandpa.windows_window_control import WindowInfo, control_window


@pytest.fixture(autouse=True)
def _approval_store_fixture(tmp_path, monkeypatch):
    store = LocalActionApprovalStore(tmp_path / "approvals.db")
    monkeypatch.setattr(local_actions, "LocalActionApprovalStore", lambda: store)
    return store


def test_window_focus_command_is_allowed_without_execution():
    result = handle_local_action("focus notepad", execute=False)

    assert result.status == "handled"
    assert result.kind == "window"
    assert result.target == "focus|notepad"
    assert result.permission == "allowed"


def test_window_minimize_command_is_allowed_without_execution():
    result = handle_local_action("minimize chrome", execute=False)

    assert result.status == "handled"
    assert result.kind == "window"
    assert result.target == "minimize|chrome"
    assert result.permission == "allowed"


def test_window_close_command_requires_confirmation():
    result = handle_local_action("close notepad", execute=False)

    assert result.status == "requires_confirmation"
    assert result.kind == "window"
    assert result.target == "close|notepad"
    assert result.permission == "requires_confirmation"
    assert result.pending_action
    assert "Confirmation required before closing Notepad." in result.message
    assert "Permission: requires_confirmation" not in result.message


def test_window_list_command_is_deterministic_without_execution():
    result = handle_local_action("what windows are open?", execute=False)

    assert result.status == "handled"
    assert result.kind == "window"
    assert result.target == "list|windows"
    assert result.should_fallback is False


def test_window_close_system_app_command_is_blocked():
    result = handle_local_action("close task manager", execute=False)

    assert result.status == "blocked"
    assert result.permission == "blocked"


def test_window_control_is_unsupported_off_windows(monkeypatch):
    monkeypatch.setattr(windows_window_control.sys, "platform", "linux")

    result = control_window("focus", "notepad")

    assert result.status == "unsupported"
    assert "only supported on Windows" in result.message


def test_window_control_reports_multiple_matches(monkeypatch):
    monkeypatch.setattr(windows_window_control.sys, "platform", "win32")
    monkeypatch.setattr(
        windows_window_control,
        "_list_windows",
        lambda: [
            WindowInfo(100, "notes - Notepad", process_id=1000),
            WindowInfo(101, "todo - Notepad", process_id=1001),
        ],
    )

    result = control_window("focus", "notepad")

    assert result.status == "multiple_matches"
    assert "multiple Notepad windows" in result.message
    assert result.windows[0].process_id == 1000


def test_window_control_blocks_closing_system_critical_window(monkeypatch):
    monkeypatch.setattr(windows_window_control.sys, "platform", "win32")
    monkeypatch.setattr(windows_window_control, "_get_foreground_window", lambda: 100)
    monkeypatch.setattr(
        windows_window_control,
        "_get_window_title",
        lambda _hwnd: "Task Manager",
    )

    result = control_window("close", "active")

    assert result.status == "blocked"
    assert "blocked" in result.message.lower()


def test_window_control_uses_graceful_window_operation(monkeypatch):
    calls: list[tuple[str, int]] = []
    monkeypatch.setattr(windows_window_control.sys, "platform", "win32")
    monkeypatch.setattr(
        windows_window_control,
        "_list_windows",
        lambda: [WindowInfo(100, "Untitled - Notepad")],
    )
    monkeypatch.setattr(
        windows_window_control,
        "_apply_action",
        lambda action, handle: calls.append((action, handle)),
    )

    result = control_window("minimize", "notepad")

    assert result.status == "handled"
    assert result.message == "Minimized Notepad."
    assert calls == [("minimize", 100)]


def test_close_reports_success_only_after_window_disappears(monkeypatch):
    exists = iter([True, False, False])
    monkeypatch.setattr(windows_window_control.sys, "platform", "win32")
    monkeypatch.setattr(
        windows_window_control,
        "_list_windows",
        lambda: [WindowInfo(100, "Untitled - Notepad", process_id=123)],
    )
    monkeypatch.setattr(windows_window_control, "_apply_action", lambda *_args: None)
    monkeypatch.setattr(
        windows_window_control, "_window_exists", lambda _handle: next(exists)
    )
    monkeypatch.setattr(windows_window_control.time, "sleep", lambda _seconds: None)

    result = control_window("close", "notepad")

    assert result.status == "handled"
    assert result.message == "Closed Notepad."


def test_close_does_not_claim_success_while_window_remains(monkeypatch):
    monkeypatch.setattr(windows_window_control.sys, "platform", "win32")
    monkeypatch.setattr(
        windows_window_control,
        "_list_windows",
        lambda: [WindowInfo(100, "Untitled - Notepad")],
    )
    monkeypatch.setattr(windows_window_control, "_apply_action", lambda *_args: None)
    monkeypatch.setattr(windows_window_control, "_window_exists", lambda _handle: True)
    monkeypatch.setattr(windows_window_control.time, "sleep", lambda _seconds: None)
    ticks = iter([0.0, 2.0])
    monkeypatch.setattr(
        windows_window_control.time, "monotonic", lambda: next(ticks, 2.0)
    )

    result = control_window("close", "notepad")

    assert result.status == "error"
    assert "did not close" in result.message
    assert "Asked to close" not in result.message


def test_close_detects_verified_notepad_unsaved_dialog(monkeypatch):
    dialog = windows_window_control.DialogInfo(
        200,
        "Notepad",
        123,
        100,
        "notepad_unsaved",
    )
    monkeypatch.setattr(windows_window_control.sys, "platform", "win32")
    monkeypatch.setattr(
        windows_window_control,
        "_list_windows",
        lambda: [WindowInfo(100, "Untitled - Notepad", "notepad", 123)],
    )
    monkeypatch.setattr(windows_window_control, "_apply_action", lambda *_args: None)
    monkeypatch.setattr(
        windows_window_control,
        "_wait_for_window_close_or_dialog",
        lambda _window, _timeout: (False, dialog),
    )

    result = control_window("close", "notepad")

    assert result.status == "dialog_pending"
    assert result.dialog == dialog
    assert result.message == (
        "Notepad has unsaved changes. Save, don't save, or cancel?"
    )


def test_unrelated_or_wrong_pid_modal_is_not_recognized(monkeypatch):
    target = WindowInfo(100, "Untitled - Notepad", "notepad", 123)
    monkeypatch.setattr(
        windows_window_control,
        "_list_windows",
        lambda: [
            WindowInfo(200, "Delete File", process_id=123),
            WindowInfo(300, "Notepad", process_id=999),
        ],
    )
    monkeypatch.setattr(
        windows_window_control, "_get_owner_window", lambda _handle: 100
    )
    monkeypatch.setattr(windows_window_control, "_get_root_owner", lambda _handle: 100)
    monkeypatch.setattr(
        windows_window_control,
        "_list_dialog_controls",
        lambda _handle: [
            windows_window_control.DialogControl(1, "Delete"),
            windows_window_control.DialogControl(2, "Cancel"),
        ],
    )
    monkeypatch.setattr(
        windows_window_control, "_get_window_class", lambda _handle: "#32770"
    )

    assert windows_window_control.find_owned_notepad_dialog(target) is None


def test_same_hwnd_notepad_content_dialog_is_recognized_by_exact_labels(
    monkeypatch,
):
    target = WindowInfo(100, "Untitled - Notepad", "notepad", 123)
    monkeypatch.setattr(windows_window_control, "_list_windows", lambda: [])
    monkeypatch.setattr(
        windows_window_control,
        "_all_dialog_controls",
        lambda _handle, _pid: [
            windows_window_control.DialogControl(0, "Save"),
            windows_window_control.DialogControl(0, "Don't Save"),
            windows_window_control.DialogControl(0, "Cancel"),
        ],
    )
    monkeypatch.setattr(
        windows_window_control,
        "_get_window_class",
        lambda _handle: "ApplicationFrameWindow",
    )

    result = windows_window_control.find_owned_notepad_dialog(target)

    assert result is not None
    assert result.handle == target.handle
    assert result.owner_handle == target.handle
    assert result.process_id == target.process_id
    assert result.kind == "notepad_unsaved"


def test_dialog_choice_rejects_wrong_owner_before_click(monkeypatch):
    target = WindowInfo(100, "Untitled - Notepad", "notepad", 123)
    dialog = windows_window_control.DialogInfo(
        200,
        "Notepad",
        123,
        999,
        "notepad_unsaved",
        (windows_window_control.DialogControl(201, "Don't Save"),),
    )
    monkeypatch.setattr(
        windows_window_control, "verify_dialog_identity", lambda *_args: False
    )

    assert (
        windows_window_control.invoke_dialog_choice(dialog, target, "discard") is False
    )


def test_uia_dialog_invocation_ignores_duplicate_text_label(monkeypatch):
    class Pattern:
        def QueryInterface(self, _interface):
            return self

        def Invoke(self):
            invoked.append(True)

    class Element:
        def __init__(self, name, control_type):
            self.CurrentProcessId = 123
            self.CurrentControlType = control_type
            self.CurrentName = name

        def GetCurrentPattern(self, _pattern_id):
            return Pattern()

    class Elements:
        def __init__(self):
            self.values = [
                Element("Cancel", 50000),
                Element("Cancel", 50020),
            ]
            self.Length = len(self.values)

        def GetElement(self, index):
            return self.values[index]

    class Root:
        def FindAll(self, _scope, _condition):
            return Elements()

    class Automation:
        def ElementFromHandle(self, _handle):
            return Root()

        def CreateTrueCondition(self):
            return object()

    class Module:
        IUIAutomationInvokePattern = object()

    invoked: list[bool] = []
    monkeypatch.setattr(
        windows_window_control,
        "_uia",
        lambda: (Automation(), Module()),
    )

    assert windows_window_control._invoke_uia_labeled_control(100, 123, {"cancel"})
    assert invoked == [True]


def test_modern_notepad_close_succeeds_when_only_selected_document_disappears(
    monkeypatch,
):
    window = WindowInfo(
        100,
        "Notes - Notepad",
        "notepad",
        123,
        "doc-2",
        "Notes",
    )
    monkeypatch.setattr(
        windows_window_control,
        "_request_notepad_document_close",
        lambda _window: True,
    )
    monkeypatch.setattr(
        windows_window_control,
        "_wait_for_close_outcome",
        lambda _window, _timeout: ("closed", None),
    )

    result = windows_window_control.control_window_info("close", window)

    assert result.status == "handled"
    assert result.message == "Closed Notepad."


def test_modern_notepad_close_reports_target_lost_when_selected_tab_changes(
    monkeypatch,
):
    window = WindowInfo(
        100,
        "Notes - Notepad",
        "notepad",
        123,
        "doc-2",
        "Notes",
    )
    monkeypatch.setattr(
        windows_window_control,
        "_request_notepad_document_close",
        lambda _window: True,
    )
    monkeypatch.setattr(
        windows_window_control,
        "_wait_for_close_outcome",
        lambda _window, _timeout: ("target_lost", None),
    )

    result = windows_window_control.control_window_info("close", window)

    assert result.status == "target_lost"
    assert "document changed" in result.message


def test_create_new_notepad_document_uses_verified_add_tab_control(monkeypatch):
    window = WindowInfo(100, "Existing - Notepad", "notepad", 123)
    document = windows_window_control.NotepadDocumentInfo(
        "doc-new", "Untitled", False, True, 1
    )
    target = windows_window_control.NotepadDocumentTarget(window, document)
    invoked: list[tuple[int, int, set[str]]] = []
    monkeypatch.setattr(
        windows_window_control, "_matching_windows", lambda _target: [window]
    )
    monkeypatch.setattr(
        windows_window_control, "snapshot_notepad_documents", lambda: ()
    )
    monkeypatch.setattr(windows_window_control, "_apply_action", lambda *_args: None)
    monkeypatch.setattr(
        windows_window_control,
        "_invoke_uia_labeled_control",
        lambda hwnd, pid, labels: invoked.append((hwnd, pid, labels)) or True,
    )
    monkeypatch.setattr(
        windows_window_control,
        "wait_for_new_notepad_document",
        lambda _before: target,
    )

    status, created = windows_window_control.create_new_notepad_document()

    assert status == "created"
    assert created == target
    assert invoked == [(100, 123, {"add new tab"})]
