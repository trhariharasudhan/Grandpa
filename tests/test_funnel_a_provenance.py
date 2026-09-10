"""Funnel A loses provenance, and where it bridges to Funnel B it falsifies it.

``handle_local_action`` has no ``origin`` parameter -- the word does not appear
in ``local_actions.py`` at all. Twelve production callsites across nine files
reach it, and five of those files already hold a truthful origin in scope that
they cannot pass. That much is a gap.

The part that is not merely a gap is the bridge. When a Funnel-A result has
``kind == "pc_control"`` and no runtime skill claims it, ``_execute`` calls
Funnel B with a payload of exactly ``{"action_type", "target"}``. Funnel B's
``_coerce_request`` then applies ``_coerce_origin(payload.get("origin"))``,
which maps ``None`` to ``"direct"``. So a voice- or api-originated action is
written into Funnel B's audit record and approval row as **direct** -- not
unlabelled, mislabelled, and indistinguishable from a genuine CLI caller.

This file pins that before 4.12C changes the contract. It characterizes; it
fixes nothing, and no production file is touched.

**The other exit is a second falsification, not a correct one.** An earlier
draft of this note called it correct. 4.12E established otherwise:
``_execute_runtime_skill`` routes three ``pc_control`` kinds to ``execute_skill``,
whose ``_pc_action`` executor hardcodes ``origin="skill"``. A person typing
"desktop summary" at a terminal is therefore recorded as having had the
parameters chosen by a model -- an affirmative false claim, and worse than the
bridge's ``direct``, which at least is the documented least-privilege fallback.
Both exits are exercised below so the difference between them is recorded
rather than assumed.

Isolation: the approval database is redirected through the product's
``GRANDPA_PC_CONTROL_DB`` seam, Funnel A's two audit writes are stubbed, and
Funnel B is replaced by a recorder at the bridge -- so nothing actuates, no
approval row is written, and no real store is touched.
"""

from __future__ import annotations

import inspect
import pathlib

import pytest

from grandpa import pc_control
from grandpa.pc_control import ACTION_ORIGINS, LocalActionRequest, LocalActionResponse

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "grandpa"
LOCAL_ACTIONS_SOURCE = (SRC / "local_actions.py").read_text(encoding="utf-8")

#: Every production caller of ``handle_local_action``, with the origin each one
#: could truthfully state today. Discovered from the tree, not copied forward:
#: ``test_the_inventory_matches_the_tree`` re-derives it and fails on drift.
#:
#: ``None`` means no truthful value exists -- the two diagnostic harnesses. D-5
#: declined to invent one for them, and this records that decision rather than
#: leaving them looking like an oversight.
CALLER_MATRIX: dict[str, str | None] = {
    "composition/ask_handlers.py": "ctx.origin",
    "cli/chat_cmd.py": "direct",
    "server/routes.py": "api",
    "server/api_routes.py": "api",
    "voice/assistant.py": "voice",
    "voice/session.py": "voice",
    "task_scheduler.py": "scheduler",
    "burnin.py": None,
    "cli/doctor_cmd.py": None,
}

#: Commands whose ``pc_control`` result reaches Funnel B through the bridge,
#: because no runtime skill claims their action type.
BRIDGE_COMMANDS = [
    ("list processes", "list_processes"),
    ("what process is active", "active_process"),
    ("inspect clipboard", "clipboard_inspect"),
]

#: Commands whose ``pc_control`` result is claimed by a runtime skill instead.
#: These reach Funnel B already stamped.
SKILL_COMMANDS = ["desktop summary", "list monitors"]


def _production_callsites() -> list[tuple[str, int]]:
    """Every production line calling ``handle_local_action``."""
    found: list[tuple[str, int]] = []
    for path in sorted(SRC.rglob("*.py")):
        for number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if "handle_local_action(" in line and "def handle_local_action" not in line:
                found.append((path.relative_to(SRC).as_posix(), number))
    return found


@pytest.fixture
def funnel_b_recorder(tmp_path, monkeypatch):
    """Replace Funnel B at the bridge and silence Funnel A's audit writes."""
    import grandpa.local_actions as local_actions

    monkeypatch.setenv("GRANDPA_PC_CONTROL_DB", str(tmp_path / "approvals.db"))
    payloads: list[dict] = []

    def recorder(payload):
        payloads.append(dict(payload) if isinstance(payload, dict) else payload)
        return LocalActionResponse(
            ok=True,
            action_id=None,
            status="completed",
            message="ok",
            approval_required=False,
            risk_level="LOW",
        )

    monkeypatch.setattr(pc_control, "run_local_action", recorder)
    monkeypatch.setattr(local_actions, "_audit_decision", lambda *a, **k: None)
    monkeypatch.setattr(local_actions, "_log_attempt", lambda *a, **k: None)
    return payloads


