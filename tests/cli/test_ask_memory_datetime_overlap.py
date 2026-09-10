"""The ask.py memory/datetime invariant: datetime-first, without side effects.

Four inputs are recognised by both ``handle_memory_command`` and
``handle_datetime_intent``. Precedence is ratified as **datetime-first** for
explicit deterministic date/time requests -- and datetime winning is not enough
on its own, because ``handle_memory_command`` mutates when it matches. Until
this was fixed, ``ask`` called memory before it consulted datetime, so
``forget what day it is today`` performed a deletion and then showed the date,
with the deletion invisible.

The invariant these tests hold: **when datetime claims a request, the memory
handler is never invoked at all**, so no mutation can occur. That is stronger
than "memory's result is discarded", and it is what makes the behaviour safe
rather than merely ordered.

**Isolation.** The real ``handle_memory_command`` and the real
``handle_datetime_intent`` both run -- stubbing either would defeat the point.
Only the store is replaced, through the ``MemoryStore`` constructor that
``handle_memory_command`` uses when no ``store=`` is passed, which is exactly
how ``ask`` calls it. No default store, no SQLite, no filesystem, no network,
no process. The handlers after datetime are stubbed to decline, and the LLM
fallback is a sentinel.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from grandpa.cli import cli
from grandpa.local_actions import LocalActionResult

#: Text both handlers recognise. Derived in the D-5C follow-up audit by running
#: the datetime matcher over memory-command phrasings.
OVERLAP_REMEMBER = ["remember what day it is today", "remember the current time"]
OVERLAP_FORGET = ["forget what day it is today", "forget the current date"]
OVERLAP_ALL = OVERLAP_REMEMBER + OVERLAP_FORGET

#: Controls: one handler each, so the overlap assertions cannot pass by
#: accident of every input behaving the same way.
MEMORY_ONLY = "remember my project is grandpa"
DATETIME_ONLY = "what day is it today"


class RecordingStore:
    """A memory store that records mutations instead of performing them."""

    def __init__(self) -> None:
        self.remembered: list[tuple[str, str, str]] = []
        self.forgotten: list[str] = []
        self.cleared = 0

    # -- the three mutating methods handle_memory_command can reach ----------
    def remember(self, category: str, key: str, value: str) -> bool:
        self.remembered.append((category, key, value))
        return True

    def forget(self, target: str) -> int:
        self.forgotten.append(target)
        return 0

    def clear_all(self) -> None:
        self.cleared += 1

    # -- read paths, present so a non-matching command does not explode ------
    def recall(self, *a, **k):
        return []

    def profile(self, *a, **k):
        return {}

    @property
    def mutated(self) -> bool:
        return bool(self.remembered or self.forgotten or self.cleared)


class _FallbackReached(Exception):
    """Sentinel proving the chain fell through without reaching an engine."""


@pytest.fixture
def store(monkeypatch) -> RecordingStore:
    """Inject the recording store at the constructor the handler uses."""
    import grandpa.memory_context as memory_context

    recording = RecordingStore()
    monkeypatch.setattr(memory_context, "MemoryStore", lambda *a, **k: recording)
    return recording


@pytest.fixture
def chain(monkeypatch, store: RecordingStore):
    """Run the real memory and datetime handlers; stub everything downstream."""
    import grandpa.cli.ask as ask_mod
    import grandpa.core.runtime_context as runtime_context
    import grandpa.core_ai_brain as brain
    import grandpa.file_assistant as file_assistant
    import grandpa.local_actions as local_actions
    import grandpa.memory_context as memory_context
    import grandpa.task_scheduler as task_scheduler

    seen = SimpleNamespace(
        datetime_calls=[],
        datetime_answer=None,
        local_action_called=False,
        memory_calls=[],
    )

    real_datetime = runtime_context.handle_datetime_intent
    real_memory = memory_context.handle_memory_command

    def memory_spy(text, *a, **k):
        seen.memory_calls.append(text)
        return real_memory(text, *a, **k)

    def datetime_spy(text, *a, **k):
        seen.datetime_calls.append(text)
        answer = real_datetime(text, *a, **k)
        seen.datetime_answer = answer
        return answer

    def declining_local_action(text, *a, **k):
        seen.local_action_called = True
        return LocalActionResult(status="no_match")

    def declining(kind):
        return lambda text, *a, **k: SimpleNamespace(
            should_fallback=True, message="", kind=kind, target=None, status="no_match"
        )

    def fallback(*a, **k):
        raise _FallbackReached

    monkeypatch.setattr(runtime_context, "handle_datetime_intent", datetime_spy)
    monkeypatch.setattr(memory_context, "handle_memory_command", memory_spy)
    monkeypatch.setattr(local_actions, "handle_local_action", declining_local_action)
    monkeypatch.setattr(file_assistant, "handle_file_command", declining("file"))
    monkeypatch.setattr(
        task_scheduler, "handle_scheduler_command", declining("scheduler")
    )
    monkeypatch.setattr(memory_context, "remember_conversation", lambda *a, **k: None)
    monkeypatch.setattr(brain, "record_assistant_outcome", lambda *a, **k: None)
    monkeypatch.setattr(
        brain,
        "process_user_message",
        lambda text, **k: SimpleNamespace(effective_text=text),
    )
    monkeypatch.setattr(ask_mod, "load_config", fallback)

    return seen


def _ask(query: str):
    return CliRunner().invoke(cli, ["ask", query], catch_exceptions=True)


# ---------------------------------------------------------------------------
# A + B -- both handlers recognise the same text
# ---------------------------------------------------------------------------


class TestBothHandlersClaim:
    @pytest.mark.parametrize("text", OVERLAP_ALL)
    def test_the_memory_handler_matches(self, text: str) -> None:
        from grandpa.memory_context import handle_memory_command

        result = handle_memory_command(text, store=RecordingStore())

        assert result.should_fallback is False, text

    @pytest.mark.parametrize("text", OVERLAP_ALL)
    def test_the_datetime_handler_matches(self, text: str) -> None:
        from grandpa.core.runtime_context import handle_datetime_intent

        assert handle_datetime_intent(text), text

    def test_the_controls_are_claimed_by_exactly_one_handler(self) -> None:
        """Without this the overlap tests could pass for any input at all."""
        from grandpa.core.runtime_context import handle_datetime_intent
        from grandpa.memory_context import handle_memory_command

        assert (
            handle_memory_command(MEMORY_ONLY, store=RecordingStore()).should_fallback
            is False
        )
        assert not handle_datetime_intent(MEMORY_ONLY)

        assert handle_datetime_intent(DATETIME_ONLY)
        assert (
            handle_memory_command(DATETIME_ONLY, store=RecordingStore()).should_fallback
            is True
        )


# ---------------------------------------------------------------------------
# C -- what the ask.py path does with them
# ---------------------------------------------------------------------------


class TestOverlapOnTheAskPath:
    @pytest.mark.parametrize("text", OVERLAP_ALL)
    def test_datetime_supplies_the_answer(self, text: str, chain, store) -> None:
        result = _ask(text)

        assert chain.datetime_calls == [text]
        assert chain.datetime_answer
        assert chain.datetime_answer in result.stdout

    @pytest.mark.parametrize("text", OVERLAP_ALL)
    def test_the_chain_stops_before_local_action(self, text: str, chain, store) -> None:
        _ask(text)

        assert chain.local_action_called is False


class TestMemoryIsNotReachedWhenDatetimeClaims:
    """The invariant. Not "its result is discarded" -- it is never called.

    Discarding would still leave the mutation in place, because
    ``handle_memory_command`` writes as it matches rather than afterwards.
    Only never invoking it makes the request side-effect free.
    """

    @pytest.mark.parametrize("text", OVERLAP_ALL)
    def test_the_memory_handler_is_never_invoked(self, text: str, chain, store) -> None:
        _ask(text)

        assert chain.memory_calls == []

    @pytest.mark.parametrize("text", OVERLAP_ALL)
    def test_the_store_is_untouched(self, text: str, chain, store) -> None:
        _ask(text)

        assert store.mutated is False
        assert store.remembered == []
        assert store.forgotten == []

    @pytest.mark.parametrize("text", OVERLAP_FORGET)
    def test_no_deletion_occurs(self, text: str, chain, store) -> None:
        """The two inputs that would delete. Named separately so a failure
        says which class of harm returned."""
        result = _ask(text)

        assert store.forgotten == []
        assert chain.datetime_answer in result.stdout

    @pytest.mark.parametrize("text", OVERLAP_REMEMBER)
    def test_no_write_occurs(self, text: str, chain, store) -> None:
        result = _ask(text)

        assert store.remembered == []
        assert chain.datetime_answer in result.stdout

    @pytest.mark.parametrize("text", OVERLAP_ALL)
    def test_the_memory_message_never_reaches_the_user(
        self, text: str, chain, store
    ) -> None:
        """It cannot, since the handler did not run -- asserted so a future
        change that re-introduces the call is caught by output too."""
        from grandpa.memory_context import handle_memory_command

        would_have_said = handle_memory_command(text, store=RecordingStore()).message
        assert would_have_said, "control: memory must have something to say"

        result = _ask(text)

        assert would_have_said not in result.stdout


class TestControls:
    """The overlap behaviour must not be what every input does."""

    def test_a_memory_only_command_is_answered_by_memory(
        self, chain, store: RecordingStore
    ) -> None:
        """Non-overlapping memory behaviour is untouched by the fix."""
        result = _ask(MEMORY_ONLY)

        assert chain.memory_calls == [MEMORY_ONLY]
        assert chain.datetime_answer is None
        assert store.remembered
        assert "remember" in result.stdout.lower()

    def test_a_datetime_only_command_mutates_nothing(
        self, chain, store: RecordingStore
    ) -> None:
        """Datetime claims it, so memory is not consulted and nothing moves."""
        result = _ask(DATETIME_ONLY)

        assert chain.memory_calls == []
        assert store.mutated is False
        assert chain.datetime_answer in result.stdout

    def test_the_default_store_is_never_constructed(
        self, chain, store: RecordingStore
    ) -> None:
        """Proves the isolation seam actually held for the whole run."""
        import grandpa.memory_context as memory_context

        _ask(OVERLAP_FORGET[0])

        assert memory_context.MemoryStore("ignored") is store
