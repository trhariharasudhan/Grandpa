"""Planner desktop steps must use the caller's runner and carry its origin.

Two holes, both at the same seam.

``WindowsCommandPipeline`` routes application launches through
``handle_desktop_command``, and called it without a runner
(``automation/pipeline.py:122``). ``DesktopExecutor`` therefore fell back to its
module default and went straight to the real ``run_local_action`` -- whatever
runner the caller had injected into the automation service. A test that thought
it had substituted the actuator had not: writing one of these tests actually
launched Chrome on the developer's machine.

The same executor built its payload without an ``origin``
(``desktop/automation.py:291``), so every application launch was recorded as
``direct`` in the audit trail, including the ones a person asked for out loud.
Screen automation had carried ``origin`` since AD-022; the desktop path never
did, and it is the path that runs the most attributable action of all -- opening
an application.

Every test here injects a runner **and** makes the real actuator raise, so a
regression that reintroduces the fallback fails loudly instead of opening
something. Asserting the fake was called is not optional: a fake that is never
invoked proves nothing, which is exactly how the original defect hid.
"""

from __future__ import annotations

from typing import Any

import pytest

from grandpa import pc_control
from grandpa.automation.pipeline import WindowsCommandPipeline
from grandpa.desktop.automation import handle_desktop_command
from grandpa.pc_control import DEFAULT_ACTION_ORIGIN, _coerce_request


class RecordingRunner:
    """Stands in for ``run_local_action`` and records every payload."""

    def __init__(self, *, status: str = "completed") -> None:
        self.payloads: list[dict[str, Any]] = []
        self.status = status

    def __call__(self, payload: dict[str, Any]):
        self.payloads.append(dict(payload))
        return pc_control.LocalActionResponse(
            ok=True,
            action_id=None,
            status=self.status,
            message="Opening Notepad.",
            approval_required=False,
            risk_level="LOW",
            evidence={"verification": {"status": "verified", "detail": "it is open"}},
        )

    @property
    def origins(self) -> list[str]:
        return [_coerce_request(payload).origin for payload in self.payloads]

    @property
    def action_types(self) -> list[str]:
        return [payload.get("action_type") for payload in self.payloads]


class NoScreenAutomation:
    """An automation service that claims nothing, so the desktop branch runs."""

    target_window = None

    def handle(self, text: str, dry_run: bool = False):
        from grandpa.automation.models import AutomationResult

        return AutomationResult("no_match", "")

    def pin_target(self, target) -> None:  # pragma: no cover - no launch target
        raise AssertionError("this fixture never produces a launch target")


@pytest.fixture
def no_real_actuator(monkeypatch):
    """Make the real actuator impossible to reach.

    ``DesktopExecutor`` imports ``run_local_action`` from ``grandpa.pc_control``
    when it runs, so replacing the module attribute catches every fallback --
    including one reached through a local import, which is how the original
    escape went unnoticed.
    """

    def explode(payload):
        raise AssertionError(
            f"the real actuator was reached with {payload!r}; "
            "an injected runner was bypassed"
        )

    monkeypatch.setattr(pc_control, "run_local_action", explode)
    return explode


@pytest.fixture
def no_open_windows(monkeypatch):
    """Make the launch path independent of what is already on the desktop.

    ``_launch_application`` reuses an application that is already open rather
    than launching it, so with Notepad running the step would never reach the
    actuator at all and the test would pass or fail according to the machine.
    """
    from grandpa.planner.executor import PlannerStepExecutor

    monkeypatch.setattr(PlannerStepExecutor, "_window_candidates", lambda self, app: ())
    monkeypatch.setattr(
        PlannerStepExecutor,
        "_wait_for_application_target",
        lambda self, step, app, **kwargs: __import__(
            "grandpa.planner.models", fromlist=["StepResult"]
        ).StepResult("success", "open", step.step_id, {"verified": True}),
    )


@pytest.fixture
def no_screen_match(monkeypatch):
    """Send pipeline commands past screen handling into the desktop branch."""
    monkeypatch.setattr(
        "grandpa.screen.handle_screen_command",
        lambda text: type("S", (), {"should_fallback": True})(),
    )