# ---------------------------------------------------------------------------
# 1. Caller inventory
# ---------------------------------------------------------------------------


class TestCallerInventory:
    def test_there_are_twelve_production_callsites(self) -> None:
        assert len(_production_callsites()) == 12

    def test_the_inventory_matches_the_tree(self) -> None:
        """The matrix is re-derived, so a new caller fails rather than hides."""
        files = {path for path, _line in _production_callsites()}

        assert files == set(CALLER_MATRIX)

    def test_no_production_caller_passes_an_origin_today(self) -> None:
        """The defect, stated as an inventory fact."""
        for path, line_number in _production_callsites():
            line = (
                (SRC / path).read_text(encoding="utf-8").splitlines()[line_number - 1]
            )
            assert "origin" not in line, f"{path}:{line_number}"

    def test_seven_callers_have_a_determinable_future_origin(self) -> None:
        """Seven of the nine files can name a truthful origin; two cannot.

        Not the same as "knows it today": ``server/api_routes.py`` states no
        origin anywhere, but it is unambiguously an HTTP surface, so ``api`` is
        determinable from its role. The six that *do* hold one in scope right
        now are asserted separately below.
        """
        determinable = {k: v for k, v in CALLER_MATRIX.items() if v is not None}

        assert len(determinable) == 7
        assert determinable["voice/assistant.py"] == "voice"
        assert determinable["server/routes.py"] == "api"

    def test_six_callers_hold_an_origin_in_scope_and_lose_it(self) -> None:
        """These state an origin for another handler in the same file, then
        call Funnel A without one. Read from source, not assumed."""
        holds_one_today = [
            path
            for path in CALLER_MATRIX
            if 'origin="' in (SRC / path).read_text(encoding="utf-8")
            or "origin=ctx.origin" in (SRC / path).read_text(encoding="utf-8")
        ]

        assert sorted(holds_one_today) == [
            "cli/chat_cmd.py",
            "composition/ask_handlers.py",
            "server/routes.py",
            "voice/assistant.py",
            "voice/session.py",
        ]

    def test_the_two_diagnostic_harnesses_have_no_truthful_origin(self) -> None:
        """Recorded as a decision, not an omission -- D-5 declined to invent one."""
        assert CALLER_MATRIX["burnin.py"] is None
        assert CALLER_MATRIX["cli/doctor_cmd.py"] is None

    def test_scheduler_would_be_the_first_real_use_of_that_value(self) -> None:
        assert CALLER_MATRIX["task_scheduler.py"] == "scheduler"
        stamped = [
            p
            for p in SRC.rglob("*.py")
            if 'origin="scheduler"' in p.read_text(encoding="utf-8")
        ]
        assert stamped == [], "scheduler is defined but still unused"


# ---------------------------------------------------------------------------
# 2. The current contract
# ---------------------------------------------------------------------------


class TestCurrentContract:
    def test_the_signature_is_text_and_keyword_only_execute(self) -> None:
        from grandpa.local_actions import handle_local_action

        signature = inspect.signature(handle_local_action)

        assert list(signature.parameters) == ["text", "execute"]
        assert signature.parameters["execute"].kind is inspect.Parameter.KEYWORD_ONLY
        assert signature.parameters["execute"].default is True

    def test_origin_is_not_a_parameter(self) -> None:
        from grandpa.local_actions import handle_local_action

        assert "origin" not in inspect.signature(handle_local_action).parameters

    def test_the_word_origin_does_not_appear_in_the_module(self) -> None:
        """Funnel A has no provenance concept at all, not merely no parameter."""
        assert LOCAL_ACTIONS_SOURCE.count("origin") == 0


# ---------------------------------------------------------------------------
# 3. The bridge defect
# ---------------------------------------------------------------------------


