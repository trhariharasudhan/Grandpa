from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from grandpa.automation.pipeline import CommandExecutionResult
from grandpa.automation.windows import WindowIdentity, WindowTargetResolutionError
from grandpa.cli.plan_cmd import plan
from grandpa.planner.action_catalog import ACTION_CATALOG
from grandpa.planner.decomposer import (
    DeterministicDecomposer,
    GoalDecompositionError,
    LocalModelDecomposer,
    normalize_goal,
)
from grandpa.planner.executive import ExecutivePlanner
from grandpa.planner.executor import PlannerStepExecutor
from grandpa.planner.formatter import (
    format_debug_trace,
    format_dump,
    format_graph,
    format_plan,
    format_trace,
)
from grandpa.planner.models import (
    ExecutionPlan,
    Goal,
    PlannerLimits,
    PlanStatus,
    PlanStep,
    RecoveryPolicy,
    RetryPolicy,
    StepAttempt,
    StepDependency,
    StepResult,
    StepStatus,
    StepVerification,
    model_to_dict,
)
from grandpa.planner.recovery import RecoveryManager
from grandpa.planner.state_store import PlanStateStore
from grandpa.planner.validator import PlanValidator
from grandpa.planner.verifier import StepVerifier


def _goal(text: str = "Open Chrome and search for FastAPI", session: str = "test") -> Goal:
    return Goal(text, normalize_goal(text), session)


def _store(tmp_path: Path) -> PlanStateStore:
    return PlanStateStore(tmp_path / "plans")


def _plan(*steps: PlanStep, session: str = "test", limits: PlannerLimits | None = None) -> ExecutionPlan:
    return ExecutionPlan.create(_goal(session=session), list(steps), limits=limits)


class FakeExecutor:
    def __init__(self, results: list[StepResult] | None = None) -> None:
        self.results = list(results or [])
        self.calls: list[tuple[str, bool, bool]] = []
        self.automation_service = SimpleNamespace(
            target_window=None,
            has_pending_dialog=False,
            window_targets=SimpleNamespace(resolve=lambda _app: object()),
        )

    def execute(self, step, *, dry_run=False, confirmed=False):
        self.calls.append((step.action, dry_run, confirmed))
        if self.results:
            return self.results.pop(0)
        return StepResult(
            "success", "Done.", step.step_id, {"verified": True, "dry_run": dry_run}
        )

    def resolve_clarification(self, step, response):
        self.calls.append((f"clarify:{response}", False, False))
        if self.results:
            return self.results.pop(0)
        return StepResult("success", "Choice applied.", step.step_id, {"verified": True})


class PassVerifier:
    def verify(self, _step, result):
        return StepResult(
            result.status,
            result.message,
            result.step_id,
            {**result.data, "verified": True},
            result.confirmation_token,
        )


def test_plan_models_serialize_and_reject_invalid_transition() -> None:
    plan_value = _plan(PlanStep("step_1", 1, "Read", "describe_screen"))

    payload = model_to_dict(plan_value)

    assert payload["status"] == "created"
    assert payload["steps"][0]["action"] == "describe_screen"
    with pytest.raises(ValueError, match="Invalid plan transition"):
        plan_value.transition(PlanStatus.COMPLETED)


def test_action_catalog_contains_only_named_allowlisted_actions() -> None:
    assert "launch_application" in ACTION_CATALOG
    assert "click_element" in ACTION_CATALOG
    assert "shell" not in ACTION_CATALOG


@pytest.mark.parametrize(
    ("goal", "actions"),
    [
        (
            "Open Chrome and search for FastAPI documentation",
            ["launch_application", "wait_for_window", "focus_window", "browser_search"],
        ),
        (
            "Open Settings and navigate to Bluetooth",
            ["launch_application", "wait_for_window", "find_element", "click_element"],
        ),
        (
            "Open Calculator and calculate 145 multiplied by 89",
            [
                "launch_application",
                "wait_for_window",
                "focus_window",
                "input_calculator_expression",
                "invoke_calculator_equals",
            ],
        ),
        (
            "Scroll down until the Install button appears",
            ["scroll_until"],
        ),
    ],
)
def test_deterministic_decomposition(goal: str, actions: list[str]) -> None:
    steps = DeterministicDecomposer().decompose(_goal(goal), PlannerLimits())

    assert steps is not None
    assert [step.action for step in steps] == actions


