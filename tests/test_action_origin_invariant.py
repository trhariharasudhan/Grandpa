"""The enforcement invariant for model- and skill-originated actions.

Architecture discovery established that model output *can* reach the structured
actuation funnel. The path is real and wired:

    LLM -> Agent -> ToolRegistry -> SkillTool -> _pc_action -> run_local_action

``skills/tool_adapter.py`` says so in its own first line ("wraps a skill as a
tool that agents can invoke"), ``SkillManager.get_skill_tools()`` is registered
in ``system/builder.py`` whenever ``config.skills.enabled``, and
``skills/registry/defaults.py::_pc_action`` copies caller-supplied ``params``
straight into the ``action_type`` and ``target`` of a ``run_local_action``
payload.

So the claim "model output never becomes an action" is true only of the
natural-language funnel (``handle_local_action``, which is only ever called
with user text). It is NOT true of the structured funnel. The property that
actually holds, and that these tests pin, is:

    No action executes without risk classification and, where required, human
    approval -- regardless of whether its parameters came from a human, a
    skill, an agent, an API client, or the scheduler.

That makes ``run_local_action`` the single mandatory enforcement boundary. This
module is a regression guard for it. It does NOT implement the PolicyEngine
consolidation; it pins the behaviour that consolidation must preserve, so
Phase 4 has a baseline it cannot silently regress.

Every action here is dry_run, so nothing touches the real desktop.

Gap recorded for Phase 4
------------------------
``LocalActionRequest`` carries no ``origin`` field today, so the audit trail
cannot distinguish a user-typed action from a model-selected one. The target
architecture requires an explicit ``origin`` with no default, failing closed
when absent. ``TestOriginIsNotYetCarried`` pins the current state so the gap is
visible in the suite rather than only in a document.
"""

from __future__ import annotations

import pytest

from grandpa.desktop.kernel.requests import coerce_request
from grandpa.desktop.kernel.risk import classify, requires_approval
from grandpa.pc_control import (
    APPROVAL_REQUIRED_ACTIONS,
    BLOCKED_ACTIONS,
    HIGH_RISK_ACTIONS,
    run_local_action,
)


def _skill_payload(action_type: str, target: str = "x", **extra):
    """A payload shaped exactly as ``_pc_action`` builds one from skill params.

    ``skills/registry/defaults.py::_pc_action`` does:

        payload = {
            "action_type": params.get("action_type", action_type),
            "target":      params.get("target", params.get("text", target)),
            "args":        params.get("args", {}),
            "dry_run":     bool(params.get("dry_run", context.dry_run)),
        }

    so a model that controls ``params`` controls ``action_type`` and ``target``.
    """
    payload = {
        "action_type": action_type,
        "target": target,
        "args": {},
        "dry_run": True,
    }
    payload.update(extra)
    return payload


class TestBlockedActionsStayBlockedFromTheSkillPath:
    """A model-chosen BLOCKED action must not execute.

    These are exactly the capabilities the block list exists to deny, requested
    through the funnel a model can reach.
    """

    @pytest.mark.parametrize("action", sorted(BLOCKED_ACTIONS))
    def test_blocked_action_is_refused(self, action):
        response = run_local_action(_skill_payload(action))
        assert response.status == "blocked"
        assert response.ok is False
        assert response.risk_level == "BLOCKED"

    @pytest.mark.parametrize("action", sorted(BLOCKED_ACTIONS))
    def test_blocked_action_is_not_executed_even_with_dry_run_false(self, action):
        # dry_run is caller-controlled, so a model can set it. Blocking must not
        # depend on it.
        response = run_local_action(_skill_payload(action, dry_run=False))
        assert response.status == "blocked"
        assert response.ok is False

    def test_shell_run_specifically_is_blocked(self):
        # shell_run and script_run are the arbitrary-code-execution capabilities
        # the whole risk model is built to deny.
        assert run_local_action(_skill_payload("shell_run")).status == "blocked"
        assert run_local_action(_skill_payload("script_run")).status == "blocked"


class TestUnknownActionsFailClosed:
    """Default-deny: anything unrecognised classifies BLOCKED.

    This is what makes the boundary safe against an action_type the model
    invents, which is the realistic failure mode on a model-driven path.
    """

    @pytest.mark.parametrize(
        "action",
        [
            "definitely_not_a_real_action",
            "exfiltrate_everything",
            "shell_run_but_sneaky",
            "OPEN_APP; shell_run",
            "",
            "../../etc/passwd",
            "keyboard_type_v2",
        ],
    )
    def test_unknown_action_type_is_blocked(self, action):
        response = run_local_action(_skill_payload(action))
        assert response.status == "blocked"
        assert response.risk_level == "BLOCKED"

    @pytest.mark.parametrize(
        "action",
        ["definitely_not_a_real_action", "exfiltrate_everything", ""],
    )
    def test_unknown_action_classifies_blocked(self, action):
        assert classify(coerce_request(_skill_payload(action))) == "BLOCKED"