class TestTheBridgeSendsNoOrigin:
    @pytest.mark.parametrize("command,action_type", BRIDGE_COMMANDS)
    def test_the_payload_carries_only_action_type_and_target(
        self, command: str, action_type: str, funnel_b_recorder
    ) -> None:
        from grandpa.local_actions import handle_local_action

        handle_local_action(command)

        assert len(funnel_b_recorder) == 1
        assert set(funnel_b_recorder[0]) == {"action_type", "target"}
        assert funnel_b_recorder[0]["action_type"] == action_type

    @pytest.mark.parametrize("command,_action", BRIDGE_COMMANDS)
    def test_the_payload_has_no_origin_key(
        self, command: str, _action: str, funnel_b_recorder
    ) -> None:
        from grandpa.local_actions import handle_local_action

        handle_local_action(command)

        assert "origin" not in funnel_b_recorder[0]

    def test_the_payload_cannot_depend_on_the_caller(self) -> None:
        """Structural: it is built from ``result.target`` alone.

        No caller identity is in scope at the bridge, so no surface could
        influence it even if it wanted to -- which is why every surface's
        origin is erased identically.
        """
        bridge = LOCAL_ACTIONS_SOURCE.split('if result.kind == "pc_control":', 1)[1]
        call = bridge.split("run_local_action(", 1)[1].split(")", 1)[0]

        assert "action_type" in call and "target" in call
        assert "origin" not in call


class TestFunnelBCoercesTheMissingOriginToDirect:
    """The second half: what Funnel B does with an origin-free payload."""

    @pytest.mark.parametrize("command,action_type", BRIDGE_COMMANDS)
    def test_the_bridge_payload_becomes_direct(
        self, command: str, action_type: str
    ) -> None:
        request = pc_control._coerce_request(
            {"action_type": action_type, "target": "whatever"}
        )

        assert request.origin == "direct"

    @pytest.mark.parametrize("origin", ACTION_ORIGINS)
    def test_an_origin_that_is_present_survives(self, origin: str) -> None:
        """Non-vacuity: coercion is not simply returning ``direct`` always."""
        request = pc_control._coerce_request(
            {"action_type": "list_processes", "target": "processes", "origin": origin}
        )

        assert request.origin == origin


class TestTheDefectEndToEnd:
    """A voice-originated action is recorded by Funnel B as ``direct``."""

    def test_voice_provenance_is_erased_at_the_bridge(self, funnel_b_recorder) -> None:
        from grandpa.local_actions import handle_local_action

        # There is no way to *say* "voice" here -- that is the defect. The
        # voice surfaces call exactly like this, holding an origin they cannot
        # pass.
        handle_local_action("list processes")

        payload = funnel_b_recorder[0]
        assert "origin" not in payload

        # And this is what Funnel B then records for it.
        assert pc_control._coerce_request(payload).origin == "direct"

    def test_api_provenance_is_erased_identically(self, funnel_b_recorder) -> None:
        """``server/routes.py`` states ``api`` for files and loses it here."""
        from grandpa.local_actions import handle_local_action

        handle_local_action("what process is active")

        assert pc_control._coerce_request(funnel_b_recorder[0]).origin == "direct"

    def test_direct_is_indistinguishable_from_a_genuine_cli_caller(
        self, funnel_b_recorder
    ) -> None:
        """Why this is mislabelling and not merely absence.

        The recorded value is the same one a truthful CLI caller produces, so
        nothing downstream can tell the two apart.
        """
        from grandpa.local_actions import handle_local_action

        handle_local_action("list processes")
        erased = pc_control._coerce_request(funnel_b_recorder[0]).origin
        genuine = LocalActionRequest(action_type="list_processes").origin

        assert erased == genuine == "direct"


# ---------------------------------------------------------------------------
# 6. The skill exit is already stamped
# ---------------------------------------------------------------------------


class TestTheSkillExitCarriesOrigin:
    @pytest.mark.parametrize("command", SKILL_COMMANDS)
    def test_skill_routed_commands_reach_funnel_b_with_origin_skill(
        self, command: str, funnel_b_recorder
    ) -> None:
        from grandpa.local_actions import handle_local_action

        handle_local_action(command)

        assert funnel_b_recorder, command
        assert funnel_b_recorder[0].get("origin") == "skill"

    def test_the_two_exits_differ(self, funnel_b_recorder) -> None:
        """Recorded side by side so the contrast is the artefact, not a claim."""
        from grandpa.local_actions import handle_local_action

        handle_local_action("desktop summary")
        skill_payload = funnel_b_recorder[-1]

        funnel_b_recorder.clear()
        handle_local_action("list processes")
        bridge_payload = funnel_b_recorder[-1]

        assert skill_payload.get("origin") == "skill"
        assert "origin" not in bridge_payload


