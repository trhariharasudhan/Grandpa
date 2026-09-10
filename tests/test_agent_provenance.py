"""Agent-originated actions must be audited as agent, not as direct.

AD-022 made provenance first-class so the audit trail can answer "who asked for
this?". Three call sites still built their payload without an ``origin``, so
``_coerce_request`` defaulted them to ``direct`` -- the label meaning "a caller
that stated nothing":

* ``agents/context.py::_desktop_context`` -- the agent gathering desktop
  context for itself.
* ``agents/goal_mode.py::_observe`` -- the agent observing the desktop while
  working a goal.
* ``skills/registry/defaults.py::_clipboard_history`` -- a registered,
  agent-invocable skill that builds its payload by hand instead of going
  through ``_pc_action``, and so misses the ``origin="agent"`` every other
  skill gets.

Model-chosen actions filed as anonymous direct calls is precisely the gap
AD-022 exists to close, and it is worse than a missing field: it is a confident
wrong answer.

Two other callers were audited and are **already truthful**, so they are
asserted rather than changed:

* ``local_actions.py`` is reached from the chat and ask CLIs, where a person
  typed the command. ``direct`` is correct.
* ``desktop/operator.py::execute_visual_step`` has no production caller at all;
  it is a public entry point, and ``direct`` is correct for one.

Nothing here executes a real action: every test substitutes the actuator.
"""

from __future__ import annotations

from typing import Any

import pytest

from grandpa import pc_control
from grandpa.pc_control import ACTION_ORIGINS, _coerce_request


class RecordingActuator:
    """Stands in for ``run_local_action`` and records every payload."""

    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []

    def __call__(self, payload: dict[str, Any]):
        self.payloads.append(dict(payload))
        return pc_control.LocalActionResponse(
            ok=True,
            action_id=None,
            status="completed",
            message="ok",
            approval_required=False,
            risk_level="LOW",
            evidence={},
        )

    @property
    def origins(self) -> list[str]:
        """The origin as ``pc_control`` will actually read it."""
        return [_coerce_request(payload).origin for payload in self.payloads]

    @property
    def action_types(self) -> list[str]:
        return [payload.get("action_type") for payload in self.payloads]


@pytest.fixture
def actuator(monkeypatch):
    recorder = RecordingActuator()
    monkeypatch.setattr(pc_control, "run_local_action", recorder)
    return recorder


# ---------------------------------------------------------------------------
# The three that were wrong
# ---------------------------------------------------------------------------


class TestAgentOriginatedActions:
    def test_agent_desktop_context_is_attributed_to_the_agent(self, actuator):
        from grandpa.agents.context import _desktop_context

        _desktop_context()

        assert actuator.action_types == ["desktop_summary"]
        assert actuator.origins == ["agent"]

    def test_goal_mode_observation_is_attributed_to_the_agent(self, actuator):
        from grandpa.agents.goal_mode import _observe

        class Store:
            def record_observation(self, *args, **kwargs):
                return None

            def append_observation(self, *args, **kwargs):
                return None

            def save(self, *args, **kwargs):
                return None

        goal = type("Goal", (), {"goal_id": "g1", "text": "look around"})()
        try:
            _observe(goal, Store())
        except Exception:
            # The observation loop swallows subsystem failures of its own; the
            # desktop call is what this pins, and it happens regardless.
            pass

        desktop = [
            payload
            for payload in actuator.payloads
            if payload.get("action_type") == "desktop_summary"
        ]
        assert desktop, "the goal observer never read the desktop"
        assert all(_coerce_request(p).origin == "agent" for p in desktop)

    def test_the_clipboard_history_skill_is_attributed_to_the_skill(self, actuator):
        """D-5 moved skills from ``agent`` to ``skill``.

        Both are automated, but they are not the same claim. An agent reading
        its own context passes literals it wrote; a skill reached through
        ``SkillTool`` can be handed arguments a model produced. AD-022 is about
        exactly that difference, so the trail now names the narrower one.
        """
        from grandpa.skills.registry.defaults import _clipboard_history

        _clipboard_history({"limit": 5}, _skill_context())

        assert actuator.action_types == ["clipboard_history"]
        assert actuator.origins == ["skill"]

    def test_the_hand_built_skill_agrees_with_every_other_skill(self, actuator):
        """``_clipboard_history`` bypasses ``_pc_action``; it must not diverge."""
        from grandpa.skills.registry.defaults import _clipboard_history, _pc_action

        _clipboard_history({"limit": 5}, _skill_context())
        _pc_action("clipboard_read", "clipboard")({}, _skill_context())

        assert actuator.origins == ["skill", "skill"]


