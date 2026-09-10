"""Why the dispatcher contract is one method, and what the alternatives cost.

4.5B established that four of ``ask``'s five handlers act while deciding
whether they claim, and 4.5B-C sharpened that: ``handle_file_command`` runs the
file automation *before* consulting its own patterns, so its claim decision is
the mutation. A ``claims()`` that must be side-effect free cannot wrap it, and
caching a ``claims()`` result does not help -- caching prevents the *second*
call, not the first.

4.5B-E ratified the combined contract on that evidence. This file keeps the
comparison that led there, so the reasoning survives the decision: the three
shapes are modelled side by side, and the cost of the one that was replaced is
still demonstrable rather than merely asserted.

``claims() + handle()``
    The 4.4a contract, now replaced. Two calls per selected handler -- shown
    below still doubling when the pair is called by hand.
``try_handle()``
    The ratified shape. One call returning a result or ``NOT_HANDLED``. It was
    **already the production idiom**: every ``grandpa.actions`` domain exposes
    ``try_handle(command) -> result | None``.
``opaque execution``
    The dispatcher cannot know whether a handler claimed without running it --
    which is the situation the real handlers are already in, and which
    ``try_handle`` is the honest interface for.

The local ``NOT_HANDLED`` below belongs to the test-only model dispatcher and
is deliberately distinct from ``grandpa.dispatch.NOT_HANDLED``; the production
sentinel is exercised by the tests that use the real ``IntentDispatcher``.

The handler doubles are modelled on measured behaviour, not invented: each
records its effects so a test can prove how many times they happened.
"""

from __future__ import annotations

from typing import Any

import pytest

from grandpa.dispatch import IntentDispatcher, RequestContext
from grandpa.file_assistant import FileAssistantResult
from grandpa.local_actions import LocalActionResult
from grandpa.memory_context import MemoryCommandResult
from grandpa.task_scheduler import SchedulerResult

#: Test-only sentinel. A handler that did not claim returns this rather than a
#: result. ``None`` would be ambiguous: ``handle_datetime_intent`` legitimately
#: returns ``None``-ish falsy strings, and a real result can be falsy too.
NOT_HANDLED = object()


def _ctx(text: str) -> RequestContext:
    return RequestContext(text=text, origin="direct")


class EffectfulHandler:
    """A handler that acts as it decides -- like four of the five real ones.

    ``effects`` counts how many times the handler did its work. The whole point
    of the contract question is whether the dispatcher can select among these
    without that count exceeding one.
    """

    def __init__(self, name: str, claims_text: set[str], result: Any) -> None:
        self.name = name
        self._claims_text = claims_text
        self._result = result
        self.effects: list[str] = []

    # -- combined shape ------------------------------------------------------
    def try_handle(self, ctx: RequestContext) -> Any:
        self.effects.append(ctx.text)  # the act of deciding IS the effect
        if ctx.text in self._claims_text:
            return self._result
        return NOT_HANDLED

    # -- split shape, as the 4.4a contract requires ---------------------------
    def claims(self, ctx: RequestContext) -> bool:
        return self.try_handle(ctx) is not NOT_HANDLED

    def handle(self, ctx: RequestContext) -> Any:
        return self.try_handle(ctx)


class TryHandleDispatcher:
    """Test-only model of a combined-protocol dispatcher.

    Ordering and selection only -- deliberately the same responsibilities the
    real ``IntentDispatcher`` has. It classifies nothing, approves nothing and
    executes nothing itself; it asks handlers in order and returns what the
    first claiming one produced.
    """

    def __init__(self) -> None:
        self._entries: list[tuple[int, int, Any]] = []
        self._seq = 0

    def register(self, handler: Any, *, order: int) -> None:
        self._entries.append((order, self._seq, handler))
        self._seq += 1
        self._entries.sort(key=lambda e: (e[0], e[1]))

    @property
    def handlers(self) -> tuple[Any, ...]:
        return tuple(h for _o, _s, h in self._entries)

    def dispatch(self, ctx: RequestContext) -> tuple[str | None, Any]:
        for handler in self.handlers:
            outcome = handler.try_handle(ctx)
            if outcome is not NOT_HANDLED:
                return handler.name, outcome
        return None, NOT_HANDLED


# ---------------------------------------------------------------------------
# PART A -- the combined contract's ten requirements
# ---------------------------------------------------------------------------


@pytest.fixture
def chain() -> tuple[TryHandleDispatcher, list[EffectfulHandler]]:
    handlers = [
        EffectfulHandler("datetime", {"what day is it today"}, "it is Tuesday"),
        EffectfulHandler("memory", {"remember my project"}, "remembered"),
        EffectfulHandler("local_action", {"open notepad"}, "opened"),
        EffectfulHandler("file", {"show recent files", "open notepad"}, "files"),
        EffectfulHandler("scheduler", {"list routines"}, "routines"),
    ]
    dispatcher = TryHandleDispatcher()
    for index, handler in enumerate(handlers):
        dispatcher.register(handler, order=(index + 1) * 10)
    return dispatcher, handlers