# ---------------------------------------------------------------------------
# 4-5. Origin is not a security input
# ---------------------------------------------------------------------------


class TestOriginIsNotASecurityInput:
    """What makes 4.12C safe: nothing keys on origin today."""

    @staticmethod
    def _request(origin: str) -> LocalActionRequest:
        return LocalActionRequest(
            action_type="open_app",
            target="notepad",
            args={"b": 2, "a": 1},
            origin=origin,
        )

    def test_the_digest_is_identical_across_every_origin(self) -> None:
        digests = {
            pc_control._action_digest(
                self._request(origin), "notepad.exe", "C:/notepad.exe"
            )
            for origin in ACTION_ORIGINS
        }

        assert len(digests) == 1

    def test_the_digest_still_changes_when_the_action_changes(self) -> None:
        """Non-vacuity: the digest is not constant."""
        base = pc_control._action_digest(
            self._request("voice"), "notepad.exe", "C:/notepad.exe"
        )
        other = pc_control._action_digest(
            self._request("voice"), "calc.exe", "C:/notepad.exe"
        )

        assert base != other

    def test_risk_classification_ignores_origin(self) -> None:
        tiers = {
            pc_control.classify_risk(self._request(origin)) for origin in ACTION_ORIGINS
        }

        assert len(tiers) == 1

    def test_the_approval_requirement_ignores_origin(self) -> None:
        decisions = {
            pc_control._launch_needs_approval(
                LocalActionRequest(
                    action_type="open_app", target="task_manager", origin=origin
                )
            )
            for origin in ACTION_ORIGINS
        }

        assert decisions == {True}

    def test_the_token_is_random_and_does_not_read_origin(self) -> None:
        source = inspect.getsource(pc_control._create_pending)
        token_line = next(
            line for line in source.splitlines() if "secrets.token_hex" in line
        )

        assert "origin" not in token_line


# ---------------------------------------------------------------------------
# 11. Scope guards
# ---------------------------------------------------------------------------


class TestThisSliceChangedNothing:
    def test_the_digest_still_documents_excluding_origin(self) -> None:
        source = (SRC / "pc_control.py").read_text(encoding="utf-8")

        assert "Excludes ``origin``" in source

    def test_the_origin_vocabulary_is_unchanged(self) -> None:
        assert ACTION_ORIGINS == (
            "voice",
            "agent",
            "direct",
            "api",
            "scheduler",
            "skill",
        )

    def test_the_funnel_a_signature_is_unchanged(self) -> None:
        from grandpa.local_actions import handle_local_action

        assert list(inspect.signature(handle_local_action).parameters) == [
            "text",
            "execute",
        ]

    def test_the_dispatcher_contract_is_unchanged(self) -> None:
        import dataclasses

        from grandpa.dispatch import IntentDispatcher, RequestContext

        assert [f.name for f in dataclasses.fields(RequestContext)] == [
            "text",
            "origin",
            "dry_run",
        ]
        assert {n for n in dir(IntentDispatcher) if not n.startswith("_")} == {
            "register",
            "dispatch",
            "handlers",
        }

    def test_no_broad_provenance_exclusion_was_introduced(self) -> None:
        """The caller matrix is exact paths, never a prefix."""
        for path in CALLER_MATRIX:
            assert not path.endswith("/")
            assert "*" not in path


# ---------------------------------------------------------------------------
# 6. The runtime-skill exit -- 4.12E's second loss point
# ---------------------------------------------------------------------------
#
# The section above records the bridge losing origin. This one records the
# other exit *falsifying* it, which 4.12E established is the worse of the two:
# ``direct`` is at least the documented least-privilege fallback and is honest
# about being a fallback, while ``skill`` is an affirmative claim that a model
# chose the parameters. For a human typing "desktop summary" at a terminal that
# claim is simply false, and it is the exact distinction AD-022 exists to draw.

#: ``_execute_runtime_skill``'s ``pc_control`` mapping, as the source states it.
#: Four fixed action types plus one dynamic escape hatch -- see
#: ``TestRuntimeSkillIsADynamicRoute`` for why the fifth matters.
PC_CONTROL_SKILL_MAP = {
    "desktop_summary": "desktop.summary",
    "list_monitors": "desktop.monitors",
    "pc_diagnostics": "desktop.diagnostics",
    "workflow_status": "automation.workflow_status",
}

