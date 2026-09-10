"""Today's routing order and selection, frozen before anything migrates.

The dispatcher migration's risk is not that a handler breaks; it is that the
*order* shifts and a request quietly reaches a different handler than it does
today. These tests describe the current selection so that a reordering has to
be an argued change rather than an unnoticed one.

Characterization only. Nothing here asserts that the current behaviour is
correct -- several facts recorded below are arguably defects, and two are noted
as such. They are pinned because they are what ships.

**``handle_local_action`` is deliberately not invoked.** It writes SQLite
through ``_audit_decision`` (the approval store) and ``_log_attempt``
(``record_activity``) before returning, including on paths that actuate
nothing. The components it composes are pure and are characterized directly:
``route_action``, ``match_skill_route``, ``_parse_pc_control_action``,
``_is_dangerous`` and ``_prefer_deterministic_browser_route``. Where the funnel's
own branch condition matters, the condition is asserted rather than the funnel
being run -- which is stated plainly here so no one reads these as end-to-end
tests.
"""

from __future__ import annotations

import pytest

from grandpa.actions import (
    browser_actions,
    desktop_actions,
    fallback_actions,
    memory_actions,
    planner_actions,
    vision_actions,
    workflow_actions,
)
from grandpa.actions.router import _HANDLERS, route_action
from grandpa.dispatch import NOT_HANDLED, RequestContext
from grandpa.dispatch.adapters.action_modules import (
    ACTION_MODULE_ORDER,
    build_action_module_dispatcher,
)
from grandpa.local_actions import (
    _is_dangerous,
    _is_safe_desktop_operator_request,
    _normalise,
    _parse_desktop_operator_action,
    _parse_pc_control_action,
    _prefer_deterministic_browser_route,
)
from grandpa.router.skill_router import _ROUTE_TABLE, match_skill_route

#: The production chain, spelled out. This is the thing being frozen.
FROZEN_DOMAIN_ORDER = (
    "desktop",
    "browser",
    "vision",
    "workflow",
    "planner",
    "memory",
    "fallback",
)

DOMAIN_TABLES = {
    "desktop": desktop_actions,
    "browser": browser_actions,
    "vision": vision_actions,
    "workflow": workflow_actions,
    "planner": planner_actions,
    "memory": memory_actions,
    "fallback": fallback_actions,
}


def _phrases(domain: str) -> set[str]:
    return set(getattr(DOMAIN_TABLES[domain], "HANDLERS", ()) or ())


CLAIMED_PHRASES = sorted(set().union(*(_phrases(d) for d in FROZEN_DOMAIN_ORDER)))

#: Phrases every one of the three routers recognises. Derived, not copied.
SHARED_BY_ALL_THREE = sorted(
    phrase
    for phrase in _phrases("desktop") & set(_ROUTE_TABLE)
    if _parse_pc_control_action(phrase).status != "no_match"
)

NO_MATCH_PHRASES = (
    "",
    "   ",
    "list monitor",
    "list monitors please",
    "LIST MONITORS",
    "desktop",
    "open notepad",
    "what time is it",
)


# ---------------------------------------------------------------------------
# The five routing classes
#
# Table overlap alone does not decide which router serves a phrase. Two gates
# ahead of the execute-dependent one take phrases out of the contest entirely:
# gate 5 (``_is_safe_desktop_operator_request``) and the deterministic-browser
# guard, neither of which consults ``execute``. Partitioning by overlap *and*
# those two gates is what separates the phrases ``execute`` actually decides
# from the ones that merely look contested.
#
# All five sets are derived from the live tables, so a phrase added to any of
# them lands in exactly one class without this file being edited.
# ---------------------------------------------------------------------------

ALL_PHRASES = set(CLAIMED_PHRASES) | set(_ROUTE_TABLE)

GATE_5_INTERCEPTED = sorted(
    p for p in ALL_PHRASES if _is_safe_desktop_operator_request(p)
)
BROWSER_GUARDED = sorted(
    p
    for p in set(CLAIMED_PHRASES) & set(_ROUTE_TABLE)
    if _prefer_deterministic_browser_route(p)
)
_TAKEN_EARLY = set(GATE_5_INTERCEPTED) | set(BROWSER_GUARDED)

