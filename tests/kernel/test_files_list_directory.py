from __future__ import annotations

from pathlib import Path

import pytest

from grandpa.kernel.compat import build_list_directory_kernel
from grandpa.kernel.errors import ToolArgumentValidationError
from grandpa.kernel.files import ListDirectoryToolDefinition, ListDirectoryVerifier
from grandpa.kernel.models import (
    AssistantContext,
    AssistantRequest,
    AssistantSource,
    PlannedAction,
    ResponseStatus,
    ToolResult,
    ToolStatus,
    VerificationSpec,
    VerificationStatus,
)


def _request(path: Path, source: AssistantSource = AssistantSource.CLI):
    return AssistantRequest.create(
        session_id="files-test",
        source=source,
        text=f"List files in {path}",
    )


@pytest.mark.parametrize("directory_name", ["empty", "path with spaces", "தமிழ்"])
def test_list_directory_handles_empty_spaces_and_unicode(tmp_path, directory_name):
    directory = tmp_path / directory_name
    directory.mkdir()

    response = build_list_directory_kernel().handle(_request(directory))

    assert response.status is ResponseStatus.COMPLETED
    assert response.actions[0].data["directory"] == str(directory.resolve())
    assert response.actions[0].data["entries"] == []
    assert response.actions[0].data["count"] == 0


def test_list_directory_returns_immediate_structured_entries_without_mutation(tmp_path):
    directory = tmp_path / "project"
    directory.mkdir()
    (directory / "alpha.txt").write_text("do not read or change", encoding="utf-8")
    (directory / "nested").mkdir()
    before = {path.name: path.stat().st_mtime_ns for path in directory.iterdir()}

    response = build_list_directory_kernel().handle(_request(directory))
    after = {path.name: path.stat().st_mtime_ns for path in directory.iterdir()}

    assert response.status is ResponseStatus.COMPLETED
    assert response.actions[0].data["entries"] == [
        {
            "name": "alpha.txt",
            "path": str(directory.resolve() / "alpha.txt"),
            "kind": "file",
        },
        {
            "name": "nested",
            "path": str(directory.resolve() / "nested"),
            "kind": "directory",
        },
    ]
    assert before == after


def test_list_directory_rejects_missing_directory(tmp_path):
    response = build_list_directory_kernel().handle(_request(tmp_path / "missing"))

    assert response.status is ResponseStatus.FAILED
    assert response.text == "That directory does not exist."
    assert response.actions == ()


def test_list_directory_rejects_file_path(tmp_path):
    file_path = tmp_path / "file.txt"
    file_path.write_text("content", encoding="utf-8")

    response = build_list_directory_kernel().handle(_request(file_path))

    assert response.status is ResponseStatus.FAILED
    assert response.text == "That path is not a directory."


@pytest.mark.parametrize(
    "arguments",
    [{}, {"path": 4}, {"path": "", "extra": True}],
)
def test_schema_rejects_missing_wrong_type_and_extra_arguments(arguments):
    with pytest.raises(ToolArgumentValidationError):
        ListDirectoryToolDefinition().validate_arguments(arguments)


def test_verifier_rejects_entry_outside_target(tmp_path):
    directory = tmp_path / "listed"
    directory.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    action = PlannedAction(
        action_id="action",
        tool_name="files.list_directory",
        arguments={"path": str(directory)},
        verification=VerificationSpec(kind="directory_listing"),
    )
    forged = ToolResult(
        status=ToolStatus.SUCCEEDED,
        data={
            "directory": str(directory.resolve()),
            "entries": [{"name": outside.name, "path": str(outside), "kind": "file"}],
            "count": 1,
        },
        safe_message="forged",
    )

    verification = ListDirectoryVerifier().verify(
        action,
        {"path": str(directory.resolve())},
        forged,
        AssistantContext(),
    )

    assert verification.status is VerificationStatus.FAILED
    assert "outside" in verification.reason


@pytest.mark.parametrize(
    "source",
    [AssistantSource.CLI, AssistantSource.VOICE, AssistantSource.API],
)
def test_same_vertical_slice_accepts_multiple_interface_sources(tmp_path, source):
    response = build_list_directory_kernel().handle(_request(tmp_path, source))

    assert response.status is ResponseStatus.COMPLETED
    assert response.actions[0].status is ToolStatus.SUCCEEDED
