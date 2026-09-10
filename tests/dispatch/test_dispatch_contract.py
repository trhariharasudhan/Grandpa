"""The dispatcher scaffold's contract, before anything consumes it.

Every test here is about shape rather than behaviour, because there is no
behaviour yet: 4.4a lands the contract and nothing else. The two properties
worth defending at this point are that provenance cannot go unstated, and that
the dispatcher has not quietly acquired the responsibilities -- risk, approval,
execution -- that already have owners elsewhere.

Nothing here touches a capability, a store, or an actuator, and the handlers
are local fakes that record calls.
"""

from __future__ import annotations

import ast
import dataclasses
from pathlib import Path

import pytest

from grandpa.dispatch import (
    NOT_HANDLED,
    DispatchResult,
    IntentDispatcher,
    IntentHandler,
    RequestContext,
)

ROOT = Path(__file__).resolve().parents[2]
DISPATCH_DIR = ROOT / "src" / "grandpa" / "dispatch"


class RecordingHandler:
    """A handler that records what it was asked, and acts on nothing.

    One method, matching the contract: ``try_handle`` either serves the request
    or returns ``NOT_HANDLED``. ``calls`` therefore counts invocations, which is
    the property the single-method contract exists to bound.
    """

    def __init__(self, name: str, *, claims_it: bool = True) -> None:
        self.name = name
        self._claims_it = claims_it
        self.calls: list[RequestContext] = []

    def try_handle(self, ctx: RequestContext):
        self.calls.append(ctx)
        if not self._claims_it:
            return NOT_HANDLED
        return f"handled by {self.name}"


def _ctx(text: str = "open notepad") -> RequestContext:
    return RequestContext(text=text, origin="direct")


class TestRequestContext:
    def test_is_frozen(self) -> None:
        ctx = _ctx()
        with pytest.raises(dataclasses.FrozenInstanceError):
            ctx.text = "something else"  # type: ignore[misc]

    def test_origin_is_required(self) -> None:
        """Omitting provenance must fail loudly, not become "direct"."""
        with pytest.raises(TypeError):
            RequestContext(text="open notepad")  # type: ignore[call-arg]

    def test_origin_has_no_default(self) -> None:
        """Asserted on the field itself, not only through the constructor.

        A default could be reintroduced later without breaking the constructor
        test above, since that test would then simply stop raising.
        """
        field = {f.name: f for f in dataclasses.fields(RequestContext)}["origin"]
        assert field.default is dataclasses.MISSING
        assert field.default_factory is dataclasses.MISSING

    def test_dry_run_is_the_only_defaulted_field(self) -> None:
        defaulted = {
            f.name
            for f in dataclasses.fields(RequestContext)
            if f.default is not dataclasses.MISSING
            or f.default_factory is not dataclasses.MISSING
        }
        assert defaulted == {"dry_run"}
        assert _ctx().dry_run is False

    def test_uses_the_existing_action_origin_vocabulary(self) -> None:
        """No new origin words invented here."""
        from grandpa.policy.models import ActionOrigin

        assert set(ActionOrigin.__args__) == {
            "voice",
            "agent",
            "direct",
            "api",
            "scheduler",
            "skill",
        }
        for origin in ActionOrigin.__args__:
            assert RequestContext(text="x", origin=origin).origin == origin


class TestHandlerProtocol:
    def test_a_try_handle_handler_satisfies_the_protocol(self) -> None:
        assert isinstance(RecordingHandler("fake"), IntentHandler)

    def test_object_missing_try_handle_does_not(self) -> None:
        class NotAHandler:
            name = "nope"

        assert not isinstance(NotAHandler(), IntentHandler)

    def test_the_old_claims_handle_pair_no_longer_satisfies_it(self) -> None:
        """The 4.5B-E amendment: a split handler is not a handler any more."""

        class LegacyHandler:
            name = "legacy"

            def claims(self, ctx):
                return True

            def handle(self, ctx):
                return "x"

        assert not isinstance(LegacyHandler(), IntentHandler)