#: Both routers claim it and no earlier gate intervenes: ``execute`` decides.
EXECUTE_CONTESTED = sorted((set(CLAIMED_PHRASES) & set(_ROUTE_TABLE)) - _TAKEN_EARLY)
#: Only the skill router claims it, and it is genuinely reachable.
EXECUTE_GATED_SKILL_ONLY = sorted(
    (set(_ROUTE_TABLE) - set(CLAIMED_PHRASES)) - _TAKEN_EARLY
)
#: Only an action module claims it; the skill router never competes.
ACTION_MODULE_ONLY = sorted(set(CLAIMED_PHRASES) - set(_ROUTE_TABLE))


def _ctx(text: str) -> RequestContext:
    return RequestContext(text=text, origin="direct")


class TestFrozenActionPrecedence:
    def test_domain_order_is_exactly_this(self) -> None:
        assert [domain for domain, _fn, _count in _HANDLERS] == list(
            FROZEN_DOMAIN_ORDER
        )

    @pytest.mark.parametrize("position,domain", list(enumerate(FROZEN_DOMAIN_ORDER)))
    def test_each_domain_holds_its_position(self, position: int, domain: str) -> None:
        """Positions individually, so a failure names the domain that moved."""
        assert _HANDLERS[position][0] == domain

    def test_fallback_is_last(self) -> None:
        """A fallback that stopped being last would shadow real handlers."""
        assert _HANDLERS[-1][0] == "fallback"

    def test_the_adapter_chain_mirrors_it(self) -> None:
        assert [name for name, _fn in ACTION_MODULE_ORDER] == list(FROZEN_DOMAIN_ORDER)
        assert [h.name for h in build_action_module_dispatcher().handlers] == list(
            FROZEN_DOMAIN_ORDER
        )


class TestTablesAreDisjoint:
    """Why order is currently behaviour-neutral inside ``grandpa.actions``.

    No phrase is claimed by two domains today, so every ordering of the seven
    produces the same winner. That makes the order freeze above look redundant
    -- and it is exactly the reason to keep it. Disjointness is a property of
    today's tables, not a guarantee of the design; the first overlapping entry
    added makes order decisive, and these two tests are what turn that into a
    visible failure rather than a silent change of behaviour.
    """

    def test_no_phrase_is_claimed_by_two_domains(self) -> None:
        collisions = {}
        for i, first in enumerate(FROZEN_DOMAIN_ORDER):
            for second in FROZEN_DOMAIN_ORDER[i + 1 :]:
                shared = _phrases(first) & _phrases(second)
                if shared:
                    collisions[(first, second)] = sorted(shared)
        assert collisions == {}, collisions

    def test_exactly_one_domain_claims_each_phrase(self) -> None:
        for phrase in CLAIMED_PHRASES:
            claiming = [
                domain for domain, fn, _count in _HANDLERS if fn(phrase) is not None
            ]
            assert len(claiming) == 1, (phrase, claiming)


class TestDeterministicWinner:
    def test_corpus_is_populated(self) -> None:
        assert len(CLAIMED_PHRASES) == 25

    @pytest.mark.parametrize("phrase", CLAIMED_PHRASES)
    def test_winner_is_the_first_claiming_domain_in_order(self, phrase: str) -> None:
        winner = next(
            domain for domain, fn, _count in _HANDLERS if fn(phrase) is not None
        )
        result = build_action_module_dispatcher().dispatch(_ctx(phrase))

        assert result.handler_name == winner

    @pytest.mark.parametrize("phrase", CLAIMED_PHRASES)
    def test_route_action_and_dispatcher_agree(self, phrase: str) -> None:
        assert build_action_module_dispatcher().dispatch(_ctx(phrase)).result == (
            route_action(phrase)
        )


