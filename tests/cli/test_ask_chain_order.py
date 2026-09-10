"""The handler chain inside ``grandpa ask``, frozen before anything migrates.

``ask.py`` probes five handlers and falls through to the LLM. Thirty-three
existing ``ask`` tests cover model resolution, context and agent behaviour, and
**none of them touches this chain** -- GAP-22, concretely. So the property the
dispatcher migration must preserve is the one property with no test behind it.

These tests characterize what ships. They do not assert it is correct, and one
thing recorded below is arguably a defect (see ``TestDatetimeOutranksMemory``).

**Nothing is executed.** Every handler is replaced at the seam ``ask`` resolves
it through, so no action runs, no approval row is written, no browser or
filesystem is touched, and the LLM is never reached -- the fallback path is
detected by a sentinel raised from ``load_config``, which is the first call
after the chain.

``handle_local_action`` is treated as impure throughout, because it is: under
``execute=True`` it audits to SQLite and actuates. It is stubbed once, called
once, and never wrapped in a ``claims()``.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from grandpa.cli import cli
from grandpa.local_actions import LocalActionResult

MEMORY = "memory"
DATETIME = "datetime"
LOCAL_ACTION = "local_action"
FILE = "file"
SCHEDULER = "scheduler"

#: The order handlers are invoked in, which is now also the precedence order.
#: Before the GAP-22 fix, memory was *called* first but *checked* last, so the
#: two orders disagreed -- see ``TestDatetimeIsFirst``.
INVOCATION_ORDER = [DATETIME, MEMORY, LOCAL_ACTION, FILE, SCHEDULER]


class _FallbackReached(Exception):
    """Raised from ``load_config`` to prove the chain fell through.

    ``load_config`` is the first thing ``ask`` does after the scheduler
    handler declines, so reaching it means every handler fell through. Raising
    is how the test observes that without an engine, a model or a network call.
    """


def _declining_result(kind: str) -> SimpleNamespace:
    return SimpleNamespace(
        should_fallback=True, message="", kind=kind, target=None, status="no_match"
    )


def _claiming_result(kind: str, message: str) -> SimpleNamespace:
    return SimpleNamespace(
        should_fallback=False,
        message=message,
        kind=kind,
        target=f"{kind}-target",
        status="handled",
    )


class Chain:
    """Records what ``ask`` asked, in order, and what it was asked with."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.texts: dict[str, str] = {}
        self.local_action_kwargs: dict = {}
        self.file_kwargs: dict = {}
        self.fallback_reached = False

        self.memory_result = _declining_result("memory")
        self.datetime_result: str | None = None
        self.local_action_result = LocalActionResult(status="no_match")
        self.file_result = _declining_result("file")
        self.scheduler_result = _declining_result("scheduler")


@pytest.fixture
def chain(monkeypatch) -> Chain:
    """Replace every handler at the seam ``ask`` resolves it through.

    ``ask`` imports each handler inside the function body, so the name is
    looked up on the source module at call time and patching that module
    attribute is what the running code actually sees. Verified against the
    import sites before these tests were written.
    """
    import grandpa.cli.ask as ask_mod
    import grandpa.core.runtime_context as runtime_context
    import grandpa.core_ai_brain as brain
    import grandpa.file_assistant as file_assistant
    import grandpa.local_actions as local_actions
    import grandpa.memory_context as memory_context
    import grandpa.task_scheduler as task_scheduler

    c = Chain()

    def memory(text, *a, **k):
        c.calls.append(MEMORY)
        c.texts[MEMORY] = text
        return c.memory_result

    def datetime_intent(text, *a, **k):
        c.calls.append(DATETIME)
        c.texts[DATETIME] = text
        return c.datetime_result

    def local_action(text, *a, **k):
        c.calls.append(LOCAL_ACTION)
        c.texts[LOCAL_ACTION] = text
        c.local_action_kwargs = dict(k)
        return c.local_action_result

    def file_command(text, *a, **k):
        c.calls.append(FILE)
        c.texts[FILE] = text
        c.file_kwargs = dict(k)
        return c.file_result

    def scheduler(text, *a, **k):
        c.calls.append(SCHEDULER)
        c.texts[SCHEDULER] = text
        return c.scheduler_result

    def fallback(*a, **k):
        c.fallback_reached = True
        raise _FallbackReached

    monkeypatch.setattr(memory_context, "handle_memory_command", memory)
    monkeypatch.setattr(runtime_context, "handle_datetime_intent", datetime_intent)
    monkeypatch.setattr(local_actions, "handle_local_action", local_action)
    monkeypatch.setattr(file_assistant, "handle_file_command", file_command)
    monkeypatch.setattr(task_scheduler, "handle_scheduler_command", scheduler)

    # Silence the two recording side effects the chain performs around each
    # handler; they write to the memory store and are not what is under test.
    monkeypatch.setattr(memory_context, "remember_conversation", lambda *a, **k: None)
    monkeypatch.setattr(brain, "record_assistant_outcome", lambda *a, **k: None)
    monkeypatch.setattr(
        brain,
        "process_user_message",
        lambda text, **k: SimpleNamespace(effective_text=text),
    )
    monkeypatch.setattr(ask_mod, "load_config", fallback)

    return c