def _capturing_planner(seen: list[Any]):
    """An ExecutivePlanner stand-in that records the executor it is given.

    Substituted so no plan runs: executing one here would drive the desktop,
    and the property under test is what the planner is handed.
    """

    class FakePlanner:
        def __init__(self, *, session_id, executor):
            seen.append(executor)

        def current(self):
            return None

        def execute(self, text, **kwargs):
            from grandpa.planner.models import ExecutionPlan, Goal, PlanResult

            plan = ExecutionPlan.create(Goal(text, text, "s"), [])
            return PlanResult("completed", "Task completed.", plan)

    return FakePlanner


def _pipeline(**kwargs) -> WindowsCommandPipeline:
    return WindowsCommandPipeline(
        automation_service=NoScreenAutomation(),
        source="planner",
        session_id="s",
        **kwargs,
    )


# ---------------------------------------------------------------------------
# A, B, D -- the injected runner is the one that runs
# ---------------------------------------------------------------------------


class TestThePipelineUsesTheInjectedRunner:
    @pytest.fixture(autouse=True)
    def _runner(self):
        self.runner = RecordingRunner()

    def test_the_injected_runner_is_actually_called(
        self, no_real_actuator, no_screen_match
    ):
        runner = RecordingRunner()

        _pipeline(action_runner=runner).handle("open notepad")

        assert runner.payloads, "the injected runner was never called"

    def test_the_runner_receives_the_parsed_desktop_action(
        self, no_real_actuator, no_screen_match
    ):
        runner = RecordingRunner()

        _pipeline(action_runner=runner).handle("open notepad")

        assert runner.action_types == ["open_app"]
        assert runner.payloads[0]["target"] == "notepad"

    def test_the_real_actuator_is_never_reached(
        self, no_real_actuator, no_screen_match
    ):
        """D: no silent fallback while an injected runner exists.

        The fixture raises on any use of the real actuator, so this fails with
        a message rather than opening an application.
        """
        runner = RecordingRunner()

        result = _pipeline(action_runner=runner).handle("open notepad")

        assert result.status == "success"
        assert len(runner.payloads) == 1

    def test_the_runner_reaches_the_planner_step_executor(
        self, no_real_actuator, no_screen_match, no_open_windows
    ):
        """The planner builds its own pipeline, so the runner has to survive it."""
        from grandpa.planner.executor import PlannerStepExecutor
        from grandpa.planner.models import PlanStep

        executor = PlannerStepExecutor(
            session_id="s",
            automation_service=NoScreenAutomation(),
            action_runner=self.runner,
        )
        executor.execute(
            PlanStep(
                "step_1", 1, "Open Notepad", "launch_application", {"app": "notepad"}
            )
        )

        assert self.runner.action_types == ["open_app"]

    def test_routing_hands_the_runner_to_the_planner(self, monkeypatch):
        """And the runner has to survive ``handle_executive_goal`` too.

        ``ExecutivePlanner`` is substituted so no plan runs: this is about the
        executor the planner is handed, and executing a real plan here would
        drive the desktop.
        """
        from grandpa.planner import routing

        runner = RecordingRunner()
        seen: list[Any] = []

        class FakePlanner:
            def __init__(self, *, session_id, executor):
                seen.append(executor)

            def current(self):
                return None

            def execute(self, text, **kwargs):
                from grandpa.planner.models import ExecutionPlan, Goal, PlanResult

                plan = ExecutionPlan.create(Goal(text, text, "s"), [])
                return PlanResult("completed", "Task completed.", plan)

        monkeypatch.setattr(routing, "ExecutivePlanner", FakePlanner)
        routing.clear_planner_sessions()
        try:
            routing.handle_executive_goal(
                "open chrome and go to gmail",
                automation_service=NoScreenAutomation(),
                source="voice_operator",
                action_runner=runner,
                origin="voice",
            )
        finally:
            routing.clear_planner_sessions()

        assert seen, "the planner was never built"
        assert seen[0].pipeline.action_runner is runner
        assert seen[0].pipeline.origin == "voice"

    def test_routing_passes_a_runner_even_with_no_stated_origin(self, monkeypatch):
        """The two travel independently -- neither may ride on the other."""
        from grandpa.planner import routing

        runner = RecordingRunner()
        seen: list[Any] = []
        monkeypatch.setattr(routing, "ExecutivePlanner", _capturing_planner(seen))
        routing.clear_planner_sessions()
        try:
            routing.handle_executive_goal(
                "open chrome and go to gmail",
                automation_service=NoScreenAutomation(),
                action_runner=runner,
            )
        finally:
            routing.clear_planner_sessions()

        assert seen[0].pipeline.action_runner is runner
        assert seen[0].pipeline.origin == DEFAULT_ACTION_ORIGIN

    def test_routing_passes_an_origin_even_with_no_runner(self, monkeypatch):
        from grandpa.planner import routing

        seen: list[Any] = []
        monkeypatch.setattr(routing, "ExecutivePlanner", _capturing_planner(seen))
        routing.clear_planner_sessions()
        try:
            routing.handle_executive_goal(
                "open chrome and go to gmail",
                automation_service=NoScreenAutomation(),
                origin="voice",
            )
        finally:
            routing.clear_planner_sessions()

        assert seen[0].pipeline.origin == "voice"
        assert seen[0].pipeline.action_runner is None