class TestCrossRouterOverlap:
    """Three routers recognise the same eight phrases.

    ``desktop_actions``, ``skill_router._ROUTE_TABLE`` and
    ``_parse_pc_control_action`` all claim them. Within one funnel pass only one
    can win, and which one does is decided by ``execute`` -- characterized in
    the next class.
    """

    def test_the_shared_set_is_exactly_these_eight(self) -> None:
        assert SHARED_BY_ALL_THREE == [
            "clipboard history",
            "desktop summary",
            "detect monitors",
            "list monitors",
            "show clipboard history",
            "show monitors",
            "summarize desktop",
            "what monitors are connected",
        ]

    @pytest.mark.parametrize("phrase", SHARED_BY_ALL_THREE)
    def test_all_three_routers_claim_it(self, phrase: str) -> None:
        assert desktop_actions.try_handle(phrase) is not None
        assert match_skill_route(phrase) is not None
        assert _parse_pc_control_action(phrase).status != "no_match"

    @pytest.mark.parametrize("phrase", SHARED_BY_ALL_THREE)
    def test_action_module_and_legacy_parser_produce_identical_results(
        self, phrase: str
    ) -> None:
        """Recorded, not endorsed.

        ``_route_with_action_modules`` runs at sub-step 2 of
        ``_parse_safe_action`` and ``_parse_pc_control_action`` at sub-step 8,
        so for these eight the later branch is unreachable. That it is
        unreachable *and* identical is what makes it harmless today; it is
        pinned so that a change to either copy shows up as a difference rather
        than as drift between a live branch and a dead one.
        """
        assert desktop_actions.try_handle(phrase) == _parse_pc_control_action(phrase)

    @pytest.mark.parametrize("phrase", SHARED_BY_ALL_THREE)
    def test_the_skill_router_answers_in_a_different_shape(self, phrase: str) -> None:
        """Same request, different result type -- which is why order matters."""
        route = match_skill_route(phrase)

        assert route.skill_name.startswith("desktop.")
        assert not hasattr(route, "kind")
        assert desktop_actions.try_handle(phrase).kind == "pc_control"


class TestExecuteModeSelection:
    """When ``execute`` decides the router -- and when it does not.

    ``handle_local_action`` reaches the skill router only under::

        if execute and not _prefer_deterministic_browser_route(command)

    and only if gate 5 has not already claimed the phrase. Both operands are
    asserted here rather than the funnel being invoked.

    For ``SHARED_BY_ALL_THREE`` neither earlier gate fires, so the branch
    reduces to ``execute``. That is **not** true of every overlapping phrase:
    see ``TestFiveRoutingClasses``, where three phrases are diverted by the
    browser guard and four by gate 5 regardless of ``execute``.
    """

    @pytest.mark.parametrize("phrase", SHARED_BY_ALL_THREE)
    def test_neither_earlier_gate_intercepts_these(self, phrase: str) -> None:
        assert _is_dangerous(_normalise(phrase)) is False
        assert _prefer_deterministic_browser_route(phrase) is False

    @pytest.mark.parametrize("phrase", SHARED_BY_ALL_THREE)
    def test_both_candidate_routers_are_ready_to_claim(self, phrase: str) -> None:
        """So the selection cannot be explained by one of them declining."""
        assert match_skill_route(phrase) is not None
        assert route_action(phrase) is not None

    def test_22_phrases_overlap_but_only_19_are_execute_decided(self) -> None:
        """Table overlap is not the same question as who serves the request.

        22 of the 25 action-module phrases also sit in the skill table. Three of
        those 22 -- the browser-guarded ones -- never reach the skill router
        even with ``execute=True``, so ``execute`` decides for 19, not 22.

        ``SHARED_BY_ALL_THREE`` is a different, narrower subset again: the
        phrases where the legacy ``_parse_pc_control_action`` branch claims as
        well, three claimants rather than two.
        """
        overlapping = set(CLAIMED_PHRASES) & set(_ROUTE_TABLE)

        assert len(overlapping) == 22
        for phrase in sorted(overlapping):
            assert route_action(phrase) is not None, phrase
            assert match_skill_route(phrase) is not None, phrase

        assert len(EXECUTE_CONTESTED) == 19
        assert set(EXECUTE_CONTESTED) == overlapping - set(BROWSER_GUARDED)
        assert set(SHARED_BY_ALL_THREE) < overlapping

    def test_13_skill_only_phrases_but_only_9_are_execute_gated(self) -> None:
        """Four of the thirteen never reach the skill router at all.

        13 phrases are in the skill table and in no action-module table. Four of
        them are claimed at gate 5, which runs ahead of the execute-dependent
        gate and does not consult ``execute``, so only 9 are genuinely reachable
        by turning ``execute`` on.
        """
        skill_only = set(_ROUTE_TABLE) - set(CLAIMED_PHRASES)

        assert len(skill_only) == 13
        for phrase in sorted(skill_only):
            assert route_action(phrase) is None, phrase

        assert len(EXECUTE_GATED_SKILL_ONLY) == 9
        assert set(EXECUTE_GATED_SKILL_ONLY) == skill_only - set(GATE_5_INTERCEPTED)

    def test_the_browser_guard_diverts_before_the_skill_router(self) -> None:
        """The other half of the gate, pinned on its own corpus."""
        assert _prefer_deterministic_browser_route("browser diagnostics") is True
        assert _prefer_deterministic_browser_route("search cats") is True
        assert _prefer_deterministic_browser_route("search google for cats") is True
        assert _prefer_deterministic_browser_route("list monitors") is False