def test_literal_type_payload_is_not_reparsed_as_commands() -> None:
    steps = DeterministicDecomposer().decompose(
        _goal("Open Notepad, type close delete shutdown, then close without saving"),
        PlannerLimits(),
    )

    assert steps is not None
    typed = next(step for step in steps if step.action == "type_text")
    assert typed.parameters["text"] == "close delete shutdown"
    assert sum(step.action == "close_window" for step in steps) == 1


@pytest.mark.parametrize(
    ("goal", "choice", "verification"),
    [
        (
            "Open Notepad, type Grandpa planner test, then close it and cancel",
            "cancel",
            "document_open",
        ),
        (
            "Open Notepad, type test, and close without saving",
            "discard",
            "document_closed",
        ),
        (
            "Open Notepad, type test, close it, and don't save",
            "discard",
            "document_closed",
        ),
        (
            "Open Notepad, type test, then close and discard changes",
            "discard",
            "document_closed",
        ),
    ],
)
def test_notepad_close_goal_variants(
    goal: str, choice: str, verification: str
) -> None:
    steps = DeterministicDecomposer().decompose(_goal(goal), PlannerLimits())

    assert steps is not None
    assert steps[0].parameters == {"app": "notepad", "new_instance": True}
    dialog_step = steps[-1]
    assert dialog_step.action == "invoke_verified_dialog_action"
    assert dialog_step.parameters["choice"] == choice
    assert dialog_step.verification.strategy == verification


@pytest.mark.parametrize(
    "phrase",
    [
        "145 multiplied by 89",
        "145 times 89",
        "145 x 89",
    ],
)
def test_calculator_arithmetic_is_normalized_without_eval(phrase: str) -> None:
    steps = DeterministicDecomposer().decompose(
        _goal(f"Open Calculator and calculate {phrase}"), PlannerLimits()
    )

    assert steps is not None
    assert steps[-2].parameters["expression"] == "145*89"
    assert steps[-1].parameters["expected_result"] == "12905"


def test_readiness_steps_retry_but_input_and_dialog_actions_do_not() -> None:
    steps = DeterministicDecomposer().decompose(
        _goal("Open Notepad, type test, and close without saving"), PlannerLimits()
    )

    assert steps is not None
    attempts = {step.action: step.retry_policy.max_attempts for step in steps}
    assert attempts["launch_application"] == 2
    assert attempts["wait_for_window"] == 2
    assert attempts["type_text"] == 1
    assert attempts["invoke_verified_dialog_action"] == 1


def test_unsupported_vague_goal_does_not_guess() -> None:
    assert DeterministicDecomposer().decompose(_goal("Click it"), PlannerLimits()) is None


def test_local_model_plan_is_strict_json_and_preserves_source(tmp_path: Path) -> None:
    def planner(*_args):
        return json.dumps(
            {
                "steps": [
                    {
                        "action": "describe_screen",
                        "parameters": {},
                        "description": "Describe screen",
                        "verification": "execution_success",
                    }
                ]
            }
        )
    executive = ExecutivePlanner(
        session_id="model",
        local_model=LocalModelDecomposer(planner),
        store=_store(tmp_path),
    )

    result = executive.preview("Explain the visible workspace", allow_local_model=True)

    assert result.status == "ready"
    assert result.plan.planner_source == "local_model"


def test_malformed_local_model_plan_is_rejected() -> None:
    decomposer = LocalModelDecomposer(lambda *_args: '{"not_steps": []}')
    with pytest.raises(GoalDecompositionError):
        decomposer.decompose(_goal("unmatched goal"), PlannerLimits())


def test_invalid_local_model_json_is_reported_as_decomposition_error() -> None:
    decomposer = LocalModelDecomposer(lambda *_args: "not json")

    with pytest.raises(GoalDecompositionError, match="valid planner JSON"):
        decomposer.decompose(_goal("unmatched goal"), PlannerLimits())


@pytest.mark.parametrize("action", ["shell", "powershell", "run_command", "unknown"])
def test_validator_rejects_unknown_or_arbitrary_actions(action: str) -> None:
    plan_value = _plan(PlanStep("step_1", 1, "Unsafe", action))

    result = PlanValidator().validate(plan_value)

    assert not result.valid
    assert any(issue.code == "unknown_action" for issue in result.issues)


