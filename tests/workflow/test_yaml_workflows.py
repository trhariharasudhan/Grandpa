"""YAML workflows whose steps are catalogued actions (F1).

Every action is mocked at ``executor._call``, the single point where the action
layer performs anything, so the real lookup, validation, confirmation and audit
code all run while nothing on the machine changes.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from grandpa.action_layer import executor
from grandpa.action_layer.model import ActionResult
from grandpa.cli.workflow_cmd import workflow
from grandpa.workflow.engine import WorkflowEngine
from grandpa.workflow.expressions import ExpressionError, evaluate_condition, render
from grandpa.workflow.loader import (
    WorkflowFileError,
    find_workflow,
    load_workflow,
    load_yaml_workflow,
)


@pytest.fixture(autouse=True)
def audit_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "audit" / "local_actions.jsonl"
    monkeypatch.setenv("GRANDPA_LOCAL_ACTION_LOG", str(path))
    return path


@pytest.fixture()
def wf_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder = tmp_path / "workflows"
    folder.mkdir()
    monkeypatch.setenv("GRANDPA_WORKFLOWS_DIR", str(folder))
    return folder


class Actuators:
    """Fake implementations, keyed by action name."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.behaviour: dict[str, Any] = {}

    def __call__(self, spec, parameters, *, confirmed, confirm_callback):
        self.calls.append((spec.name, dict(parameters)))
        behaviour = self.behaviour.get(spec.name)
        if callable(behaviour):
            return behaviour(parameters)
        if behaviour is not None:
            return behaviour
        return ActionResult.ok(f"{spec.name} done", **dict(parameters))

    def names(self) -> list[str]:
        return [name for name, _ in self.calls]


@pytest.fixture()
def actuators(monkeypatch: pytest.MonkeyPatch) -> Actuators:
    fake = Actuators()
    monkeypatch.setattr(executor, "_call", fake)
    return fake


def write(folder: Path, name: str, text: str) -> Path:
    path = folder / f"{name}.yaml"
    path.write_text(text, encoding="utf-8")
    return path


QUIET = """
name: quiet
description: Lower the volume
vars:
  level: 20
steps:
  - id: before
    action: volume_get
  - id: lower
    action: volume_set
    params: {level: "{{ vars.level }}"}
    when: steps.before.ok
"""


# --- expressions --------------------------------------------------------------


def test_render_keeps_type_for_a_whole_template_and_text_inside_a_string() -> None:
    ctx = {"vars": {"level": 20, "city": "Bengaluru"}, "steps": {}}
    assert render("{{ vars.level }}", ctx) == 20
    assert render("{{ level }}", ctx) == 20
    assert render("Weather in {{ city }}", ctx) == "Weather in Bengaluru"
    assert render({"a": ["{{ vars.city }}"]}, ctx) == {"a": ["Bengaluru"]}


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("steps.a.ok", True),
        ("not steps.a.ok", False),
        ("steps.a.data.level < 30", True),
        ("steps.a.data.level >= 30", False),
        ("vars.mode == 'quiet'", True),
        ("vars.mode != 'quiet'", False),
        ("steps.a.message contains 'DONE'", True),
        ("steps.a.message not contains 'done'", False),
        ("steps.missing.ok", False),
        ("steps.missing.ok or vars.mode == 'quiet'", True),
        ("steps.a.ok and vars.mode == 'loud'", False),
        ("vars.mode == 'a and b'", False),
    ],
)
def test_conditions(expression: str, expected: bool) -> None:
    ctx = {
        "vars": {"mode": "quiet"},
        "steps": {"a": {"ok": True, "message": "all done", "data": {"level": 12}}},
    }
    assert evaluate_condition(expression, ctx) is expected


def test_a_condition_is_never_python() -> None:
    with pytest.raises(ExpressionError):
        evaluate_condition("__import__('os').system('echo hi')", {"vars": {}})


# --- loading and validation ---------------------------------------------------


def test_load_valid_workflow(wf_dir: Path) -> None:
    graph = load_workflow(write(wf_dir, "quiet", QUIET))
    assert graph.name == "quiet"
    assert [n.id for n in graph.nodes] == ["before", "lower"]
    assert graph.variables == {"level": 20}
    assert graph.execution_stages() == [["before"], ["lower"]]


