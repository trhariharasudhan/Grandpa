"""Voice and agent must reach the computer through one actuator boundary.

``run_local_action`` (pc_control.py:249) is that boundary. It normalises the
action, classifies risk, applies the approval gate, honours emergency stop and
dry-run, writes the audit record, and only then dispatches to ``_execute``
(:715). Nothing here introduces a second one -- these tests assert that both
callers converge on it and that its guarantees survive the trip.

Everything runs with ``dry_run=True`` or against a recording double, so no test
launches an app, presses a key, or moves a window.
"""

from __future__ import annotations

from typing import Any

import pytest

from grandpa import pc_control
from grandpa.pc_control import (
    APPROVAL_REQUIRED_ACTIONS,
    BLOCKED_ACTIONS,
    DEFAULT_ACTION_ORIGIN,
    LocalActionRequest,
    _coerce_request,
    run_local_action,
)
from grandpa.skills.registry.core import get_skill, list_skills
from grandpa.skills.registry.defaults import ensure_default_skills_registered
from grandpa.skills.runtime import SkillExecutionContext


@pytest.fixture(autouse=True)
def _skills_registered():
    ensure_default_skills_registered()


def _run_skill(
    name: str, params: dict[str, Any] | None = None, *, dry_run: bool = True
):
    skill = get_skill(name)
    return skill.execute(params or {}, SkillExecutionContext(dry_run=dry_run))


# ---------------------------------------------------------------------------
# Action origin (AD-022)
# ---------------------------------------------------------------------------


class TestActionOrigin:
    def test_default_origin_is_direct(self):
        assert LocalActionRequest(action_type="open_app").origin == "direct"
        assert DEFAULT_ACTION_ORIGIN == "direct"

    def test_existing_callers_keep_working_without_origin(self):
        """Backward compatibility: a payload with no origin still runs."""
        request = _coerce_request({"action_type": "open_app", "target": "notepad"})

        assert request.origin == "direct"
        assert request.action_type == "open_app"

    @pytest.mark.parametrize("origin", ["voice", "agent", "direct"])
    def test_known_origins_survive_coercion(self, origin):
        request = _coerce_request({"action_type": "open_app", "origin": origin})

        assert request.origin == origin

    def test_unknown_origin_falls_back_to_least_privileged(self):
        """An unrecognised caller must never be recorded as a trusted one."""
        request = _coerce_request({"action_type": "open_app", "origin": "root"})

        assert request.origin == "direct"

    def test_origin_is_written_into_the_audit_record(self, monkeypatch, tmp_path):
        """AD-022 consequence 3: the trail must say who asked.

        This reads the record actually written to disk rather than inspecting
        the arguments passed to ``_audit`` -- asserting on the arguments passes
        even if the field is dropped on the way into the record, which is the
        exact regression this guards.
        """
        import json

        log = tmp_path / "audit.log"
        monkeypatch.setattr(pc_control, "get_audit_log_path", lambda: log)

        run_local_action(
            {
                "action_type": "open_app",
                "target": "notepad",
                "dry_run": True,
                "origin": "agent",
            }
        )

        lines = [line for line in log.read_text(encoding="utf-8").splitlines() if line]
        assert lines, "no audit record was written"
        record = json.loads(lines[-1])
        assert record["origin"] == "agent"
        assert record["action_type"] == "open_app"

    def test_audit_record_defaults_origin_for_legacy_callers(
        self, monkeypatch, tmp_path
    ):
        import json

        log = tmp_path / "audit.log"
        monkeypatch.setattr(pc_control, "get_audit_log_path", lambda: log)

        run_local_action(
            {"action_type": "open_app", "target": "notepad", "dry_run": True}
        )

        record = json.loads(
            [line for line in log.read_text(encoding="utf-8").splitlines() if line][-1]
        )
        assert record["origin"] == "direct"


# ---------------------------------------------------------------------------
# Pinned action type
# ---------------------------------------------------------------------------