class TestCombinedContractRequirements:
    def test_1_exactly_one_invocation_of_the_selected_handler(self, chain) -> None:
        dispatcher, handlers = chain

        dispatcher.dispatch(_ctx("open notepad"))

        local_action = handlers[2]
        assert len(local_action.effects) == 1

    def test_2_no_separate_claims_call_precedes_execution(self, chain) -> None:
        """The selected handler is asked once, not asked-then-told."""
        dispatcher, handlers = chain

        dispatcher.dispatch(_ctx("what day is it today"))

        assert handlers[0].effects == ["what day is it today"]

    def test_3_no_double_execution_anywhere_in_the_chain(self, chain) -> None:
        dispatcher, handlers = chain

        dispatcher.dispatch(_ctx("list routines"))

        assert all(len(h.effects) <= 1 for h in handlers)

    def test_4_earlier_handlers_still_win(self, chain) -> None:
        """``open notepad`` is claimed by both local_action and file."""
        dispatcher, _handlers = chain

        name, _result = dispatcher.dispatch(_ctx("open notepad"))

        assert name == "local_action"

    def test_5_registration_order_matches_ask(self, chain) -> None:
        dispatcher, _handlers = chain

        assert [h.name for h in dispatcher.handlers] == [
            "datetime",
            "memory",
            "local_action",
            "file",
            "scheduler",
        ]

    def test_6_handlers_after_the_winner_are_never_asked(self, chain) -> None:
        """No safety gate downstream can be triggered by a served request."""
        dispatcher, handlers = chain

        dispatcher.dispatch(_ctx("open notepad"))

        assert handlers[3].effects == []  # file
        assert handlers[4].effects == []  # scheduler

    def test_7_the_result_object_passes_through_unchanged(self) -> None:
        sentinel = object()
        dispatcher = TryHandleDispatcher()
        dispatcher.register(EffectfulHandler("only", {"x"}, sentinel), order=10)

        _name, result = dispatcher.dispatch(_ctx("x"))

        assert result is sentinel

    def test_8_declining_handlers_act_at_most_once(self, chain) -> None:
        """Declining still costs one invocation -- the price of the shape."""
        dispatcher, handlers = chain

        dispatcher.dispatch(_ctx("list routines"))

        assert handlers[0].effects == ["list routines"]
        assert len(handlers[0].effects) == 1

    def test_9_unhandled_input_continues_to_the_next_handler(self, chain) -> None:
        dispatcher, handlers = chain

        name, _ = dispatcher.dispatch(_ctx("list routines"))

        assert name == "scheduler"
        assert [h.name for h in handlers if h.effects] == [
            "datetime",
            "memory",
            "local_action",
            "file",
            "scheduler",
        ]

    def test_10_handled_input_stops_the_chain(self, chain) -> None:
        dispatcher, handlers = chain

        dispatcher.dispatch(_ctx("what day is it today"))

        assert [h.name for h in handlers if h.effects] == ["datetime"]


# ---------------------------------------------------------------------------
# PART B -- the three shapes, side by side
# ---------------------------------------------------------------------------


class TestClaimsPlusHandleDoublesTheEffect:
    """Why 4.4a's split cannot wrap handlers that act while deciding."""

    def test_the_split_invokes_the_handler_twice(self) -> None:
        handler = EffectfulHandler("file", {"create folder notes"}, "made")

        handler.claims(_ctx("create folder notes"))
        handler.handle(_ctx("create folder notes"))

        assert len(handler.effects) == 2

    def test_the_production_dispatcher_no_longer_doubles(self) -> None:
        """What the 4.5B-E amendment changed.

        Before it, registering this handler and dispatching produced **two**
        effects, because the dispatcher asked ``claims`` and then ``handle``.
        It now asks ``try_handle`` once. The split above still doubles when
        called by hand, which is why the contract stopped requiring it.
        """
        handler = EffectfulHandler("file", {"create folder notes"}, "made")
        dispatcher = IntentDispatcher()
        dispatcher.register(handler, order=10)

        dispatcher.dispatch(_ctx("create folder notes"))

        assert len(handler.effects) == 1

    def test_caching_would_not_prevent_the_first_effect(self) -> None:
        """The decisive point against a caching ``claims()``.

        Caching removes the *second* call. The first still happened, and for
        ``handle_file_command`` the first call is the one that reaches the
        mutation boundary.
        """
        handler = EffectfulHandler("file", {"create folder notes"}, "made")

        cached = handler.try_handle(_ctx("create folder notes"))  # the "claims"

        assert cached is not NOT_HANDLED
        assert len(handler.effects) == 1, "the effect already happened"

    def test_try_handle_costs_exactly_one(self) -> None:
        handler = EffectfulHandler("file", {"create folder notes"}, "made")
        dispatcher = TryHandleDispatcher()
        dispatcher.register(handler, order=10)

        dispatcher.dispatch(_ctx("create folder notes"))

        assert len(handler.effects) == 1