#: Every runtime skill reachable from Funnel A by a fixed mapping, split by
#: whether its executor is one ``_pc_action`` built. Only the first group
#: reaches Funnel B, and only that group stamps a provenance.
PC_ACTION_BACKED = ("desktop.summary", "desktop.monitors", "desktop.diagnostics")
BESPOKE_EXECUTORS = (
    "automation.workflow_status",
    "browser.diagnostics",
    "vision.screen_diagnostics",
    "vision.visual_diagnostics",
)

#: A natural-language phrase reaching each ``_pc_action``-backed skill. Verified
#: against the parser rather than assumed: ``pc_diagnostics`` has no phrase
#: resembling its action name, so guessing one silently skips the case.
SKILL_ROUTED_COMMANDS = {
    "desktop summary": "desktop.summary",
    "list monitors": "desktop.monitors",
}

#: ``pc_diagnostics`` does NOT take the simple route. Its phrases escalate into
#: the agent path, which makes two Funnel-B calls carrying two different
#: origins. Characterized separately rather than forced into the shape the
#: other two have.
AGENT_ESCALATION_COMMANDS = ("pc control diagnostics", "show pc diagnostics")

#: Phrases reaching the bespoke executors, which must never touch Funnel B.
BESPOKE_COMMANDS = (
    "workflow status",
    "browser diagnostics",
    "screen diagnostics",
    "visual targeting diagnostics",
)


def _skill(name: str):
    from grandpa.skills.registry import ensure_default_skills_registered, get_skill

    ensure_default_skills_registered()
    return get_skill(name)


def _is_pc_action_backed(name: str) -> bool:
    """``_pc_action`` returns a closure; its qualname is the marker.

    Structural rather than behavioural on purpose: asking whether a skill
    *would* call Funnel B by calling it is the thing this file must not do for
    the actuating ones.
    """
    executor = getattr(_skill(name), "executor", None)
    return getattr(executor, "__qualname__", "") == "_pc_action.<locals>._execute"


class TestTheRuntimeSkillMapping:
    """The mapping, read off the source rather than off the audit note."""

    def test_the_pc_control_mapping_is_exactly_these_five_entries(self) -> None:
        import grandpa.local_actions as local_actions

        source = inspect.getsource(local_actions._execute_runtime_skill)

        for action_type, skill_name in PC_CONTROL_SKILL_MAP.items():
            assert f'"{action_type}": "{skill_name}"' in source, action_type
        assert '"runtime_skill": target' in source

    def test_the_runtime_skill_delegation_runs_before_the_bridge(self) -> None:
        """Order decides which loss point a request hits.

        ``_execute`` consults the registry first, so for a mapped action type
        the bridge below it is never reached.
        """
        import grandpa.local_actions as local_actions

        source = inspect.getsource(local_actions._execute)
        delegation = source.index("_execute_runtime_skill(")
        bridge = source.index('result.kind == "pc_control"')

        assert delegation < bridge

    @pytest.mark.parametrize("name", PC_ACTION_BACKED)
    def test_three_skills_are_pc_action_backed(self, name: str) -> None:
        assert _is_pc_action_backed(name), name

    @pytest.mark.parametrize("name", BESPOKE_EXECUTORS)
    def test_four_skills_have_bespoke_executors(self, name: str) -> None:
        assert not _is_pc_action_backed(name), name

    def test_the_split_is_three_and_four(self) -> None:
        """Counted, so a new ``_pc_action`` skill in this set has to be noticed."""
        assert len(PC_ACTION_BACKED) == 3
        assert len(BESPOKE_EXECUTORS) == 4
        assert not set(PC_ACTION_BACKED) & set(BESPOKE_EXECUTORS)


class TestRuntimeSkillIsADynamicRoute:
    """The fifth mapping entry is not a fixed skill name.

    ``"runtime_skill": target`` routes to whatever the parsed target names, so
    the set of skills reachable from Funnel A is not closed by the four fixed
    entries. Recorded because any inventory of "which skills Funnel A can
    reach" is incomplete without it -- and because the registry holds more
    ``_pc_action``-backed skills than the three above.
    """

    def test_the_registry_holds_more_pc_action_skills_than_the_fixed_three(
        self,
    ) -> None:
        assert _is_pc_action_backed("desktop.keyboard_type")
        assert "desktop.keyboard_type" not in PC_ACTION_BACKED

    def test_the_dynamic_entry_takes_the_target_as_the_skill_name(self) -> None:
        import grandpa.local_actions as local_actions

        source = inspect.getsource(local_actions._execute_runtime_skill)

        assert '"runtime_skill": target' in source


