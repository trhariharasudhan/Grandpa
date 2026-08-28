from __future__ import annotations

from pathlib import Path

import pytest

from grandpa.core.events import EventType, get_event_bus, reset_event_bus
from grandpa.files.automation import FileAutomation
from grandpa.files.executor import FileExecutor
from grandpa.files.models import FileOperationResult
from grandpa.files.parser import FileParser
from grandpa.kernel import files as kernel_files
from grandpa.kernel.compat import build_read_only_file_kernel
from grandpa.kernel.errors import ToolArgumentValidationError
from grandpa.kernel.files import StatPathExecutor, StatPathToolDefinition
from grandpa.kernel.models import (
    AssistantRequest,
    AssistantSource,
    ExecutionAuthorization,
    PolicyDecision,
    PolicyOutcome,
    ResponseStatus,
    RiskLevel,
    VerificationResult,
    VerificationStatus,
)


def _legacy_properties(command: str, root: Path) -> FileOperationResult:
    action = FileParser().parse(command)
    assert action is not None and action.action == "properties"
    return FileExecutor(roots=(root,)).execute(action)


def _assert_parity(actual: FileOperationResult, expected: FileOperationResult) -> None:
    assert actual.status == expected.status
    assert actual.message == expected.message
    assert actual.action == expected.action
    assert actual.path == expected.path
    assert actual.matches == expected.matches
    assert actual.error == expected.error


def _snapshot(root: Path) -> dict[str, tuple[bool, bytes | None]]:
    return {
        path.relative_to(root).as_posix(): (
            path.is_dir(),
            None if path.is_dir() else path.read_bytes(),
        )
        for path in sorted(root.rglob("*"))
    }


@pytest.mark.parametrize(
    ("name", "content"),
    [
        ("normal.txt", b"content"),
        ("empty.txt", b""),
        ("README", b"without extension"),
        ("large.bin", b"x" * (2 * 1024 * 1024)),
        ("path with spaces.md", b"spaces"),
        ("தமிழ்.txt", b"unicode"),
    ],
    ids=("normal", "empty", "no-extension", "large", "spaces", "unicode"),
)
def test_file_properties_match_legacy_behavior(tmp_path, name, content):
    target = tmp_path / name
    target.write_bytes(content)
    command = f"Show properties of {name}"

    expected = _legacy_properties(command, tmp_path)
    actual = FileAutomation(roots=(tmp_path,)).handle(command)

    _assert_parity(actual, expected)


def test_directory_properties_match_legacy_behavior(tmp_path):
    target = tmp_path / "Project Folder"
    target.mkdir()

    expected = _legacy_properties("Show properties of Project Folder", tmp_path)
    actual = FileAutomation(roots=(tmp_path,)).handle(
        "Show properties of Project Folder"
    )

    _assert_parity(actual, expected)


def test_in_root_symlink_properties_match_legacy_behavior(tmp_path):
    target = tmp_path / "target.txt"
    link = tmp_path / "linked.txt"
    target.write_text("linked content", encoding="utf-8")
    try:
        link.symlink_to(target)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlinks are unavailable: {exc}")

    expected = _legacy_properties("Show properties of linked.txt", tmp_path)
    actual = FileAutomation(roots=(tmp_path,)).handle("Show properties of linked.txt")

    # Legacy parity is the point of this test and is unchanged.
    _assert_parity(actual, expected)

    # The symlink above targets target.txt, a regular file, and the properties
    # reporter resolves the link before classifying: metadata.py:32 computes
    # `kind = "folder" if is_directory else (extension or "file")`, so the
    # correct kind here is "txt".
    #
    # This previously asserted "- Type: folder", which could never hold for a
    # file symlink. It went unnoticed because the assertion had never executed:
    # creating a symlink on Windows needs SeCreateSymbolicLinkPrivilege, so on
    # an unprivileged developer machine symlink_to raises WinError 1314 and the
    # test skips at the guard above. GitHub's windows-latest runner does hold
    # that privilege, so the body ran for the first time there and the bad
    # expectation surfaced. The parity assertion passed on that same run, which
    # is what confirms the reporter itself is behaving correctly.
    assert "- Type: txt" in actual.message


def test_missing_path_matches_legacy_error(tmp_path):
    expected = _legacy_properties("Show properties of missing.txt", tmp_path)
    actual = FileAutomation(roots=(tmp_path,)).handle("Show properties of missing.txt")

    _assert_parity(actual, expected)
    assert actual.action is None


def test_ambiguous_path_matches_legacy_result(tmp_path):
    for folder in (tmp_path / "one", tmp_path / "two"):
        folder.mkdir()
        (folder / "report.txt").write_text("report", encoding="utf-8")

    expected = _legacy_properties("Show properties of report.txt", tmp_path)
    actual = FileAutomation(roots=(tmp_path,)).handle("Show properties of report.txt")

    _assert_parity(actual, expected)
    assert actual.status == "ambiguous"


