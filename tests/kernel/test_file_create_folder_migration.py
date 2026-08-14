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
from grandpa.kernel.compat import build_file_compatibility_kernel
from grandpa.kernel.errors import ToolArgumentValidationError
from grandpa.kernel.files import CreateFolderExecutor, CreateFolderToolDefinition
from grandpa.kernel.models import (
    AssistantRequest,
    AssistantSource,
    ExecutionAuthorization,
    PlannedAction,
    PolicyDecision,
    PolicyOutcome,
    ResponseStatus,
    RiskLevel,
    VerificationResult,
    VerificationSpec,
    VerificationStatus,
    action_digest,
)


def _legacy_create(command: str, root: Path) -> FileOperationResult:
    action = FileParser().parse(command)
    assert action is not None and action.action == "create_folder"
    return FileExecutor(roots=(root,)).execute(action)


def _assert_parity(actual: FileOperationResult, expected: FileOperationResult) -> None:
    assert actual.status == expected.status
    assert actual.message == expected.message
    assert actual.action == expected.action
    assert actual.path == expected.path
    assert actual.destination == expected.destination
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
    assert list(inspect.signature(FileAutomation).parameters) == [
        "roots",
        "parser",
        "executor",
        "opener",
    ]
    assert list(inspect.signature(FileAutomation.handle).parameters) == [
        "self",
        "text",
        "confirm",
    ]
    assert list(inspect.signature(handle_file_automation).parameters) == [
        "text",
        "roots",
        "confirm",
        "opener",
    ]


@pytest.mark.parametrize(
    "command",
    (
        "Create folder Alpha",
        "Make folder Alpha",
        "Create a folder Alpha",
        "Make a folder called Alpha",
    ),
)
def test_create_folder_parser_forms_and_result_match_legacy(tmp_path, command):
    target = tmp_path / "alpha"
    expected = _legacy_create(command, tmp_path)
    target.rmdir()

    actual = FileAutomation(roots=(tmp_path,)).handle(command)

    _assert_parity(actual, expected)


def test_nested_folder_creation_matches_legacy(tmp_path):
    target = tmp_path / "parent" / "child" / "leaf"
    expected = _legacy_create("Create folder parent/child/leaf", tmp_path)
    target.rmdir()
    target.parent.rmdir()
    target.parent.parent.rmdir()

    actual = FileAutomation(roots=(tmp_path,)).handle(
        "Create folder parent/child/leaf"
    )

    _assert_parity(actual, expected)


@pytest.mark.parametrize("target_kind", ("directory", "file"))
def test_existing_target_semantics_match_legacy(tmp_path, target_kind):
    target = tmp_path / "existing"
    if target_kind == "directory":
        target.mkdir()
    else:
        target.write_text("unchanged", encoding="utf-8")

    expected = _legacy_create("Create folder existing", tmp_path)
    actual = FileAutomation(roots=(tmp_path,)).handle("Create folder existing")

    _assert_parity(actual, expected)
    assert actual.status == "needs_confirmation"


def test_create_folder_returns_structured_mutation_evidence(tmp_path):
    kernel = build_file_compatibility_kernel(roots=(tmp_path,))

    response = kernel.handle(
        AssistantRequest.create(
            session_id="create-structure",
            source=AssistantSource.SDK,
            text="Create folder reports",
        )
    )

    data = response.actions[0].data
    assert response.status is ResponseStatus.COMPLETED
    assert data == {
        "outcome": "created",
        "path": str((tmp_path / "reports").resolve()),
        "newly_created": True,
        "previously_existed": False,
        "created_chain": [str((tmp_path / "reports").resolve())],
    }


def test_create_folder_uses_complete_kernel_lifecycle(tmp_path):
    reset_event_bus()
    bus = get_event_bus(record_history=True)

    result = FileAutomation(roots=(tmp_path,)).handle("Create folder reports")

    audits = [event.data["kernel_audit"] for event in bus.history]
    assert result.status == "handled"
    assert audits[2]["redacted_payload"]["tool_name"] == "files.create_folder"
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
    assert audits[3]["redacted_payload"]["risk"] == "medium"
    assert "confirmation_required" not in [audit["stage"] for audit in audits]
    reset_event_bus()