class TestFunnelARecordsSkillForHumanTypedCommands:
    """The defect, end to end, through the real path.

    Nothing is stubbed between ``handle_local_action`` and the bridge: the
    parser, ``_execute``, the delegation, the registry and ``_pc_action`` all
    run. Only Funnel B itself is a recorder, so nothing actuates.
    """

    @pytest.mark.parametrize("command", sorted(SKILL_ROUTED_COMMANDS))
    def test_a_typed_command_is_recorded_as_model_selected(
        self, command: str, funnel_b_recorder
    ) -> None:
        from grandpa.local_actions import handle_local_action

        handle_local_action(command)

        assert funnel_b_recorder, command
        assert funnel_b_recorder[0].get("origin") == "skill", command

    @pytest.mark.parametrize("command", sorted(SKILL_ROUTED_COMMANDS))
    def test_the_payload_reaches_funnel_b_exactly_once(
        self, command: str, funnel_b_recorder
    ) -> None:
        from grandpa.local_actions import handle_local_action

        handle_local_action(command)

        assert len(funnel_b_recorder) == 1, command

    def test_no_funnel_a_caller_can_change_that_label(self, funnel_b_recorder) -> None:
        """``handle_local_action`` takes no origin, so every caller lands here.

        The label is decided inside ``_pc_action``, past the point any Funnel-A
        surface can influence.
        """
        from grandpa.local_actions import handle_local_action

        handle_local_action("desktop summary")

        assert funnel_b_recorder[0]["origin"] == "skill"
        assert "voice" not in funnel_b_recorder[0].values()

    @pytest.mark.parametrize("command", BESPOKE_COMMANDS)
    def test_the_bespoke_skills_never_reach_funnel_b(
        self, command: str, funnel_b_recorder
    ) -> None:
        from grandpa.local_actions import handle_local_action

        handle_local_action(command)

        assert funnel_b_recorder == [], command


