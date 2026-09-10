"""The five ``ask`` handlers, presented in the dispatcher's shape.

``composition.ask_handlers`` wraps the handlers ``cli/ask.py`` already calls so
each satisfies ``try_handle(ctx) -> HandlerResult | NOT_HANDLED``. The adapters
are translation and nothing else: they call the handler once, decide claimed or
not from the value it returned, and hand that value back untouched.

**Nothing is wired.** ``ask.py`` is unchanged and does not import this; these
adapters have no production consumer yet, which is what makes this slice
reversible by deletion.

Why each rule below is asserted rather than assumed, in one line each:

* *called exactly once* -- four of the five act while deciding, so a second
  call would repeat a write, a deletion or an actuation.
* *result returned by identity* -- twelve call sites downstream read ``status``,
  ``kind``, ``message`` and ``should_fallback`` off these objects; a copy is a
  chance for one of them to differ.
* *``execute`` never passed* -- ``ask`` leaves it at its default, which is what
  puts it on the ``execute=True`` side of the 4.4c routing split.
* *datetime truthiness* -- ``ask.py:681`` tests ``if dt_resp:`` while
  ``voice/assistant.py:155`` tests ``is not None``. The adapter follows ``ask``.

The handlers themselves are stubbed at the module attribute each adapter
resolves at call time, so no real store, filesystem, browser or subprocess is
reached.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from grandpa.dispatch import (
    NOT_HANDLED,
    IntentDispatcher,
    IntentHandler,
    RequestContext,
)

ASK_ORDER = ["datetime", "memory", "local_action", "file", "scheduler"]

#: (adapter name, module that owns the handler, attribute patched)
SEAMS = {
    "datetime": ("grandpa.core.runtime_context", "handle_datetime_intent"),
    "memory": ("grandpa.memory_context", "handle_memory_command"),
    "local_action": ("grandpa.local_actions", "handle_local_action"),
    "file": ("grandpa.file_assistant", "handle_file_command"),
    "scheduler": ("grandpa.task_scheduler", "handle_scheduler_command"),
}


def _ctx(text: str = "anything", origin: str = "direct", dry_run: bool = False):
    return RequestContext(text=text, origin=origin, dry_run=dry_run)


def _claiming(kind: str) -> SimpleNamespace:
    return SimpleNamespace(
        should_fallback=False, status="handled", kind=kind, target="t", message="m"
    )


def _declining(kind: str) -> SimpleNamespace:
    return SimpleNamespace(
        should_fallback=True, status="no_match", kind=kind, target=None, message=""
    )


class Spy:
    """Records every call and returns a fixed value."""

    def __init__(self, result) -> None:
        self.calls: list[tuple[tuple, dict]] = []
        self.result = result

    def __call__(self, *args, **kwargs):
        self.calls.append((args, dict(kwargs)))
        return self.result


@pytest.fixture
def patch_handler(monkeypatch):
    """Replace one handler at the module attribute its adapter resolves."""
    import importlib

    def _patch(name: str, result):
        module_name, attr = SEAMS[name]
        spy = Spy(result)
        monkeypatch.setattr(importlib.import_module(module_name), attr, spy)
        return spy

    return _patch


def _adapter(name: str):
    from grandpa.composition.ask_handlers import build_ask_handlers

    return next(h for h in build_ask_handlers() if h.name == name)


# ---------------------------------------------------------------------------
# Shape
# ---------------------------------------------------------------------------


class TestAdaptersSatisfyTheContract:
    @pytest.mark.parametrize("name", ASK_ORDER)
    def test_each_adapter_is_an_intent_handler(self, name: str) -> None:
        assert isinstance(_adapter(name), IntentHandler)

    @pytest.mark.parametrize("name", ASK_ORDER)
    def test_each_adapter_exposes_only_try_handle(self, name: str) -> None:
        """No ``claims``/``handle`` pair: that shape is what 4.5B-E replaced."""
        adapter = _adapter(name)

        assert hasattr(adapter, "try_handle")
        assert not hasattr(adapter, "claims")
        assert not hasattr(adapter, "handle")

    def test_all_five_are_built(self) -> None:
        from grandpa.composition.ask_handlers import build_ask_handlers

        assert [h.name for h in build_ask_handlers()] == ASK_ORDER


# ---------------------------------------------------------------------------
# One call, exactly
# ---------------------------------------------------------------------------


class TestExactlyOneInvocation:
    @pytest.mark.parametrize("name", ASK_ORDER)
    def test_a_claiming_handler_is_called_once(self, name, patch_handler) -> None:
        result = "it is Tuesday" if name == "datetime" else _claiming(name)
        spy = patch_handler(name, result)

        _adapter(name).try_handle(_ctx())

        assert len(spy.calls) == 1

    @pytest.mark.parametrize("name", ASK_ORDER)
    def test_a_declining_handler_is_also_called_once(self, name, patch_handler) -> None:
        result = None if name == "datetime" else _declining(name)
        spy = patch_handler(name, result)

        _adapter(name).try_handle(_ctx())

        assert len(spy.calls) == 1


# ---------------------------------------------------------------------------
# Verdicts and identity
# ---------------------------------------------------------------------------


class TestClaimAndDecline:
    @pytest.mark.parametrize("name", ASK_ORDER)
    def test_a_claimed_result_is_returned_by_identity(
        self, name, patch_handler
    ) -> None:
        result = "it is Tuesday" if name == "datetime" else _claiming(name)
        patch_handler(name, result)

        assert _adapter(name).try_handle(_ctx()) is result

    @pytest.mark.parametrize("name", ASK_ORDER)
    def test_an_unclaimed_call_returns_not_handled(self, name, patch_handler) -> None:
        result = None if name == "datetime" else _declining(name)
        patch_handler(name, result)

        assert _adapter(name).try_handle(_ctx()) is NOT_HANDLED

    @pytest.mark.parametrize("name", [n for n in ASK_ORDER if n != "datetime"])
    def test_the_verdict_comes_from_should_fallback(self, name, patch_handler) -> None:
        """Not from truthiness of the object, and not from ``status``."""
        odd = SimpleNamespace(
            should_fallback=False, status="blocked", kind=name, target="", message=""
        )
        patch_handler(name, odd)

        assert _adapter(name).try_handle(_ctx()) is odd


class TestDatetimeTruthiness:
    """``ask`` uses ``if dt_resp:``; the adapter must match that, not ``is not None``."""

    @pytest.mark.parametrize("value", ["it is Tuesday", "0"])
    def test_a_truthy_string_claims(self, value, patch_handler) -> None:
        patch_handler("datetime", value)

        assert _adapter("datetime").try_handle(_ctx()) is value

    @pytest.mark.parametrize("value", [None, "", 0, False])
    def test_a_falsy_value_declines(self, value, patch_handler) -> None:
        """An empty string is *not* a claim -- ``ask`` would fall through."""
        patch_handler("datetime", value)

        assert _adapter("datetime").try_handle(_ctx()) is NOT_HANDLED


# ---------------------------------------------------------------------------
# Call arguments
# ---------------------------------------------------------------------------


class TestCallArguments:
    @pytest.mark.parametrize("name", ASK_ORDER)
    def test_the_text_is_the_only_positional(self, name, patch_handler) -> None:
        result = "x" if name == "datetime" else _declining(name)
        spy = patch_handler(name, result)

        _adapter(name).try_handle(_ctx("some request"))

        args, _kwargs = spy.calls[0]
        assert args == ("some request",)

    def test_local_action_is_not_passed_execute(self, patch_handler) -> None:
        """Leaving the default is what keeps ``ask`` on the 4.4c ``execute=True``
        side of the routing split."""
        spy = patch_handler("local_action", _declining("app"))

        _adapter("local_action").try_handle(_ctx())

        _args, kwargs = spy.calls[0]
        assert "execute" not in kwargs

    def test_scheduler_is_not_passed_execute(self, patch_handler) -> None:
        spy = patch_handler("scheduler", _declining("scheduler"))

        _adapter("scheduler").try_handle(_ctx())

        _args, kwargs = spy.calls[0]
        assert "execute" not in kwargs

    @pytest.mark.parametrize("origin", ["direct", "voice", "api"])
    def test_file_receives_the_context_origin(self, origin, patch_handler) -> None:
        """No new vocabulary: whatever the caller stated is forwarded."""
        spy = patch_handler("file", _declining("file"))

        _adapter("file").try_handle(_ctx(origin=origin))

        _args, kwargs = spy.calls[0]
        assert kwargs == {"origin": origin}

    @pytest.mark.parametrize("name", [n for n in ASK_ORDER if n != "file"])
    def test_only_the_file_adapter_forwards_origin(self, name, patch_handler) -> None:
        """The other four take no origin parameter today."""
        result = "x" if name == "datetime" else _declining(name)
        spy = patch_handler(name, result)

        _adapter(name).try_handle(_ctx())

        _args, kwargs = spy.calls[0]
        assert "origin" not in kwargs

    @pytest.mark.parametrize("name", ASK_ORDER)
    @pytest.mark.parametrize("dry_run", [True, False])
    def test_dry_run_is_ignored(self, name, dry_run, patch_handler) -> None:
        """``ask`` has no dry-run mode; no handler takes the parameter."""
        result = "x" if name == "datetime" else _declining(name)
        spy = patch_handler(name, result)

        _adapter(name).try_handle(_ctx(dry_run=dry_run))

        _args, kwargs = spy.calls[0]
        assert "dry_run" not in kwargs


# ---------------------------------------------------------------------------
# The builder
# ---------------------------------------------------------------------------


class TestBuilder:
    def test_registration_order_is_the_ask_order(self) -> None:
        from grandpa.composition.ask_handlers import build_ask_dispatcher

        dispatcher = build_ask_dispatcher()

        assert [h.name for h in dispatcher.handlers] == ASK_ORDER

    def test_it_returns_a_real_dispatcher(self) -> None:
        from grandpa.composition.ask_handlers import build_ask_dispatcher

        assert isinstance(build_ask_dispatcher(), IntentDispatcher)

    def test_each_call_builds_a_fresh_dispatcher(self) -> None:
        from grandpa.composition.ask_handlers import build_ask_dispatcher

        assert build_ask_dispatcher() is not build_ask_dispatcher()


class TestDispatchThroughTheBuilder:
    def test_the_first_claiming_adapter_wins(self, patch_handler) -> None:
        from grandpa.composition.ask_handlers import build_ask_dispatcher

        patch_handler("datetime", None)
        claimed = _claiming("memory")
        patch_handler("memory", claimed)
        later = patch_handler("local_action", _claiming("app"))

        result = build_ask_dispatcher().dispatch(_ctx())

        assert result.handler_name == "memory"
        assert result.result is claimed
        assert later.calls == [], "a later handler was invoked after a claim"

    def test_declining_adapters_fall_through(self, patch_handler) -> None:
        from grandpa.composition.ask_handlers import build_ask_dispatcher

        spies = {}
        patch_handler("datetime", None)
        for name in ("memory", "local_action", "file"):
            spies[name] = patch_handler(name, _declining(name))
        claimed = _claiming("scheduler")
        patch_handler("scheduler", claimed)

        result = build_ask_dispatcher().dispatch(_ctx())

        assert result.handler_name == "scheduler"
        assert result.result is claimed
        assert all(len(s.calls) == 1 for s in spies.values())

    def test_nothing_claiming_is_the_llm_fallback_case(self, patch_handler) -> None:
        from grandpa.composition.ask_handlers import build_ask_dispatcher

        patch_handler("datetime", None)
        for name in ("memory", "local_action", "file", "scheduler"):
            patch_handler(name, _declining(name))

        result = build_ask_dispatcher().dispatch(_ctx())

        assert result.claimed is False
        assert result.result is NOT_HANDLED

    def test_datetime_claiming_leaves_memory_uninvoked(self, patch_handler) -> None:
        """The ratified GAP-22 invariant, through the dispatcher."""
        from grandpa.composition.ask_handlers import build_ask_dispatcher

        patch_handler("datetime", "it is Tuesday")
        memory = patch_handler("memory", _claiming("memory"))

        result = build_ask_dispatcher().dispatch(_ctx())

        assert result.handler_name == "datetime"
        assert memory.calls == []


# ---------------------------------------------------------------------------
# What the adapters must not do
# ---------------------------------------------------------------------------


class TestAdaptersDoNothingElse:
    def test_an_adapter_invokes_only_its_own_handler(self, patch_handler) -> None:
        spies = {
            name: patch_handler(name, None if name == "datetime" else _declining(name))
            for name in ASK_ORDER
        }

        _adapter("file").try_handle(_ctx())

        assert len(spies["file"].calls) == 1
        assert all(spies[n].calls == [] for n in ASK_ORDER if n != "file")

    def test_exceptions_propagate(self, monkeypatch) -> None:
        """The adapter adds no error envelope of its own."""
        import grandpa.memory_context as memory_context

        def boom(*_a, **_k):
            raise RuntimeError("handler failed")

        monkeypatch.setattr(memory_context, "handle_memory_command", boom)

        with pytest.raises(RuntimeError, match="handler failed"):
            _adapter("memory").try_handle(_ctx())

    def test_the_module_imports_no_policy_or_execution_machinery(self) -> None:
        import ast
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "grandpa"
            / "composition"
            / "ask_handlers.py"
        ).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }

        for banned in ("grandpa.policy.engine", "grandpa.pc_control"):
            assert banned not in imported, banned


class TestHandlerModulesAreUntouched:
    def test_the_five_handlers_keep_their_signatures(self) -> None:
        """The adapters required no change to any handler."""
        import inspect

        from grandpa.core.runtime_context import handle_datetime_intent
        from grandpa.file_assistant import handle_file_command
        from grandpa.local_actions import handle_local_action
        from grandpa.memory_context import handle_memory_command
        from grandpa.task_scheduler import handle_scheduler_command

        assert list(inspect.signature(handle_datetime_intent).parameters) == ["query"]
        assert list(inspect.signature(handle_memory_command).parameters) == [
            "text",
            "store",
        ]
        assert list(inspect.signature(handle_local_action).parameters) == [
            "text",
            "execute",
        ]
        assert list(inspect.signature(handle_file_command).parameters) == [
            "text",
            "store",
            "origin",
        ]
        assert list(inspect.signature(handle_scheduler_command).parameters) == [
            "text",
            "store",
            "execute",
        ]

    def test_ask_py_now_uses_the_composition_builder(self) -> None:
        """Wired in 4.5I. ``ask`` is the dispatcher's first production consumer.

        This assertion was the inverse until then -- it pinned that nothing
        consumed the adapters yet. The adapters themselves are unchanged by the
        wiring, which is what the rest of this file goes on checking.
        """
        from pathlib import Path

        ask = (
            Path(__file__).resolve().parents[1] / "src" / "grandpa" / "cli" / "ask.py"
        ).read_text(encoding="utf-8")

        assert "build_ask_dispatcher" in ask
        assert "RequestContext(" in ask