def test_latest_pdf_without_match_preserves_legacy_result(tmp_path):
    expected = _legacy_properties("Show properties of latest PDF", tmp_path)
    actual = FileAutomation(roots=(tmp_path,)).handle("Show properties of latest PDF")

    _assert_parity(actual, expected)
    assert actual.status == "handled"


def test_stat_path_returns_structured_metadata(tmp_path):
    target = tmp_path / "report.txt"
    target.write_text("report", encoding="utf-8")
    kernel = build_read_only_file_kernel(roots=(tmp_path,))
    request = AssistantRequest.create(
        session_id="stat-structure",
        source=AssistantSource.SDK,
        text="Show properties of report.txt",
    )

    response = kernel.handle(request)

    data = response.actions[0].data
    assert response.status is ResponseStatus.COMPLETED
    assert data["outcome"] == "resolved"
    assert data["path"] == str(target.resolve())
    assert data["name"] == "report.txt"
    assert data["type"] == "txt"
    assert data["extension"] == "txt"
    assert data["size"] == len("report")
    assert isinstance(data["created_timestamp"], float)
    assert isinstance(data["modified_timestamp"], float)


def test_properties_routes_through_complete_kernel_lifecycle(tmp_path):
    reset_event_bus()
    bus = get_event_bus(record_history=True)
    (tmp_path / "report.txt").write_text("report", encoding="utf-8")

    result = FileAutomation(roots=(tmp_path,)).handle("Show properties of report.txt")

    audits = [event.data["kernel_audit"] for event in bus.history]
    assert result.status == "handled"
    assert audits[2]["redacted_payload"]["tool_name"] == "files.stat_path"
    assert [audit["stage"] for audit in audits] == [
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


def test_stat_executor_and_verifier_run_once(tmp_path, monkeypatch):
    target = tmp_path / "report.txt"
    target.write_text("report", encoding="utf-8")
    calls = {"execute": 0, "verify": 0, "authorization": None}
    original_execute = kernel_files.StatPathExecutor.execute
    original_verify = kernel_files.StatPathVerifier.verify

    def execute(self, *args, **kwargs):
        calls["execute"] += 1
        calls["authorization"] = (
            kwargs["authorization"] if "authorization" in kwargs else args[4]
        )
        return original_execute(self, *args, **kwargs)

    def verify(self, *args, **kwargs):
        calls["verify"] += 1
        return original_verify(self, *args, **kwargs)

    monkeypatch.setattr(kernel_files.StatPathExecutor, "execute", execute)
    monkeypatch.setattr(kernel_files.StatPathVerifier, "verify", verify)

    result = FileAutomation(roots=(tmp_path,)).handle("Show properties of report.txt")

    assert result.status == "handled"
    assert calls["execute"] == 1
    assert calls["verify"] == 1
    assert isinstance(calls["authorization"], ExecutionAuthorization)


def test_properties_does_not_reenter_legacy_executor(tmp_path, monkeypatch):
    target = tmp_path / "report.txt"
    target.write_text("report", encoding="utf-8")
    automation = FileAutomation(roots=(tmp_path,))

    def recursive_call(*args, **kwargs):
        raise AssertionError("legacy properties executor must not be called")

    monkeypatch.setattr(automation.executor, "execute", recursive_call)

    result = automation.handle("Show properties of report.txt")

    assert result.status == "handled"


def test_injected_executor_remains_properties_rollback_path(tmp_path):
    class RecordingExecutor:
        roots = (tmp_path,)

        def __init__(self):
            self.calls = 0

        def execute(self, action, *, confirm=None):
            self.calls += 1
            return FileOperationResult("handled", "injected properties", action)

    executor = RecordingExecutor()
    automation = FileAutomation(executor=executor)

    result = automation.handle("Show properties of report.txt")

    assert result.message == "injected properties"
    assert executor.calls == 1


def test_properties_do_not_mutate_filesystem(tmp_path):
    target = tmp_path / "report.txt"
    target.write_text("unchanged", encoding="utf-8")
    before = _snapshot(tmp_path)

    result = FileAutomation(roots=(tmp_path,)).handle("Show properties of report.txt")

    assert result.status == "handled"
    assert _snapshot(tmp_path) == before


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"path": 1, "roots": ["C:/safe"]},
        {"path": "report", "roots": "C:/safe"},
        {"path": "report", "roots": ["C:/safe"], "extra": True},
    ],
)
def test_stat_schema_rejects_invalid_arguments(arguments):
    with pytest.raises(ToolArgumentValidationError):
        StatPathToolDefinition().validate_arguments(arguments)