class TestNoMatchSemantics:
    @pytest.mark.parametrize("phrase", NO_MATCH_PHRASES)
    def test_route_action_declines(self, phrase: str) -> None:
        assert route_action(phrase) is None

    @pytest.mark.parametrize("phrase", NO_MATCH_PHRASES)
    def test_dispatcher_declines_identically(self, phrase: str) -> None:
        result = build_action_module_dispatcher().dispatch(_ctx(phrase))

        assert result.claimed is False
        assert result.handler_name is None
        assert result.result is NOT_HANDLED

    def test_matching_is_exact_not_substring(self) -> None:
        """A prefix or suffix must not claim; these are exact-match tables."""
        assert route_action("list monitors") is not None
        assert route_action("list monitors now") is None
        assert route_action("please list monitors") is None


class TestStillZeroProductionConsumers:
    def test_no_production_module_imports_the_dispatcher(self) -> None:
        import ast
        from pathlib import Path

        root = Path(__file__).resolve().parents[2] / "src" / "grandpa"
        dispatch_dir = root / "dispatch"
        importers: list[str] = []
        for path in root.rglob("*.py"):
            if dispatch_dir == path.parent or dispatch_dir in path.parents:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    if any(a.name.startswith("grandpa.dispatch") for a in node.names):
                        importers.append(path.as_posix())
                elif isinstance(node, ast.ImportFrom):
                    if (node.module or "").startswith("grandpa.dispatch"):
                        importers.append(path.as_posix())
        # 4.5H-3: ``composition/ask_handlers.py`` is the one approved
        # consumer -- the ask.py dispatcher adapters, which live in the
        # composition layer precisely so ``dispatch`` itself stays
        # capability-free. Still an exact set: any other importer fails.
        # This guard records absolute paths, so the suffix is compared
        # rather than a machine-specific prefix.
        # Deduplicated: the guard appends once per import statement, and the
        # adapter module imports three names from ``grandpa.dispatch``.
        # Still an exact set -- not a containment check.
        # 4.5I: ``cli/ask.py`` is the first production consumer of the
        # dispatcher -- the authorized wiring. It imports ``RequestContext``
        # from ``grandpa.dispatch`` and the builder from ``composition``.
        # Still an exact set; a third consumer must be a decision.
        assert sorted({p.split("src/grandpa/")[-1] for p in importers}) == [
            "cli/ask.py",
            "composition/ask_handlers.py",
        ]


class TestPriorContractsIntact:
    def test_request_context_still_requires_origin(self) -> None:
        with pytest.raises(TypeError):
            RequestContext(text="list monitors")  # type: ignore[call-arg]

    def test_dispatcher_surface_is_still_selection_only(self) -> None:
        from grandpa.dispatch import IntentDispatcher

        public = {n for n in dir(IntentDispatcher) if not n.startswith("_")}
        assert public == {"register", "dispatch", "handlers"}