def test_validator_rejects_raw_coordinates() -> None:
    step = PlanStep(
        "step_1",
        1,
        "Click",
        "click_element",
        {"name": "Save", "x": 20, "y": 30},
        verification=StepVerification("target_state_changed"),
    )

    result = PlanValidator().validate(_plan(step))

    assert not result.valid
    assert {issue.code for issue in result.issues} >= {"unexpected_parameter", "raw_coordinates"}


def test_validator_rejects_dependency_cycle() -> None:
    first = PlanStep(
        "a", 1, "First", "describe_screen", dependencies=(StepDependency("b"),)
    )
    second = PlanStep(
        "b", 2, "Second", "describe_screen", dependencies=(StepDependency("a"),)
    )

    result = PlanValidator().validate(_plan(first, second))

    assert not result.valid
    assert any(issue.code == "dependency_cycle" for issue in result.issues)


def test_validator_enforces_step_and_retry_limits() -> None:
    limits = PlannerLimits(max_steps=1, max_retries_per_step=1)
    first = PlanStep(
        "a",
        1,
        "First",
        "describe_screen",
        retry_policy=RetryPolicy(max_attempts=3),
    )
    second = PlanStep("b", 2, "Second", "describe_screen")

    result = PlanValidator().validate(_plan(first, second, limits=limits))

    assert {issue.code for issue in result.issues} >= {"step_limit", "retry_limit"}


def test_successful_multi_step_plan_updates_every_step(tmp_path: Path) -> None:
    executor = FakeExecutor()
    executive = ExecutivePlanner(
        session_id="success",
        executor=executor,
        verifier=PassVerifier(),
        store=_store(tmp_path),
    )

    result = executive.execute(
        "Open Chrome and search for FastAPI", dry_run=True
    )

    assert result.status == "completed"
    assert all(step.status == StepStatus.COMPLETED for step in result.plan.steps)
    assert len(executor.calls) == 4


def test_false_success_is_prevented_by_verifier(tmp_path: Path) -> None:
    class FailVerifier:
        def verify(self, step, result):
            return StepResult("failed", "Postcondition missing.", step.step_id)

    executive = ExecutivePlanner(
        session_id="verify",
        executor=FakeExecutor(),
        verifier=FailVerifier(),
        store=_store(tmp_path),
    )

    result = executive.execute("Open Chrome")

    assert result.status == "failed"
    assert result.plan.steps[0].status == StepStatus.FAILED


def test_confirmation_pauses_and_same_session_can_resume(tmp_path: Path) -> None:
    executor = FakeExecutor(
        [
            StepResult("confirmation_required", "Confirm?", "step_1", confirmation_token="abc"),
            StepResult("success", "Done.", "step_1", {"verified": True}),
        ]
    )
    executive = ExecutivePlanner(
        session_id="confirm",
        executor=executor,
        verifier=PassVerifier(),
        store=_store(tmp_path),
    )

    first = executive.execute("Open Chrome")
    resumed = executive.resume(confirmed=True)

    assert first.status == "confirmation_required"
    assert resumed.status == "completed"
    assert executor.calls[-1][2] is True


def test_wrong_session_cannot_resume_confirmation(tmp_path: Path) -> None:
    store = _store(tmp_path)
    owner = ExecutivePlanner(
        session_id="owner",
        executor=FakeExecutor(
            [StepResult("confirmation_required", "Confirm?", "step_1")]
        ),
        verifier=PassVerifier(),
        store=store,
    )
    other = ExecutivePlanner(
        session_id="other", executor=FakeExecutor(), verifier=PassVerifier(), store=store
    )
    owner.execute("Open Chrome")

    result = other.resume(confirmed=True)

    assert result.status == "not_found"
    assert owner.current().status == PlanStatus.WAITING_FOR_CONFIRMATION