class TestOpaqueExecutionIsWhatTheHandlersAlreadyAre:
    """Shape 3: the dispatcher cannot know without running.

    This is not a hypothetical protocol -- it is the measured behaviour of the
    real handlers, and ``try_handle`` is simply the honest interface for it.
    ``grandpa.actions`` already ships that exact signature.
    """

    def test_production_already_uses_the_combined_signature(self) -> None:
        import inspect

        from grandpa.actions import desktop_actions

        params = list(inspect.signature(desktop_actions.try_handle).parameters)
        assert params == ["command"]
        assert desktop_actions.try_handle("list monitors") is not None
        assert desktop_actions.try_handle("not a command") is None

    def test_the_44b_adapters_synthesise_claims_by_calling_it_twice(self) -> None:
        """Safe only because those seven are pure -- verified in 4.4b."""
        from grandpa.dispatch.adapters.action_modules import ActionModuleHandler

        calls: list[str] = []
        handler = ActionModuleHandler("counting", lambda text: calls.append(text))

        handler.claims(_ctx("x"))
        handler.handle(_ctx("x"))

        assert calls == ["x", "x"]


# ---------------------------------------------------------------------------
# PART C -- result opacity across the five real shapes
# ---------------------------------------------------------------------------

REAL_RESULTS = [
    ("datetime", "it is Tuesday"),  # Optional[str] -- not an object at all
    ("memory", MemoryCommandResult("handled", "memory", "k", "m", "t")),
    ("local_action", LocalActionResult(status="handled", kind="app", message="m")),
    ("file", FileAssistantResult("handled", "file", "t", "m", "t")),
    ("scheduler", SchedulerResult("handled", "scheduler", "t", "m", "t")),
]


class TestResultsStayOpaque:
    @pytest.mark.parametrize("name,result", REAL_RESULTS)
    def test_each_real_result_passes_through_identically(
        self, name: str, result: Any
    ) -> None:
        """No normalization: the same object comes back out."""
        dispatcher = TryHandleDispatcher()
        dispatcher.register(EffectfulHandler(name, {"go"}, result), order=10)

        claimed, out = dispatcher.dispatch(_ctx("go"))

        assert claimed == name
        assert out is result

    @pytest.mark.parametrize("name,result", REAL_RESULTS)
    def test_the_dispatcher_never_inspects_the_result(
        self, name: str, result: Any
    ) -> None:
        """It compares against the sentinel by identity, nothing more.

        This is what lets the datetime string and four unrelated dataclasses
        travel the same path without a common base type.
        """
        dispatcher = TryHandleDispatcher()
        dispatcher.register(EffectfulHandler(name, {"go"}, result), order=10)

        _claimed, out = dispatcher.dispatch(_ctx("go"))

        assert type(out) is type(result)

    def test_unhandled_is_distinguishable_from_a_falsy_result(self) -> None:
        """Why a sentinel rather than ``None`` or truthiness.

        ``handle_datetime_intent`` returns ``Optional[str]`` and a result object
        can be falsy; only an identity sentinel separates "did not claim" from
        "claimed and produced something empty".
        """
        dispatcher = TryHandleDispatcher()
        dispatcher.register(EffectfulHandler("empty", {"go"}, ""), order=10)

        claimed, out = dispatcher.dispatch(_ctx("go"))

        assert claimed == "empty"
        assert out == ""
        assert out is not NOT_HANDLED

    def test_nothing_claiming_yields_the_sentinel(self) -> None:
        dispatcher = TryHandleDispatcher()
        dispatcher.register(EffectfulHandler("a", {"x"}, "r"), order=10)

        claimed, out = dispatcher.dispatch(_ctx("something else"))

        assert claimed is None
        assert out is NOT_HANDLED


# ---------------------------------------------------------------------------
# PART D -- precedence
# ---------------------------------------------------------------------------