class TestPinnedActionType:
    """A skill must always execute the action it was registered for.

    ``_pc_action`` previously read ``params.get("action_type", action_type)``,
    so a caller could turn any skill into any other action and the declared
    risk/approval metadata would no longer describe what ran.
    """

    def test_action_type_cannot_be_overridden_by_params(self, monkeypatch):
        seen: list[str] = []

        def spy_run(payload):
            seen.append(payload["action_type"])
            return pc_control.LocalActionResponse(
                ok=True,
                action_id=None,
                status="dry_run",
                message="ok",
                approval_required=False,
                risk_level="LOW",
            )

        monkeypatch.setattr(pc_control, "run_local_action", spy_run)

        _run_skill("desktop.open_app", {"action_type": "file_delete", "target": "x"})

        assert seen == ["open_app"], "params overrode the pinned action type"

    def test_blocked_action_cannot_be_reached_through_a_benign_skill(self):
        result = _run_skill(
            "desktop.open_app", {"action_type": "shell_run", "target": "whoami"}
        )

        # Pinned to open_app, so this is a dry-run open_app -- never a shell.
        assert result.status in {"dry_run", "completed"}
        assert "shell" not in (result.message or "").lower()

    def test_every_actuator_skill_declares_the_risk_policy_will_apply(self):
        """Declared metadata must match what run_local_action computes."""
        mismatches = []
        for skill in list_skills():
            if not skill.name.startswith("desktop."):
                continue
            action = skill.name.split(".", 1)[1]
            if (
                action
                not in pc_control.LOW_RISK_ACTIONS | pc_control.MEDIUM_RISK_ACTIONS
            ):
                continue
            expected_approval = action in APPROVAL_REQUIRED_ACTIONS
            if skill.approval_required != expected_approval:
                mismatches.append(
                    (skill.name, skill.approval_required, expected_approval)
                )

        assert not mismatches, f"declared approval diverges from policy: {mismatches}"


# ---------------------------------------------------------------------------
# Policy is enforced at the boundary, not by the caller
# ---------------------------------------------------------------------------


class TestPolicyAtTheBoundary:
    @pytest.mark.parametrize("action", sorted(BLOCKED_ACTIONS))
    def test_blocked_actions_stay_blocked(self, action):
        response = run_local_action(
            {"action_type": action, "target": "x", "dry_run": True}
        )

        assert response.ok is False
        assert response.status == "blocked"
        assert response.risk_level == "BLOCKED"

    def test_unknown_action_is_rejected_not_executed(self):
        response = run_local_action(
            {"action_type": "definitely_not_an_action", "dry_run": False}
        )

        assert response.ok is False
        assert response.status == "blocked"

    def test_risk_is_computed_from_the_action_not_the_caller(self):
        """A caller cannot declare its own risk level."""
        response = run_local_action(
            {
                "action_type": "file_delete",
                "target": "x",
                "dry_run": True,
                "risk_level": "LOW",
            }
        )

        assert response.risk_level == "HIGH"

    def test_dry_run_reports_without_executing(self):
        response = run_local_action(
            {"action_type": "open_app", "target": "notepad", "dry_run": True}
        )

        assert response.status == "dry_run"
        assert response.evidence.get("would_execute") is True


# ---------------------------------------------------------------------------
# Voice and agent converge on one actuator
# ---------------------------------------------------------------------------


