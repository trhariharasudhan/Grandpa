"""The seven ``grandpa.actions`` adapters, against the router they mirror.

The claim these tests defend is narrow and total: wrapping the seven domains in
the dispatcher contract changes nothing. Same order, same verdicts, same result
objects, same exceptions. Parity is asserted against ``route_action`` itself
rather than against a copied list of expectations, so the two cannot drift apart
without a failure here.

The corpus is derived from the live ``HANDLERS`` tables (25 phrases today), not
hand-written, so a phrase added to any domain is covered the moment it lands.

Nothing here actuates. Every phrase in these tables parses to a description of
an action; ``_execute`` is what would act on one, and it is never called.
"""

from __future__ import annotations

import ast
import copy
from pathlib import Path

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
    ActionModuleHandler,
    build_action_module_dispatcher,
    build_action_module_handlers,
)

ROOT = Path(__file__).resolve().parents[2]
ADAPTERS_DIR = ROOT / "src" / "grandpa" / "dispatch" / "adapters"

DOMAIN_MODULES = (
    desktop_actions,
    browser_actions,
    vision_actions,
    workflow_actions,
    planner_actions,
    memory_actions,
    fallback_actions,
)

#: Every phrase any domain claims, derived from the live tables.
CLAIMED_PHRASES = sorted(
    {phrase for module in DOMAIN_MODULES for phrase in getattr(module, "HANDLERS", {})}
)

#: Text no domain should claim. Includes near-misses of real entries, because
#: these are exact-match tables and a substring or prefix match would be a
#: behaviour change this suite must catch.
NO_MATCH_PHRASES = (
    "",
    "   ",
    "list monitor",
    "list monitors please",
    "please list monitors",
    "LIST MONITORS",
    "desktop",
    "summary",
    "open notepad",
    "what time is it",
    "delete everything",
    "search google for cats",
)


def _ctx(text: str) -> RequestContext:
    return RequestContext(text=text, origin="direct")


class TestRegistrationOrder:
    def test_matches_actions_router_handlers(self) -> None:
        """The adapter order is the router's order, asserted against it.

        ``ACTION_MODULE_ORDER`` spells the sequence out rather than importing
        ``_HANDLERS``; this is what stops the two from drifting.
        """
        assert [name for name, _fn in ACTION_MODULE_ORDER] == [
            domain for domain, _fn, _count in _HANDLERS
        ]

    def test_wraps_the_same_functions(self) -> None:
        assert [fn for _name, fn in ACTION_MODULE_ORDER] == [
            fn for _domain, fn, _count in _HANDLERS
        ]

    def test_dispatcher_preserves_that_order(self) -> None:
        dispatcher = build_action_module_dispatcher()

        assert [h.name for h in dispatcher.handlers] == [
            domain for domain, _fn, _count in _HANDLERS
        ]

    def test_all_seven_domains_are_present(self) -> None:
        assert len(build_action_module_handlers()) == 7


class TestParityWithRouteAction:
    """The dispatcher and ``route_action`` must agree, phrase for phrase."""

    def test_corpus_is_not_empty(self) -> None:
        """Guards the two parity tests below from passing vacuously."""
        assert len(CLAIMED_PHRASES) == 25

    @pytest.mark.parametrize("phrase", CLAIMED_PHRASES)
    def test_claimed_phrases_produce_equal_results(self, phrase: str) -> None:
        expected = route_action(phrase)
        result = build_action_module_dispatcher().dispatch(_ctx(phrase))

        assert expected is not None, phrase
        assert result.claimed is True
        assert result.result == expected

    @pytest.mark.parametrize("phrase", NO_MATCH_PHRASES)
    def test_unclaimed_phrases_agree_too(self, phrase: str) -> None:
        assert route_action(phrase) is None
        result = build_action_module_dispatcher().dispatch(_ctx(phrase))

        assert result.claimed is False
        assert result.handler_name is None
        assert result.result is NOT_HANDLED

    @pytest.mark.parametrize("phrase", CLAIMED_PHRASES)
    def test_the_same_domain_claims_each_phrase(self, phrase: str) -> None:
        """Not just an equal result -- the same domain produced it.

        Two domains returning equal results for one phrase would satisfy the
        equality test above while the selection had silently moved.
        """
        expected_domain = next(
            domain for domain, fn, _count in _HANDLERS if fn(phrase) is not None
        )
        result = build_action_module_dispatcher().dispatch(_ctx(phrase))

        assert result.handler_name == expected_domain