class TestFiveRoutingClasses:
    """Every phrase either router knows, partitioned by who actually serves it.

    Overlap between the two tables is not the deciding question. Two gates run
    ahead of the execute-dependent one and consult ``execute`` not at all, so a
    phrase can sit in both tables and still never be contested. The partition
    below is the real routing model; the sizes are pinned so that a phrase
    moving between classes is a failure rather than a surprise during migration.
    """

    def test_the_five_classes_partition_every_known_phrase(self) -> None:
        classes = (
            set(EXECUTE_CONTESTED),
            set(EXECUTE_GATED_SKILL_ONLY),
            set(BROWSER_GUARDED),
            set(GATE_5_INTERCEPTED),
            set(ACTION_MODULE_ONLY),
        )
        union: set[str] = set().union(*classes)

        assert union == ALL_PHRASES
        assert sum(len(c) for c in classes) == len(union), "classes overlap"
        assert len(union) == 38

    def test_class_sizes_are_frozen(self) -> None:
        assert len(EXECUTE_CONTESTED) == 19
        assert len(EXECUTE_GATED_SKILL_ONLY) == 9
        assert len(BROWSER_GUARDED) == 3
        assert len(GATE_5_INTERCEPTED) == 4
        assert len(ACTION_MODULE_ONLY) == 3

    @pytest.mark.parametrize("phrase", EXECUTE_CONTESTED)
    def test_contested_phrases_have_two_claimants_and_no_early_gate(
        self, phrase: str
    ) -> None:
        assert route_action(phrase) is not None
        assert match_skill_route(phrase) is not None
        assert _is_safe_desktop_operator_request(phrase) is False
        assert _prefer_deterministic_browser_route(phrase) is False
        assert _is_dangerous(_normalise(phrase)) is False

    @pytest.mark.parametrize("phrase", EXECUTE_GATED_SKILL_ONLY)
    def test_skill_only_phrases_are_claimed_by_the_skill_router_alone(
        self, phrase: str
    ) -> None:
        assert match_skill_route(phrase) is not None
        assert route_action(phrase) is None
        assert _is_safe_desktop_operator_request(phrase) is False
        assert _prefer_deterministic_browser_route(phrase) is False

    def test_browser_guarded_phrases_are_exactly_these_three(self) -> None:
        assert BROWSER_GUARDED == [
            "browser diagnostics",
            "browser status",
            "show browser diagnostics",
        ]

    @pytest.mark.parametrize("phrase", BROWSER_GUARDED)
    def test_browser_guarded_phrases_are_execute_independent(self, phrase: str) -> None:
        """The guard removes the skill router from the branch.

        ``execute`` therefore cannot change who serves these: the action module
        always does. The skill router would claim the phrase -- the guard is
        what keeps it away, which is why both assertions are here.
        """
        assert _prefer_deterministic_browser_route(phrase) is True
        assert route_action(phrase) is not None
        assert match_skill_route(phrase) is not None

    def test_gate_5_phrases_are_exactly_these_four(self) -> None:
        assert GATE_5_INTERCEPTED == [
            "desktop operator diagnostics",
            "detect active app and suggest actions",
            "operator diagnostics",
            "summarize current desktop state",
        ]

    @pytest.mark.parametrize("phrase", GATE_5_INTERCEPTED)
    def test_gate_5_phrases_are_execute_independent(self, phrase: str) -> None:
        """Gate 5 runs before the execute-dependent gate and ignores it."""
        assert _is_safe_desktop_operator_request(phrase) is True
        assert _parse_desktop_operator_action(phrase).status != "no_match"

    @pytest.mark.parametrize("phrase", ACTION_MODULE_ONLY)
    def test_action_module_only_phrases_never_meet_the_skill_router(
        self, phrase: str
    ) -> None:
        assert route_action(phrase) is not None
        assert match_skill_route(phrase) is None


class TestGateFiveDeadRouteEntries:
    """The four gate-5 phrases have ``_ROUTE_TABLE`` entries that cannot run.

    Recorded, not repaired. Gate 5 claims them before the funnel reaches the
    execute-dependent gate, so their skill-router entries are unreachable in the
    current ordering under either value of ``execute``. That is a pre-existing
    condition of the shipped routing, not something the dispatcher work
    introduced, and the entries are deliberately left in place: removing them is
    a behaviour decision belonging to whoever owns ``grandpa/router``.

    Pinning it means that if the ordering ever changes these become live again,
    and this test is what makes that visible rather than silent.
    """

    @pytest.mark.parametrize("phrase", GATE_5_INTERCEPTED)
    def test_the_entry_exists_but_is_shadowed(self, phrase: str) -> None:
        assert phrase in _ROUTE_TABLE
        assert match_skill_route(phrase) is not None
        assert _is_safe_desktop_operator_request(phrase) is True

    def test_all_four_are_still_present_in_the_route_table(self) -> None:
        """The entries must not be quietly removed while this stands."""
        assert set(GATE_5_INTERCEPTED) <= set(_ROUTE_TABLE)