def test_validation_reports_every_problem(wf_dir: Path) -> None:
    path = write(
        wf_dir,
        "bad",
        """
steps:
  - id: one
    action: no_such_action
  - id: two
    action: volume_set
    params: {loudness: 3}
    when: steps.three.ok
    retries: 99
  - id: three
    action: file_delete
    params: {path: "{{ vars.nope }}"}
    colour: red
""",
    )
    with pytest.raises(WorkflowFileError) as info:
        load_yaml_workflow(path)
    text = "\n".join(info.value.problems)
    assert "no catalogued action called 'no_such_action'" in text
    assert "needs parameter 'level'" in text
    assert "has no parameter 'loudness'" in text
    assert "step 'three', which does not run before it" in text
    assert "retries must be at most" in text
    assert "unknown variable 'vars.nope'" in text
    assert "unknown key 'colour'" in text


def test_find_by_file_name_or_by_name_field(wf_dir: Path) -> None:
    write(wf_dir, "file-name", QUIET)
    assert find_workflow("file-name").name == "file-name.yaml"
    assert find_workflow("quiet").name == "file-name.yaml"
    with pytest.raises(FileNotFoundError):
        find_workflow("absent")


# --- running ------------------------------------------------------------------


def test_dry_run_performs_nothing(wf_dir: Path, actuators: Actuators) -> None:
    graph = load_yaml_workflow(write(wf_dir, "quiet", QUIET))
    result = WorkflowEngine().run(graph, dry_run=True)
    assert result.success
    assert actuators.calls == []
    assert "Would run volume_set {'level': 20}" in result.steps[1].output


def test_run_passes_variables_and_step_results(
    wf_dir: Path, actuators: Actuators
) -> None:
    graph = load_yaml_workflow(write(wf_dir, "quiet", QUIET))
    result = WorkflowEngine().run(graph, variables={"level": 35})
    assert result.success
    assert actuators.calls == [("volume_get", {}), ("volume_set", {"level": 35})]


def test_false_condition_skips_the_step(wf_dir: Path, actuators: Actuators) -> None:
    actuators.behaviour["volume_get"] = ActionResult.failed("no audio device")
    path = write(
        wf_dir,
        "q",
        QUIET.replace("id: before", "id: before\n    continue_on_error: true"),
    )
    result = WorkflowEngine().run(load_yaml_workflow(path))
    assert actuators.names() == ["volume_get"]
    assert result.steps[1].metadata.get("skipped") is True
    assert result.success  # the failure was allowed to continue


def test_a_failed_step_stops_the_workflow(wf_dir: Path, actuators: Actuators) -> None:
    actuators.behaviour["volume_get"] = ActionResult.failed("no audio device")
    result = WorkflowEngine().run(load_yaml_workflow(write(wf_dir, "quiet", QUIET)))
    assert not result.success
    assert actuators.names() == ["volume_get"]
    assert len(result.steps) == 1


def test_retries_until_success(
    wf_dir: Path, actuators: Actuators, monkeypatch: pytest.MonkeyPatch
) -> None:
    outcomes = [ActionResult.failed("busy"), ActionResult.failed("busy")]
    actuators.behaviour["volume_get"] = lambda _p: (
        outcomes.pop(0) if outcomes else ActionResult.ok("50")
    )
    path = write(
        wf_dir,
        "r",
        "steps:\n  - id: v\n    action: volume_get\n    retries: 2\n    retry_delay: 0\n",
    )
    result = WorkflowEngine().run(load_yaml_workflow(path))
    assert result.success
    assert result.steps[0].metadata["attempts"] == 3


def test_retries_give_up(wf_dir: Path, actuators: Actuators) -> None:
    actuators.behaviour["volume_get"] = ActionResult.failed("busy")
    path = write(
        wf_dir,
        "r",
        "steps:\n  - id: v\n    action: volume_get\n    retries: 1\n    retry_delay: 0\n",
    )
    result = WorkflowEngine().run(load_yaml_workflow(path))
    assert not result.success
    assert actuators.names() == ["volume_get", "volume_get"]


def test_timeout(wf_dir: Path, actuators: Actuators) -> None:
    actuators.behaviour["volume_get"] = lambda _p: time.sleep(1.0) or "late"
    path = write(
        wf_dir,
        "t",
        "steps:\n  - id: v\n    action: volume_get\n    timeout: 0.2\n    retries: 3\n",
    )
    started = time.monotonic()
    result = WorkflowEngine().run(load_yaml_workflow(path))
    assert not result.success
    assert "did not finish within 0.2 seconds" in result.steps[0].output
    assert time.monotonic() - started < 0.9
    assert result.steps[0].metadata["attempts"] == 1  # a timeout is never retried


RISKY = """
name: risky
steps:
  - id: wipe
    action: empty_recycle_bin
    retries: 3
"""