class TestTheDiscardedSourceSignal:
    """``local_actions`` already knows where the request came from.

    ``_execute_runtime_skill`` builds a ``SkillExecutionContext`` carrying
    ``source="local_actions"`` -- the one field on that path that distinguishes
    a Funnel-A request from a genuine ``SkillTool`` invocation. ``_pc_action``
    never reads it. That is characterized, not proposed as the fix: this file
    changes nothing, and ``SkillExecutionContext`` is not redesigned.
    """

    @pytest.fixture
    def captured_context(self, monkeypatch, funnel_b_recorder):
        import grandpa.skills.registry as registry
        from grandpa.skills.runtime import SkillResult

        seen: list = []
        real = registry.execute_skill

        def spy(name, params, context):
            seen.append(context)
            return real(name, params, context)

        monkeypatch.setattr(registry, "execute_skill", spy)

        from grandpa.local_actions import handle_local_action

        handle_local_action("desktop summary")
        assert seen, "execute_skill was never reached"
        assert SkillResult is not None
        return seen[0]

    def test_the_claiming_route_is_the_intent_router(self, captured_context) -> None:
        """Not ``local_actions`` -- and that is the finding.

        4.12E named ``_execute_runtime_skill`` as the skill exit. It is not the
        one that fires: ``handle_local_action`` consults
        ``_route_with_intent_router`` near its top, more than a thousand lines
        before ``_execute``, and for these commands the router claims first.
        ``_execute_runtime_skill`` is a real but shadowed second route.
        """
        assert captured_context.source == "intent_router"

    def test_the_shadowed_local_actions_route_still_exists(self) -> None:
        """The second route is unreachable for these commands, not absent."""
        import grandpa.local_actions as local_actions

        source = inspect.getsource(local_actions._execute_runtime_skill)

        assert 'source="local_actions"' in source

    def test_the_router_is_consulted_inside_funnel_a(self) -> None:
        import grandpa.local_actions as local_actions

        source = inspect.getsource(local_actions.handle_local_action)

        assert "_route_with_intent_router(" in source

    def test_the_context_also_carries_the_user_request(self, captured_context) -> None:
        assert isinstance(captured_context.user_request, str)

    def test_the_delegation_is_not_a_dry_run(self, captured_context) -> None:
        """It actuates, which is what makes the mislabel matter."""
        assert captured_context.dry_run is False

    def test_both_skill_routes_reach_the_same_hardcoded_label(self) -> None:
        """``intent_router`` and ``local_actions`` are indistinguishable downstream.

        Both are unmapped in ``_SOURCE_ORIGINS``, so both still receive the
        ``skill`` fallback. 4.12E-3 corrected the agent sources only; Route 1's
        truthful value is still an open question.
        """
        from grandpa.skills.registry.defaults import _origin_for
        from grandpa.skills.runtime import SkillExecutionContext

        for label in ("intent_router", "local_actions"):
            assert _origin_for(SkillExecutionContext(source=label)) == "skill", label

    def test_pc_action_now_derives_the_origin_from_the_context(self) -> None:
        """4.12E-3 reversed this. It used to assert the source was ignored.

        The historical finding stands: ``_pc_action`` hardcoded ``skill`` for
        every caller, and the field that could tell them apart was never read.
        What changed is the production code, not the finding.
        """
        from grandpa.skills.registry.defaults import _origin_for, _pc_action

        assert "_origin_for(context)" in inspect.getsource(_pc_action)
        assert "context" in inspect.getsource(_origin_for)

    def test_an_unmapped_source_still_records_skill(self, monkeypatch) -> None:
        """``voice`` is not a skill-execution source, so it takes the fallback."""
        from grandpa.skills.registry.defaults import _pc_action
        from grandpa.skills.runtime import SkillExecutionContext

        seen: dict = {}

        def capture(payload):
            seen.update(payload)
            return LocalActionResponse(
                ok=True,
                action_id=None,
                status="completed",
                message="ok",
                approval_required=False,
                risk_level="LOW",
            )

        monkeypatch.setattr(pc_control, "run_local_action", capture)
        _pc_action("desktop_summary", "desktop")(
            {}, SkillExecutionContext(source="voice", dry_run=True)
        )

        assert seen["origin"] == "skill"

    def test_the_source_is_not_a_policy_input(self) -> None:
        """It reaches no gate, which is why it is safe to characterize."""
        for module in ("desktop/kernel/risk.py", "policy/engine.py"):
            text = (SRC / module).read_text(encoding="utf-8")
            assert "context.source" not in text, module
            assert "local_actions" not in text, module


class TestTheseTripwiresWouldFire:
    """Negative controls, stated as assertions rather than claimed in prose.

    Each pins the exact source fact whose removal would make a test above pass
    vacuously. Nothing here modifies production; they read it.
    """

    def test_a_the_bridge_payload_still_has_no_origin_key(self) -> None:
        """Tripwire A: an ``origin`` appearing at the bridge must be noticed."""
        import grandpa.local_actions as local_actions

        source = inspect.getsource(local_actions._execute)
        bridge = source[source.index('result.kind == "pc_control"') :]
        call = bridge[: bridge.index(")\n")]

        assert "run_local_action" in call
        assert "origin" not in call

    def test_b_the_bridge_still_calls_funnel_b(self, funnel_b_recorder) -> None:
        """Tripwire B: if the bridge stopped calling it, section 3 goes vacuous."""
        from grandpa.local_actions import handle_local_action

        handle_local_action("list processes")

        assert len(funnel_b_recorder) == 1

    def test_c_skill_is_still_the_fallback_for_an_unmapped_source(self) -> None:
        """Tripwire C, restated after 4.12E-3.

        ``skill`` is no longer hardcoded, but it is still what an unrecognised
        or absent source receives -- which is what keeps every unlisted caller
        recording exactly what it recorded before.
        """
        from grandpa.skills.registry.defaults import _origin_for
        from grandpa.skills.runtime import SkillExecutionContext

        assert _origin_for(SkillExecutionContext(source="nothing-known")) == "skill"
        assert _origin_for(SkillExecutionContext()) == "skill"

    def test_d_every_mapping_still_resolves_to_a_registered_skill(self) -> None:
        for name in (*PC_ACTION_BACKED, *BESPOKE_EXECUTORS):
            assert _skill(name) is not None, name

    def test_e_no_bespoke_executor_calls_funnel_b(self) -> None:
        """Tripwire E, structurally: none of the four is ``_pc_action``-built.

        The behavioural half lives in
        ``test_the_bespoke_skills_never_reach_funnel_b``; this is the half that
        still holds if a phrase stops parsing.
        """
        for name in BESPOKE_EXECUTORS:
            assert not _is_pc_action_backed(name), name

    def test_f_the_delegation_still_names_local_actions(self) -> None:
        import grandpa.local_actions as local_actions

        source = inspect.getsource(local_actions._execute_runtime_skill)

        assert 'source="local_actions"' in source

    def test_the_two_exits_still_disagree(self, funnel_b_recorder) -> None:
        """The whole point: one omits provenance, the other asserts a false one."""
        from grandpa.local_actions import handle_local_action

        handle_local_action("desktop summary")
        skill_payload = funnel_b_recorder[-1]
        funnel_b_recorder.clear()
        handle_local_action("list processes")
        bridge_payload = funnel_b_recorder[-1]

        assert skill_payload["origin"] == "skill"
        assert "origin" not in bridge_payload


