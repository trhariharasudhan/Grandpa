"""A multi-step plan must report verification as honestly as a single action.

Single-step voice actions already say verified / failed / unknown. A plan said
"Task completed." either way, because the per-step verification evidence never
reached the sentence -- it was dropped twice on the way up:

* ``automation/executor.py::_result_from_response`` rebuilt ``data`` from
  scratch and left ``LocalActionResponse.evidence`` behind, and
* ``automation/pipeline.py``'s desktop branch kept only ``target_verified``
  from ``pc_response``.

Everything above those two points already carried it: the service preserves
``data``, ``PlannerStepExecutor`` copies it into ``StepResult.data``, and
``ExecutivePlanner`` writes it onto ``PlanStep.result_metadata``. So this slice
propagates existing evidence and aggregates it; it does not verify anything
new, and it cannot: a plan step with no device evidence stays unknown.

Aggregation is deterministic -- ``failed`` beats ``unknown`` beats
``verified`` -- and a step with no evidence counts as unknown, never verified.

Nothing here touches a real desktop. Plans are built as plain data models,
propagation is tested on the two functions that drop the evidence, and the
voice turn runs with a recorded actuator and a planner spy.
"""

from __future__ import annotations

from typing import Any

import pytest

from grandpa import pc_control
from grandpa.desktop.control.verification import (
    aggregate_plan_verification,
    verification_sentence,
)
from grandpa.planner.models import (
    ExecutionPlan,
    Goal,
    PlanResult,
    PlanStatus,
    PlanStep,
)

# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _step(order: int, action: str, verification: Any | None) -> PlanStep:
    """A finished plan step carrying whatever evidence the run produced."""
    metadata: dict[str, Any] = {"duration_ms": 1.0}
    if verification is not None:
        metadata["verification"] = verification
    step = PlanStep(f"step_{order}", order, f"Step {order}", action)
    step.result_metadata = metadata
    return step


def _verified(detail: str = "volume is 46") -> dict[str, Any]:
    return {"status": "verified", "detail": detail}


def _failed(detail: str = "volume is still 40") -> dict[str, Any]:
    return {"status": "failed", "detail": detail}


def _unknown(detail: str = "no reliable read-back") -> dict[str, Any]:
    return {"status": "unknown", "detail": detail}


def _plan(*steps: PlanStep) -> ExecutionPlan:
    return ExecutionPlan.create(Goal("a goal", "a goal", "session"), list(steps))


def _result(status: str, message: str, *steps: PlanStep) -> PlanResult:
    return PlanResult(status, message, _plan(*steps))


def _metadata(*steps: PlanStep) -> list[dict[str, Any]]:
    return [step.result_metadata for step in steps]


# ---------------------------------------------------------------------------
# The aggregation contract
# ---------------------------------------------------------------------------


class TestAggregationPrecedence:
    def test_every_step_verified_is_verified(self):
        outcome = aggregate_plan_verification(
            _metadata(
                _step(1, "launch_application", _verified()),
                _step(2, "type_text", _verified()),
            )
        )

        assert outcome.status == "verified"

    def test_verified_plus_unknown_is_unknown(self):
        outcome = aggregate_plan_verification(
            _metadata(
                _step(1, "launch_application", _verified()),
                _step(2, "navigate_url", _unknown()),
            )
        )

        assert outcome.status == "unknown"

    def test_verified_plus_failed_is_failed(self):
        outcome = aggregate_plan_verification(
            _metadata(
                _step(1, "launch_application", _verified()),
                _step(2, "type_text", _failed()),
            )
        )

        assert outcome.status == "failed"

    def test_failed_outranks_unknown(self):
        """FAILED > UNKNOWN > VERIFIED, whatever order the steps ran in."""
        outcome = aggregate_plan_verification(
            _metadata(
                _step(1, "launch_application", _unknown()),
                _step(2, "type_text", _failed()),
                _step(3, "focus_window", _verified()),
            )
        )

        assert outcome.status == "failed"

    def test_multiple_failures_are_all_reported(self):
        outcome = aggregate_plan_verification(
            _metadata(
                _step(1, "type_text", _failed("nothing was typed")),
                _step(2, "focus_window", _failed("the window did not focus")),
            )
        )

        assert outcome.status == "failed"
        assert "nothing was typed" in outcome.detail
        assert "the window did not focus" in outcome.detail

    def test_a_step_with_no_evidence_counts_as_unknown(self):
        """Absence of evidence is never evidence of success."""
        outcome = aggregate_plan_verification(
            _metadata(
                _step(1, "launch_application", _verified()),
                _step(2, "browser_search", None),
            )
        )

        assert outcome.status == "unknown"

    def test_no_steps_at_all_is_unknown(self):
        assert aggregate_plan_verification([]).status == "unknown"

    @pytest.mark.parametrize("junk", ["not a dict", 42, [], None, {"status": "weird"}])
    def test_malformed_evidence_is_unknown_not_verified(self, junk):
        outcome = aggregate_plan_verification(_metadata(_step(1, "type_text", junk)))

        assert outcome.status == "unknown"

    def test_aggregation_reads_only_existing_evidence(self):
        """No verifier is run here -- this reads what the steps already carry."""
        outcome = aggregate_plan_verification(
            [{"verification": {"status": "verified", "detail": "d"}}]
        )

        assert outcome.status == "verified"
        assert outcome.detail