# ---------------------------------------------------------------------------
# C -- the default path is untouched
# ---------------------------------------------------------------------------


class TestDefaultBehaviourIsPreserved:
    def test_without_a_runner_the_default_actuator_is_used(
        self, monkeypatch, no_screen_match
    ):
        """Production callers pass no runner and must keep reaching pc_control."""
        seen: list[dict[str, Any]] = []
        monkeypatch.setattr(
            pc_control,
            "run_local_action",
            lambda payload: (
                seen.append(dict(payload))
                or pc_control.LocalActionResponse(
                    ok=True,
                    action_id=None,
                    status="completed",
                    message="ok",
                    approval_required=False,
                    risk_level="LOW",
                    evidence={},
                )
            ),
        )

        _pipeline().handle("open notepad")

        assert [item["action_type"] for item in seen] == ["open_app"]

    def test_the_pipeline_defaults_to_no_runner(self):
        assert _pipeline().action_runner is None

    def test_the_pipeline_defaults_to_the_shared_default_origin(self):
        """Nothing becomes voice by omission -- provenance must be stated."""
        assert _pipeline().origin == DEFAULT_ACTION_ORIGIN

    def test_the_planner_step_executor_defaults_to_the_same(self):
        from grandpa.planner.executor import PlannerStepExecutor

        executor = PlannerStepExecutor(
            session_id="s", automation_service=NoScreenAutomation()
        )

        assert executor.pipeline.action_runner is None
        assert executor.pipeline.origin == DEFAULT_ACTION_ORIGIN

    def test_handle_desktop_command_still_works_without_a_runner(self, monkeypatch):
        seen: list[dict[str, Any]] = []
        monkeypatch.setattr(
            pc_control, "run_local_action", lambda payload: seen.append(dict(payload))
        )

        handle_desktop_command("open notepad")

        assert len(seen) == 1


# ---------------------------------------------------------------------------
# E, F, G -- origin
# ---------------------------------------------------------------------------