class TestResultPassthrough:
    def test_handle_returns_the_underlying_object_itself(self) -> None:
        """No wrapping, no copying, no reconstruction."""
        sentinel = object()
        handler = ActionModuleHandler("fake", lambda _text: sentinel)

        assert handler.handle(_ctx("anything")) is sentinel

    def test_claims_is_true_exactly_when_result_is_not_none(self) -> None:
        claims_it = ActionModuleHandler("yes", lambda _text: object())
        declines = ActionModuleHandler("no", lambda _text: None)

        assert claims_it.claims(_ctx("x")) is True
        assert declines.claims(_ctx("x")) is False

    def test_falsy_but_not_none_results_still_claim(self) -> None:
        """``is not None``, not truthiness -- an empty result is still a result."""
        handler = ActionModuleHandler("falsy", lambda _text: "")

        assert handler.claims(_ctx("x")) is True


class TestPurity:
    """The double call is only safe because these seven are pure."""

    @pytest.mark.parametrize("phrase", CLAIMED_PHRASES)
    def test_repeated_calls_agree(self, phrase: str) -> None:
        for module in DOMAIN_MODULES:
            first = module.try_handle(phrase)
            second = module.try_handle(phrase)
            assert first == second, module.__name__

    @pytest.mark.parametrize("phrase", CLAIMED_PHRASES)
    def test_handler_tables_are_not_mutated_by_dispatch(self, phrase: str) -> None:
        # deepcopy rather than dict(): the tables are not all dicts.
        # ``workflow`` and ``planner`` hold sets, which their ``try_handle``
        # reads with ``command not in HANDLERS``.
        before = {
            module.__name__: copy.deepcopy(getattr(module, "HANDLERS", None))
            for module in DOMAIN_MODULES
        }

        build_action_module_dispatcher().dispatch(_ctx(phrase))

        after = {
            module.__name__: copy.deepcopy(getattr(module, "HANDLERS", None))
            for module in DOMAIN_MODULES
        }
        assert before == after

    def test_claims_then_handle_calls_the_function_twice(self) -> None:
        """Documents the cost the purity argument buys, rather than hiding it."""
        calls: list[str] = []
        handler = ActionModuleHandler("counting", lambda text: calls.append(text))
        ctx = _ctx("some text")

        handler.claims(ctx)
        handler.handle(ctx)

        assert calls == ["some text", "some text"]


class TestExceptionPropagation:
    def test_claims_propagates(self) -> None:
        def boom(_text: str):
            raise RuntimeError("domain failed")

        with pytest.raises(RuntimeError, match="domain failed"):
            ActionModuleHandler("boom", boom).claims(_ctx("x"))

    def test_handle_propagates(self) -> None:
        def boom(_text: str):
            raise RuntimeError("domain failed")

        with pytest.raises(RuntimeError, match="domain failed"):
            ActionModuleHandler("boom", boom).handle(_ctx("x"))

    def test_dispatcher_does_not_swallow(self) -> None:
        """``route_action`` lets these through; the dispatcher must too."""

        def boom(_text: str):
            raise RuntimeError("domain failed")

        dispatcher = build_action_module_dispatcher()
        dispatcher.register(ActionModuleHandler("boom", boom), order=1)

        with pytest.raises(RuntimeError, match="domain failed"):
            dispatcher.dispatch(_ctx("x"))


class TestOnlyTextIsRead:
    def test_origin_and_dry_run_do_not_reach_the_parser(self) -> None:
        seen: list[str] = []
        handler = ActionModuleHandler("recording", lambda text: seen.append(text))

        for origin in ("voice", "agent", "direct"):
            for dry_run in (True, False):
                handler.claims(
                    RequestContext(
                        text="list monitors",
                        origin=origin,
                        dry_run=dry_run,
                    )
                )

        assert seen == ["list monitors"] * 6

    def test_verdict_is_identical_across_every_origin(self) -> None:
        dispatcher = build_action_module_dispatcher()
        results = [
            dispatcher.dispatch(RequestContext(text="list monitors", origin=origin))
            for origin in ("voice", "agent", "direct")
        ]

        assert all(r.handler_name == results[0].handler_name for r in results)
        assert all(r.result == results[0].result for r in results)


