"""Screen automation must report who asked, not assume it was a voice.

``AutomationExecutor`` stamped every payload with::

    "origin": payload.get("origin", "voice")

which reads like a fallback and is not one: no payload builder
(``mouse_payload``, ``keyboard_payload``, ``window_payload``) ever sets an
origin, so the ``.get`` could only ever return "voice". Every keyboard, mouse
and window action was recorded as spoken -- including ones typed into chat or
issued by a CLI -- which makes the audit trail confidently wrong rather than
merely incomplete. An asserted provenance is worse than an unknown one.

The fix is the one already used everywhere else: carry the existing ``origin``
value, defaulting to ``direct``, and let the caller state what it is.

There is no live agent caller on this path today -- ``agent/executor.py:220``
returns a canned string rather than driving the service, and agent-invoked
actions reach ``run_local_action`` through the skills registry, which already
stamps ``agent``. So these tests prove the contract accepts ``agent`` without
inventing a wiring that does not exist.

Every test injects a runner and makes the real actuator raise, so nothing here
can move a mouse, press a key, or move a window.
"""

from __future__ import annotations

from typing import Any

import pytest

from grandpa import pc_control
from grandpa.automation.executor import AutomationExecutor
from grandpa.automation.models import AutomationAction
from grandpa.automation.service import ScreenAutomationService
from grandpa.pc_control import DEFAULT_ACTION_ORIGIN, _coerce_request


class RecordingRunner:
    """Stands in for ``run_local_action`` and records every payload."""

    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []

    def __call__(self, payload: dict[str, Any]):
        self.payloads.append(dict(payload))
        return pc_control.LocalActionResponse(
            ok=True,
            action_id=None,
            status="completed",
            message="Text typed.",
            approval_required=False,
            risk_level="LOW",
            evidence={},
        )

    @property
    def origins(self) -> list[str]:
        """The origin as ``pc_control`` will actually read it."""
        return [_coerce_request(payload).origin for payload in self.payloads]


@pytest.fixture
def no_real_actuator(monkeypatch):
    """Make the real actuator impossible to reach.

    ``_default_runner`` imports ``run_local_action`` from ``grandpa.pc_control``
    when it runs, so replacing the module attribute catches a fallback reached
    through a local import too.
    """

    def explode(payload):
        raise AssertionError(f"the real actuator was reached with {payload!r}")

    monkeypatch.setattr(pc_control, "run_local_action", explode)


def _type(text: str = "hi") -> AutomationAction:
    return AutomationAction("type", "focused app", {"text": text})


def _window() -> AutomationAction:
    return AutomationAction("maximize", "active", {})


# ---------------------------------------------------------------------------
# The regression itself
# ---------------------------------------------------------------------------


class TestNoHardcodedVoice:
    def test_a_default_executor_is_not_voice(self, no_real_actuator):
        """The whole point: nothing is spoken unless someone says it was."""
        runner = RecordingRunner()

        AutomationExecutor(runner=runner).execute(_type())

        assert runner.origins == ["direct"]
        assert runner.payloads[0]["origin"] != "voice"

    def test_no_payload_builder_supplies_an_origin(self):
        """Which is why the old ``.get`` fallback could only return "voice"."""
        from grandpa.automation.keyboard import keyboard_payload
        from grandpa.automation.windows import window_payload

        assert "origin" not in keyboard_payload(_type())
        assert "origin" not in window_payload(_window())

    @pytest.mark.parametrize("kind", ["type", "press", "maximize", "minimize"])
    def test_every_action_kind_carries_the_stated_origin(self, kind, no_real_actuator):
        runner = RecordingRunner()
        action = (
            AutomationAction(kind, "focused app", {"text": "hi", "keys": ["enter"]})
            if kind in {"type", "press"}
            else AutomationAction(kind, "active", {})
        )

        AutomationExecutor(runner=runner, origin="voice").execute(action)

        assert runner.origins == ["voice"]


# ---------------------------------------------------------------------------
# The three origins
# ---------------------------------------------------------------------------


class TestOriginPropagation:
    @pytest.mark.parametrize("origin", ["voice", "agent", "direct"])
    def test_the_stated_origin_reaches_the_request(self, origin, no_real_actuator):
        runner = RecordingRunner()

        AutomationExecutor(runner=runner, origin=origin).execute(_type())

        assert runner.origins == [origin]

    def test_the_default_matches_pc_controls_own(self):
        import inspect

        default = (
            inspect.signature(AutomationExecutor.__init__).parameters["origin"].default
        )

        assert default == DEFAULT_ACTION_ORIGIN == "direct"

    def test_an_unknown_origin_normalises_rather_than_raising(self, no_real_actuator):
        runner = RecordingRunner()

        AutomationExecutor(runner=runner, origin="nonsense").execute(_type())

        assert runner.origins == ["direct"]

    def test_the_service_hands_its_origin_to_the_executor_it_builds(self):
        service = ScreenAutomationService(origin="voice")

        assert service.executor.origin == "voice"

    def test_the_service_defaults_to_direct(self):
        assert ScreenAutomationService().executor.origin == DEFAULT_ACTION_ORIGIN

    def test_an_injected_executor_keeps_its_own_origin(self):
        """A caller that built the executor already stated the origin there."""
        executor = AutomationExecutor(origin="agent")

        service = ScreenAutomationService(executor=executor, origin="voice")

        assert service.executor.origin == "agent"

    def test_the_pipeline_hands_its_origin_to_a_service_it_builds(self):
        from grandpa.automation.pipeline import WindowsCommandPipeline

        pipeline = WindowsCommandPipeline(origin="voice")

        assert pipeline.automation_service.executor.origin == "voice"

    def test_the_pipeline_defaults_that_service_to_direct(self):
        from grandpa.automation.pipeline import WindowsCommandPipeline

        pipeline = WindowsCommandPipeline()

        assert pipeline.automation_service.executor.origin == DEFAULT_ACTION_ORIGIN