def test_clarification_choice_resumes_without_replaying_action(tmp_path: Path) -> None:
    executor = FakeExecutor(
        [
            StepResult(
                "clarification_required",
                "Choose a window.",
                "step_1",
                {"choices": ["First", "Second"]},
            ),
            StepResult("success", "Focused First.", "step_1", {"verified": True}),
        ]
    )
    executive = ExecutivePlanner(
        session_id="clarify",
        executor=executor,
        verifier=PassVerifier(),
        store=_store(tmp_path),
    )

    pending = executive.execute("Open Chrome")
    resumed = executive.clarify("choose first")

    assert pending.status == "clarification_required"
    assert resumed.status == "completed"
    assert executor.calls == [
        ("launch_application", False, False),
        ("clarify:choose first", False, False),
    ]


def test_clarification_isolated_from_other_session(tmp_path: Path) -> None:
    store = _store(tmp_path)
    owner = ExecutivePlanner(
        session_id="owner-clarify",
        executor=FakeExecutor(
            [StepResult("clarification_required", "Choose.", "step_1")]
        ),
        verifier=PassVerifier(),
        store=store,
    )
    other = ExecutivePlanner(
        session_id="other-clarify",
        executor=FakeExecutor(),
        verifier=PassVerifier(),
        store=store,
    )
    owner.execute("Open Chrome")

    result = other.clarify("choose first")

    assert result.status == "not_found"
    assert owner.current().status == PlanStatus.WAITING_FOR_CLARIFICATION


def test_cancel_is_session_local(tmp_path: Path) -> None:
    executive = ExecutivePlanner(session_id="cancel", store=_store(tmp_path))
    plan_value = executive.create("Open Chrome")

    result = executive.cancel()

    assert plan_value.status == PlanStatus.CANCELLED
    assert result.status == "cancelled"


def test_non_idempotent_action_is_never_recovered() -> None:
    step = PlanStep(
        "step_1",
        1,
        "Click Save",
        "click_element",
        {"name": "Save"},
        recovery_policy=RecoveryPolicy(("refresh_vision",), 2),
    )
    plan_value = _plan(step)

    recovery = RecoveryManager().recover(
        plan_value,
        step,
        StepResult("failed", "failed", step.step_id),
        SimpleNamespace(),
    )

    assert recovery is None


def test_state_store_sanitizes_secrets_on_disk(tmp_path: Path) -> None:
    store = _store(tmp_path)
    plan_value = _plan(
        PlanStep(
            "step_1",
            1,
            "Type password",
            "type_text",
            {"text": "password=hunter2"},
        ),
        session="safe",
    )

    store.save(plan_value)

    payload = (store.root / "safe.json").read_text(encoding="utf-8")
    assert "hunter2" not in payload
    assert "[REDACTED]" in payload


def test_state_store_restores_attempt_history(tmp_path: Path) -> None:
    store = _store(tmp_path)
    plan_value = _plan(
        PlanStep("step_1", 1, "Read screen", "describe_screen"),
        session="round-trip",
    )
    plan_value.steps[0].attempts.append(
        StepAttempt(1, status="completed", message="Verified locally.")
    )
    store.save(plan_value)

    restored = PlanStateStore(store.root).get("round-trip")

    assert restored is not None
    assert restored.steps[0].attempts[0].message == "Verified locally."


def test_plan_dump_sanitizes_sensitive_values() -> None:
    plan_value = _plan(
        PlanStep(
            "step_1",
            1,
            "Type sensitive text",
            "type_text",
            {"text": "password=hunter2", "token": "secret-token"},
        )
    )

    payload = format_dump(plan_value)

    assert "hunter2" not in payload
    assert "secret-token" not in payload
    assert "[REDACTED]" in payload


def test_safe_formatters_do_not_expose_runtime_ids() -> None:
    plan_value = _plan(PlanStep("step_1", 1, "Read screen", "describe_screen"))
    plan_value.steps[0].result_metadata = {
        "window_handle": 123,
        "process_id": 456,
        "verified": True,
    }

    rendered = format_plan(plan_value) + format_trace(plan_value) + format_graph(plan_value)

    assert "window_handle" not in rendered
    assert "process_id" not in rendered