def _ask(query: str = "hello there", *extra: str):
    return CliRunner().invoke(cli, ["ask", query, *extra], catch_exceptions=True)


# ---------------------------------------------------------------------------
# Invocation order and fall-through
# ---------------------------------------------------------------------------


class TestFullFallThrough:
    def test_every_handler_is_asked_in_this_order(self, chain: Chain) -> None:
        _ask()

        assert chain.calls == INVOCATION_ORDER

    def test_the_llm_fallback_is_reached_when_nobody_claims(self, chain: Chain) -> None:
        _ask()

        assert chain.fallback_reached is True

    def test_every_handler_receives_the_same_effective_text(self, chain: Chain) -> None:
        """One text, resolved once by the brain, passed to all five."""
        _ask("what is the weather")

        assert set(chain.texts) == set(INVOCATION_ORDER)
        assert set(chain.texts.values()) == {"what is the weather"}


class TestDatetimeIsFirst:
    """Datetime is asked first and, when it claims, nothing else is asked.

    This is the ratified precedence, and the GAP-22 fix made invocation match
    it. Before that fix ``handle_memory_command`` was *called* at ask.py:678 but
    its result was not *checked* until ask.py:710 -- after datetime had already
    answered and returned. Memory therefore ran on requests it did not serve,
    and because it mutates as it matches, "forget what day it is today"
    performed a deletion that nothing displayed.

    ``tests/cli/test_ask_memory_datetime_overlap.py`` holds the side-effect half
    of this invariant, on the four inputs both handlers recognise.
    """

    def test_datetime_is_invoked_before_memory(self, chain: Chain) -> None:
        _ask()

        assert chain.calls.index(DATETIME) < chain.calls.index(MEMORY)

    def test_datetime_wins_when_both_would_claim(self, chain: Chain) -> None:
        chain.memory_result = _claiming_result("memory", "remembered answer")
        chain.datetime_result = "it is Tuesday"

        result = _ask()

        assert "it is Tuesday" in result.stdout
        assert "remembered answer" not in result.stdout

    def test_memory_is_not_run_for_a_request_datetime_answers(
        self, chain: Chain
    ) -> None:
        """The property the fix added: not merely discarded, never invoked."""
        chain.datetime_result = "it is Tuesday"

        _ask()

        assert MEMORY not in chain.calls

    def test_nothing_at_all_is_asked_once_datetime_claims(self, chain: Chain) -> None:
        chain.datetime_result = "it is Tuesday"

        _ask()

        assert chain.calls == [DATETIME]
        assert chain.fallback_reached is False


class TestEarlyReturn:
    def test_memory_claiming_stops_the_chain(self, chain: Chain) -> None:
        chain.memory_result = _claiming_result("memory", "remembered")

        _ask()

        assert chain.calls == [DATETIME, MEMORY]
        assert LOCAL_ACTION not in chain.calls
        assert chain.fallback_reached is False

    def test_local_action_claiming_stops_file_and_scheduler(self, chain: Chain) -> None:
        chain.local_action_result = LocalActionResult(
            status="handled", kind="app", target="notepad", message="Notepad opened."
        )

        _ask()

        assert chain.calls == [DATETIME, MEMORY, LOCAL_ACTION]
        assert FILE not in chain.calls
        assert SCHEDULER not in chain.calls
        assert chain.fallback_reached is False

    def test_local_action_falling_back_continues_the_chain(self, chain: Chain) -> None:
        chain.local_action_result = LocalActionResult(status="no_match")

        _ask()

        assert FILE in chain.calls
        assert SCHEDULER in chain.calls

    def test_file_claiming_stops_scheduler_and_fallback(self, chain: Chain) -> None:
        chain.file_result = _claiming_result("file", "Listed your files.")

        _ask()

        assert chain.calls == [DATETIME, MEMORY, LOCAL_ACTION, FILE]
        assert SCHEDULER not in chain.calls
        assert chain.fallback_reached is False

    def test_scheduler_claiming_stops_the_fallback(self, chain: Chain) -> None:
        chain.scheduler_result = _claiming_result("scheduler", "Reminder set.")

        _ask()

        assert chain.calls == INVOCATION_ORDER
        assert chain.fallback_reached is False


