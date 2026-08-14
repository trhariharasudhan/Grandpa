from __future__ import annotations

import inspect
import subprocess
from pathlib import Path

import pytest

from grandpa.core.events import EventType, get_event_bus, reset_event_bus
from grandpa.files.automation import FileAutomation, handle_file_automation
from grandpa.files.executor import FileExecutor
from grandpa.files.models import FileOperationResult
from grandpa.files.parser import FileParser
from grandpa.kernel import files as kernel_files
from grandpa.kernel.errors import ToolArgumentValidationError
from grandpa.kernel.files import SearchFilesExecutor, SearchFilesToolDefinition


def _legacy_search(command: str, root: Path) -> FileOperationResult:
    action = FileParser().parse(command)
    assert action is not None and action.action == "search"
    return FileExecutor(roots=(root,)).execute(action)


def _assert_parity(actual: FileOperationResult, expected: FileOperationResult) -> None:
    assert actual.status == expected.status
    assert actual.message == expected.message
    assert actual.path == expected.path
    assert actual.matches == expected.matches
    assert actual.requires_confirmation == expected.requires_confirmation
    assert actual.error == expected.error


def _snapshot(root: Path) -> dict[str, tuple[bool, bytes | None]]:
    return {
        path.relative_to(root).as_posix(): (
            path.is_dir(),
            None if path.is_dir() else path.read_bytes(),
        )
        for path in sorted(root.rglob("*"))
    }


def test_public_file_automation_signatures_remain_compatible():
    init_parameters = inspect.signature(FileAutomation).parameters
    handle_parameters = inspect.signature(FileAutomation.handle).parameters
    entry_parameters = inspect.signature(handle_file_automation).parameters

    assert list(init_parameters) == ["roots", "parser", "executor", "opener"]
    assert list(handle_parameters) == ["self", "text", "confirm"]
    assert list(entry_parameters) == ["text", "roots", "confirm", "opener"]


@pytest.mark.parametrize(
    "command",
    [
        "Find report.txt",
        "Find missing.txt",
        "Find PDF files",
        "Find files containing report",
        "Show recent PDFs",
    ],
)
def test_search_results_match_legacy_executor(tmp_path, command):
    nested = tmp_path / "Project Files"
    nested.mkdir()
    (nested / "report.txt").write_text("report", encoding="utf-8")
    (nested / "report.pdf").write_text("pdf", encoding="utf-8")

    expected = _legacy_search(command, tmp_path)
    actual = FileAutomation(roots=(tmp_path,)).handle(command)

    _assert_parity(actual, expected)


def test_latest_search_matches_legacy_path_and_message(tmp_path):
    first = tmp_path / "screenshot-old.png"
    second = tmp_path / "screenshot-new.png"
    first.write_text("old", encoding="utf-8")
    second.write_text("new", encoding="utf-8")
    first.touch()
    second.touch()

    expected = _legacy_search("Find latest screenshot", tmp_path)
    actual = FileAutomation(roots=(tmp_path,)).handle("Find latest screenshot")

    _assert_parity(actual, expected)


@pytest.mark.parametrize("name", ["path with spaces", "தமிழ்"])
def test_search_preserves_spaces_and_unicode(tmp_path, name):
    target = tmp_path / f"{name}.txt"
    target.write_text("content", encoding="utf-8")

    result = FileAutomation(roots=(tmp_path,)).handle(f"Find {name}.txt")

    assert result.status == "handled"
    assert result.matches == (target.resolve(),)


def test_search_accepts_file_as_existing_legacy_root(tmp_path):
    target = tmp_path / "single.txt"
    target.write_text("content", encoding="utf-8")

    expected = _legacy_search("Find single.txt", target)
    actual = FileAutomation(roots=(target,)).handle("Find single.txt")

    _assert_parity(actual, expected)


def test_search_routes_through_complete_kernel_lifecycle(tmp_path):
    reset_event_bus()
    bus = get_event_bus(record_history=True)
    target = tmp_path / "report.txt"
    target.write_text("report", encoding="utf-8")

    result = FileAutomation(roots=(tmp_path,)).handle("Find report.txt")

    stages = [event.data["kernel_audit"]["stage"] for event in bus.history]
    assert result.status == "handled"
    assert stages == [
        "request_received",
        "plan_created",
        "action_attempted",
        "policy_evaluated",
        "execution_started",
        "execution_finished",
        "verification_finished",
        "memory_updated",
        "request_completed",
    ]
    reset_event_bus()