def test_cli_help_and_preview_are_read_only(monkeypatch, tmp_path: Path) -> None:
    created: list[ExecutivePlanner] = []

    def factory(*, session_id):
        item = ExecutivePlanner(
            session_id=session_id,
            executor=FakeExecutor(),
            verifier=PassVerifier(),
            store=_store(tmp_path),
        )
        created.append(item)
        return item

    monkeypatch.setattr("grandpa.cli.plan_cmd.ExecutivePlanner", factory)
    runner = CliRunner()

    help_result = runner.invoke(plan, ["--help"])
    preview_result = runner.invoke(
        plan, ["--session", "cli-test", "preview", "Open Chrome and search for FastAPI"]
    )

    assert help_result.exit_code == 0
    assert "preview" in help_result.output
    assert preview_result.exit_code == 0
    assert "Plan:" in preview_result.output
    assert created[-1].executor.calls == []


def test_plan_graph_preserves_dependency_order() -> None:
    steps = DeterministicDecomposer().decompose(_goal(), PlannerLimits())
    plan_value = _plan(*steps)

    graph = format_graph(plan_value, mermaid=True)

    assert "step_1 --> step_2" in graph
    assert "step_3 --> step_4" in graph


class _WindowTargets:
    def __init__(self, batches=(), *, resolved=None, error=None) -> None:
        self.batches = list(batches)
        self.resolved = resolved
        self.error = error
        self.calls = 0
        self.invoked = []
        self.control_text = {}

    def candidates(self, _app):
        self.calls += 1
        if self.batches:
            return self.batches.pop(0)
        return (self.resolved,) if self.resolved is not None else ()

    def resolve(self, _app):
        if self.error is not None:
            raise self.error
        return self.resolved

    def is_ready(self, _window):
        return True

    def verify_foreground(self, window):
        return SimpleNamespace(ok=True, message="Focused.", expected=window)

    def focus_and_verify(self, window):
        return SimpleNamespace(ok=True, message="Focused.", expected=window)

    def invoke_controls(self, window, control_ids):
        self.invoked.append((window, control_ids))
        return True

    def controls_available(self, _window, _control_ids):
        return True

    def read_controls(self, _window, _control_ids):
        return self.control_text


class _AutomationService:
    def __init__(self, window_targets) -> None:
        self.window_targets = window_targets
        self.target_window = None
        self.has_pending_dialog = False
        self.commands = []

    def pin_target(self, window):
        self.target_window = window

    def clear_target(self):
        self.target_window = None

    def handle(self, command, **_kwargs):
        self.commands.append(command)
        return SimpleNamespace(
            status="success",
            message="Launched.",
            data={},
            confirmation_token=None,
        )


def test_delayed_calculator_window_is_polled_and_pinned() -> None:
    calculator = WindowIdentity(
        101,
        "Calculator",
        process_id=12,
        process_name="CalculatorApp.exe",
        target="calculator",
    )
    targets = _WindowTargets([(), (), (calculator,)], resolved=calculator)
    service = _AutomationService(targets)
    executor = PlannerStepExecutor(session_id="calculator", automation_service=service)
    executor.pipeline = SimpleNamespace(
        handle=lambda _command: CommandExecutionResult(
            "success", "Calculator launch requested."
        )
    )
    step = PlanStep(
        "step_1",
        1,
        "Open Calculator",
        "launch_application",
        {"app": "calculator"},
        verification=StepVerification("application_window_exists"),
    )

    result = executor.execute(step)

    assert result.status == "success"
    assert result.data["target_ready"] is True
    assert service.target_window == calculator
    assert targets.calls >= 3


def test_existing_calculator_window_is_reused_without_launching() -> None:
    calculator = WindowIdentity(
        103,
        "Calculator",
        process_name="CalculatorApp.exe",
        target="calculator",
    )
    service = _AutomationService(_WindowTargets(resolved=calculator))
    executor = PlannerStepExecutor(session_id="reuse", automation_service=service)
    launches = []
    executor.pipeline = SimpleNamespace(handle=lambda command: launches.append(command))
    step = PlanStep(
        "step_1",
        1,
        "Open Calculator",
        "launch_application",
        {"app": "calculator"},
        verification=StepVerification("application_window_exists"),
    )

    result = executor.execute(step)

    assert result.status == "success"
    assert result.data["reused_existing"] is True
    assert service.target_window == calculator
    assert launches == []