# ---------------------------------------------------------------------------
# Wording -- shared with the single-action path, not a second vocabulary
# ---------------------------------------------------------------------------


class TestSharedWording:
    def test_verified_keeps_the_plain_message(self):
        assert verification_sentence("verified", "d", "Task completed.") == (
            "Task completed."
        )

    def test_failed_does_not_lead_with_the_success_message(self):
        spoken = verification_sentence("failed", "nothing was typed", "Task completed.")

        assert not spoken.startswith("Task completed")
        assert "nothing was typed" in spoken

    def test_unknown_keeps_the_message_and_adds_the_hedge(self):
        spoken = verification_sentence("unknown", "", "Task completed.")

        assert spoken.startswith("Task completed.")
        assert "could not confirm" in spoken

    def test_unknown_is_not_phrased_as_failure(self):
        spoken = verification_sentence("unknown", "", "Task completed.")

        assert "did not take effect" not in spoken

    def test_unknown_does_not_double_a_full_stop(self):
        assert ".." not in verification_sentence("unknown", "", "Task completed.")

    def test_an_unrecognised_status_changes_nothing(self):
        assert verification_sentence("weird", "d", "Task completed.") == (
            "Task completed."
        )

    def test_the_single_action_helper_uses_the_same_wording(self):
        """One vocabulary for both paths -- not two that can drift apart."""
        from types import SimpleNamespace

        from grandpa.voice.operator import spoken_text_for_verification

        response = SimpleNamespace(
            evidence={"verification": {"status": "unknown", "detail": ""}}
        )

        assert spoken_text_for_verification(
            response, "Volume increased."
        ) == verification_sentence("unknown", "", "Volume increased.")


# ---------------------------------------------------------------------------
# The plan message
# ---------------------------------------------------------------------------


class TestPlanMessage:
    def _message(self, result: PlanResult) -> str:
        from grandpa.planner.routing import plan_result_message

        return plan_result_message(result)

    def test_a_fully_verified_plan_reads_as_before(self):
        message = self._message(
            _result(
                "completed",
                "Task completed.",
                _step(1, "launch_application", _verified()),
                _step(2, "type_text", _verified()),
            )
        )

        assert message == "Task completed."

    def test_an_unconfirmed_plan_says_so(self):
        message = self._message(
            _result(
                "completed",
                "Task completed.",
                _step(1, "launch_application", _verified()),
                _step(2, "navigate_url", None),
            )
        )

        assert "Task completed." in message
        assert "could not confirm" in message

    def test_a_failed_step_is_not_reported_as_a_completed_task(self):
        message = self._message(
            _result(
                "partially_completed",
                "Task completed with partial verification evidence.",
                _step(1, "launch_application", _verified()),
                _step(2, "type_text", _failed("nothing was typed")),
            )
        )

        assert not message.startswith("Task completed")
        assert "nothing was typed" in message

    def test_a_blocked_plan_keeps_its_safety_message(self):
        message = self._message(
            _result(
                "blocked",
                "That plan belongs to another session.",
                _step(1, "launch_application", _failed()),
            )
        )

        assert message == "That plan belongs to another session."

    @pytest.mark.parametrize(
        "status", ["confirmation_required", "clarification_required", "ready", "paused"]
    )
    def test_a_plan_still_waiting_is_not_hedged(self, status):
        """Nothing has finished yet, so there is nothing to confirm or deny."""
        message = self._message(
            _result(status, "I need your confirmation.", _step(1, "type_text", None))
        )

        assert message == "I need your confirmation."

    def test_a_cancelled_plan_keeps_its_message(self):
        message = self._message(
            _result("cancelled", "The task was cancelled safely.", _step(1, "x", None))
        )

        assert message == "The task was cancelled safely."