class TestPrecedenceIsPreservable:
    def test_datetime_beats_memory_on_the_overlap(self, chain) -> None:
        """The ratified GAP-22 invariant, in the combined shape."""
        dispatcher, handlers = chain
        handlers[0]._claims_text = {"forget what day it is today"}
        handlers[1]._claims_text = {"forget what day it is today"}

        name, _ = dispatcher.dispatch(_ctx("forget what day it is today"))

        assert name == "datetime"
        assert handlers[1].effects == [], "memory must not even be asked"

    def test_local_action_beats_file_on_open_notepad(self, chain) -> None:
        """The overlap found in 4.5B-C: both claim, position decides."""
        dispatcher, handlers = chain

        name, _ = dispatcher.dispatch(_ctx("open notepad"))

        assert name == "local_action"
        assert handlers[3].effects == []

    def test_file_and_scheduler_do_not_overlap(self, chain) -> None:
        dispatcher, _handlers = chain

        assert dispatcher.dispatch(_ctx("show recent files"))[0] == "file"
        assert dispatcher.dispatch(_ctx("list routines"))[0] == "scheduler"

    def test_an_unclaimed_phrase_falls_through_to_the_llm(self, chain) -> None:
        dispatcher, _handlers = chain

        name, out = dispatcher.dispatch(_ctx("tell me a joke"))

        assert name is None
        assert out is NOT_HANDLED

    def test_the_full_order_is_reproducible(self, chain) -> None:
        dispatcher, _handlers = chain

        assert [h.name for h in dispatcher.handlers] == [
            "datetime",
            "memory",
            "local_action",
            "file",
            "scheduler",
        ]


# ---------------------------------------------------------------------------
# PART E -- the dispatcher stays out of policy and execution
# ---------------------------------------------------------------------------


class GatedHandler:
    """A handler that runs its own gates, as the real ones do."""

    def __init__(self, name: str, gates: list[str]) -> None:
        self.name = name
        self._gates = gates
        self.gates_run: list[str] = []

    def try_handle(self, ctx: RequestContext) -> Any:
        self.gates_run.extend(self._gates)
        if ctx.text == "dangerous":
            return "blocked by the handler's own gate"
        if ctx.text == "needs approval":
            return "approval staged by the handler"
        return NOT_HANDLED


class TestDispatcherRemainsSelectionOnly:
    """Combining ``claims`` and ``handle`` does not move any gate.

    The gates stay where they are -- inside the handlers and the funnels beneath
    them. What changes is only how many times the dispatcher asks.
    """

    GATES = [
        "dangerous_check",
        "approval",
        "emergency_stop",
        "dry_run",
        "delete_confirmation",
        "mutation_boundary",
        "provenance",
    ]

    def test_every_gate_still_runs_inside_the_handler(self) -> None:
        handler = GatedHandler("local_action", self.GATES)
        dispatcher = TryHandleDispatcher()
        dispatcher.register(handler, order=10)

        dispatcher.dispatch(_ctx("dangerous"))

        assert handler.gates_run == self.GATES

    def test_a_blocked_request_is_still_a_claim(self) -> None:
        """Blocking is an answer; the chain must stop, not fall through."""
        handler = GatedHandler("local_action", self.GATES)
        dispatcher = TryHandleDispatcher()
        dispatcher.register(handler, order=10)
        later = EffectfulHandler("file", {"dangerous"}, "file result")
        dispatcher.register(later, order=20)

        name, out = dispatcher.dispatch(_ctx("dangerous"))

        assert name == "local_action"
        assert out == "blocked by the handler's own gate"
        assert later.effects == [], "a blocked request reached a later handler"

    def test_approval_staging_also_stops_the_chain(self) -> None:
        handler = GatedHandler("file", self.GATES)
        dispatcher = TryHandleDispatcher()
        dispatcher.register(handler, order=10)
        later = EffectfulHandler("scheduler", {"needs approval"}, "sched")
        dispatcher.register(later, order=20)

        name, _ = dispatcher.dispatch(_ctx("needs approval"))

        assert name == "file"
        assert later.effects == []

    def test_the_dispatcher_model_exposes_no_policy_api(self) -> None:
        """Same shape as the production dispatcher's frozen public surface."""
        public = {n for n in dir(TryHandleDispatcher) if not n.startswith("_")}

        assert public == {"register", "dispatch", "handlers"}

    def test_the_production_dispatcher_surface_is_unchanged_by_this_file(
        self,
    ) -> None:
        public = {n for n in dir(IntentDispatcher) if not n.startswith("_")}

        assert public == {"register", "dispatch", "handlers"}


class TestTheAmendedProductionContract:
    def test_intent_handler_declares_try_handle_only(self) -> None:
        """Ratified in 4.5B-E: one method, not two."""
        from grandpa.dispatch.protocol import IntentHandler

        assert hasattr(IntentHandler, "try_handle")
        assert not hasattr(IntentHandler, "claims")
        assert not hasattr(IntentHandler, "handle")

    def test_request_context_is_untouched(self) -> None:
        import dataclasses

        names = [f.name for f in dataclasses.fields(RequestContext)]
        assert names == ["text", "origin", "dry_run"]