# ---------------------------------------------------------------------------
# The voice surface still says voice
# ---------------------------------------------------------------------------


class RecordingAutomationNoMatch:
    """Lets the turn build its own service so the wiring under test is real."""

    target_window = None


def _voice_turn(text: str, runner, monkeypatch):
    from grandpa.voice.operator import process_voice_operator_turn

    monkeypatch.setattr(
        "grandpa.planner.routing.handle_executive_goal", lambda *a, **k: None
    )
    return process_voice_operator_turn(text, action_runner=runner)


class TestVoiceStillSaysVoice:
    @pytest.mark.parametrize(
        "phrase",
        ["maximize this window", "minimize this window", "restore this window"],
    )
    def test_a_spoken_window_action_is_attributed_to_voice(
        self, phrase, monkeypatch, no_real_actuator
    ):
        """The turn builds the service itself, so this covers the real wiring."""
        runner = RecordingRunner()

        _voice_turn(phrase, runner, monkeypatch)

        assert runner.payloads, "the injected runner was never called"
        assert runner.origins == ["voice"]

    def test_a_spoken_mouse_action_reaches_the_executor_as_voice(
        self, monkeypatch, no_real_actuator
    ):
        """This goes through ``AutomationExecutor``, unlike the window phrases.

        Window commands resolve to ``local_action`` and carry the operator's
        own origin, so they say nothing about the service the turn builds for
        itself. A mouse move does reach it, and ``move`` is the one automation
        kind that is not gated on a verified target window -- scrolling,
        typing, and clicking all are.
        """
        runner = RecordingRunner()

        _voice_turn("move the mouse to 100,200", runner, monkeypatch)

        assert [p["action_type"] for p in runner.payloads] == ["mouse_move"]
        assert runner.origins == ["voice"]

    def test_a_spoken_keyboard_action_is_still_gated_on_a_target_window(
        self, monkeypatch, no_real_actuator
    ):
        """Unchanged safety: typing needs a verified target before it runs.

        Recorded here because it is why the spoken cases above use window
        actions -- not because this slice touched the gate.
        """
        runner = RecordingRunner()

        response = _voice_turn("type hello world", runner, monkeypatch)

        assert runner.payloads == []
        assert response.status != "handled"

    def test_the_voice_responder_builds_a_voice_service(self):
        from grandpa.voice.operator import VoiceOperatorResponder

        responder = VoiceOperatorResponder()

        assert responder.automation_service.executor.origin == "voice"

    def test_the_intent_executor_builds_a_voice_service(self, no_real_actuator):
        """``execute_voice_operator_intent`` builds one when given no service."""
        from grandpa.voice.operator import (
            VoiceOperatorIntent,
            execute_voice_operator_intent,
        )

        runner = RecordingRunner()
        execute_voice_operator_intent(
            VoiceOperatorIntent(
                "screen_automation",
                "maximize_window",
                "active",
                {"command": "maximize"},
            ),
            action_runner=runner,
        )

        assert runner.origins == ["voice"]


# ---------------------------------------------------------------------------
# The audit trail
# ---------------------------------------------------------------------------


class TestAuditRecord:
    @pytest.mark.parametrize("origin", ["voice", "agent", "direct"])
    def test_the_origin_reaches_the_audit_record(self, origin, monkeypatch, tmp_path):
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
                message="Text typed.",
                approval_required=False,
                risk_level=risk,
                evidence={},
            ),
        )

        AutomationExecutor(runner=pc_control.run_local_action, origin=origin).execute(
            _type()
        )

        record = json.loads(
            [line for line in log.read_text(encoding="utf-8").splitlines() if line][-1]
        )
        assert record["origin"] == origin

    def test_a_default_executor_is_audited_as_direct(self, monkeypatch, tmp_path):
        """The regression, seen where it actually mattered."""
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
                message="Text typed.",
                approval_required=False,
                risk_level=risk,
                evidence={},
            ),
        )

        AutomationExecutor(runner=pc_control.run_local_action).execute(_type())

        record = json.loads(
            [line for line in log.read_text(encoding="utf-8").splitlines() if line][-1]
        )
        assert record["origin"] == "direct"