class TestOriginReachesTheRequest:
    def test_voice_origin_reaches_the_desktop_request(self, no_real_actuator):
        runner = RecordingRunner()

        handle_desktop_command("open notepad", runner=runner, origin="voice")

        assert runner.origins == ["voice"]

    def test_voice_origin_survives_the_pipeline(
        self, no_real_actuator, no_screen_match
    ):
        runner = RecordingRunner()

        _pipeline(action_runner=runner, origin="voice").handle("open notepad")

        assert runner.origins == ["voice"]

    def test_voice_origin_survives_the_planner_step_executor(
        self, no_real_actuator, no_screen_match, no_open_windows
    ):
        from grandpa.planner.executor import PlannerStepExecutor
        from grandpa.planner.models import PlanStep

        runner = RecordingRunner()
        PlannerStepExecutor(
            session_id="s",
            automation_service=NoScreenAutomation(),
            action_runner=runner,
            origin="voice",
        ).execute(
            PlanStep(
                "step_1", 1, "Open Notepad", "launch_application", {"app": "notepad"}
            )
        )

        assert runner.origins == ["voice"]

    def test_a_direct_caller_stays_direct(self, no_real_actuator):
        """G: nothing that did not say otherwise becomes voice."""
        runner = RecordingRunner()

        handle_desktop_command("open notepad", runner=runner)

        assert runner.origins == [DEFAULT_ACTION_ORIGIN] == ["direct"]

    def test_the_pipeline_defaults_to_direct(self, no_real_actuator, no_screen_match):
        runner = RecordingRunner()

        _pipeline(action_runner=runner).handle("open notepad")

        assert runner.origins == ["direct"]

    def test_an_unknown_origin_falls_back_rather_than_raising(self, no_real_actuator):
        """pc_control already normalises this; the path must not fight it."""
        runner = RecordingRunner()

        handle_desktop_command("open notepad", runner=runner, origin="nonsense")

        assert runner.origins == ["direct"]

    def test_the_origin_reaches_the_audit_record(self, monkeypatch, tmp_path):
        """F: the point of provenance is that it survives to the trail."""
        import json

        log = tmp_path / "audit.log"
        monkeypatch.setattr(pc_control, "get_audit_log_path", lambda: log)
        monkeypatch.setattr(
            pc_control,
            "_execute",
            lambda request, risk: pc_control.LocalActionResponse(
                ok=True,
                action_id=None,
                status="completed",
                message="Opening Notepad.",
                approval_required=False,
                risk_level="LOW",
                evidence={},
            ),
        )

        handle_desktop_command(
            "open notepad", runner=pc_control.run_local_action, origin="voice"
        )

        record = json.loads(
            [line for line in log.read_text(encoding="utf-8").splitlines() if line][-1]
        )
        assert record["action_type"] == "open_app"
        assert record["origin"] == "voice"

    @pytest.mark.parametrize(
        ("module", "attribute"),
        [
            ("grandpa.desktop.automation", "DesktopExecutor.__init__"),
            ("grandpa.desktop.automation", "handle_desktop_command"),
            ("grandpa.automation.pipeline", "WindowsCommandPipeline.__init__"),
            ("grandpa.planner.executor", "PlannerStepExecutor.__init__"),
            ("grandpa.planner.routing", "handle_executive_goal"),
            ("grandpa.planner.routing", "_executor"),
        ],
    )
    def test_every_origin_default_matches_pc_controls_own(self, module, attribute):
        """One source of truth for what "no stated origin" means.

        These modules spell the default out rather than importing
        ``DEFAULT_ACTION_ORIGIN``: the kernel baseline guard
        (``tests/architecture/test_direct_executor_baseline.py``) counts every
        reference to ``grandpa.pc_control`` anywhere in a module -- lazy
        imports included -- and threading provenance is no reason to deepen a
        dependency the architecture is unwinding. This test is what keeps the
        spelled-out defaults honest, so a change to the constant cannot leave
        them behind.
        """
        import importlib
        import inspect

        target = importlib.import_module(module)
        for part in attribute.split("."):
            target = getattr(target, part)

        assert (
            inspect.signature(target).parameters["origin"].default
            == DEFAULT_ACTION_ORIGIN
        )


# ---------------------------------------------------------------------------
# H, I -- safety and dry run
# ---------------------------------------------------------------------------


class RecordingAutomation:
    target_window = None

    def __init__(self) -> None:
        self.commands: list[str] = []

    def has_pending_confirmation(self) -> bool:
        return False

    def has_pending_window_choice(self) -> bool:
        return False

    def has_pending_dialog(self) -> bool:
        return False

    def handle(self, command: str, dry_run: bool = False):
        from types import SimpleNamespace

        self.commands.append(command)
        return SimpleNamespace(
            status="handled", message="", data={}, confirmation_token=None
        )


def _turn(text: str, monkeypatch, runner):
    from grandpa.voice.operator import process_voice_operator_turn

    goals: list[str] = []
    kwargs: list[dict[str, Any]] = []

    def fake_goal(goal_text, **kw):
        goals.append(goal_text)
        kwargs.append(kw)
        return None

    monkeypatch.setattr("grandpa.planner.routing.handle_executive_goal", fake_goal)
    automation = RecordingAutomation()
    response = process_voice_operator_turn(
        text, action_runner=runner, automation_service=automation
    )
    return response, automation, goals, kwargs