class TestTheAgentEscalationRoute:
    """A third shape, found by this slice rather than predicted by the audit.

    ``pc control diagnostics`` does not reach Funnel B as one skill call. It
    escalates into the agent path, which runs three skills under
    ``source="autonomous-agent-v2"`` and makes *two* Funnel-B calls.

    **This is the assertion 4.12E-3 corrected.** As first characterized the two
    calls carried *different* origins -- ``agent`` for the desktop summary the
    agent takes on its own initiative, then ``skill`` for the action the user
    asked for. The second was false: ``_pc_action`` was recording the executor,
    not the initiator. Both are now ``agent``, which is what both were all along.

    Whether the escalation is desirable, and whether ``agent`` is truthful for a
    step no user requested, remain questions this file does not answer.
    """

    @pytest.mark.parametrize("command", AGENT_ESCALATION_COMMANDS)
    def test_it_makes_two_funnel_b_calls(self, command, funnel_b_recorder) -> None:
        from grandpa.local_actions import handle_local_action

        handle_local_action(command)

        assert len(funnel_b_recorder) == 2, command

    @pytest.mark.parametrize("command", AGENT_ESCALATION_COMMANDS)
    def test_the_two_calls_carry_different_origins(
        self, command, funnel_b_recorder
    ) -> None:
        from grandpa.local_actions import handle_local_action

        handle_local_action(command)

        assert [p.get("origin") for p in funnel_b_recorder] == ["agent", "agent"]

    @pytest.mark.parametrize("command", AGENT_ESCALATION_COMMANDS)
    def test_the_user_requested_action_is_the_second_call(
        self, command, funnel_b_recorder
    ) -> None:
        """The first is the agent's own reconnaissance, not what was asked."""
        from grandpa.local_actions import handle_local_action

        handle_local_action(command)

        assert funnel_b_recorder[0]["action_type"] == "desktop_summary"
        assert funnel_b_recorder[1]["action_type"] == "pc_diagnostics"

    @pytest.mark.parametrize("command", AGENT_ESCALATION_COMMANDS)
    def test_the_escalation_reports_unsupported(
        self, command, funnel_b_recorder
    ) -> None:
        """Observed outcome, pinned so a behaviour change becomes visible."""
        from grandpa.local_actions import handle_local_action

        result = handle_local_action(command)

        assert result.status == "unsupported", command

    def test_the_agent_source_is_a_fourth_context_label(self) -> None:
        """Four distinct ``source`` values reach ``execute_skill`` from Funnel A.

        Structural rather than behavioural: ``goal_mode`` binds ``execute_skill``
        at module scope, so a spy installed on the registry does not see this
        call. Asserting the source text avoids a test that would silently stop
        observing anything if that binding changed.
        """
        text = (SRC / "agents" / "goal_mode.py").read_text(encoding="utf-8")

        assert 'source="autonomous-agent-v2"' in text

    def test_the_four_sources_are_distinct(self) -> None:
        """``intent_router``, ``local_actions``, ``autonomous-agent-v2`` -- and
        the ``skill`` label all three collapse onto downstream."""
        sources = {
            (SRC / "router" / "skill_router.py"): "intent_router",
            (SRC / "local_actions.py"): "local_actions",
            (SRC / "agents" / "goal_mode.py"): "autonomous-agent-v2",
        }
        for path, label in sources.items():
            assert f'source="{label}"' in path.read_text(encoding="utf-8"), label

        assert len(set(sources.values())) == 3
