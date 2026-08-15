from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from grandpa.core.events import EventType, get_event_bus, reset_event_bus
from grandpa.files.automation import FileAutomation
from grandpa.files.executor import FileExecutor
from grandpa.files.models import FileOperationResult
from grandpa.files.parser import FileParser
from grandpa.kernel import files as kernel_files
from grandpa.kernel.compat import build_file_compatibility_kernel
from grandpa.kernel.errors import ToolArgumentValidationError
from grandpa.kernel.files import CopyPathExecutor, CopyPathToolDefinition
from grandpa.kernel.models import (
    AssistantContext,
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


def _legacy_copy(command: str, root: Path) -> FileOperationResult:
    action = FileParser().parse(command)
    assert action is not None and action.action == "copy"
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


def _snapshot(root: Path) -> dict[str, bytes | None]:
    return {
        path.relative_to(root).as_posix(): (
            None if path.is_dir() else path.read_bytes()
        )
        for path in sorted(root.rglob("*"))
    }


@pytest.mark.parametrize("verb", ("copy", "duplicate", "copy file"))
def test_regular_file_copy_matches_legacy_public_result(tmp_path, verb):
    source = tmp_path / "source.txt"
    destination = tmp_path / "copied.txt"
    source.write_text("same bytes", encoding="utf-8")
    command = f"{verb} {source} to {destination}"
    expected = _legacy_copy(command, tmp_path)
    destination.unlink()

    actual = FileAutomation(roots=(tmp_path,)).handle(command)

    _assert_parity(actual, expected)
    assert destination.read_bytes() == source.read_bytes()


def test_default_copy_name_matches_legacy(tmp_path):
    source = tmp_path / "report.txt"
    source.write_text("report", encoding="utf-8")
    command = f"copy {source}"
    expected = _legacy_copy(command, tmp_path)
    (tmp_path / "report copy.txt").unlink()

    actual = FileAutomation(roots=(tmp_path,)).handle(command)

    _assert_parity(actual, expected)


def test_copy_to_existing_directory_matches_legacy(tmp_path):
    source = tmp_path / "source.txt"
    target_directory = tmp_path / "target"
    source.write_text("content", encoding="utf-8")
    target_directory.mkdir()
    command = f"copy {source} to {target_directory}"
    expected = _legacy_copy(command, tmp_path)
    (target_directory / source.name).unlink()

    actual = FileAutomation(roots=(tmp_path,)).handle(command)

    _assert_parity(actual, expected)


def test_copy_returns_structured_result_and_preserves_source(tmp_path):
    source = tmp_path / "source.bin"
    destination = tmp_path / "destination.bin"
    source.write_bytes(b"\x00phase-five\xff")
    before = source.stat()
    kernel = build_file_compatibility_kernel(roots=(tmp_path,))

    response = kernel.handle(
        AssistantRequest.create(
            session_id="copy-structure",
            source=AssistantSource.SDK,
            text=f"copy {source} to {destination}",
        )
    )

    assert response.status is ResponseStatus.COMPLETED
    assert response.actions[0].data == {
        "outcome": "copied",
        "source": str(source.resolve()),
        "destination": str(destination.resolve()),
    }
    assert source.read_bytes() == destination.read_bytes()
    assert source.stat().st_mtime_ns == before.st_mtime_ns


def test_copy_action_digest_binds_tool_source_destination_and_request(tmp_path):
    first_source = tmp_path / "first.txt"
    second_source = tmp_path / "second.txt"
    first_source.write_text("first", encoding="utf-8")
    second_source.write_text("second", encoding="utf-8")
    tool = CopyPathToolDefinition()
    request = AssistantRequest(
        request_id="request",
        session_id="session",
        source=AssistantSource.SDK,
        text="copy first.txt to destination.txt",
    )
    first_raw = {
        "source": str(first_source),
        "destination": str(tmp_path / "destination.txt"),
        "roots": [str(tmp_path)],
    }
    second_source_raw = {**first_raw, "source": str(second_source)}
    second_destination_raw = {
        **first_raw,
        "destination": str(tmp_path / "other.txt"),
    }
    first_action = PlannedAction(
        action_id="action",
        tool_name="files.copy_path",
        arguments=first_raw,
        verification=VerificationSpec("file_copied"),
    )
    changed_tool = PlannedAction(
        action_id="action",
        tool_name="files.stat_path",
        arguments=first_raw,
        verification=VerificationSpec("path_metadata"),
    )
    first_args = tool.validate_arguments(first_raw)

    digest = action_digest(request, first_action, first_args)

    assert digest == action_digest(request, first_action, first_args)
    assert digest != action_digest(
        request,
        first_action,
        tool.validate_arguments(second_source_raw),
    )
    assert digest != action_digest(
        request,
        first_action,
        tool.validate_arguments(second_destination_raw),
    )
    assert digest != action_digest(request, changed_tool, first_args)


def test_copy_uses_complete_kernel_lifecycle_with_medium_allow(tmp_path):
    source = tmp_path / "source.txt"
    destination = tmp_path / "destination.txt"
    source.write_text("content", encoding="utf-8")
    reset_event_bus()
    bus = get_event_bus(record_history=True)

    result = FileAutomation(roots=(tmp_path,)).handle(f"copy {source} to {destination}")

    audits = [event.data["kernel_audit"] for event in bus.history]
    assert result.status == "handled"
    assert audits[2]["redacted_payload"]["tool_name"] == "files.copy_path"
    assert audits[3]["redacted_payload"]["risk"] == "medium"
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


def test_policy_authorization_execution_and_verification_order(tmp_path, monkeypatch):
    source = tmp_path / "source.txt"
    destination = tmp_path / "destination.txt"
    source.write_text("content", encoding="utf-8")
    calls: list[str] = []
    captured_authorization = None
    original_policy = kernel_files.FileCompatibilityPolicy.evaluate
    original_execute = kernel_files.CopyPathExecutor.execute
    original_verify = kernel_files.CopyPathVerifier.verify

    def evaluate(self, *args, **kwargs):
        calls.append("policy")
        return original_policy(self, *args, **kwargs)

    def execute(self, *args, **kwargs):
        nonlocal captured_authorization
        calls.append("execute")
        captured_authorization = kwargs.get("authorization", args[4])
        return original_execute(self, *args, **kwargs)

    def verify(self, *args, **kwargs):
        calls.append("verify")
        return original_verify(self, *args, **kwargs)

    monkeypatch.setattr(kernel_files.FileCompatibilityPolicy, "evaluate", evaluate)
    monkeypatch.setattr(kernel_files.CopyPathExecutor, "execute", execute)
    monkeypatch.setattr(kernel_files.CopyPathVerifier, "verify", verify)

    result = FileAutomation(roots=(tmp_path,)).handle(f"copy {source} to {destination}")

    assert result.status == "handled"
    assert calls == ["policy", "execute", "verify"]
    assert isinstance(captured_authorization, ExecutionAuthorization)
    assert captured_authorization.decision.outcome is PolicyOutcome.ALLOW
    assert captured_authorization.decision.risk is RiskLevel.MEDIUM


def test_executor_rejects_missing_authorization_digest(tmp_path):
    source = tmp_path / "source.txt"
    destination = tmp_path / "destination.txt"
    source.write_text("content", encoding="utf-8")
    tool = CopyPathToolDefinition()
    raw_arguments = {
        "source": str(source),
        "destination": str(destination),
        "roots": [str(tmp_path)],
    }
    canonical_arguments = tool.validate_arguments(raw_arguments)
    action = PlannedAction(
        action_id="action",
        tool_name="files.copy_path",
        arguments=canonical_arguments,
        verification=VerificationSpec("file_copied"),
    )
    authorization = ExecutionAuthorization(
        decision=PolicyDecision(
            PolicyOutcome.ALLOW,
            RiskLevel.MEDIUM,
            "allowed",
            "",
        )
    )

    with pytest.raises(kernel_files.SecurityInvariantError):
        CopyPathExecutor().execute(
            tool,
            action,
            canonical_arguments,
            AssistantContext(),
            authorization,
        )
    assert not destination.exists()


def test_copy_does_not_reenter_legacy_executor(tmp_path, monkeypatch):
    source = tmp_path / "source.txt"
    source.write_text("content", encoding="utf-8")
    automation = FileAutomation(roots=(tmp_path,))

    def recursive_call(*args, **kwargs):
        raise AssertionError("legacy copy executor must not run")

    monkeypatch.setattr(automation.executor, "execute", recursive_call)

    result = automation.handle(f"copy {source} to {tmp_path / 'copy.txt'}")

    assert result.status == "handled"


def test_injected_executor_remains_copy_rollback_path(tmp_path):
    class RecordingExecutor:
        roots = (tmp_path,)

        def __init__(self):
            self.calls = 0

        def execute(self, action, *, confirm=None):
            self.calls += 1
            return FileOperationResult("handled", "injected copy", action)

    executor = RecordingExecutor()
    result = FileAutomation(executor=executor).handle("copy source to destination")

    assert result.message == "injected copy"
    assert executor.calls == 1


def test_existing_destination_preserves_legacy_confirmation_without_execution(
    tmp_path, monkeypatch
):
    source = tmp_path / "source.txt"
    destination = tmp_path / "destination.txt"
    source.write_text("source", encoding="utf-8")
    destination.write_text("preserve", encoding="utf-8")
    expected = _legacy_copy(f"copy {source} to {destination}", tmp_path)
    calls = 0

    def execute(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("existing destinations must not reach copy execution")

    monkeypatch.setattr(CopyPathExecutor, "execute", execute)
    reset_event_bus()
    bus = get_event_bus(record_history=True)

    actual = FileAutomation(roots=(tmp_path,)).handle(f"copy {source} to {destination}")

    _assert_parity(actual, expected)
    assert calls == 0
    assert destination.read_text(encoding="utf-8") == "preserve"
    stages = [event.data["kernel_audit"]["stage"] for event in bus.history]
    assert "execution_started" not in stages
    assert "confirmation_required" not in stages
    reset_event_bus()


def test_folder_copy_is_recognized_but_safely_deferred(tmp_path):
    source = tmp_path / "folder"
    destination = tmp_path / "folder-copy"
    source.mkdir()
    (source / "file.txt").write_text("unchanged", encoding="utf-8")

    result = FileAutomation(roots=(tmp_path,)).handle(
        f"copy folder {source} to {destination}"
    )

    assert result.status == "unsupported"
    assert "not supported" in result.message.lower()
    assert not destination.exists()


def test_missing_destination_parent_is_not_created(tmp_path):
    source = tmp_path / "source.txt"
    destination = tmp_path / "missing" / "copy.txt"
    source.write_text("unchanged", encoding="utf-8")

    result = FileAutomation(roots=(tmp_path,)).handle(f"copy {source} to {destination}")

    assert result.status == "unsupported"
    assert "create it before copying" in result.message.lower()
    assert not destination.parent.exists()


@pytest.mark.parametrize(
    "arguments",
    (
        {},
        {"source": 1, "destination": "copy", "roots": ["C:/safe"]},
        {"source": "file", "destination": 1, "roots": ["C:/safe"]},
        {"source": "file", "destination": "copy", "roots": "C:/safe"},
        {
            "source": "file",
            "destination": "copy",
            "roots": ["C:/safe"],
            "overwrite": True,
        },
    ),
)
def test_copy_schema_rejects_invalid_arguments(arguments):
    with pytest.raises(ToolArgumentValidationError):
        CopyPathToolDefinition().validate_arguments(arguments)


def test_missing_and_ambiguous_sources_preserve_legacy_results(tmp_path):
    first = tmp_path / "first" / "report.txt"
    second = tmp_path / "second" / "report.txt"
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_text("first", encoding="utf-8")
    second.write_text("second", encoding="utf-8")

    missing = FileAutomation(roots=(tmp_path,)).handle("copy missing.txt")
    ambiguous = FileAutomation(roots=(tmp_path,)).handle("copy report.txt")

    assert missing.status == "error"
    assert missing.error == "missing_path"
    assert ambiguous.status == "ambiguous"
    assert ambiguous.matches == (first.resolve(), second.resolve())


def test_traversal_protected_and_outside_paths_are_blocked(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    source = root / "source.txt"
    source.write_text("unchanged", encoding="utf-8")
    outside = tmp_path / "outside.txt"

    traversal = FileAutomation(roots=(root,)).handle(f"copy {source} to ../outside.txt")
    protected = FileAutomation(roots=(root,)).handle(
        f"copy {source} to {root / '.ssh' / 'copy.txt'}"
    )
    outside_result = FileAutomation(roots=(root,)).handle(f"copy {source} to {outside}")

    assert traversal.status == "blocked"
    assert protected.status == "blocked"
    assert outside_result.status == "blocked"
    assert not outside.exists()


def test_symlink_destination_escape_is_blocked_when_supported(tmp_path):
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    source = root / "source.txt"
    source.write_text("unchanged", encoding="utf-8")
    link = root / "link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlinks are unavailable: {exc}")

    result = FileAutomation(roots=(root,)).handle(
        f"copy {source} to {link / 'copy.txt'}"
    )

    assert result.status == "blocked"
    assert not (outside / "copy.txt").exists()


def test_policy_block_wrong_digest_and_audit_failure_prevent_copy(
    tmp_path, monkeypatch
):
    source = tmp_path / "source.txt"
    source.write_text("unchanged", encoding="utf-8")
    blocked_destination = tmp_path / "blocked.txt"

    def blocked(self, request, context, action, action_digest):
        return PolicyDecision(
            PolicyOutcome.BLOCK,
            RiskLevel.HIGH,
            "Blocked for test.",
            action_digest,
        )

    monkeypatch.setattr(kernel_files.FileCompatibilityPolicy, "evaluate", blocked)
    result = FileAutomation(roots=(tmp_path,)).handle(
        f"copy {source} to {blocked_destination}"
    )
    assert result.status == "blocked"
    assert not blocked_destination.exists()

    def wrong_digest(self, request, context, action, action_digest):
        return PolicyDecision(
            PolicyOutcome.ALLOW,
            RiskLevel.MEDIUM,
            "Allowed for test.",
            "wrong-digest",
        )

    monkeypatch.setattr(kernel_files.FileCompatibilityPolicy, "evaluate", wrong_digest)
    wrong_destination = tmp_path / "wrong.txt"
    result = FileAutomation(roots=(tmp_path,)).handle(
        f"copy {source} to {wrong_destination}"
    )
    assert result.status == "error"
    assert not wrong_destination.exists()

    monkeypatch.undo()
    reset_event_bus()


def test_policy_exception_prevents_copy(tmp_path, monkeypatch):
    source = tmp_path / "source.txt"
    destination = tmp_path / "destination.txt"
    source.write_text("unchanged", encoding="utf-8")

    def failed_policy(self, *args, **kwargs):
        raise RuntimeError("policy unavailable")

    monkeypatch.setattr(kernel_files.FileCompatibilityPolicy, "evaluate", failed_policy)

    result = FileAutomation(roots=(tmp_path,)).handle(f"copy {source} to {destination}")

    assert result.status == "error"
    assert "policy unavailable" not in result.message
    assert not destination.exists()
    bus = get_event_bus(record_history=True)

    def reject_execution_start(event):
        if event.data.get("kernel_audit", {}).get("stage") == "execution_started":
            raise OSError("audit unavailable")

    bus.subscribe(EventType.TRACE_STEP, reject_execution_start)
    audit_destination = tmp_path / "audit.txt"
    result = FileAutomation(roots=(tmp_path,)).handle(
        f"copy {source} to {audit_destination}"
    )
    assert result.status == "error"
    assert not audit_destination.exists()
    reset_event_bus()


def test_permission_error_is_translated_without_false_success(tmp_path, monkeypatch):
    source = tmp_path / "source.txt"
    destination = tmp_path / "destination.txt"
    source.write_text("unchanged", encoding="utf-8")

    def denied(*args, **kwargs):
        raise PermissionError("denied")

    monkeypatch.setattr(shutil, "copy2", denied)

    result = FileAutomation(roots=(tmp_path,)).handle(f"copy {source} to {destination}")

    assert result.status == "error"
    assert result.error == "PermissionError"
    assert "denied" in result.message
    assert not destination.exists()


def test_verifier_rejects_tampering_and_unrelated_mutation(tmp_path, monkeypatch):
    source = tmp_path / "source.txt"
    destination = tmp_path / "destination.txt"
    source.write_text("source", encoding="utf-8")
    original = kernel_files.CopyPathExecutor.execute

    def execute_with_tampering(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        destination.write_text("tampered", encoding="utf-8")
        (tmp_path / "unexpected.txt").write_text("unexpected", encoding="utf-8")
        return result

    monkeypatch.setattr(
        kernel_files.CopyPathExecutor, "execute", execute_with_tampering
    )

    result = FileAutomation(roots=(tmp_path,)).handle(f"copy {source} to {destination}")

    assert result.status == "error"
    assert "independently verified" in result.message.lower()


def test_verifier_detects_concurrent_source_change(tmp_path, monkeypatch):
    source = tmp_path / "source.txt"
    destination = tmp_path / "destination.txt"
    source.write_text("source", encoding="utf-8")
    original = kernel_files.CopyPathExecutor.execute

    def execute_then_change_source(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        source.write_text("changed after copy", encoding="utf-8")
        return result

    monkeypatch.setattr(
        kernel_files.CopyPathExecutor, "execute", execute_then_change_source
    )

    result = FileAutomation(roots=(tmp_path,)).handle(f"copy {source} to {destination}")

    assert result.status == "error"
    assert result.error == "verification_failed"
    assert destination.exists()


def test_verification_failure_never_claims_success(tmp_path, monkeypatch):
    source = tmp_path / "source.txt"
    destination = tmp_path / "destination.txt"
    source.write_text("source", encoding="utf-8")

    def fail(self, *args, **kwargs):
        return VerificationResult(
            VerificationStatus.FAILED,
            "Independent copy verification failed.",
        )

    monkeypatch.setattr(kernel_files.CopyPathVerifier, "verify", fail)

    result = FileAutomation(roots=(tmp_path,)).handle(f"copy {source} to {destination}")

    assert result.status == "error"
    assert result.message == "Independent copy verification failed."
    assert destination.exists()


@pytest.mark.parametrize("size", (0, 1024, 1024 * 1024))
def test_copy_preserves_binary_content_across_sizes(tmp_path, size):
    source = tmp_path / f"source-{size}.bin"
    destination = tmp_path / f"destination-{size}.bin"
    source.write_bytes(bytes(range(256)) * (size // 256) + b"x" * (size % 256))

    result = FileAutomation(roots=(tmp_path,)).handle(f"copy {source} to {destination}")

    assert result.status == "handled"
    assert destination.read_bytes() == source.read_bytes()


def test_copy_handles_spaces_unicode_and_larger_binary_file(tmp_path):
    source = tmp_path / "source ☃ file.bin"
    destination = tmp_path / "copied ☃ file.bin"
    source.write_bytes((bytes(range(256)) * (10 * 1024 * 1024 // 256)))

    result = FileAutomation(roots=(tmp_path,)).handle(f"copy {source} to {destination}")

    assert result.status == "handled"
    assert destination.read_bytes() == source.read_bytes()


def test_copy_uses_no_shell_process(tmp_path, monkeypatch):
    source = tmp_path / "source.txt"
    source.write_text("source", encoding="utf-8")

    def forbidden(*args, **kwargs):
        raise AssertionError("file copy must not invoke a shell process")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)

    result = FileAutomation(roots=(tmp_path,)).handle(
        f"copy {source} to {tmp_path / 'destination.txt'}"
    )

    assert result.status == "handled"


def test_only_destination_file_is_added(tmp_path):
    source = tmp_path / "source.txt"
    preserved = tmp_path / "preserved.txt"
    destination = tmp_path / "destination.txt"
    source.write_text("source", encoding="utf-8")
    preserved.write_text("preserved", encoding="utf-8")
    before = _snapshot(tmp_path)

    result = FileAutomation(roots=(tmp_path,)).handle(f"copy {source} to {destination}")

    assert result.status == "handled"
    assert _snapshot(tmp_path) == {**before, "destination.txt": b"source"}