class TestRoutingActuallyUsesTheAggregate:
    """The wiring, not just the helper.

    Testing ``plan_result_message`` on its own leaves the obvious regression
    uncovered: ``handle_executive_goal`` could simply go back to returning
    ``result.message`` and every helper test would still pass. These drive the
    real routing entry point with a substituted planner, so nothing is executed
    and the goal still has to survive the real decomposer and the real
    two-step floor.
    """

    def _route(self, monkeypatch, result: PlanResult, goal: str) -> str | None:
        from grandpa.planner import routing

        class FakePlanner:
            def __init__(self, *, session_id, executor):
                self.session_id = session_id

            def current(self):
                return None

            def execute(self, text, **kwargs):
                return result

        monkeypatch.setattr(routing, "ExecutivePlanner", FakePlanner)
        routing.clear_planner_sessions()
        try:
            return routing.handle_executive_goal(goal, source="test")
        finally:
            routing.clear_planner_sessions()

    def test_an_unconfirmed_plan_is_hedged_through_the_real_entry_point(
        self, monkeypatch
    ):
        message = self._route(
            monkeypatch,
            _result(
                "completed",
                "Task completed.",
                _step(1, "launch_application", _verified()),
                _step(2, "navigate_url", None),
            ),
            "open chrome and go to gmail",
        )

        assert message is not None
        assert "could not confirm" in message

    def test_a_failed_step_is_audible_through_the_real_entry_point(self, monkeypatch):
        message = self._route(
            monkeypatch,
            _result(
                "completed",
                "Task completed.",
                _step(1, "type_text", _failed("nothing was typed")),
            ),
            "open notepad and type hello world",
        )

        assert message is not None
        assert not message.startswith("Task completed")
        assert "nothing was typed" in message

    def test_a_fully_verified_plan_is_unchanged_through_the_entry_point(
        self, monkeypatch
    ):
        message = self._route(
            monkeypatch,
            _result(
                "completed",
                "Task completed.",
                _step(1, "launch_application", _verified()),
                _step(2, "navigate_url", _verified()),
            ),
            "open chrome and go to gmail",
        )

        assert message == "Task completed."

    def test_a_blocked_plan_keeps_its_message_through_the_entry_point(
        self, monkeypatch
    ):
        message = self._route(
            monkeypatch,
            _result(
                "blocked",
                "That plan belongs to another session.",
                _step(1, "launch_application", None),
            ),
            "open chrome and go to gmail",
        )

        assert message == "That plan belongs to another session."

    def test_a_single_step_goal_is_still_declined(self, monkeypatch):
        """The two-step floor is untouched -- the planner never sees this."""
        message = self._route(
            monkeypatch,
            _result("completed", "Task completed.", _step(1, "x", _verified())),
            "open chrome",
        )

        assert message is None


# ---------------------------------------------------------------------------
# Propagation -- the two points that dropped the evidence
# ---------------------------------------------------------------------------


def _response(verification: Any | None, status: str = "completed"):
    evidence: dict[str, Any] = {}
    if verification is not None:
        evidence["verification"] = verification
    return pc_control.LocalActionResponse(
        ok=status == "completed",
        action_id=None,
        status=status,
        message="Text typed.",
        approval_required=False,
        risk_level="LOW",
        evidence=evidence,
    )


