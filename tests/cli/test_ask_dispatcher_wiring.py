"""``ask`` routes through the dispatcher, and does so exactly once.

The behavioural guarantees -- precedence, single invocation, output shape, the
datetime special case -- are already pinned by the parity and output suites.
This file covers only what wiring itself introduces: that ``ask`` builds one
dispatcher per invocation, hands it the right ``RequestContext``, and no longer
reaches any of the five handlers directly.

Written before the wiring, and failing against the pre-wiring implementation.
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from grandpa.cli import cli

ASK_PATH = Path(__file__).resolve().parents[2] / "src" / "grandpa" / "cli" / "ask.py"
ASK_SOURCE = ASK_PATH.read_text(encoding="utf-8")

#: The five handlers ``ask`` used to call itself. It must now call none of them.
DIRECT_HANDLER_CALLS = [
    "handle_datetime_intent(",
    "handle_memory_command(",
    "handle_local_action(",
    "handle_file_command(",
    "handle_scheduler_command(",
]


class _FallbackReached(Exception):
    """Sentinel raised from ``load_config`` -- the first call after the chain."""


@pytest.fixture
def wiring(monkeypatch):
    """Watch dispatcher construction and what it is dispatched with."""
    import grandpa.cli.ask as ask_mod
    import grandpa.composition.ask_handlers as ask_handlers
    import grandpa.core_ai_brain as brain
    import grandpa.memory_context as memory_context

    seen = SimpleNamespace(builds=0, contexts=[], fallback_reached=False)
    real_build = ask_handlers.build_ask_dispatcher

    def counting_build():
        seen.builds += 1
        dispatcher = real_build()
        real_dispatch = dispatcher.dispatch

        def watched(ctx):
            seen.contexts.append(ctx)
            return real_dispatch(ctx)

        dispatcher.dispatch = watched  # type: ignore[method-assign]
        return dispatcher

    monkeypatch.setattr(ask_handlers, "build_ask_dispatcher", counting_build)

    # Every handler declines, so the chain runs to the end unless a test says
    # otherwise. Patched where the adapters resolve them, at call time.
    import grandpa.core.runtime_context as runtime_context
    import grandpa.file_assistant as file_assistant
    import grandpa.local_actions as local_actions
    import grandpa.task_scheduler as task_scheduler
    from grandpa.local_actions import LocalActionResult

    def declines(kind):
        return lambda text, *a, **k: SimpleNamespace(
            should_fallback=True, message="", kind=kind, target=None, status="no_match"
        )

    monkeypatch.setattr(runtime_context, "handle_datetime_intent", lambda t: None)
    monkeypatch.setattr(memory_context, "handle_memory_command", declines("memory"))
    monkeypatch.setattr(
        local_actions,
        "handle_local_action",
        lambda t, *a, **k: LocalActionResult(status="no_match"),
    )
    monkeypatch.setattr(file_assistant, "handle_file_command", declines("file"))
    monkeypatch.setattr(
        task_scheduler, "handle_scheduler_command", declines("scheduler")
    )
    monkeypatch.setattr(memory_context, "remember_conversation", lambda *a, **k: None)
    monkeypatch.setattr(brain, "record_assistant_outcome", lambda *a, **k: None)
    monkeypatch.setattr(
        brain,
        "process_user_message",
        lambda text, **k: SimpleNamespace(effective_text=text),
    )

    def fallback(*a, **k):
        seen.fallback_reached = True
        raise _FallbackReached

    monkeypatch.setattr(ask_mod, "load_config", fallback)
    return seen


def _ask(query: str = "hello there"):
    return CliRunner().invoke(cli, ["ask", query], catch_exceptions=True)


class TestAskUsesTheDispatcher:
    def test_one_dispatcher_is_built_per_invocation(self, wiring) -> None:
        _ask()

        assert wiring.builds == 1

    def test_a_second_invocation_builds_its_own(self, wiring) -> None:
        """No sharing between requests, which is what module scope would give."""
        _ask()
        _ask()

        assert wiring.builds == 2

    def test_the_dispatcher_is_used_exactly_once_per_invocation(self, wiring) -> None:
        _ask()

        assert len(wiring.contexts) == 1


class TestTheRequestContext:
    def test_it_carries_the_effective_text(self, wiring) -> None:
        _ask("what is the weather")

        assert wiring.contexts[0].text == "what is the weather"

    def test_origin_is_direct(self, wiring) -> None:
        _ask()

        assert wiring.contexts[0].origin == "direct"

    def test_dry_run_is_false(self, wiring) -> None:
        """``ask`` has no dry-run mode; nothing should invent one."""
        _ask()

        assert wiring.contexts[0].dry_run is False

    def test_it_has_no_surface_field(self, wiring) -> None:
        _ask()

        assert not hasattr(wiring.contexts[0], "surface")


class TestAskNoLongerCallsHandlersDirectly:
    """Source-level, because the point is the absence of a call."""

    @pytest.mark.parametrize("call", DIRECT_HANDLER_CALLS)
    def test_no_direct_handler_call_remains(self, call: str) -> None:
        assert call not in ASK_SOURCE, call

    def test_the_dispatcher_builder_is_used(self) -> None:
        assert "build_ask_dispatcher" in ASK_SOURCE
        assert "RequestContext" in ASK_SOURCE

    def test_the_builder_is_not_imported_at_module_scope(self) -> None:
        """Module-scope construction would share one dispatcher across calls.

        The import itself must sit inside the function, matching how ``ask``
        resolves every other handler.
        """
        tree = ast.parse(ASK_SOURCE)
        module_level = {
            node.module
            for node in tree.body
            if isinstance(node, ast.ImportFrom) and node.module
        }

        assert not any("ask_handlers" in (m or "") for m in module_level)

    def test_no_dispatcher_is_constructed_at_module_scope(self) -> None:
        tree = ast.parse(ASK_SOURCE)
        for node in tree.body:
            if isinstance(node, ast.Assign):
                call = getattr(node, "value", None)
                name = getattr(getattr(call, "func", None), "id", "")
                assert name != "build_ask_dispatcher"


class TestFallThroughStillReachesTheLlm:
    def test_nothing_claiming_reaches_load_config(self, wiring) -> None:
        _ask()

        assert wiring.fallback_reached is True