class TestNoDefaultOriginIntroduced:
    def test_adapters_never_construct_a_request_context(self) -> None:
        """A context built inside an adapter would need an origin from somewhere.

        The only honest source is the caller, so adapters must not build one --
        that is how a silent default would get reintroduced below the surface
        that actually knows the provenance.
        """
        for path in sorted(ADAPTERS_DIR.glob("*.py")):
            source = path.read_text(encoding="utf-8")
            assert "RequestContext(" not in source, path.name

    def test_request_context_still_requires_origin(self) -> None:
        with pytest.raises(TypeError):
            RequestContext(text="list monitors")  # type: ignore[call-arg]


class TestAdapterLayering:
    """Adapters may name the capability they wrap -- and nothing heavier."""

    FORBIDDEN = {
        "grandpa.pc_control",
        "grandpa.local_actions",
        "grandpa.router",
        "grandpa.policy.engine",
        "grandpa.apps",
        "subprocess",
        "sqlite3",
        "webbrowser",
    }

    def _imports(self) -> set[str]:
        modules: set[str] = set()
        for path in sorted(ADAPTERS_DIR.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    modules.update(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    modules.add(node.module)
        return modules

    def test_no_forbidden_imports(self) -> None:
        imported = self._imports()
        assert imported, "no imports parsed -- the AST walk found nothing"

        offending = {
            module
            for module in imported
            for banned in self.FORBIDDEN
            if module == banned or module.startswith(f"{banned}.")
        }
        assert offending == set(), offending

    def test_grandpa_dependencies_are_the_wrapped_capability_and_dispatch(
        self,
    ) -> None:
        grandpa_imports = {m for m in self._imports() if m.startswith("grandpa.")}

        assert grandpa_imports == {
            "grandpa.actions",
            "grandpa.dispatch.context",
            "grandpa.dispatch.protocol",
            "grandpa.dispatch.registry",
        }, grandpa_imports

    def test_adapters_add_no_policy_importer(self) -> None:
        """The allowlist amended in 4.4a must not need widening again."""
        for path in sorted(ADAPTERS_DIR.glob("*.py")):
            assert "grandpa.policy" not in path.read_text(encoding="utf-8"), path.name


class TestStillZeroProductionConsumers:
    def test_nothing_outside_dispatch_imports_the_adapters(self) -> None:
        dispatch_dir = ROOT / "src" / "grandpa" / "dispatch"
        importers: list[str] = []
        for path in (ROOT / "src" / "grandpa").rglob("*.py"):
            if dispatch_dir in path.parents or path.parent == dispatch_dir:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    if any(a.name.startswith("grandpa.dispatch") for a in node.names):
                        importers.append(path.relative_to(ROOT).as_posix())
                elif isinstance(node, ast.ImportFrom):
                    if (node.module or "").startswith("grandpa.dispatch"):
                        importers.append(path.relative_to(ROOT).as_posix())
        # 4.5H-3: ``composition/ask_handlers.py`` is the one approved
        # consumer -- the ask.py dispatcher adapters, which live in the
        # composition layer precisely so ``dispatch`` itself stays
        # capability-free. Still an exact set: any other importer fails.
        # Deduplicated: the guard appends once per import statement, and the
        # adapter module imports three names from ``grandpa.dispatch``.
        # Still an exact set -- not a containment check.
        # 4.5I: ``cli/ask.py`` is the first production consumer of the
        # dispatcher -- the authorized wiring. It imports ``RequestContext``
        # from ``grandpa.dispatch`` and the builder from ``composition``.
        # Still an exact set; a third consumer must be a decision.
        assert sorted(set(importers)) == [
            "src/grandpa/cli/ask.py",
            "src/grandpa/composition/ask_handlers.py",
        ]


class TestExistingActionsBehaviourUnchanged:
    def test_router_handler_tuple_is_untouched(self) -> None:
        assert [domain for domain, _fn, _count in _HANDLERS] == [
            "desktop",
            "browser",
            "vision",
            "workflow",
            "planner",
            "memory",
            "fallback",
        ]

    def test_route_action_still_answers_directly(self) -> None:
        """``route_action`` is production; adapting it must not have moved it."""
        result = route_action("list monitors")

        assert result is not None
        assert result.target == "list_monitors|monitors"
        assert route_action("not a command at all") is None
