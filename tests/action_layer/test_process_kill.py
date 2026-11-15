"""V1-T9: process_kill -- HIGH risk, confirmation-gated, refuses critical processes.

The planner and executor are driven with a fake process table and a recording
terminator, so no test here can end a real process. The catalogued entry point
(``kill_process``) is replaced by the actuation guard in every test, and the
tests that go through the executor replace it again with a mock.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from grandpa.action_layer import executor
from grandpa.action_layer.catalogue import (
    Confirmation,
    candidate_domains,
    domain_of,
    get,
)
from grandpa.action_layer.executor import execute
from grandpa.action_layer.loop import run
from grandpa.action_layer.model import ActionRequest, ActionResult, RiskLevel
from grandpa.apps.process_kill import (
    RunningProcess,
    execute_plan,
    is_kill_refused,
    plan_kill,
)

TABLE = [
    RunningProcess(4, "System"),
    RunningProcess(612, "csrss.exe"),
    RunningProcess(900, "lsass.exe"),
    RunningProcess(1200, "explorer.exe"),
    RunningProcess(2001, "chrome.exe"),
    RunningProcess(2002, "chrome.exe"),
    RunningProcess(3000, "notepad.exe"),
    RunningProcess(3100, "vscode-helper.exe"),
    RunningProcess(4000, "MsMpEng.exe"),
    RunningProcess(5000, "python.exe"),
]


@pytest.fixture(autouse=True)
def audit_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("GRANDPA_LOCAL_ACTION_LOG", str(tmp_path / "actions.jsonl"))
    return tmp_path / "actions.jsonl"


class Recorder:
    def __init__(self, survivors: tuple[int, ...] = ()):
        self.calls: list[tuple[RunningProcess, ...]] = []
        self.survivors = survivors

    def __call__(self, targets):
        self.calls.append(tuple(targets))
        return [proc for proc in targets if proc.pid in self.survivors]


# --- the catalogue entry ------------------------------------------------------


def test_process_kill_is_catalogued_high_and_confirmed_by_the_layer() -> None:
    spec = get("process_kill")
    assert spec.risk is RiskLevel.HIGH
    assert spec.confirmation is Confirmation.LAYER
    assert spec.requires_confirmation
    assert domain_of("process_kill") == "processes"


@pytest.mark.parametrize(
    "goal", ["kill chrome", "kill the notepad process", "terminate notepad"]
)
def test_kill_requests_preload_the_processes_domain(goal: str) -> None:
    assert candidate_domains(goal)[:1] == ("processes",), goal


# --- what the planner refuses -------------------------------------------------


@pytest.mark.parametrize(
    "name",
    ["explorer", "explorer.exe", "csrss", "LSASS.EXE", "svchost", "msmpeng", "System"],
)
def test_system_critical_names_are_refused(name: str) -> None:
    assert is_kill_refused(name)


@pytest.mark.parametrize("name", ["explorer", "lsass.exe", "MsMpEng"])
def test_a_critical_process_by_name_is_never_planned(name: str) -> None:
    plan = plan_kill(name=name, processes=TABLE)
    assert plan.targets == ()
    assert "system process" in plan.refusal


@pytest.mark.parametrize("pid", [0, 4, 612, 900, 1200])
def test_a_critical_process_by_pid_is_never_planned(pid: int) -> None:
    plan = plan_kill(pid=pid, processes=TABLE)
    assert plan.targets == ()
    assert "system process" in plan.refusal


def test_grandpas_own_process_tree_is_refused() -> None:
    plan = plan_kill(name="python", processes=TABLE, protected_pids={5000})
    assert plan.targets == ()
    assert "Grandpa is running inside it" in plan.refusal


def test_names_match_exactly_not_by_substring() -> None:
    plan = plan_kill(name="code", processes=TABLE)
    assert plan.targets == ()
    assert "could not find" in plan.refusal


@pytest.mark.parametrize(
    "kwargs", [{}, {"name": "notepad", "pid": 3000}, {"name": "  "}]
)
def test_exactly_one_of_name_or_pid(kwargs: dict) -> None:
    assert plan_kill(processes=TABLE, **kwargs).refusal


def test_an_unknown_pid_is_refused() -> None:
    assert "PID 9999" in plan_kill(pid=9999, processes=TABLE).refusal


# --- what it ends -------------------------------------------------------------


def test_every_process_with_the_name_is_ended() -> None:
    terminate = Recorder()
    result = execute_plan(plan_kill(name="chrome", processes=TABLE), terminate)

    assert [p.pid for p in terminate.calls[0]] == [2001, 2002]
    assert result.success
    assert result.data["ended"] == [2001, 2002]


def test_a_pid_ends_only_that_process() -> None:
    terminate = Recorder()
    result = execute_plan(plan_kill(pid=3000, processes=TABLE), terminate)

    assert terminate.calls == [(RunningProcess(3000, "notepad.exe"),)]
    assert result.success


def test_a_refusal_never_reaches_the_terminator() -> None:
    terminate = Recorder()
    result = execute_plan(plan_kill(name="explorer", processes=TABLE), terminate)

    assert terminate.calls == []
    assert result.success is False


def test_survivors_are_reported_as_a_failure() -> None:
    result = execute_plan(
        plan_kill(name="chrome", processes=TABLE), Recorder(survivors=(2002,))
    )
    assert result.success is False
    assert result.data["survivors"] == [2002]


# --- through the executor and the tool loop -----------------------------------


def _mock_kill(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    mock = MagicMock(return_value=ActionResult.ok("Ended notepad.exe (process)."))
    monkeypatch.setattr(get("process_kill").implementation, mock, raising=True)
    return mock


def test_with_no_one_to_ask_nothing_is_ended(monkeypatch: pytest.MonkeyPatch) -> None:
    implementation = _mock_kill(monkeypatch)
    result = execute(ActionRequest("process_kill", {"name": "notepad"}))

    implementation.assert_not_called()
    assert result.error == executor.CONFIRMATION_REQUIRED


def test_a_no_ends_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    implementation = _mock_kill(monkeypatch)
    asked: list[tuple] = []

    def decline(action, parameters, risk):
        asked.append((action, dict(parameters), risk))
        return False

    result = execute(
        ActionRequest("process_kill", {"name": "notepad"}), confirm_callback=decline
    )

    implementation.assert_not_called()
    assert asked == [("process_kill", {"name": "notepad"}, RiskLevel.HIGH)]
    assert result.error == executor.CONFIRMATION_DECLINED


def test_a_yes_calls_the_implementation_with_the_parameters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    implementation = _mock_kill(monkeypatch)
    result = execute(
        ActionRequest("process_kill", {"pid": 3000}), confirm_callback=lambda *_: True
    )

    implementation.assert_called_once_with(pid=3000)
    assert result.success


def test_extra_parameters_are_rejected_before_anyone_is_asked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    implementation = _mock_kill(monkeypatch)
    asked = MagicMock(return_value=True)
    result = execute(
        ActionRequest("process_kill", {"name": "notepad", "force_system": True}),
        confirm_callback=asked,
    )

    assert result.success is False
    asked.assert_not_called()
    implementation.assert_not_called()


class StubEngine:
    def __init__(self, *turns):
        self.turns = list(turns)
        self.requests: list[dict] = []

    def supports_tools(self, model: str) -> bool:
        return True

    def generate(self, messages, *, model, tools=None, temperature=0.0, **kwargs):
        self.requests.append({"tools": tools})
        return self.turns.pop(0) if self.turns else {"content": "Done."}


def test_kill_notepad_is_offered_first_turn_and_asks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    implementation = _mock_kill(monkeypatch)
    asked: list[str] = []

    def decline(action, parameters, risk):
        asked.append(action)
        return False

    call = {
        "id": "call_0",
        "name": "process_kill",
        "arguments": json.dumps({"name": "notepad"}),
    }
    engine = StubEngine({"content": "", "tool_calls": [call]}, {"content": "Left it."})
    run("kill notepad", engine=engine, model="stub", confirm_callback=decline)

    offered = {
        (t.get("function") or t).get("name") for t in engine.requests[0]["tools"]
    }
    assert "process_kill" in offered
    assert asked == ["process_kill"]
    implementation.assert_not_called()


def test_the_real_entry_point_is_guarded_in_tests() -> None:
    """The actuation guard replaces kill_process; this file never ends a process."""
    from grandpa.apps import process_kill

    assert getattr(process_kill.kill_process, "__actuation_denied__", None)
    assert os.getpid()  # nothing above touched psutil