def test_policy_and_authorization_precede_single_execution(tmp_path, monkeypatch):
    calls: list[str] = []
    authorization = None
    original_policy = kernel_files.FileCompatibilityPolicy.evaluate
    original_execute = kernel_files.CreateFolderExecutor.execute
    original_verify = kernel_files.CreateFolderVerifier.verify

    def evaluate(self, *args, **kwargs):
        calls.append("policy")
        return original_policy(self, *args, **kwargs)

    def execute(self, *args, **kwargs):
        nonlocal authorization
        calls.append("execute")
        authorization = kwargs["authorization"] if kwargs else args[4]
        return original_execute(self, *args, **kwargs)

    def verify(self, *args, **kwargs):
        calls.append("verify")
        return original_verify(self, *args, **kwargs)

    monkeypatch.setattr(kernel_files.FileCompatibilityPolicy, "evaluate", evaluate)
    monkeypatch.setattr(kernel_files.CreateFolderExecutor, "execute", execute)
    monkeypatch.setattr(kernel_files.CreateFolderVerifier, "verify", verify)

    result = FileAutomation(roots=(tmp_path,)).handle("Create folder reports")

    assert result.status == "handled"
    assert calls == ["policy", "execute", "verify"]
    assert isinstance(authorization, ExecutionAuthorization)
    assert authorization.decision.outcome is PolicyOutcome.ALLOW
    assert authorization.decision.risk is RiskLevel.MEDIUM


def test_action_digest_binds_request_tool_and_canonical_target(tmp_path):
    request = AssistantRequest(
        request_id="request",
        session_id="session",
        source=AssistantSource.SDK,
        text="Create folder A",
    )
    tool = CreateFolderToolDefinition()
    first_args = tool.validate_arguments(
        {"path": "FolderA", "roots": [str(tmp_path)]}
    )
    second_args = tool.validate_arguments(
        {"path": "FolderB", "roots": [str(tmp_path)]}
    )
    first_action = PlannedAction(
        action_id="action",
        tool_name="files.create_folder",
        arguments={"path": "FolderA", "roots": [str(tmp_path)]},
        verification=VerificationSpec("directory_created"),
    )
    changed_tool = PlannedAction(
        action_id="action",
        tool_name="files.stat_path",
        arguments=first_action.arguments,
        verification=VerificationSpec("path_metadata"),
    )

    first = action_digest(request, first_action, first_args)

    assert first == action_digest(request, first_action, first_args)
    assert first != action_digest(request, first_action, second_args)
    assert first != action_digest(request, changed_tool, first_args)


def test_create_folder_does_not_reenter_legacy_executor(tmp_path, monkeypatch):
    automation = FileAutomation(roots=(tmp_path,))

    def recursive_call(*args, **kwargs):
        raise AssertionError("legacy create-folder executor must not run")

    monkeypatch.setattr(automation.executor, "execute", recursive_call)

    result = automation.handle("Create folder reports")

    assert result.status == "handled"


def test_injected_executor_remains_create_folder_rollback_path(tmp_path):
    class RecordingExecutor:
        roots = (tmp_path,)

        def __init__(self):
            self.calls = 0

        def execute(self, action, *, confirm=None):
            self.calls += 1
            return FileOperationResult("handled", "injected create", action)

    executor = RecordingExecutor()
    result = FileAutomation(executor=executor).handle("Create folder reports")

    assert result.message == "injected create"
    assert executor.calls == 1


def test_only_the_requested_directory_chain_is_created(tmp_path):
    preserved = tmp_path / "preserved.txt"
    preserved.write_text("unchanged", encoding="utf-8")
    before = _snapshot(tmp_path)

    result = FileAutomation(roots=(tmp_path,)).handle(
        "Create folder parent/child/leaf"
    )

    after = _snapshot(tmp_path)
    assert result.status == "handled"
    assert after == {
        **before,
        "parent": (True, None),
        "parent/child": (True, None),
        "parent/child/leaf": (True, None),
    }


def test_repeated_request_is_idempotent_and_does_not_mutate_again(tmp_path):
    automation = FileAutomation(roots=(tmp_path,))
    first = automation.handle("Create folder reports")
    before_repeat = _snapshot(tmp_path)

    repeated = automation.handle("Create folder reports")

    assert first.status == "handled"
    assert repeated.status == "needs_confirmation"
    assert repeated.requires_confirmation is True
    assert _snapshot(tmp_path) == before_repeat


@pytest.mark.parametrize(
    "arguments",
    (
        {},
        {"path": 1, "roots": ["C:/safe"]},
        {"path": "reports", "roots": "C:/safe"},
        {"path": "reports", "roots": ["C:/safe"], "extra": True},
    ),
)
def test_create_folder_schema_rejects_invalid_arguments(arguments):
    with pytest.raises(ToolArgumentValidationError):
        CreateFolderToolDefinition().validate_arguments(arguments)


@pytest.mark.parametrize("command", ("Create folder ../escape", "Create folder .ssh"))
def test_traversal_and_protected_paths_are_blocked(tmp_path, command):
    result = FileAutomation(roots=(tmp_path,)).handle(command)

    assert result.status == "blocked"
    assert not (tmp_path.parent / "escape").exists()
    assert not (tmp_path / ".ssh").exists()