class TestSafetyAndDryRun:
    @pytest.mark.parametrize(
        "phrase",
        [
            "shutdown",
            "run command",
            "open cmd",
            "open cmd and search for fastapi",
            "open powershell and go to gmail",
        ],
    )
    def test_a_blocked_phrase_never_reaches_the_runner(
        self, phrase, monkeypatch, no_real_actuator
    ):
        runner = RecordingRunner()

        response, automation, goals, _kwargs = _turn(phrase, monkeypatch, runner)

        assert response.status == "blocked"
        assert runner.payloads == []
        assert goals == [], "a blocked phrase was offered to the planner"
        assert automation.commands == []

    def test_dry_run_reaches_the_runner_but_not_the_device(self, monkeypatch):
        """I: dry run still stops before actuation, through this path too."""

        def explode(request, risk):
            raise AssertionError("dry run executed the action")

        monkeypatch.setattr(pc_control, "_execute", explode)

        result = handle_desktop_command(
            "open notepad",
            runner=pc_control.run_local_action,
            dry_run=True,
            origin="voice",
        )

        assert result.pc_response.status == "dry_run"

    def test_the_dry_run_flag_survives_the_pipeline(
        self, no_real_actuator, no_screen_match
    ):
        runner = RecordingRunner(status="dry_run")

        _pipeline(action_runner=runner).handle("open notepad", dry_run=True)

        assert runner.payloads[0]["dry_run"] is True

    def test_risk_and_approval_are_still_derived_from_the_action(
        self, monkeypatch, tmp_path
    ):
        """Threading a runner and an origin must not touch policy."""
        monkeypatch.setattr(
            pc_control, "get_audit_log_path", lambda: tmp_path / "a.log"
        )
        monkeypatch.setattr(
            pc_control,
            "_execute",
            lambda request, risk: pc_control.LocalActionResponse(
                ok=True,
                action_id=None,
                status="completed",
                message="ok",
                approval_required=False,
                risk_level=risk,
                evidence={},
            ),
        )

        result = handle_desktop_command(
            "open notepad", runner=pc_control.run_local_action, origin="voice"
        )

        assert result.pc_response.risk_level == "LOW"
        assert result.pc_response.approval_required is False


# ---------------------------------------------------------------------------
# J, K, L -- nothing already working may break
# ---------------------------------------------------------------------------


class TestExistingBehaviourPreserved:
    def test_verification_evidence_still_reaches_the_pipeline_result(
        self, no_real_actuator, no_screen_match
    ):
        """J: last slice's propagation must survive the new threading."""
        runner = RecordingRunner()

        result = _pipeline(action_runner=runner, origin="voice").handle("open notepad")

        assert result.data["verification"] == {
            "status": "verified",
            "detail": "it is open",
        }

    def test_multi_step_voice_routing_still_reaches_the_planner(self, monkeypatch):
        """K: the routing precedence from the previous slice is unchanged."""
        runner = RecordingRunner()

        _response, _automation, goals, _kwargs = _turn(
            "open chrome and go to gmail", monkeypatch, runner
        )

        assert goals == ["open chrome and go to gmail"]

    def test_the_turn_hands_its_runner_and_voice_origin_to_the_planner(
        self, monkeypatch
    ):
        runner = RecordingRunner()

        _response, _automation, _goals, kwargs = _turn(
            "open chrome and go to gmail", monkeypatch, runner
        )

        assert kwargs[0]["action_runner"] is runner
        assert kwargs[0]["origin"] == "voice"

    def test_single_step_voice_actions_still_run(self, monkeypatch):
        """L: the device path is untouched by any of this."""
        runner = RecordingRunner()

        _response, _automation, _goals, _kwargs = _turn(
            "open chrome", monkeypatch, runner
        )

        assert runner.action_types == ["open_app"]
        assert runner.origins == ["voice"]


# ---------------------------------------------------------------------------
# Scope
# ---------------------------------------------------------------------------


class TestNoSecondRunner:
    def test_the_desktop_executor_still_ends_at_run_local_action(self):
        from grandpa.desktop.automation import _default_runner

        source = _default_runner.__code__.co_names
        assert "run_local_action" in source

    def test_no_new_origin_values_were_invented(self):
        from grandpa.pc_control import ACTION_ORIGINS

        assert ACTION_ORIGINS == (
            "voice",
            "agent",
            "direct",
            "api",
            "scheduler",
            "skill",
        )
