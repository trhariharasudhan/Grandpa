from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from grandpa.kernel.models import (
    AssistantRequest,
    AssistantSource,
    PlannedAction,
    PolicyOutcome,
    ResponseStatus,
    ToolStatus,
    VerificationSpec,
    action_digest,
    model_to_dict,
)


def _request() -> AssistantRequest:
    return AssistantRequest(
        request_id="request-1",
        session_id="session-1",
        source=AssistantSource.CLI,
        text="List files in C:/example",
    )


def _action(tool: str = "files.list_directory") -> PlannedAction:
    return PlannedAction(
        action_id="action-1",
        tool_name=tool,
        arguments={"path": "C:/example"},
        verification=VerificationSpec(kind="directory_listing"),
        idempotency_key="key-1",
    )


def test_models_are_frozen_and_enum_values_are_stable():
    request = _request()

    with pytest.raises(FrozenInstanceError):
        request.text = "changed"  # type: ignore[misc]

    assert PolicyOutcome.ALLOW.value == "allow"
    assert ToolStatus.SUCCEEDED.value == "succeeded"
    assert ResponseStatus.CONFIRMATION_REQUIRED.value == "confirmation_required"


def test_models_serialize_to_json_compatible_values():
    data = model_to_dict(_request())

    assert data["source"] == "cli"
    assert data["attachments"] == []


def test_action_digest_is_deterministic_for_canonical_arguments():
    request = _request()
    action = _action()

    first = action_digest(request, action, {"path": "C:/example", "depth": 1})
    second = action_digest(request, action, {"depth": 1, "path": "C:/example"})

    assert first == second


def test_action_digest_changes_with_path_or_tool():
    request = _request()

    baseline = action_digest(request, _action(), {"path": "C:/example"})
    changed_path = action_digest(request, _action(), {"path": "C:/other"})
    changed_tool = action_digest(
        request,
        _action("files.other"),
        {"path": "C:/example"},
    )

    assert baseline != changed_path
    assert baseline != changed_tool