def test_focus_step_uses_pinned_notepad_document_identity() -> None:
    notepad = WindowIdentity(
        105,
        "*Untitled - Notepad",
        process_name="Notepad.exe",
        target="notepad",
        document_id="document-1",
        document_title="Untitled",
    )
    targets = _WindowTargets(resolved=notepad)
    service = _AutomationService(targets)
    service.pin_target(notepad)
    executor = PlannerStepExecutor(session_id="notepad-focus", automation_service=service)
    step = PlanStep(
        "step_3",
        3,
        "Focus Notepad",
        "focus_window",
        {"app": "notepad"},
        verification=StepVerification("application_window_focused"),
    )

    result = executor.execute(step)

    assert result.status == "success"
    assert service.target_window == notepad
    assert service.commands == []


def test_calculator_alias_mismatch_uses_pinned_ready_window() -> None:
    calculator = WindowIdentity(
        102,
        "Calculator",
        process_name="CalculatorApp.exe",
        target="windows calculator",
    )
    targets = _WindowTargets(resolved=calculator)
    service = _AutomationService(targets)
    service.pin_target(calculator)
    executor = SimpleNamespace(automation_service=service, vision_engine=None)
    verifier = StepVerifier(executor)
    step = PlanStep(
        "step_1",
        1,
        "Open Calculator",
        "launch_application",
        {"app": "calculator"},
        verification=StepVerification("application_window_exists"),
    )

    result = verifier.verify(
        step, StepResult("success", "Opened.", step.step_id)
    )

    assert result.status == "success"
    assert result.data["verified"] is True


def test_window_resolution_failure_is_structured_not_raised() -> None:
    targets = _WindowTargets(
        error=WindowTargetResolutionError("Calculator is not ready yet.")
    )
    service = _AutomationService(targets)
    verifier = StepVerifier(SimpleNamespace(automation_service=service))
    step = PlanStep(
        "step_1",
        1,
        "Open Calculator",
        "launch_application",
        {"app": "calculator"},
        verification=StepVerification("application_window_exists"),
    )

    result = verifier.verify(step, StepResult("success", "Opened.", step.step_id))

    assert result.status == "target_lost"
    assert result.data["verified"] is False


def test_calculator_result_is_verified_from_visible_semantic_text() -> None:
    vision = SimpleNamespace(
        read=lambda: SimpleNamespace(message="Display is 12,905")
    )
    verifier = StepVerifier(
        SimpleNamespace(
            automation_service=_AutomationService(_WindowTargets()),
            vision_engine=vision,
        )
    )
    step = PlanStep(
        "step_5",
        5,
        "Calculate",
        "invoke_calculator_equals",
        {"expected_result": "12905"},
        verification=StepVerification("calculator_result"),
    )

    result = verifier.verify(
        step, StepResult("success", "Equals invoked.", step.step_id)
    )

    assert result.status == "success"
    assert result.data["calculator_result"] == "12905"


def test_calculator_expression_uses_accessible_expression_and_display_text() -> None:
    vision = SimpleNamespace(
        read=lambda: SimpleNamespace(
            message="Expression is 145 ×\nDisplay is 89"
        )
    )
    verifier = StepVerifier(
        SimpleNamespace(
            automation_service=_AutomationService(_WindowTargets()),
            vision_engine=vision,
        )
    )
    step = PlanStep(
        "step_4",
        4,
        "Enter expression",
        "input_calculator_expression",
        {"expression": "145*89"},
        verification=StepVerification("calculator_expression_visible"),
    )

    result = verifier.verify(
        step, StepResult("success", "Expression entered.", step.step_id)
    )

    assert result.status == "success"
    assert result.data["verified"] is True


def test_calculator_expression_invokes_exact_uia_controls() -> None:
    calculator = WindowIdentity(
        104,
        "Calculator",
        process_name="CalculatorApp.exe",
        target="calculator",
    )
    targets = _WindowTargets(resolved=calculator)
    service = _AutomationService(targets)
    service.pin_target(calculator)
    executor = PlannerStepExecutor(session_id="calculator-uia", automation_service=service)
    step = PlanStep(
        "step_4",
        4,
        "Enter expression",
        "input_calculator_expression",
        {"expression": "145*89"},
        verification=StepVerification("calculator_expression_visible"),
    )

    result = executor.execute(step)

    assert result.status == "success"
    assert targets.invoked == [
        (
            calculator,
            (
                "num1Button",
                "num4Button",
                "num5Button",
                "multiplyButton",
                "num8Button",
                "num9Button",
            ),
        )
    ]