class TestEvidenceReachesTheStep:
    def test_the_automation_executor_carries_verification_through(self):
        from grandpa.automation.executor import _result_from_response
        from grandpa.automation.models import AutomationAction

        result = _result_from_response(
            AutomationAction("type", "focused app", {"text": "hi"}),
            _response(_verified()),
            None,
            0.0,
        )

        assert result.data["verification"] == _verified()

    def test_a_response_without_verification_adds_no_key(self):
        from grandpa.automation.executor import _result_from_response
        from grandpa.automation.models import AutomationAction

        result = _result_from_response(
            AutomationAction("type", "focused app", {"text": "hi"}),
            _response(None),
            None,
            0.0,
        )

        assert "verification" not in result.data

    def test_the_executor_does_not_invent_evidence_for_a_missing_response(self):
        from types import SimpleNamespace

        from grandpa.automation.executor import _result_from_response
        from grandpa.automation.models import AutomationAction

        result = _result_from_response(
            AutomationAction("move", "1,1", {}), SimpleNamespace(), None, 0.0
        )

        assert "verification" not in result.data

    def test_the_desktop_branch_carries_verification_through(self, monkeypatch):
        """``launch_application`` steps take the desktop branch, not screen
        automation, so the evidence has to survive that route too.

        ``WindowsCommandPipeline`` imports ``handle_desktop_command`` inside
        the function body, so the substitution has to be made on the module
        that defines it. Patching the pipeline's own namespace does nothing and
        lets the real launcher run -- which is not a test failure mode worth
        risking, since the real launcher opens an application.
        """
        from grandpa.automation import pipeline as pipeline_mod
        from grandpa.desktop import automation as desktop_mod
        from grandpa.desktop.automation import DesktopAction, DesktopAutomationResult

        desktop = DesktopAutomationResult(
            "handled",
            "Opening Chrome.",
            DesktopAction("open_app", "open_app", "chrome", "Chrome"),
            _response(_verified("chrome is running")),
        )
        launched: list[str] = []

        def fake_desktop(text, **kwargs):
            launched.append(text)
            return desktop

        monkeypatch.setattr(desktop_mod, "handle_desktop_command", fake_desktop)
        monkeypatch.setattr(
            "grandpa.screen.handle_screen_command",
            lambda text: type("S", (), {"should_fallback": True})(),
        )

        class NoScreenAutomation:
            def handle(self, text, dry_run=False):
                from grandpa.automation.models import AutomationResult

                return AutomationResult("no_match", "")

            def pin_target(self, target):  # pragma: no cover - not reached
                raise AssertionError("no launch target in this fixture")

        result = pipeline_mod.WindowsCommandPipeline(
            automation_service=NoScreenAutomation(),
            source="planner",
            session_id="s",
        ).handle("open chrome")

        assert launched == ["open chrome"], "the real launcher ran"
        assert result.data["verification"] == _verified("chrome is running")

    def test_a_desktop_response_without_verification_adds_no_key(self, monkeypatch):
        from grandpa.automation import pipeline as pipeline_mod
        from grandpa.desktop import automation as desktop_mod
        from grandpa.desktop.automation import DesktopAction, DesktopAutomationResult

        desktop = DesktopAutomationResult(
            "handled",
            "Opening Chrome.",
            DesktopAction("open_app", "open_app", "chrome", "Chrome"),
            _response(None),
        )
        monkeypatch.setattr(
            desktop_mod, "handle_desktop_command", lambda text, **k: desktop
        )
        monkeypatch.setattr(
            "grandpa.screen.handle_screen_command",
            lambda text: type("S", (), {"should_fallback": True})(),
        )

        class NoScreenAutomation:
            def handle(self, text, dry_run=False):
                from grandpa.automation.models import AutomationResult

                return AutomationResult("no_match", "")

            def pin_target(self, target):  # pragma: no cover - not reached
                raise AssertionError("no launch target in this fixture")

        result = pipeline_mod.WindowsCommandPipeline(
            automation_service=NoScreenAutomation(),
            source="planner",
            session_id="s",
        ).handle("open chrome")

        assert "verification" not in result.data
        assert result.data["target_verified"] is False


# ---------------------------------------------------------------------------
# The voice turn
# ---------------------------------------------------------------------------


class RecordingActuator:
    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []

    def __call__(self, payload: dict[str, Any]):
        self.payloads.append(dict(payload))
        return pc_control.LocalActionResponse(
            ok=True,
            action_id=None,
            status="dry_run",
            message="would run",
            approval_required=False,
            risk_level="LOW",
            evidence={},
        )


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


def _turn(text: str, monkeypatch, *, planned: str | None = None):
    """Run the production entry point with the planner's answer supplied."""
    from grandpa.voice.operator import process_voice_operator_turn

    seen: list[str] = []

    def fake_goal(
        goal_text,
        *,
        automation_service=None,
        source="chat",
        action_runner=None,
        origin="direct",
    ):
        seen.append(goal_text)
        return planned

    monkeypatch.setattr("grandpa.planner.routing.handle_executive_goal", fake_goal)
    actuator = RecordingActuator()
    automation = RecordingAutomation()
    response = process_voice_operator_turn(
        text, dry_run=True, action_runner=actuator, automation_service=automation
    )
    return response, actuator, automation, seen


