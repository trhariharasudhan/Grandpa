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

import asyncio
from types import SimpleNamespace

import pytest

from grandpa.desktop.kernel.requests import coerce_request
from grandpa.desktop.kernel.risk import classify, requires_approval
from grandpa.pc_control import (
    ACTION_ORIGINS,
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


class TestOriginIsCarried:
    """``origin`` has landed on ``LocalActionRequest`` (AD-022).

    This class replaces ``TestOriginIsNotYetCarried``, which pinned the absence
    of provenance and instructed that its failure was the signal to update this
    module rather than a regression. That signal has now fired.

    One deliberate deviation from what that note asked for. It said origin
    should be "required, with no default, failing closed when absent", matching
    ACTION_ORIGIN_AUDIT.md recommendation 3. It ships with a default of
    ``direct`` instead, because a required field with no default is a breaking
    change for every existing construction site and payload, and this slice was
    scoped to preserve backward compatibility.

    The safety consequence is bounded: origin is currently provenance only. No
    policy decision reads it, so a defaulted origin cannot grant anything -- and
    ``direct`` is the least-privileged label, so an untagged caller is never
    recorded as a trusted one. Making it required is a separate, deliberate
    breaking change, and Q-10 (should agent-origin actions face a lower approval
    threshold?) is still open.
    """

    def test_request_carries_origin(self):
        request = coerce_request(_skill_payload("open_app", target="notepad"))
        assert hasattr(request, "origin")

    def test_origin_defaults_to_direct_for_untagged_callers(self):
        request = coerce_request(_skill_payload("open_app", target="notepad"))
        assert request.origin == "direct"

    def test_origin_round_trips_through_coercion(self):
        payload = dict(_skill_payload("open_app", target="notepad"))
        payload["origin"] = "agent"
        assert coerce_request(payload).origin == "agent"

    def test_unknown_origin_is_downgraded_not_trusted(self):
        payload = dict(_skill_payload("open_app", target="notepad"))
        payload["origin"] = "kernel"
        assert coerce_request(payload).origin == "direct"

    def test_origin_does_not_change_the_policy_decision(self):
        """Provenance is recorded, not yet acted on.

        Risk must still be computed from the action alone -- the property the
        original invariant suite exists to protect. If a future origin-aware
        policy lands (Q-10), this is the test that must be revisited
        deliberately rather than drift.
        """
        as_user = run_local_action(
            {**_skill_payload("open_folder", target="."), "origin": "voice"}
        )
        as_agent = run_local_action(
            {**_skill_payload("open_folder", target="."), "origin": "agent"}
        )
        assert as_user.risk_level == as_agent.risk_level
        assert as_user.approval_required == as_agent.approval_required


# ---------------------------------------------------------------------------
# Q-10 -- the provenance-agnostic invariant
# ---------------------------------------------------------------------------

#: Actions chosen to span every consequence tier the classifier produces and
#: both approval states. ``open_app terminal`` is here deliberately: it is the
#: sensitive-launch clause that ``requires_approval`` records as having once
#: drifted out of step with enforcement, so it is the clause most worth holding
#: still. The spread is asserted rather than assumed -- see the non-vacuity
#: guards at the end of the class.
ORIGIN_PROBE_ACTIONS = (
    ("open_folder", "."),
    ("open_app", "notepad"),
    ("open_app", "terminal"),
    ("file_delete", "x"),
    ("shell_run", "x"),
)


def _probe(action_type: str, target: str, origin: str):
    """A request differing from its siblings in ``origin`` and nothing else."""
    return coerce_request(
        {
            "action_type": action_type,
            "target": target,
            "args": {},
            "dry_run": True,
            "origin": origin,
        }
    )


class TestProvenanceIsAuditOnly:
    """Q-10 ANSWERED: origin is recorded, never consumed by policy.

    ``TestOriginIsCarried.test_origin_does_not_change_the_policy_decision``
    already pins this for one pair of origins on one action, and is deliberately
    left in place: its docstring is the marker saying which test must be
    revisited if an origin-aware policy ever lands. This class is the
    generalisation the Q-10 audit concluded should hold -- every value in the
    vocabulary, across every consequence tier.

    The policy path here is the real one. ``classify`` and ``requires_approval``
    are the production predicates ``run_local_action`` itself calls; nothing is
    stubbed and no constant is asserted against. The end-to-end case goes
    through ``run_local_action`` on a LOW, non-staging action so the suite never
    writes an approval record.

    Q-10's answer is *no*: agent- and skill-originated actions do not face a
    different threshold, and neither does any other origin. If that is ever
    revisited, it must be by changing these tests deliberately.
    """

    @pytest.mark.parametrize("action_type,target", ORIGIN_PROBE_ACTIONS)
    def test_risk_is_identical_for_every_origin(self, action_type, target) -> None:
        tiers = {
            origin: classify(_probe(action_type, target, origin))
            for origin in ACTION_ORIGINS
        }

        assert len(set(tiers.values())) == 1, tiers

    @pytest.mark.parametrize("action_type,target", ORIGIN_PROBE_ACTIONS)
    def test_approval_requirement_is_identical_for_every_origin(
        self, action_type, target
    ) -> None:
        gates = {
            origin: requires_approval(_probe(action_type, target, origin))
            for origin in ACTION_ORIGINS
        }

        assert len(set(gates.values())) == 1, gates

    @pytest.mark.parametrize("origin", ACTION_ORIGINS)
    def test_no_origin_can_clear_a_gate_the_action_sets(self, origin: str) -> None:
        """The monotonicity precedent, extended to provenance.

        ``test_require_approval_can_only_raise_never_lower`` pins that a
        caller-supplied ``require_approval=False`` cannot clear a gate. The same
        must hold for provenance: no origin may be a way in through the side.
        """
        request = coerce_request(
            {
                "action_type": "file_delete",
                "target": "x",
                "args": {},
                "dry_run": True,
                "require_approval": False,
                "origin": origin,
            }
        )

        assert requires_approval(request) is True

    def test_run_local_action_reports_one_decision_for_every_origin(self) -> None:
        """End to end, not just through the predicates.

        ``open_folder`` is LOW and stages nothing, so this runs the full
        boundary without creating a pending approval row.
        """
        responses = {
            origin: run_local_action(
                {
                    "action_type": "open_folder",
                    "target": ".",
                    "args": {},
                    "dry_run": True,
                    "origin": origin,
                }
            )
            for origin in ACTION_ORIGINS
        }

        assert len({r.risk_level for r in responses.values()}) == 1
        assert len({r.approval_required for r in responses.values()}) == 1

    # -- non-vacuity guards --------------------------------------------------
    #
    # The invariant above is an equality across origins. Equality holds
    # trivially if the probe set collapses onto one tier, so the spread is
    # asserted rather than trusted.

    def test_the_probe_set_spans_more_than_one_risk_tier(self) -> None:
        tiers = {
            classify(_probe(action_type, target, "direct"))
            for action_type, target in ORIGIN_PROBE_ACTIONS
        }

        assert len(tiers) >= 3, tiers

    def test_the_probe_set_covers_both_approval_states(self) -> None:
        gates = {
            requires_approval(_probe(action_type, target, "direct"))
            for action_type, target in ORIGIN_PROBE_ACTIONS
        }

        assert gates == {True, False}

    def test_every_shipped_origin_is_exercised(self) -> None:
        """If the vocabulary grows, these tests must grow with it."""
        assert len(ACTION_ORIGINS) == 6
        assert set(ACTION_ORIGINS) == {
            "voice",
            "agent",
            "direct",
            "api",
            "scheduler",
            "skill",
        }


class TestOriginIsNotForgeableByItsSubject:
    """Provenance a caller can set is not provenance.

    Neither boundary is a policy input today, which is exactly why both are
    worth pinning now: they are cheap to preserve while origin is audit-only and
    expensive to reintroduce if Q-10 is ever reversed. The route's own comment
    makes the same argument -- it "stops being cosmetic the moment Q-10 is
    answered yes".

    Both tests substitute ``run_local_action`` and assert on the payload it was
    handed, so nothing actuates, no request leaves the process, and no approval
    record is written.
    """

    @staticmethod
    def _capture(monkeypatch, seen: dict) -> None:
        from grandpa import pc_control

        def _fake(payload):
            seen.update(payload)
            return SimpleNamespace(
                ok=True,
                status="dry_run",
                message="",
                evidence={},
                action_id=None,
                risk_level="LOW",
                approval_required=False,
                error=None,
                to_dict=lambda: {"ok": True},
            )

        monkeypatch.setattr(pc_control, "run_local_action", _fake)

    # -- A. the HTTP boundary ------------------------------------------------

    def test_http_route_overwrites_a_client_supplied_origin(self, monkeypatch) -> None:
        from grandpa.server.routes import run_structured_local_action

        seen: dict = {}
        self._capture(monkeypatch, seen)

        asyncio.run(
            run_structured_local_action(
                {
                    "action_type": "open_folder",
                    "target": ".",
                    "dry_run": True,
                    "origin": "voice",
                }
            )
        )

        assert seen["origin"] == "api"

    def test_http_route_stamps_api_when_the_body_names_none(self, monkeypatch) -> None:
        from grandpa.server.routes import run_structured_local_action

        seen: dict = {}
        self._capture(monkeypatch, seen)

        asyncio.run(
            run_structured_local_action(
                {"action_type": "open_folder", "target": ".", "dry_run": True}
            )
        )

        assert seen["origin"] == "api"

    def test_http_route_passes_the_rest_of_the_body_through(self, monkeypatch) -> None:
        """The overwrite is scoped to provenance and touches nothing else."""
        from grandpa.server.routes import run_structured_local_action

        seen: dict = {}
        self._capture(monkeypatch, seen)

        asyncio.run(
            run_structured_local_action(
                {
                    "action_type": "open_folder",
                    "target": "somewhere",
                    "args": {"depth": 2},
                    "dry_run": True,
                    "origin": "voice",
                }
            )
        )

        assert seen["action_type"] == "open_folder"
        assert seen["target"] == "somewhere"
        assert seen["args"] == {"depth": 2}
        assert seen["dry_run"] is True

    # -- B. the skill boundary -----------------------------------------------

    def test_skill_params_cannot_override_the_skill_origin(self, monkeypatch) -> None:
        from grandpa.skills.registry.defaults import _pc_action
        from grandpa.skills.runtime import SkillExecutionContext

        seen: dict = {}
        self._capture(monkeypatch, seen)

        _pc_action("open_folder", target=".")(
            {"origin": "direct", "target": "."},
            SkillExecutionContext(dry_run=True),
        )

        assert seen["origin"] == "skill"

    def test_skill_origin_is_stamped_when_params_name_none(self, monkeypatch) -> None:
        from grandpa.skills.registry.defaults import _pc_action
        from grandpa.skills.runtime import SkillExecutionContext

        seen: dict = {}
        self._capture(monkeypatch, seen)

        _pc_action("open_folder", target=".")(
            {"target": "."}, SkillExecutionContext(dry_run=True)
        )

        assert seen["origin"] == "skill"

    def test_skill_still_honours_params_for_everything_it_owns(
        self, monkeypatch
    ) -> None:
        """Pinning origin must not freeze the fields params legitimately set.

        ``action_type`` stays fixed at registration -- that is a separate,
        already-closed truth-in-advertising gap -- while ``target``, ``args``
        and ``dry_run`` remain caller-supplied.
        """
        from grandpa.skills.registry.defaults import _pc_action
        from grandpa.skills.runtime import SkillExecutionContext

        seen: dict = {}
        self._capture(monkeypatch, seen)

        _pc_action("open_folder", target="default")(
            {"target": "chosen", "args": {"depth": 3}, "dry_run": True},
            SkillExecutionContext(dry_run=False),
        )

        assert seen["action_type"] == "open_folder"
        assert seen["target"] == "chosen"
        assert seen["args"] == {"depth": 3}
        assert seen["dry_run"] is True