def test_search_executor_and_verifier_each_run_once(tmp_path, monkeypatch):
    calls = {"execute": 0, "verify": 0}
    original_execute = kernel_files.SearchFilesExecutor.execute
    original_verify = kernel_files.SearchFilesVerifier.verify

    def execute(self, *args, **kwargs):
        calls["execute"] += 1
        return original_execute(self, *args, **kwargs)

    def verify(self, *args, **kwargs):
        calls["verify"] += 1
        return original_verify(self, *args, **kwargs)

    monkeypatch.setattr(kernel_files.SearchFilesExecutor, "execute", execute)
    monkeypatch.setattr(kernel_files.SearchFilesVerifier, "verify", verify)

    result = FileAutomation(roots=(tmp_path,)).handle("Find missing.txt")

    assert result.status == "handled"
    assert calls == {"execute": 1, "verify": 1}


def test_search_does_not_reenter_legacy_executor(tmp_path, monkeypatch):
    automation = FileAutomation(roots=(tmp_path,))

    def recursive_call(*args, **kwargs):
        raise AssertionError("legacy executor must not be called for migrated search")

    monkeypatch.setattr(automation.executor, "execute", recursive_call)

    result = automation.handle("Find missing.txt")

    assert result.status == "handled"


def test_injected_legacy_executor_remains_a_compatibility_override(tmp_path):
    class RecordingExecutor:
        roots = (tmp_path,)

        def __init__(self):
            self.calls = 0

        def execute(self, action, *, confirm=None):
            self.calls += 1
            return FileOperationResult("handled", "injected", action)

    executor = RecordingExecutor()
    automation = FileAutomation(executor=executor)

    result = automation.handle("Find report.txt")

    assert result.message == "injected"
    assert executor.calls == 1


def test_read_only_search_does_not_mutate_filesystem(tmp_path):
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "report.txt").write_text("unchanged", encoding="utf-8")
    before = _snapshot(tmp_path)

    result = FileAutomation(roots=(tmp_path,)).handle("Find report.txt")

    assert result.status == "handled"
    assert _snapshot(tmp_path) == before


def test_protected_search_root_is_rejected_before_execution(tmp_path, monkeypatch):
    protected = tmp_path / ".ssh"
    protected.mkdir()
    calls = 0
    original = SearchFilesExecutor.execute

    def execute(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        return original(self, *args, **kwargs)

    monkeypatch.setattr(SearchFilesExecutor, "execute", execute)

    result = FileAutomation(roots=(protected,)).handle("Find config")

    assert result.status == "error"
    assert "protected" in result.message.lower()
    assert calls == 0


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"query": 1, "roots": ["C:/safe"]},
        {"query": "report", "roots": "C:/safe"},
        {"query": "report", "roots": ["C:/safe"], "latest": "yes"},
        {"query": "report", "roots": ["C:/safe"], "unexpected": True},
    ],
)
def test_search_schema_rejects_invalid_arguments(arguments):
    with pytest.raises(ToolArgumentValidationError):
        SearchFilesToolDefinition().validate_arguments(arguments)


def test_policy_failure_blocks_search_execution(tmp_path, monkeypatch):
    calls = 0

    def fail_policy(self, *args, **kwargs):
        raise RuntimeError("policy unavailable")

    def execute(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("executor must not run")

    monkeypatch.setattr(kernel_files.FileReadOnlyPolicy, "evaluate", fail_policy)
    monkeypatch.setattr(kernel_files.SearchFilesExecutor, "execute", execute)

    result = FileAutomation(roots=(tmp_path,)).handle("Find report.txt")

    assert result.status == "error"
    assert calls == 0


def test_audit_failure_before_execution_blocks_search(tmp_path, monkeypatch):
    reset_event_bus()
    bus = get_event_bus(record_history=True)
    calls = 0

    def reject_execution_start(event):
        payload = event.data.get("kernel_audit", {})
        if payload.get("stage") == "execution_started":
            raise OSError("audit unavailable")

    def execute(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("executor must not run")

    bus.subscribe(EventType.TRACE_STEP, reject_execution_start)
    monkeypatch.setattr(kernel_files.SearchFilesExecutor, "execute", execute)

    result = FileAutomation(roots=(tmp_path,)).handle("Find report.txt")

    assert result.status == "error"
    assert calls == 0
    reset_event_bus()


def test_access_error_is_translated_to_legacy_result(tmp_path, monkeypatch):
    def denied(*args, **kwargs):
        raise PermissionError("denied")

    monkeypatch.setattr(kernel_files, "_find_matches", denied)

    result = FileAutomation(roots=(tmp_path,)).handle("Find report.txt")

    assert result.status == "error"
    assert result.message == "I could not complete that file action: denied"
    assert result.error == "PermissionError"


def test_search_uses_no_shell_process(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("search must not invoke a shell process")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)

    result = FileAutomation(roots=(tmp_path,)).handle("Find missing.txt")

    assert result.status == "handled"