def _skill_context():
    from grandpa.skills.registry.defaults import SkillExecutionContext

    try:
        return SkillExecutionContext(dry_run=False)
    except TypeError:  # pragma: no cover - contract differs
        return SkillExecutionContext()


# ---------------------------------------------------------------------------
# The two that were already right
# ---------------------------------------------------------------------------


class TestAlreadyTruthfulCallers:
    def test_a_cli_typed_command_stays_direct(self, actuator):
        """``local_actions`` is reached from chat and ask -- a person typed it."""
        from grandpa.local_actions import handle_local_action

        handle_local_action("what time is it", execute=False)

        for payload in actuator.payloads:
            assert _coerce_request(payload).origin == "direct"

    def test_the_public_visual_step_entry_stays_direct(self, actuator):
        """No production caller: a direct API call is what it is."""
        from grandpa.desktop.operator import execute_visual_step

        execute_visual_step(
            {"action_type": "desktop_summary", "target": "desktop"}, dry_run=True
        )

        for payload in actuator.payloads:
            assert _coerce_request(payload).origin == "direct"


# ---------------------------------------------------------------------------
# The audit trail
# ---------------------------------------------------------------------------


class TestAuditRecord:
    def test_an_agent_action_is_recorded_as_agent(self, monkeypatch, tmp_path):
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
                message="ok",
                approval_required=False,
                risk_level=risk,
                evidence={},
            ),
        )

        from grandpa.agents.context import _desktop_context

        _desktop_context()

        record = json.loads(
            [line for line in log.read_text(encoding="utf-8").splitlines() if line][-1]
        )
        assert record["action_type"] == "desktop_summary"
        assert record["origin"] == "agent"


# ---------------------------------------------------------------------------
# Scope
# ---------------------------------------------------------------------------