# ---------------------------------------------------------------------------
# What ask.py asks for, and what it reads back
# ---------------------------------------------------------------------------


class TestLocalActionInvocation:
    def test_it_is_called_once_and_only_once(self, chain: Chain) -> None:
        """``handle_local_action`` actuates and audits; calling it twice would
        run the action twice. This is why it cannot be wrapped in a
        ``claims()``/``handle()`` pair without a contract change."""
        _ask()

        assert chain.calls.count(LOCAL_ACTION) == 1

    def test_execute_is_left_at_its_default(self, chain: Chain) -> None:
        """``ask`` passes no ``execute``, so the default ``True`` applies."""
        _ask()

        assert "execute" not in chain.local_action_kwargs

    def test_the_default_really_is_execute_true(self) -> None:
        """The other half of the claim, read off the production signature."""
        import inspect

        from grandpa.local_actions import handle_local_action

        assert (
            inspect.signature(handle_local_action).parameters["execute"].default is True
        )


class TestFileProvenance:
    def test_the_file_handler_is_told_the_origin_is_direct(self, chain: Chain) -> None:
        """``ask`` is local interactive human use, which is what ``direct``
        names. Unchanged by D-5, which split ``api`` out of it."""
        _ask()

        assert chain.file_kwargs.get("origin") == "direct"


class TestConsumedResultFields:
    """The five fields ``ask`` reads off a claiming result.

    The result object is passed through unmodified -- these assertions read the
    values back out of ``--json`` rather than reconstructing anything.
    """

    def test_local_action_fields_reach_the_json_output(self, chain: Chain) -> None:
        chain.local_action_result = LocalActionResult(
            status="handled",
            kind="app",
            target="notepad",
            message="Notepad opened.",
        )

        result = _ask("open notepad", "--json")
        payload = json.loads(result.stdout)

        assert payload["content"] == "Notepad opened."
        assert payload["local_action"] == {
            "status": "handled",
            "kind": "app",
            "target": "notepad",
        }

    def test_should_fallback_is_what_decides_the_chain(self, chain: Chain) -> None:
        """``no_match`` is the only status that continues the chain."""
        chain.local_action_result = LocalActionResult(status="no_match")
        _ask()
        assert FILE in chain.calls

        chain.calls.clear()
        chain.local_action_result = LocalActionResult(
            status="blocked", message="I blocked this action for safety."
        )
        _ask()
        assert FILE not in chain.calls

    @pytest.mark.parametrize("status", ["handled", "blocked", "error", "unsupported"])
    def test_every_non_no_match_status_stops_the_chain_identically(
        self, chain: Chain, status: str
    ) -> None:
        """``ask`` does not branch on status -- it echoes and returns.

        Unlike the voice surfaces it has no special handling for
        ``pending_confirmation`` or ``requires_confirmation``.
        """
        chain.local_action_result = LocalActionResult(status=status, message="m")

        _ask()

        assert chain.calls == [DATETIME, MEMORY, LOCAL_ACTION]


class TestExecuteModeConsequence:
    """What ``execute=True`` commits ``ask`` to, without restating 4.4c.

    Because ``ask`` leaves ``execute`` at its default, the funnel's
    execute-dependent gate is live for it: the legacy skill router serves the
    19 execute-contested phrases and the 9 execute-gated skill-only ones, and
    the action modules do not. The full partition is characterized in
    ``tests/dispatch/test_golden_order.py``; pinned here is only the ``ask``
    half -- that it is on the ``execute=True`` side of that split.
    """

    def test_ask_is_on_the_execute_true_side_of_the_split(self, chain: Chain) -> None:
        _ask()

        assert "execute" not in chain.local_action_kwargs

    def test_the_gate_that_makes_this_matter_still_reads_execute(self) -> None:
        import inspect

        from grandpa.local_actions import handle_local_action

        source = inspect.getsource(handle_local_action)

        assert "if execute and not _prefer_deterministic_browser_route" in source