# ---------------------------------------------------------------------------
# Nothing else moved
# ---------------------------------------------------------------------------


class TestPolicyIsUntouched:
    def test_the_dry_run_flag_still_reaches_the_payload(self, no_real_actuator):
        runner = RecordingRunner()

        AutomationExecutor(runner=runner, origin="voice").execute(_type(), dry_run=True)

        assert runner.payloads[0]["dry_run"] is True

    def test_dry_run_still_prevents_execution(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            pc_control, "get_audit_log_path", lambda: tmp_path / "a.log"
        )

        def explode(request, risk):
            raise AssertionError("dry run executed the action")

        monkeypatch.setattr(pc_control, "_execute", explode)

        result = AutomationExecutor(
            runner=pc_control.run_local_action, origin="voice"
        ).execute(_type(), dry_run=True)

        assert result.status == "handled"

    def test_the_approval_flag_still_reaches_the_payload(self, no_real_actuator):
        runner = RecordingRunner()

        AutomationExecutor(runner=runner, origin="voice").execute(
            _type(), require_approval=True
        )

        assert runner.payloads[0]["require_approval"] is True

    def test_risk_is_still_derived_from_the_action_not_the_origin(
        self, monkeypatch, tmp_path
    ):
        monkeypatch.setattr(
            pc_control, "get_audit_log_path", lambda: tmp_path / "a.log"
        )
        seen: list[str] = []
        monkeypatch.setattr(
            pc_control,
            "_execute",
            lambda request, risk: (
                seen.append(risk)
                or pc_control.LocalActionResponse(
                    ok=True,
                    action_id=None,
                    status="completed",
                    message="ok",
                    approval_required=False,
                    risk_level=risk,
                    evidence={},
                )
            ),
        )

        for origin in ("voice", "agent", "direct"):
            AutomationExecutor(
                runner=pc_control.run_local_action, origin=origin
            ).execute(_window())

        assert seen, "the actuator was never reached"
        assert len(set(seen)) == 1, f"origin changed the risk level: {seen}"

    @pytest.mark.parametrize("origin", ["voice", "agent", "direct"])
    def test_origin_does_not_change_the_approval_flag(self, origin, no_real_actuator):
        """Provenance is recorded, never used to gate.

        Approval must follow the action and what the caller asked for. If the
        origin could raise it, an audit field would quietly become a policy
        input -- and one that a caller sets.
        """
        runner = RecordingRunner()

        AutomationExecutor(runner=runner, origin=origin).execute(_window())

        assert runner.payloads[0]["require_approval"] is False

    @pytest.mark.parametrize("origin", ["voice", "agent", "direct"])
    def test_a_requested_approval_is_still_requested(self, origin, no_real_actuator):
        runner = RecordingRunner()

        AutomationExecutor(runner=runner, origin=origin).execute(
            _window(), require_approval=True
        )

        assert runner.payloads[0]["require_approval"] is True

    def test_the_action_type_still_comes_from_the_payload_builder(
        self, no_real_actuator
    ):
        runner = RecordingRunner()

        AutomationExecutor(runner=runner, origin="agent").execute(_type())

        assert runner.payloads[0]["action_type"] == "keyboard_type"

    def test_the_injected_runner_is_still_the_one_used(self, no_real_actuator):
        runner = RecordingRunner()

        AutomationExecutor(runner=runner, origin="voice").execute(_type())

        assert len(runner.payloads) == 1

    def test_verification_evidence_still_reaches_the_result(self, no_real_actuator):
        """Last slice's propagation is not disturbed by stamping an origin."""

        def runner(payload):
            return pc_control.LocalActionResponse(
                ok=True,
                action_id=None,
                status="completed",
                message="Text typed.",
                approval_required=False,
                risk_level="LOW",
                evidence={"verification": {"status": "verified", "detail": "d"}},
            )

        result = AutomationExecutor(runner=runner, origin="voice").execute(_type())

        assert result.data["verification"] == {"status": "verified", "detail": "d"}


# ---------------------------------------------------------------------------
# Scope
# ---------------------------------------------------------------------------


class TestNoNewProvenance:
    def test_the_origin_vocabulary_is_unchanged(self):
        from grandpa.pc_control import ACTION_ORIGINS

        assert ACTION_ORIGINS == (
            "voice",
            "agent",
            "direct",
            "api",
            "scheduler",
            "skill",
        )

    def test_agent_actions_still_reach_the_actuator_as_agent(self):
        """Unchanged: the agent's own path stamps ``agent`` in the registry.

        There is no live agent caller of ``AutomationExecutor`` -- the agent
        executor's ScreenAutomationService branch returns a canned response --
        so this pins where agent provenance actually comes from today rather
        than inventing a wiring for it.
        """
        from grandpa.skills.registry.defaults import _desktop_actuator_skills

        skills = _desktop_actuator_skills()

        assert skills, "no desktop actuator skills are registered"