def test_absolute_path_outside_validated_root_is_blocked(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"

    result = FileAutomation(roots=(root,)).handle(f"Create folder {outside}")

    assert result.status == "blocked"
    assert not outside.exists()


def test_symlink_escape_is_blocked_when_supported(tmp_path):
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    link = root / "link"
    root.mkdir()
    outside.mkdir()
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlinks are unavailable: {exc}")

    result = FileAutomation(roots=(root,)).handle("Create folder link/escaped")

    assert result.status == "blocked"
    assert not (outside / "escaped").exists()


def test_parent_file_is_rejected_before_execution(tmp_path, monkeypatch):
    parent = tmp_path / "parent"
    parent.write_text("unchanged", encoding="utf-8")
    calls = 0

    def execute(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("executor must not run")

    monkeypatch.setattr(CreateFolderExecutor, "execute", execute)

    result = FileAutomation(roots=(tmp_path,)).handle(
        "Create folder parent/child"
    )

    assert result.status == "error"
    assert "parent path is not a directory" in result.message.lower()
    assert calls == 0


def test_permission_error_is_translated_without_partial_success(tmp_path, monkeypatch):
    def denied(path):
        raise PermissionError("denied")

    monkeypatch.setattr(kernel_files, "_mkdir", denied)

    result = FileAutomation(roots=(tmp_path,)).handle("Create folder reports")

    assert result.status == "error"
    assert result.message == "I could not complete that file action: denied"
    assert result.error == "PermissionError"
    assert not (tmp_path / "reports").exists()


def test_policy_block_and_exception_prevent_creation(tmp_path, monkeypatch):
    calls = 0

    def blocked(self, request, context, action, action_digest):
        return PolicyDecision(
            PolicyOutcome.BLOCK,
            RiskLevel.HIGH,
            "Blocked for test.",
            action_digest,
        )

    def execute(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("executor must not run")

    monkeypatch.setattr(kernel_files.FileCompatibilityPolicy, "evaluate", blocked)
    monkeypatch.setattr(CreateFolderExecutor, "execute", execute)
    blocked_result = FileAutomation(roots=(tmp_path,)).handle(
        "Create folder blocked"
    )

    def failed_policy(self, *args, **kwargs):
        raise RuntimeError("policy unavailable")

    monkeypatch.setattr(
        kernel_files.FileCompatibilityPolicy, "evaluate", failed_policy
    )
    failed_result = FileAutomation(roots=(tmp_path,)).handle(
        "Create folder failed"
    )

    assert blocked_result.status == "error"
    assert failed_result.status == "error"
    assert calls == 0
    assert not (tmp_path / "blocked").exists()
    assert not (tmp_path / "failed").exists()


def test_audit_failure_before_execution_prevents_creation(tmp_path, monkeypatch):
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
    monkeypatch.setattr(CreateFolderExecutor, "execute", execute)

    result = FileAutomation(roots=(tmp_path,)).handle("Create folder reports")

    assert result.status == "error"
    assert calls == 0
    assert not (tmp_path / "reports").exists()
    reset_event_bus()


def test_executor_exception_fails_closed(tmp_path, monkeypatch):
    def fail(self, *args, **kwargs):
        raise RuntimeError("internal detail")

    monkeypatch.setattr(CreateFolderExecutor, "execute", fail)

    result = FileAutomation(roots=(tmp_path,)).handle("Create folder reports")

    assert result.status == "error"
    assert result.message == "The tool could not complete the action."
    assert "internal detail" not in result.message
    assert not (tmp_path / "reports").exists()


def test_verification_failure_does_not_claim_success_or_delete_target(
    tmp_path, monkeypatch
):
    def fail(self, *args, **kwargs):
        return VerificationResult(
            VerificationStatus.FAILED,
            "Independent folder verification failed.",
        )

    monkeypatch.setattr(kernel_files.CreateFolderVerifier, "verify", fail)

    result = FileAutomation(roots=(tmp_path,)).handle("Create folder reports")

    assert result.status == "error"
    assert result.message == "Independent folder verification failed."
    assert (tmp_path / "reports").is_dir()


def test_verifier_rejects_unexpected_sibling_mutation(tmp_path, monkeypatch):
    original = kernel_files.CreateFolderExecutor.execute

    def execute_with_extra_sibling(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        (tmp_path / "unexpected").mkdir()
        return result

    monkeypatch.setattr(
        kernel_files.CreateFolderExecutor, "execute", execute_with_extra_sibling
    )

    result = FileAutomation(roots=(tmp_path,)).handle("Create folder reports")

    assert result.status == "error"
    assert "unexpected filesystem changes" in result.message.lower()


def test_create_folder_uses_no_shell_process(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("folder creation must not invoke a shell process")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)

    result = FileAutomation(roots=(tmp_path,)).handle("Create folder reports")

    assert result.status == "handled"