def test_protected_root_blocks_stat_before_execution(tmp_path, monkeypatch):
    protected = tmp_path / ".ssh"
    protected.mkdir()
    (protected / "config").write_text("secret", encoding="utf-8")
    calls = 0

    def execute(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("executor must not run")

    monkeypatch.setattr(StatPathExecutor, "execute", execute)

    result = FileAutomation(roots=(protected,)).handle("Show properties of config")

    assert result.status == "error"
    assert "protected" in result.message.lower()
    assert calls == 0


def test_path_outside_validated_root_is_blocked(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")

    result = FileAutomation(roots=(root,)).handle(f"Show properties of {outside}")

    assert result.status == "error"
    assert "outside the allowed" in result.message.lower()


def test_access_error_translates_to_legacy_error(tmp_path, monkeypatch):
    target = tmp_path / "report.txt"
    target.write_text("report", encoding="utf-8")

    def denied(path):
        raise PermissionError("denied")

    monkeypatch.setattr(kernel_files, "_inspect_path_metadata", denied)

    result = FileAutomation(roots=(tmp_path,)).handle("Show properties of report.txt")

    assert result.status == "error"
    assert result.message == "I could not complete that file action: denied"
    assert result.error == "PermissionError"


def test_policy_block_and_exception_prevent_stat_execution(tmp_path, monkeypatch):
    target = tmp_path / "report.txt"
    target.write_text("report", encoding="utf-8")
    calls = 0

    def blocked(self, request, context, action, action_digest):
        return PolicyDecision(
            PolicyOutcome.BLOCK,
            RiskLevel.LOW,
            "Blocked for test.",
            action_digest,
        )

    def execute(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("executor must not run")

    monkeypatch.setattr(kernel_files.FileReadOnlyPolicy, "evaluate", blocked)
    monkeypatch.setattr(StatPathExecutor, "execute", execute)
    blocked_result = FileAutomation(roots=(tmp_path,)).handle(
        "Show properties of report.txt"
    )

    def failed_policy(self, *args, **kwargs):
        raise RuntimeError("policy unavailable")

    monkeypatch.setattr(kernel_files.FileReadOnlyPolicy, "evaluate", failed_policy)
    failed_result = FileAutomation(roots=(tmp_path,)).handle(
        "Show properties of report.txt"
    )

    assert blocked_result.status == "error"
    assert failed_result.status == "error"
    assert calls == 0


def test_audit_failure_blocks_stat_execution(tmp_path, monkeypatch):
    target = tmp_path / "report.txt"
    target.write_text("report", encoding="utf-8")
    reset_event_bus()
    bus = get_event_bus(record_history=True)
    calls = 0

    def reject_execution_start(event):
        if event.data.get("kernel_audit", {}).get("stage") == "execution_started":
            raise OSError("audit unavailable")

    def execute(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("executor must not run")

    bus.subscribe(EventType.TRACE_STEP, reject_execution_start)
    monkeypatch.setattr(StatPathExecutor, "execute", execute)

    result = FileAutomation(roots=(tmp_path,)).handle("Show properties of report.txt")

    assert result.status == "error"
    assert calls == 0
    reset_event_bus()


def test_executor_exception_returns_safe_legacy_error(tmp_path, monkeypatch):
    target = tmp_path / "report.txt"
    target.write_text("report", encoding="utf-8")

    def fail(self, *args, **kwargs):
        raise RuntimeError("internal detail")

    monkeypatch.setattr(StatPathExecutor, "execute", fail)

    result = FileAutomation(roots=(tmp_path,)).handle("Show properties of report.txt")

    assert result.status == "error"
    assert result.message == "The tool could not complete the action."
    assert "internal detail" not in result.message


def test_verifier_failure_is_not_translated_as_success(tmp_path, monkeypatch):
    target = tmp_path / "report.txt"
    target.write_text("report", encoding="utf-8")

    def fail(self, *args, **kwargs):
        return VerificationResult(
            VerificationStatus.FAILED,
            "Independent stat verification failed.",
        )

    monkeypatch.setattr(kernel_files.StatPathVerifier, "verify", fail)

    result = FileAutomation(roots=(tmp_path,)).handle("Show properties of report.txt")

    assert result.status == "error"
    assert result.message == "Independent stat verification failed."


def test_changed_file_fails_independent_size_verification(tmp_path, monkeypatch):
    target = tmp_path / "report.txt"
    target.write_text("before", encoding="utf-8")
    original = kernel_files.StatPathExecutor.execute

    def execute_then_change(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        target.write_text("changed and larger", encoding="utf-8")
        return result

    monkeypatch.setattr(StatPathExecutor, "execute", execute_then_change)

    result = FileAutomation(roots=(tmp_path,)).handle("Show properties of report.txt")

    assert result.status == "error"
    assert "size changed" in result.message.lower()