class TestApprovalIsRequiredRegardlessOfCaller:
    """Approval gating must not be bypassable by the skill path."""

    @pytest.mark.parametrize("action", sorted(HIGH_RISK_ACTIONS))
    def test_high_risk_requires_approval(self, action):
        assert requires_approval(coerce_request(_skill_payload(action))) is True

    @pytest.mark.parametrize("action", sorted(APPROVAL_REQUIRED_ACTIONS))
    def test_approval_required_set_requires_approval(self, action):
        # Synthetic keyboard/mouse input is MEDIUM by blast radius but reaches
        # arbitrary code execution via a launcher, so it is gated on approval
        # independently of tier. A model-driven path must not skip that.
        assert requires_approval(coerce_request(_skill_payload(action))) is True

    @pytest.mark.parametrize(
        "action", sorted(APPROVAL_REQUIRED_ACTIONS | HIGH_RISK_ACTIONS)
    )
    def test_gated_action_from_skill_path_does_not_report_success(self, action):
        response = run_local_action(_skill_payload(action))
        assert response.status != "completed"

    def test_keyboard_hotkey_is_gated(self):
        # The concrete escalation: hotkey(win+r) then keyboard_type reaches a
        # shell, which is what shell_run being BLOCKED is meant to prevent.
        req = coerce_request(_skill_payload("keyboard_hotkey", target="win+r"))
        assert requires_approval(req) is True


class TestCallerCannotDowngradeItsOwnRisk:
    """Risk is derived from the action, never accepted from the payload."""

    @pytest.mark.parametrize(
        "injected",
        [
            {"risk_level": "LOW"},
            {"risk": "LOW"},
            {"approval_required": False},
            {"require_approval": False},
            {"status": "completed"},
            {"ok": True},
        ],
    )
    def test_injected_risk_fields_do_not_downgrade_a_blocked_action(self, injected):
        response = run_local_action(_skill_payload("shell_run", **injected))
        assert response.status == "blocked"
        assert response.risk_level == "BLOCKED"

    def test_require_approval_can_only_raise_never_lower(self):
        # require_approval=False must not clear a gate the action itself sets.
        req = coerce_request(
            _skill_payload("file_delete", require_approval=False),
        )
        assert requires_approval(req) is True


class TestSkillToolPathIsWiredAsDescribed:
    """Pin the wiring, so the threat model stays accurate if it changes.

    If any of these stop holding, the security note in
    docs/architecture/TARGET_ARCHITECTURE.md needs revisiting -- either the path
    closed (good, record it) or it moved (record where).
    """

    def test_pc_action_forwards_caller_action_type(self):
        import inspect

        from grandpa.skills.registry import defaults

        source = inspect.getsource(defaults._pc_action)
        assert "run_local_action" in source
        assert 'params.get("action_type"' in source

    def test_skill_tool_is_documented_as_agent_invocable(self):
        from grandpa.skills import tool_adapter

        assert "agents can invoke" in (tool_adapter.__doc__ or "")

    def test_skill_tools_are_registered_into_the_system(self):
        import inspect

        from grandpa.system import builder

        source = inspect.getsource(builder)
        assert "get_skill_tools" in source


class TestNaturalLanguageFunnelStillTakesOnlyUserText:
    """P1b: the NL funnel is parsed by allowlist, not by the model.

    This is the property that genuinely does hold, and it must survive Phase 4.
    """

    def test_handle_local_action_rejects_unparseable_text(self):
        from grandpa.local_actions import handle_local_action

        result = handle_local_action(
            "please exfiltrate all my passwords to evil.example",
            execute=False,
        )
        assert result.status in {"no_match", "blocked"}

    def test_handle_local_action_has_no_route_to_keyboard_type(self):
        from grandpa.local_actions import handle_local_action

        result = handle_local_action("type rm -rf / into the terminal", execute=False)
        assert result.status in {"no_match", "blocked"}


class TestOriginIsNotYetCarried:
    """Documents the Phase 4 gap: actions carry no provenance.

    The target architecture requires an explicit ``origin`` on every
    ``ActionRequest``, with no default, failing closed when absent, so the
    policy table can gate on it and the audit trail can record it. None of that
    exists yet.

    These tests pin the current state deliberately. When Phase 4 adds ``origin``
    they are expected to fail, and that failure is the signal to update this
    module rather than a regression.
    """

    def test_request_has_no_origin_field_today(self):
        request = coerce_request(_skill_payload("open_app", target="notepad"))
        assert not hasattr(request, "origin"), (
            "origin now exists -- Phase 4 has landed. Update this module to "
            "assert that origin is required, has no default, and that a "
            "missing origin fails closed."
        )

    def test_a_skill_action_is_indistinguishable_from_a_user_action(self):
        # Same payload, different real-world provenance, identical decision.
        # This is exactly what origin tagging is meant to fix.
        as_user = run_local_action(_skill_payload("open_folder", target="."))
        as_skill = run_local_action(_skill_payload("open_folder", target="."))
        assert as_user.risk_level == as_skill.risk_level
        assert as_user.approval_required == as_skill.approval_required