class TestResultShapeDivergence:
    """What the caller observes differs by router, for the contested 19.

    Both shapes come from pure functions: ``route_action`` for the
    ``execute=False`` side, and ``skill_result_to_local_action`` -- the same
    adapter the live path uses -- fed a stub ``SkillResult`` for the
    ``execute=True`` side. No skill is executed, nothing is written, and no
    actuator is reached.

    This is why the conditional must be preserved rather than normalised:
    collapsing the two paths would change ``target``, ``message`` and ``status``
    for all 19.
    """

    @staticmethod
    def _skill_shape(phrase: str, *, ok: bool = True, status: str = "completed"):
        from grandpa.router.legacy_adapter import skill_result_to_local_action
        from grandpa.skills.runtime import SkillResult

        route = match_skill_route(phrase)
        stub = SkillResult(ok=ok, status=status, message="stub skill message")
        return skill_result_to_local_action(route, stub)

    @pytest.mark.parametrize("phrase", EXECUTE_CONTESTED)
    def test_kind_is_the_one_field_that_agrees(self, phrase: str) -> None:
        assert self._skill_shape(phrase).kind == route_action(phrase).kind

    @pytest.mark.parametrize("phrase", EXECUTE_CONTESTED)
    def test_target_differs_and_the_skill_side_is_always_the_skill_name(
        self, phrase: str
    ) -> None:
        """``desktop.summary`` versus ``desktop_summary|desktop``.

        The skill side is uniform -- always the dotted skill name. The action
        side is not: ``desktop``, ``browser``, ``workflow`` and ``planner``
        emit ``action|target``, while ``vision`` emits a bare identifier such
        as ``screen_diagnostics``. The invariant that holds across all 19 is
        that the two differ, which is what a migration would have to preserve;
        the per-domain format split is recorded in the test below rather than
        asserted as a rule that does not hold.
        """
        route = match_skill_route(phrase)
        skill_target = self._skill_shape(phrase).target
        action_target = route_action(phrase).target

        assert skill_target == route.skill_name
        assert "." in skill_target
        assert "|" not in skill_target
        assert skill_target != action_target

    def test_action_target_format_is_not_uniform_across_domains(self) -> None:
        """Recorded because it defeats any single-rule normalisation.

        Four domains use ``action|target``; ``vision`` uses a bare identifier.
        A migration that assumed one shape would corrupt the other.
        """
        piped = {
            phrase for phrase in EXECUTE_CONTESTED if "|" in route_action(phrase).target
        }
        bare = set(EXECUTE_CONTESTED) - piped

        assert len(piped) == 13
        assert len(bare) == 6
        for phrase in bare:
            assert route_action(phrase).kind == "screen"

    @pytest.mark.parametrize("phrase", EXECUTE_CONTESTED)
    def test_message_source_differs(self, phrase: str) -> None:
        """Dynamic skill output versus a fixed parser string."""
        assert self._skill_shape(phrase).message == "stub skill message"
        assert route_action(phrase).message != "stub skill message"
        assert route_action(phrase).message.startswith("Checking ")

    @pytest.mark.parametrize("phrase", EXECUTE_CONTESTED)
    def test_action_module_status_is_always_handled(self, phrase: str) -> None:
        assert route_action(phrase).status == "handled"

    @pytest.mark.parametrize(
        "ok,skill_status,expected",
        [
            (True, "completed", "handled"),
            (False, "unsupported", "unsupported"),
            (False, "blocked", "blocked"),
            (False, "failed", "error"),
        ],
    )
    def test_skill_status_can_take_values_the_parser_cannot_produce(
        self, ok: bool, skill_status: str, expected: str
    ) -> None:
        """A failing skill surfaces as error, blocked or unsupported.

        The action-module path cannot express any of those -- it reports
        ``handled`` before anything has run. The two paths differ in what they
        are able to say, not only in what they say today.
        """
        shape = self._skill_shape("list monitors", ok=ok, status=skill_status)

        assert shape.status == expected