def test_risky_step_without_a_way_to_ask_is_refused(
    wf_dir: Path, actuators: Actuators, audit_log: Path
) -> None:
    result = WorkflowEngine().run(load_yaml_workflow(write(wf_dir, "risky", RISKY)))
    assert not result.success
    assert actuators.calls == []
    assert result.steps[0].metadata["attempts"] == 1
    records = [json.loads(x) for x in audit_log.read_text().splitlines()]
    assert records[-1]["action_type"] == "empty_recycle_bin"
    assert records[-1]["origin"] == "skill"
    assert records[-1]["status"] == "confirmation_required"


def test_risky_step_declined_is_not_run_or_retried(
    wf_dir: Path, actuators: Actuators
) -> None:
    asked: list[str] = []

    def no(action, parameters, risk):
        asked.append(action)
        return False

    result = WorkflowEngine().run(
        load_yaml_workflow(write(wf_dir, "risky", RISKY)), confirm_callback=no
    )
    assert not result.success
    assert asked == ["empty_recycle_bin"]
    assert actuators.calls == []


def test_risky_step_runs_after_yes_and_the_wait_is_not_timed(
    wf_dir: Path, actuators: Actuators
) -> None:
    def slow_yes(action, parameters, risk):
        time.sleep(2.0)
        return True

    path = write(wf_dir, "risky", RISKY.replace("retries: 3", "timeout: 1.0"))
    result = WorkflowEngine().run(load_yaml_workflow(path), confirm_callback=slow_yes)
    assert result.success, result.steps[0].output
    assert actuators.names() == ["empty_recycle_bin"]


# --- CLI ----------------------------------------------------------------------


def test_cli_list_validate_and_dry_run(wf_dir: Path, actuators: Actuators) -> None:
    write(wf_dir, "quiet", QUIET)
    write(wf_dir, "broken", "steps: []\n")
    runner = CliRunner()

    listed = runner.invoke(workflow, ["list"])
    assert listed.exit_code == 0
    assert "quiet" in listed.output and "2 step(s)" in listed.output
    assert "INVALID" in listed.output

    ok = runner.invoke(workflow, ["validate", "quiet"])
    assert ok.exit_code == 0, ok.output
    assert "lower: volume_set [LOW]" in ok.output

    bad = runner.invoke(workflow, ["validate", "broken"])
    assert bad.exit_code == 1

    dry = runner.invoke(workflow, ["run", "quiet", "--var", "level=10"])
    assert dry.exit_code == 0, dry.output
    assert "Dry run" in dry.output and "{'level': 10}" in dry.output
    assert actuators.calls == []


def test_cli_run_yes_executes(wf_dir: Path, actuators: Actuators) -> None:
    write(wf_dir, "quiet", QUIET)
    result = CliRunner().invoke(workflow, ["run", "quiet", "--yes"])
    assert result.exit_code == 0, result.output
    assert actuators.names() == ["volume_get", "volume_set"]


def test_cli_yes_does_not_approve_risky_steps(
    wf_dir: Path, actuators: Actuators
) -> None:
    write(wf_dir, "risky", RISKY)
    # CliRunner's stdin is not a terminal, so nobody can answer the prompt.
    result = CliRunner().invoke(workflow, ["run", "risky", "--yes"], input="y\n")
    assert result.exit_code == 1
    assert actuators.calls == []


def test_cli_rejects_unknown_variable(wf_dir: Path) -> None:
    write(wf_dir, "quiet", QUIET)
    result = CliRunner().invoke(workflow, ["run", "quiet", "--var", "volume=3"])
    assert result.exit_code != 0
    assert "not in this workflow's vars" in result.output


EXAMPLES = Path(__file__).resolve().parents[2] / "examples" / "workflows"


@pytest.mark.parametrize("path", sorted(EXAMPLES.glob("*.yaml")), ids=lambda p: p.stem)
def test_shipped_examples_validate_and_dry_run(
    path: Path, actuators: Actuators
) -> None:
    graph = load_yaml_workflow(path)
    result = WorkflowEngine().run(graph, dry_run=True)
    assert result.success
    assert actuators.calls == []


def test_example_lowers_only_a_loud_volume(actuators: Actuators) -> None:
    graph = load_yaml_workflow(EXAMPLES / "check-my-pc.yaml")
    actuators.behaviour["volume_get"] = ActionResult.ok("Volume is 80%.", level=80)
    assert WorkflowEngine().run(graph).success
    assert actuators.calls[-1] == ("volume_set", {"level": 30})

    actuators.calls.clear()
    actuators.behaviour["volume_get"] = ActionResult.ok("Volume is 10%.", level=10)
    assert WorkflowEngine().run(graph).success
    assert "volume_set" not in actuators.names()