def test_failed_launch_stops_dependent_input_and_records_failure(tmp_path: Path) -> None:
    executor = FakeExecutor(
        [
            StepResult("target_lost", "Calculator was not ready.", "step_1"),
            StepResult("target_lost", "Calculator was not ready.", "step_1"),
        ]
    )
    executive = ExecutivePlanner(
        session_id="short-circuit",
        executor=executor,
        verifier=PassVerifier(),
        store=_store(tmp_path),
    )

    result = executive.execute("Open Calculator and calculate 145 times 89")

    assert result.status == "failed"
    assert executor.calls == [
        ("launch_application", False, False),
        ("launch_application", False, False),
    ]
    assert result.plan.metadata["failure_point"]["step_id"] == "step_1"


def _browser_step() -> PlanStep:
    return PlanStep(
        "step_4",
        4,
        "Search",
        "browser_search",
        {"query": "FastAPI documentation"},
        verification=StepVerification("browser_results_visible"),
        timeout_seconds=0.1,
    )


def test_browser_search_accepts_visible_semantic_evidence() -> None:
    def awareness(_command):
        return SimpleNamespace(
            snapshot=SimpleNamespace(
                title="FastAPI documentation - Google Search",
                url="https://www.google.com/search?q=FastAPI+documentation",
                visible_text="FastAPI documentation results",
            )
        )

    verifier = StepVerifier(SimpleNamespace(), browser_awareness=awareness)

    result = verifier.verify(
        _browser_step(),
        StepResult(
            "success",
            "Search opened.",
            "step_4",
            {"url": "https://www.google.com/search?q=FastAPI+documentation"},
        ),
    )

    assert result.status == "success"
    assert result.data["browser_evidence"] == "visible_page"


def test_browser_search_navigation_without_page_capture_is_partial() -> None:
    verifier = StepVerifier(
        SimpleNamespace(),
        browser_awareness=lambda _command: None,
        sleep_func=lambda _seconds: None,
    )

    result = verifier.verify(
        _browser_step(),
        StepResult(
            "success",
            "Search opened.",
            "step_4",
            {"url": "https://duckduckgo.com/?q=FastAPI+documentation"},
        ),
    )

    assert result.status == "partial_success"
    assert result.data["browser_evidence"] == "navigation_requested"


def test_browser_search_never_reports_success_without_navigation() -> None:
    verifier = StepVerifier(
        SimpleNamespace(),
        browser_awareness=lambda _command: None,
        sleep_func=lambda _seconds: None,
    )

    result = verifier.verify(
        _browser_step(), StepResult("success", "No URL.", "step_4")
    )

    assert result.status == "verification_failed"
    assert result.data["verified"] is False


def test_cli_failed_preview_has_no_empty_plan_shell() -> None:
    result = CliRunner().invoke(plan, ["preview", "Click it"])

    assert result.exit_code == 1
    assert "Status: clarification_required" in result.output
    assert "Plan:" not in result.output
    assert "Risk:" not in result.output
    assert "Estimated maximum duration:" not in result.output


def test_cli_partial_plan_with_failure_returns_nonzero(monkeypatch, tmp_path: Path) -> None:
    def factory(*, session_id):
        return ExecutivePlanner(
            session_id=session_id,
                executor=FakeExecutor(
                    [
                        StepResult(
                            "success", "Opened.", "step_1", {"verified": True}
                        ),
                        StepResult("target_lost", "Target changed.", "step_2"),
                        StepResult("target_lost", "Target changed.", "step_2"),
                    ]
                ),
            verifier=PassVerifier(),
            store=_store(tmp_path),
        )

    monkeypatch.setattr("grandpa.cli.plan_cmd.ExecutivePlanner", factory)

    result = CliRunner().invoke(
        plan, ["execute", "Open Chrome and search for FastAPI"]
    )

    assert result.exit_code == 1
    assert "Target changed." in result.output


def test_debug_trace_is_sanitized() -> None:
    plan_value = _plan(PlanStep("step_1", 1, "Type", "type_text"))
    plan_value.metadata["diagnostics"] = [
        {"action": "type_text", "parameters": {"text": "password=hunter2"}}
    ]

    rendered = format_debug_trace(plan_value)

    assert "Planner diagnostics" in rendered
    assert "hunter2" not in rendered