class TestOrderingAndSelection:
    def test_registration_preserves_explicit_order(self) -> None:
        dispatcher = IntentDispatcher()
        third = RecordingHandler("third")
        first = RecordingHandler("first")
        second = RecordingHandler("second")

        dispatcher.register(third, order=30)
        dispatcher.register(first, order=10)
        dispatcher.register(second, order=20)

        assert [h.name for h in dispatcher.handlers] == ["first", "second", "third"]

    def test_equal_orders_fall_back_to_registration_sequence(self) -> None:
        """Ties must be defined, not left to sort stability."""
        dispatcher = IntentDispatcher()
        for name in ("a", "b", "c"):
            dispatcher.register(RecordingHandler(name), order=5)

        assert [h.name for h in dispatcher.handlers] == ["a", "b", "c"]

    def test_first_claiming_handler_serves_the_request(self) -> None:
        dispatcher = IntentDispatcher()
        declines = RecordingHandler("declines", claims_it=False)
        claims = RecordingHandler("claims")
        never = RecordingHandler("never")
        dispatcher.register(declines, order=10)
        dispatcher.register(claims, order=20)
        dispatcher.register(never, order=30)

        result = dispatcher.dispatch(_ctx())

        assert result.handler_name == "claims"
        assert result.result == "handled by claims"
        assert result.claimed is True
        # The later handler was never even asked.
        assert never.calls == []

    def test_a_declining_handler_is_asked_exactly_once(self) -> None:
        """The contract's core guarantee: one invocation, not two."""
        dispatcher = IntentDispatcher()
        declines = RecordingHandler("declines", claims_it=False)
        dispatcher.register(declines, order=10)
        dispatcher.register(RecordingHandler("claims"), order=20)

        dispatcher.dispatch(_ctx())

        assert len(declines.calls) == 1

    def test_the_serving_handler_is_also_asked_exactly_once(self) -> None:
        dispatcher = IntentDispatcher()
        serves = RecordingHandler("serves")
        dispatcher.register(serves, order=10)

        dispatcher.dispatch(_ctx())

        assert len(serves.calls) == 1

    def test_handler_receives_the_context_unchanged(self) -> None:
        dispatcher = IntentDispatcher()
        handler = RecordingHandler("only")
        dispatcher.register(handler, order=10)
        ctx = _ctx("open task manager")

        dispatcher.dispatch(ctx)

        assert handler.calls == [ctx]


class TestNoMatchBehaviour:
    def test_empty_dispatcher_returns_an_unclaimed_result(self) -> None:
        result = IntentDispatcher().dispatch(_ctx())

        assert result.claimed is False
        assert result.handler_name is None
        assert result.result is NOT_HANDLED

    def test_no_handler_claiming_is_not_an_error(self) -> None:
        """Falling through to conversation is ordinary, not exceptional."""
        dispatcher = IntentDispatcher()
        dispatcher.register(RecordingHandler("a", claims_it=False), order=10)
        dispatcher.register(RecordingHandler("b", claims_it=False), order=20)

        result = dispatcher.dispatch(_ctx())

        assert result.claimed is False


class TestNoPolicyShapedFields:
    """The dispatcher must not become a second policy boundary.

    Three policy-shaped result models already exist -- ``PolicyDecision``,
    ``PermissionStatus`` and ``IntentRoute``. A fourth grown here would have to
    be reconciled along with the other three.
    """

    FORBIDDEN = {
        "risk",
        "risk_level",
        "approval",
        "approval_required",
        "permission",
        "permission_status",
        "blocked",
        "blocked_reason",
        "approval_token",
    }

    @pytest.mark.parametrize("model", [RequestContext, DispatchResult])
    def test_no_risk_or_approval_fields(self, model: type) -> None:
        names = {f.name for f in dataclasses.fields(model)}
        assert not (names & self.FORBIDDEN), names & self.FORBIDDEN

    def test_dispatcher_exposes_no_classification_api(self) -> None:
        public = {n for n in dir(IntentDispatcher) if not n.startswith("_")}
        assert public == {"register", "dispatch", "handlers"}


class TestLayering:
    """``dispatch`` may not reach into capability, execution or storage."""

    FORBIDDEN_MODULES = {
        "grandpa.pc_control",
        "grandpa.local_actions",
        "grandpa.apps",
        "grandpa.browser",
        "grandpa.files",
        "grandpa.desktop",
        "grandpa.router",
        "grandpa.skills",
        "subprocess",
        "sqlite3",
        "webbrowser",
        "shutil",
        "os",
    }

    def _imported_modules(self) -> set[str]:
        modules: set[str] = set()
        for path in sorted(DISPATCH_DIR.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    modules.update(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    modules.add(node.module)
        return modules

    def test_no_forbidden_imports(self) -> None:
        imported = self._imported_modules()
        # Guard against a vacuous pass: an empty set would satisfy every
        # assertion below without proving anything about the package.
        assert imported, "no imports parsed -- the AST walk found nothing"

        offending = {
            module
            for module in imported
            for banned in self.FORBIDDEN_MODULES
            if module == banned or module.startswith(f"{banned}.")
        }
        assert offending == set(), offending

    def test_the_only_grandpa_dependency_is_policy_models(self) -> None:
        """Narrower than the denylist: an allowlist of what may be imported."""
        grandpa_imports = {
            m for m in self._imported_modules() if m.startswith("grandpa.")
        }
        assert grandpa_imports <= {
            "grandpa.policy.models",
            "grandpa.dispatch.context",
            "grandpa.dispatch.protocol",
            "grandpa.dispatch.registry",
        }, grandpa_imports


class TestNothingConsumesItYet:
    def test_no_production_module_outside_dispatch_imports_it(self) -> None:
        """4.4a is additive: existing routing cannot have changed.

        If this ever fails, a surface has been migrated and the claim that
        production routing is untouched no longer holds -- which is a thing to
        assert deliberately, not to discover.
        """
        importers: list[str] = []
        for path in (ROOT / "src" / "grandpa").rglob("*.py"):
            if DISPATCH_DIR in path.parents:
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