class TestVoiceAndAgentShareOneActuator:
    """Both callers must reach ``run_local_action`` -- not two implementations."""

    def _record_boundary(self, monkeypatch) -> list[dict[str, Any]]:
        seen: list[dict[str, Any]] = []
        real = pc_control.run_local_action

        def spy(payload):
            coerced = _coerce_request(payload)
            seen.append({"action_type": coerced.action_type, "origin": coerced.origin})
            return real(payload)

        monkeypatch.setattr(pc_control, "run_local_action", spy)
        return seen

    def test_skill_open_app_reaches_the_boundary(self, monkeypatch):
        seen = self._record_boundary(monkeypatch)

        _run_skill("desktop.open_app", {"target": "notepad"})

        assert [entry["action_type"] for entry in seen] == ["open_app"]
        assert seen[0]["origin"] == "skill"

    def test_skill_keyboard_type_reaches_the_boundary_once_approved(self, monkeypatch):
        """Approval-gated skills reach the boundary only after approval.

        ``RuntimeSkill.execute`` (skills/runtime.py:103) refuses to call the
        executor at all while ``approval_required`` and the context is not
        approved, so the approval state has to be supplied to observe the
        boundary. That gate is additive to the one inside run_local_action --
        see ``test_approval_gated_skill_is_refused_without_approval``.
        """
        seen = self._record_boundary(monkeypatch)
        skill = get_skill("desktop.keyboard_type")

        skill.execute(
            {"text": "hello"},
            SkillExecutionContext(dry_run=True, approval_state="approved"),
        )

        assert [entry["action_type"] for entry in seen] == ["keyboard_type"]
        assert seen[0]["origin"] == "skill"

    def test_approval_gated_skill_is_refused_without_approval(self, monkeypatch):
        seen = self._record_boundary(monkeypatch)

        result = _run_skill("desktop.keyboard_type", {"text": "hello"})

        assert seen == [], "an unapproved skill reached the actuator boundary"
        assert result.ok is False
        assert result.status == "approval_required"

    def test_voice_open_app_reaches_the_same_boundary(self):
        from grandpa.voice.operator import process_voice_operator_turn

        seen: list[str] = []

        def runner(payload):
            seen.append(_coerce_request(payload).action_type)
            return pc_control.LocalActionResponse(
                ok=True,
                action_id=None,
                status="dry_run",
                message="ok",
                approval_required=False,
                risk_level="LOW",
            )

        process_voice_operator_turn("open notepad", dry_run=True, action_runner=runner)

        assert seen == ["open_app"]

    def test_voice_and_agent_resolve_open_app_identically(self, monkeypatch):
        """The same action type, from both callers, through the same function."""
        agent_seen = self._record_boundary(monkeypatch)
        _run_skill("desktop.open_app", {"target": "notepad"})

        from grandpa.voice.operator import process_voice_operator_turn

        voice_seen: list[str] = []

        def runner(payload):
            voice_seen.append(_coerce_request(payload).action_type)
            return pc_control.LocalActionResponse(
                ok=True,
                action_id=None,
                status="dry_run",
                message="ok",
                approval_required=False,
                risk_level="LOW",
            )

        process_voice_operator_turn("open notepad", dry_run=True, action_runner=runner)

        assert (
            [entry["action_type"] for entry in agent_seen] == voice_seen == ["open_app"]
        )


# ---------------------------------------------------------------------------
# Coverage of the registered surface
# ---------------------------------------------------------------------------


class TestActuatorSkillSurface:
    def test_core_actuators_are_agent_reachable(self):
        names = {skill.name for skill in list_skills()}
        expected = {
            "desktop.open_app",
            "desktop.close_app",
            "desktop.focus_window",
            "desktop.maximize_window",
            "desktop.minimize_window",
            "desktop.keyboard_type",
            "desktop.keyboard_hotkey",
            "desktop.mouse_click",
            "desktop.mouse_move",
            "desktop.mouse_scroll",
            "desktop.volume_up",
            "desktop.volume_set",
            "desktop.brightness_set",
            "desktop.open_folder",
            "desktop.system_lock",
        }

        assert expected <= names, f"missing: {sorted(expected - names)}"

    def test_dangerous_actions_are_not_exposed_as_skills(self):
        """No skill may be registered for a policy-blocked or destructive action."""
        names = {skill.name for skill in list_skills()}
        forbidden = {
            "desktop.shell_run",
            "desktop.script_run",
            "desktop.file_delete",
            "desktop.file_permanent_delete",
            "desktop.system_shutdown",
            "desktop.system_restart",
            "desktop.empty_recycle_bin",
        }

        assert not (forbidden & names), f"dangerous skills exposed: {forbidden & names}"

    def test_every_registered_actuator_maps_to_a_classified_action(self):
        """No skill may point at an action policy does not know about."""
        classified = (
            pc_control.LOW_RISK_ACTIONS
            | pc_control.MEDIUM_RISK_ACTIONS
            | pc_control.HIGH_RISK_ACTIONS
            | pc_control.BLOCKED_ACTIONS
        )
        unknown = []
        for action_type, *_rest in pc_control_actuator_table():
            if action_type not in classified:
                unknown.append(action_type)

        assert not unknown, f"unclassified actions registered: {unknown}"


def pc_control_actuator_table():
    from grandpa.skills.registry.defaults import _DESKTOP_ACTUATORS

    return _DESKTOP_ACTUATORS