class TestScope:
    def test_the_origin_vocabulary_is_unchanged(self):
        assert ACTION_ORIGINS == (
            "voice",
            "agent",
            "direct",
            "api",
            "scheduler",
            "skill",
        )

    def test_no_new_action_types(self, actuator):
        from grandpa.agents.context import _desktop_context
        from grandpa.skills.registry.defaults import _clipboard_history

        _desktop_context()
        _clipboard_history({"limit": 5}, _skill_context())

        for action_type in actuator.action_types:
            assert action_type in pc_control.LOW_RISK_ACTIONS

    @pytest.mark.parametrize("origin", ["voice", "agent", "direct"])
    def test_risk_is_still_derived_from_the_action_not_the_origin(
        self, origin, monkeypatch, tmp_path
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

        pc_control.run_local_action(
            {"action_type": "desktop_summary", "target": "desktop", "origin": origin}
        )

        assert seen == ["LOW"]

    def test_the_dry_run_flag_is_preserved(self, actuator):
        """The agent's context reads are dry runs and must stay that way."""
        from grandpa.agents.context import _desktop_context

        _desktop_context()

        assert actuator.payloads[0]["dry_run"] is True


# ---------------------------------------------------------------------------
# 4.12E-3: the agent path stops being filed as a skill
# ---------------------------------------------------------------------------
#
# ``_pc_action`` hardcoded ``origin="skill"`` for every caller. 4.12E-2 showed
# that records the *execution mechanism*, not the provenance: the autonomous
# agent reaches ``run_local_action`` through a registry skill, but nothing about
# that request was model-selected. Its steps come from
# ``planner/engine.decompose_multi_step_task``, which returns hardcoded
# ``PlannerStep`` literals -- so ``skill`` ("invoked through ``SkillTool``,
# carrying model-chosen parameters") was false on both clauses.
#
# ``SkillExecutionContext.source`` already distinguishes the callers, so the fix
# reads a field that was being ignored rather than adding one.
#
# **Deliberately unfixed here:** ``intent_router``. Route 1's truthful value is
# whatever Funnel-A caller asked, which ``handle_local_action`` does not carry.
# It keeps ``skill`` -- still wrong, still recorded as wrong below -- until the
# caller-origin question is settled.

#: Sources whose provenance 4.12E-2 established unambiguously.
AGENT_SOURCES = ("autonomous-agent-v2", "autonomous-agent-v2-retry")

#: Sources that must keep ``skill``: the deferred route, and the fallback for
#: anything unrecognised. ``SkillTool`` itself is absent on purpose -- it runs
#: manifest skills through ``SkillExecutor`` and never reaches ``_pc_action``.
SKILL_SOURCES = ("intent_router", "local_actions", "mcp-local", "", "unknown-source")


def _context(source: str, *, dry_run: bool = False):
    from grandpa.skills.runtime import SkillExecutionContext

    return SkillExecutionContext(source=source, dry_run=dry_run)


class TestTheAgentPathIsRecordedAsAgent:
    """B and C: the two sources whose provenance is not in doubt."""

    @pytest.mark.parametrize("source", AGENT_SOURCES)
    def test_an_agent_source_records_agent(self, source: str, actuator) -> None:
        from grandpa.skills.registry.defaults import _pc_action

        _pc_action("desktop_summary", "desktop")({}, _context(source))

        assert actuator.origins == ["agent"], source

    def test_the_retry_agrees_with_the_first_attempt(self, actuator) -> None:
        """A retry is the same actor; it must not change provenance."""
        from grandpa.skills.registry.defaults import _pc_action

        run = _pc_action("desktop_summary", "desktop")
        run({}, _context("autonomous-agent-v2"))
        run({}, _context("autonomous-agent-v2-retry"))

        assert actuator.origins == ["agent", "agent"]


class TestEverythingElseKeepsSkill:
    """A and G: no other source's provenance changes in this slice."""

    @pytest.mark.parametrize("source", SKILL_SOURCES)
    def test_a_non_agent_source_still_records_skill(
        self, source: str, actuator
    ) -> None:
        from grandpa.skills.registry.defaults import _pc_action

        _pc_action("desktop_summary", "desktop")({}, _context(source))

        assert actuator.origins == ["skill"], source

    def test_the_intent_router_is_not_claimed_as_agent(self, actuator) -> None:
        """G, stated on its own because it is the one we know is still wrong.

        Route 1 is a person typing a phrase that a static table maps to a skill.
        It is not agent-originated and not skill-originated. Recording the
        second remains wrong; recording the first would be a different wrong
        answer. Pinned as ``skill`` until the caller-origin question is settled.
        """
        from grandpa.skills.registry.defaults import _pc_action

        _pc_action("desktop_summary", "desktop")({}, _context("intent_router"))

        assert actuator.origins == ["skill"]
        assert actuator.origins != ["agent"]

    def test_the_hand_built_skill_is_untouched(self, actuator) -> None:
        """``_clipboard_history`` does not go through ``_pc_action``."""
        from grandpa.skills.registry.defaults import _clipboard_history

        _clipboard_history({"limit": 5}, _context("autonomous-agent-v2"))

        assert actuator.origins == ["skill"]


class TestOnlyTheOriginChanges:
    """D and the §5 non-vacuity requirement: the payload is otherwise identical."""

    @staticmethod
    def _payloads_for(actuator, sources) -> list[dict]:
        from grandpa.skills.registry.defaults import _pc_action

        run = _pc_action("desktop_summary", "desktop")
        for source in sources:
            run({"target": "desktop", "args": {"depth": 2}}, _context(source))
        return actuator.payloads

    def test_every_field_but_origin_is_identical(self, actuator) -> None:
        agent, skill = self._payloads_for(
            actuator, ("autonomous-agent-v2", "intent_router")
        )

        assert agent["origin"] == "agent"
        assert skill["origin"] == "skill"
        assert {k: v for k, v in agent.items() if k != "origin"} == {
            k: v for k, v in skill.items() if k != "origin"
        }

    def test_the_action_type_is_still_fixed_at_registration(self, actuator) -> None:
        """Provenance did not become a way to choose the action."""
        from grandpa.skills.registry.defaults import _pc_action

        _pc_action("desktop_summary", "desktop")(
            {"action_type": "shell_run"}, _context("autonomous-agent-v2")
        )

        assert actuator.action_types == ["desktop_summary"]

    def test_params_still_own_target_args_and_dry_run(self, actuator) -> None:
        from grandpa.skills.registry.defaults import _pc_action

        _pc_action("desktop_summary", "default")(
            {"target": "chosen", "args": {"depth": 3}, "dry_run": True},
            _context("autonomous-agent-v2", dry_run=False),
        )

        payload = actuator.payloads[0]
        assert payload["target"] == "chosen"
        assert payload["args"] == {"depth": 3}
        assert payload["dry_run"] is True

    def test_the_context_dry_run_still_applies_when_params_are_silent(
        self, actuator
    ) -> None:
        from grandpa.skills.registry.defaults import _pc_action

        _pc_action("desktop_summary", "desktop")(
            {}, _context("autonomous-agent-v2", dry_run=True)
        )

        assert actuator.payloads[0]["dry_run"] is True


class TestPolicyIsUnaffected:
    """E and F: Q-10 holds. Origin is audit-only, before and after."""

    @pytest.mark.parametrize("source", (*AGENT_SOURCES, "intent_router"))
    def test_risk_and_approval_ignore_the_recorded_origin(self, source: str) -> None:
        from grandpa.desktop.kernel.risk import classify, requires_approval

        base = {
            "action_type": "file_delete",
            "target": "x",
            "args": {},
            "dry_run": True,
        }
        as_agent = _coerce_request({**base, "origin": "agent"})
        as_skill = _coerce_request({**base, "origin": "skill"})

        assert classify(as_agent) == classify(as_skill)
        assert requires_approval(as_agent) == requires_approval(as_skill)

    def test_the_digest_does_not_move_with_origin(self) -> None:
        base = {"action_type": "open_app", "target": "notepad", "args": {}}
        agent = pc_control._action_digest(
            _coerce_request({**base, "origin": "agent"}), "", ""
        )
        skill = pc_control._action_digest(
            _coerce_request({**base, "origin": "skill"}), "", ""
        )

        assert agent == skill


class TestTheMappingIsDrivenBySource:
    """§5: prove the input is the context, not the skill name."""

    def test_the_same_skill_yields_both_origins(self, actuator) -> None:
        """One executor, two sources, two labels -- so the name cannot be it."""
        from grandpa.skills.registry.defaults import _pc_action

        run = _pc_action("desktop_summary", "desktop")
        run({}, _context("autonomous-agent-v2"))
        run({}, _context("intent_router"))

        assert actuator.origins == ["agent", "skill"]

    @pytest.mark.parametrize(
        "action_type", ("open_app", "clipboard_read", "volume_mute", "keyboard_type")
    )
    def test_different_skills_share_one_mechanism(
        self, action_type: str, actuator
    ) -> None:
        """The 27 ``_pc_action`` skills are covered by the same seam."""
        from grandpa.skills.registry.defaults import _pc_action

        _pc_action(action_type, "x")({}, _context("autonomous-agent-v2"))

        assert actuator.origins == ["agent"], action_type

    def test_no_skill_name_appears_in_the_mapping(self) -> None:
        """Structural: provenance is not inferred from what is being run."""
        import inspect

        from grandpa.skills.registry.defaults import _pc_action

        source = inspect.getsource(_pc_action)

        for name in ("desktop_summary", "desktop.summary", "pc_diagnostics"):
            assert name not in source, name

    def test_the_registry_still_holds_the_pc_action_skills(self) -> None:
        """The topology did not change: the seam is inside the executor."""
        from grandpa.skills.registry import ensure_default_skills_registered, get_skill

        ensure_default_skills_registered()
        for name in ("desktop.summary", "desktop.monitors", "desktop.diagnostics"):
            executor = get_skill(name).executor
            assert executor.__qualname__ == "_pc_action.<locals>._execute", name

    def test_every_recorded_origin_is_in_the_vocabulary(self, actuator) -> None:
        from grandpa.skills.registry.defaults import _pc_action

        run = _pc_action("desktop_summary", "desktop")
        for source in (*AGENT_SOURCES, *SKILL_SOURCES):
            run({}, _context(source))

        assert set(actuator.origins) <= set(ACTION_ORIGINS)
        assert set(actuator.origins) == {"agent", "skill"}