class TestSpokenPlanResponse:
    def test_the_plan_message_is_what_the_user_hears(self, monkeypatch):
        hedged = verification_sentence("unknown", "", "Task completed.")
        response, _actuator, _automation, _seen = _turn(
            "open chrome and go to gmail", monkeypatch, planned=hedged
        )

        assert response.spoken_text == hedged
        assert "could not confirm" in response.spoken_text

    def test_a_failed_plan_does_not_sound_like_success(self, monkeypatch):
        hedged = verification_sentence("failed", "nothing was typed", "Task completed.")
        response, _actuator, _automation, _seen = _turn(
            "open notepad and type hello world", monkeypatch, planned=hedged
        )

        assert not response.spoken_text.startswith("Task completed")
        assert "nothing was typed" in response.spoken_text

    def test_a_declined_plan_falls_through_unchanged(self, monkeypatch):
        response, actuator, _automation, seen = _turn(
            "open chrome", monkeypatch, planned=None
        )

        assert seen == ["open chrome"]
        assert [p["action_type"] for p in actuator.payloads] == ["open_app"]
        assert response.spoken_text

    def test_single_step_verification_speech_is_unchanged(self, monkeypatch):
        """The single-action path keeps hedging on its own evidence."""
        from grandpa.voice.operator import process_voice_operator_turn

        monkeypatch.setattr(
            "grandpa.planner.routing.handle_executive_goal",
            lambda *a, **k: None,
        )

        def runner(payload):
            return pc_control.LocalActionResponse(
                ok=True,
                action_id=None,
                status="completed",
                message="Volume increased.",
                approval_required=False,
                risk_level="LOW",
                evidence={"verification": {"status": "unknown", "detail": ""}},
            )

        response = process_voice_operator_turn(
            "turn up the volume",
            action_runner=runner,
            automation_service=RecordingAutomation(),
        )

        assert "could not confirm" in response.spoken_text

    def test_origin_is_still_voice(self, monkeypatch):
        _response, actuator, _automation, _seen = _turn(
            "open chrome", monkeypatch, planned=None
        )

        assert actuator.payloads[0]["origin"] == "voice"


# ---------------------------------------------------------------------------
# Safety is untouched
# ---------------------------------------------------------------------------


class TestSafetyIsUnaffected:
    @pytest.mark.parametrize(
        "phrase",
        [
            "shutdown",
            "restart",
            "run command",
            "open cmd",
            "open cmd and search for fastapi",
            "open powershell and go to gmail",
            "delete all my files",
        ],
    )
    def test_blocked_before_the_planner_and_before_any_actuator(
        self, phrase, monkeypatch
    ):
        response, actuator, automation, seen = _turn(
            phrase, monkeypatch, planned="Task completed."
        )

        assert response.status == "blocked"
        assert seen == [], f"{phrase!r} reached the planner"
        assert actuator.payloads == []
        assert automation.commands == []

    def test_a_blocked_plan_is_never_relabelled_as_unknown(self):
        from grandpa.planner.routing import plan_result_message

        message = plan_result_message(
            _result("blocked", "I blocked that for safety.", _step(1, "x", None))
        )

        assert message == "I blocked that for safety."
        assert "could not confirm" not in message

    def test_verification_does_not_touch_risk_or_approval(self):
        """Aggregation is observational: it reads evidence and returns words."""
        outcome = aggregate_plan_verification(
            _metadata(_step(1, "type_text", _failed()))
        )

        assert outcome.status == "failed"
        assert not hasattr(outcome, "risk_level")
        assert not hasattr(outcome, "approval_required")


# ---------------------------------------------------------------------------
# One mechanism, not two
# ---------------------------------------------------------------------------


class TestNoSecondVerificationSystem:
    def test_aggregation_lives_with_the_other_verification_code(self):
        from grandpa.desktop.control import verification as module

        assert module.aggregate_plan_verification.__module__ == module.__name__

    def test_the_aggregate_reuses_the_existing_outcome_type(self):
        from grandpa.desktop.control.verification import VerificationOutcome

        outcome = aggregate_plan_verification(
            _metadata(_step(1, "type_text", _verified()))
        )

        assert isinstance(outcome, VerificationOutcome)

    def test_the_status_vocabulary_is_the_existing_one(self):
        statuses = {
            aggregate_plan_verification(_metadata(_step(1, "a", _verified()))).status,
            aggregate_plan_verification(_metadata(_step(1, "a", _unknown()))).status,
            aggregate_plan_verification(_metadata(_step(1, "a", _failed()))).status,
        }

        assert statuses == {"verified", "unknown", "failed"}

    def test_the_plan_status_itself_is_not_rewritten(self):
        """Speech is adjusted; the machine-readable plan status is not."""
        result = _result(
            "completed", "Task completed.", _step(1, "type_text", _failed())
        )
        from grandpa.planner.routing import plan_result_message

        plan_result_message(result)

        assert result.status == "completed"
        assert result.plan.status is not PlanStatus.FAILED
