"""One test per rule the executor enforces.

The rules only mean anything if breaking them is observable, so the
confirmation tests assert on the *implementation mock* rather than on the
returned result: a refusal that still ran the action would produce a
refusal-shaped result and pass a weaker test.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from grandpa.action_layer import executor
from grandpa.action_layer.catalogue import CATALOGUE, Binding, get
from grandpa.action_layer.executor import execute
from grandpa.action_layer.model import ActionRequest, ActionResult, Origin, RiskLevel


@pytest.fixture(autouse=True)
def audit_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Never append to the real log while testing."""
    path = tmp_path / "audit" / "local_actions.jsonl"
    monkeypatch.setenv("GRANDPA_LOCAL_ACTION_LOG", str(path))
    return path


def audit_records(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _patch(monkeypatch: pytest.MonkeyPatch, action: str, returns=None) -> MagicMock:
    """Replace one catalogued action's implementation with a mock."""
    mock = MagicMock(return_value=returns)
    monkeypatch.setattr(get(action).implementation, mock, raising=True)
    return mock


class _Response:
    """The shape pc_control's LocalActionResponse presents to a caller."""

    def __init__(self, ok=True, status="completed", message="done", evidence=None):
        self.ok = ok
        self.status = status
        self.message = message
        self.evidence = evidence or {}
        self.error = None if ok else "service_error"


# --- unknown actions ----------------------------------------------------------


def test_an_unknown_action_fails_rather_than_raising(audit_log: Path) -> None:
    result = execute(ActionRequest("summon_a_dragon", origin=Origin.MODEL))

    assert isinstance(result, ActionResult)
    assert result.success is False
    assert result.error == executor.UNKNOWN_ACTION
    assert "summon_a_dragon" in result.message
    assert audit_records(audit_log)[0]["action_type"] == "summon_a_dragon"


def test_an_excluded_action_is_unknown_to_the_executor() -> None:
    """Being named in pc_control's tables is not the same as being available."""
    result = execute(ActionRequest("shell_run", parameters={"command": "dir"}))

    assert result.error == executor.UNKNOWN_ACTION


# --- parameter validation -----------------------------------------------------


@pytest.mark.parametrize(
    ("action", "parameters", "expected"),
    [
        ("open_app", {}, "missing required parameter 'app'"),
        ("open_app", {"app": "notepad", "nope": 1}, "unknown parameter 'nope'"),
        ("open_app", {"app": 7}, "'app' must be string"),
        ("volume_set", {"level": 300}, "'level' must be at most 100"),
        ("volume_set", {"level": -1}, "'level' must be at least 0"),
        ("file_create", {"path": "x", "kind": "symlink"}, "'kind' must be one of"),
        ("keyboard_hotkey", {"keys": "ctrl+s"}, "'keys' must be array"),
        ("keyboard_hotkey", {"keys": [1]}, "keys[0] must be string"),
    ],
)
def test_invalid_parameters_fail_and_name_the_problem(
    monkeypatch: pytest.MonkeyPatch, action: str, parameters: dict, expected: str
) -> None:
    implementation = _patch(monkeypatch, action, _Response())

    result = execute(
        ActionRequest(action, parameters, requires_confirmation=False),
        confirm_callback=lambda *_: True,
    )

    assert result.error == executor.INVALID_PARAMETERS, result
    assert expected in result.message, result.message
    implementation.assert_not_called()


def test_a_valid_call_reaches_the_implementation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    implementation = _patch(monkeypatch, "volume_set", _Response(message="Volume set."))

    result = execute(
        ActionRequest("volume_set", {"level": 30}, requires_confirmation=False)
    )

    assert result.success is True, result
    assert result.message == "Volume set."
    _instance, service_request, action = implementation.call_args.args
    assert action == "volume_set"
    assert service_request.args == {"level": 30}


# --- confirmation -------------------------------------------------------------


def test_a_high_risk_action_with_no_callback_refuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    implementation = _patch(monkeypatch, "file_delete", _Response())

    result = execute(ActionRequest("file_delete", {"path": "C:/tmp/x.txt"}))

    assert result.success is False
    assert result.error == executor.CONFIRMATION_REQUIRED
    implementation.assert_not_called()


def test_a_declined_confirmation_never_calls_the_implementation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    implementation = _patch(monkeypatch, "file_delete", _Response())

    result = execute(
        ActionRequest("file_delete", {"path": "C:/tmp/x.txt"}),
        confirm_callback=lambda *_: False,
    )

    implementation.assert_not_called()
    assert result.error == executor.CONFIRMATION_DECLINED


def test_a_callback_that_raises_is_a_refusal_not_a_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    implementation = _patch(monkeypatch, "file_delete", _Response())

    def explode(*_args):
        raise RuntimeError("no terminal to ask on")

    result = execute(
        ActionRequest("file_delete", {"path": "C:/tmp/x.txt"}), confirm_callback=explode
    )

    implementation.assert_not_called()
    assert result.error == executor.CONFIRMATION_DECLINED
    assert "no terminal to ask on" in result.message


def test_ctrl_c_at_the_prompt_still_interrupts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A refusal is caught; the user interrupting the program is not."""
    implementation = _patch(monkeypatch, "file_delete", _Response())

    def interrupted(*_args):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        execute(
            ActionRequest("file_delete", {"path": "C:/tmp/x.txt"}),
            confirm_callback=interrupted,
        )

    implementation.assert_not_called()


def test_the_callback_is_asked_with_the_resolved_parameters_and_risk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch(monkeypatch, "file_delete", _Response())
    asked = MagicMock(return_value=True)

    execute(
        ActionRequest("file_delete", {"path": "C:/tmp/x.txt"}), confirm_callback=asked
    )

    action, parameters, risk = asked.call_args.args
    assert action == "file_delete"
    assert parameters == {"path": "C:/tmp/x.txt"}
    assert risk is RiskLevel.HIGH


def test_defaults_are_resolved_before_the_user_is_asked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """What the user is shown has to be what actually happens."""
    _patch(monkeypatch, "browser_summary", _Response(status="handled"))
    asked = MagicMock(return_value=True)

    execute(
        ActionRequest("browser_summary", requires_confirmation=True),
        confirm_callback=asked,
    )

    assert asked.call_args.args[1] == {"scope": "visible"}


def test_a_low_risk_action_runs_without_being_asked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    implementation = _patch(monkeypatch, "volume_up", _Response())
    asked = MagicMock(return_value=True)

    execute(
        ActionRequest("volume_up", requires_confirmation=False), confirm_callback=asked
    )

    asked.assert_not_called()
    implementation.assert_called_once()


def test_a_caller_may_be_stricter_than_the_catalogue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """requires_confirmation on the request can add a prompt, never remove one."""
    implementation = _patch(monkeypatch, "volume_up", _Response())

    result = execute(ActionRequest("volume_up", requires_confirmation=True))

    assert result.error == executor.CONFIRMATION_REQUIRED
    implementation.assert_not_called()


# --- calling, and what comes back ---------------------------------------------


def test_an_exception_in_the_implementation_becomes_a_failed_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        get("volume_up").implementation,
        MagicMock(side_effect=RuntimeError("no audio device")),
        raising=True,
    )

    result = execute(ActionRequest("volume_up", requires_confirmation=False))

    assert result.success is False
    assert result.error == executor.EXECUTION_FAILED
    assert "no audio device" in result.message
    assert result.data["exception"] == "RuntimeError"


def test_a_failing_service_response_is_reported_as_a_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch(monkeypatch, "volume_up", _Response(ok=False, status="failed", message="no"))

    result = execute(ActionRequest("volume_up", requires_confirmation=False))

    assert result.success is False
    assert result.error == "service_error"


def test_a_browser_style_result_is_read_by_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BrowserActionResult has no .ok field, so success comes from its status.

    Read through a browser *awareness* action: navigation moved to the
    browser domain and its own binding when the two confirmation paths were
    reconciled, and these read-only actions are what ACTION_TARGET still
    serves.
    """

    class _BrowserResult:
        status = "handled"
        message = "You are on an active browser page."

    _patch(monkeypatch, "browser_context", _BrowserResult())

    result = execute(
        ActionRequest(
            "browser_context", {"scope": "active"}, requires_confirmation=False
        )
    )

    assert result.success is True, result
    assert result.data["status"] == "handled"


def test_the_browser_binding_passes_the_short_sub_action_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    implementation = _patch(
        monkeypatch, "browser_headings", _Response(status="handled")
    )

    execute(
        ActionRequest(
            "browser_headings", {"scope": "visible"}, requires_confirmation=False
        )
    )

    assert implementation.call_args.args == ("headings", "visible")


def test_a_real_action_has_a_real_effect(tmp_path: Path) -> None:
    """One round trip through an unmocked implementation, effect asserted."""
    target = tmp_path / "written-by-the-executor.txt"

    result = execute(
        ActionRequest(
            "file_create",
            {"path": str(target), "content": "hello from the action layer"},
            requires_confirmation=False,
        )
    )

    assert result.success is True, result
    assert target.read_text(encoding="utf-8") == "hello from the action layer"


# --- the audit trail ----------------------------------------------------------


def test_every_execution_is_logged_with_who_asked_and_what_happened(
    monkeypatch: pytest.MonkeyPatch, audit_log: Path
) -> None:
    _patch(monkeypatch, "volume_up", _Response())

    execute(
        ActionRequest("volume_up", origin=Origin.MODEL, requires_confirmation=False)
    )
    execute(
        ActionRequest("file_delete", {"path": "C:/tmp/x"}, origin=Origin.USER_CHAT),
        confirm_callback=lambda *_: False,
    )

    ran, declined = audit_records(audit_log)
    assert ran["action_type"] == "volume_up"
    assert ran["origin"] == "model"
    assert ran["risk_level"] == "LOW"
    assert ran["confirmed"] is None
    assert ran["ok"] is True

    assert declined["origin"] == "user_chat"
    assert declined["risk_level"] == "HIGH"
    assert declined["confirmed"] is False
    assert declined["ok"] is False
    assert declined["status"] == executor.CONFIRMATION_DECLINED


def test_the_audit_record_is_one_json_object_per_line(
    monkeypatch: pytest.MonkeyPatch, audit_log: Path
) -> None:
    """pc_control's reader and its rotation policy both assume that shape."""
    _patch(monkeypatch, "volume_up", _Response())

    execute(ActionRequest("volume_up", requires_confirmation=False))

    lines = audit_log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["source"] == "action_layer"


def test_the_layer_writes_where_pc_control_reads(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from grandpa import pc_control

    monkeypatch.delenv("GRANDPA_LOCAL_ACTION_LOG", raising=False)
    monkeypatch.setenv("GRANDPA_RUNTIME_DIR", str(tmp_path))

    assert executor.audit_log_path() == pc_control._get_audit_log_path_impl()


# --- the assumptions the adapter rests on -------------------------------------


@pytest.mark.parametrize(
    "spec",
    [spec for spec in CATALOGUE if spec.binding is not Binding.ACTION_TARGET],
    ids=lambda spec: spec.name,
)
def test_every_service_class_is_still_constructible_with_no_arguments(spec) -> None:
    """_call() builds the instance itself; this is the assumption behind that."""
    _implementation, owner = executor._resolve(spec.implementation)

    if owner is None:
        return  # a plain function: nothing to construct
    assert owner() is not None
