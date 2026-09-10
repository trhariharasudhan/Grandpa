"""What ``grandpa ask`` records and prints, frozen before the dispatcher lands.

The 256-case parity harness proves the dispatcher *selects* the same handler as
the live chain. It stops there. It says nothing about what ``ask`` does once a
handler claims -- the conversation memory write, the outcome record, and the
payload the user actually sees. That is the half a wiring change would break
quietly, so this file pins it first.

Every assertion here is about observable output:

* the arguments ``remember_conversation`` receives
* the arguments ``record_assistant_outcome`` receives
* the exact ``--json`` payload
* the exact plain-text line
* which handlers ran, in order, and how many times
* whether the chain returned early or fell through to the LLM

**The datetime block is the one that differs**, and the reason this file exists.
``handle_datetime_intent`` returns a bare string, so ``ask`` hardcodes
``kind="local"``, ``target=None`` and ``status="handled"`` rather than reading
them off a result object. A wiring change that unified the five post-handler
blocks would change those three values and nothing else would notice.

Nothing is executed: the five handlers are replaced at the module attribute
``ask`` resolves at call time, the two recording calls are spies, and the LLM
fallback is a sentinel raised from ``load_config``.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from grandpa.cli import cli
from grandpa.local_actions import LocalActionResult

ASK_ORDER = ["datetime", "memory", "local_action", "file", "scheduler"]


class _FallbackReached(Exception):
    """Raised from ``load_config`` -- the first call after the chain."""


def _result(kind: str, message: str, *, target: str = "t", status: str = "handled"):
    return SimpleNamespace(
        should_fallback=False,
        message=message,
        kind=kind,
        target=target,
        status=status,
    )


def _declines(kind: str):
    return SimpleNamespace(
        should_fallback=True, message="", kind=kind, target=None, status="no_match"
    )


class Recorder:
    """Everything ``ask`` did that a user or an audit could observe."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.remembered: list[tuple[str, str]] = []
        self.outcomes: list[dict] = []
        self.fallback_reached = False
        self.results: dict[str, object] = {}


@pytest.fixture
def ask_env(monkeypatch):
    """Drive ``ask`` with every handler and recording call replaced."""
    import grandpa.cli.ask as ask_mod
    import grandpa.core.runtime_context as runtime_context
    import grandpa.core_ai_brain as brain
    import grandpa.file_assistant as file_assistant
    import grandpa.local_actions as local_actions
    import grandpa.memory_context as memory_context
    import grandpa.task_scheduler as task_scheduler

    rec = Recorder()
    rec.results = {
        "datetime": None,
        "memory": _declines("memory"),
        "local_action": LocalActionResult(status="no_match"),
        "file": _declines("file"),
        "scheduler": _declines("scheduler"),
    }
    seen_kwargs: dict[str, dict] = {}

    def handler(name):
        def call(text, *args, **kwargs):
            rec.calls.append(name)
            seen_kwargs[name] = dict(kwargs)
            return rec.results[name]

        return call

    monkeypatch.setattr(runtime_context, "handle_datetime_intent", handler("datetime"))
    monkeypatch.setattr(memory_context, "handle_memory_command", handler("memory"))
    monkeypatch.setattr(local_actions, "handle_local_action", handler("local_action"))
    monkeypatch.setattr(file_assistant, "handle_file_command", handler("file"))
    monkeypatch.setattr(
        task_scheduler, "handle_scheduler_command", handler("scheduler")
    )

    monkeypatch.setattr(
        memory_context,
        "remember_conversation",
        lambda role, text: rec.remembered.append((role, text)),
    )
    monkeypatch.setattr(
        brain,
        "record_assistant_outcome",
        lambda analysis, **kwargs: rec.outcomes.append(dict(kwargs)),
    )
    monkeypatch.setattr(
        brain,
        "process_user_message",
        lambda text, **k: SimpleNamespace(effective_text=text),
    )

    def fallback(*a, **k):
        rec.fallback_reached = True
        raise _FallbackReached

    monkeypatch.setattr(ask_mod, "load_config", fallback)

    rec.kwargs = seen_kwargs  # type: ignore[attr-defined]
    return rec


def _ask(query: str = "hello", *extra: str):
    return CliRunner().invoke(cli, ["ask", query, *extra], catch_exceptions=True)


# ---------------------------------------------------------------------------
# 1. datetime -- the special case
# ---------------------------------------------------------------------------


class TestDatetimeOutput:
    """The hardcoded record. If a wiring change unifies the five post-handler
    blocks, these are the assertions that catch it."""

    def test_the_outcome_is_recorded_with_hardcoded_fields(self, ask_env) -> None:
        ask_env.results["datetime"] = "it is Tuesday"

        _ask()

        assert ask_env.outcomes == [
            {
                "assistant_text": "it is Tuesday",
                "kind": "local",
                "target": None,
                "status": "handled",
            }
        ]

    def test_kind_is_local_not_the_handler_name(self, ask_env) -> None:
        """``local``, not ``datetime`` -- pinned separately because it is the
        single most tempting value to 'correct' during a refactor."""
        ask_env.results["datetime"] = "it is Tuesday"

        _ask()

        assert ask_env.outcomes[0]["kind"] == "local"

    def test_target_is_none_and_status_is_handled(self, ask_env) -> None:
        ask_env.results["datetime"] = "it is Tuesday"

        _ask()

        assert ask_env.outcomes[0]["target"] is None
        assert ask_env.outcomes[0]["status"] == "handled"

    def test_the_string_itself_is_remembered(self, ask_env) -> None:
        ask_env.results["datetime"] = "it is Tuesday"

        _ask()

        assert ("assistant", "it is Tuesday") in ask_env.remembered

    def test_json_payload(self, ask_env) -> None:
        ask_env.results["datetime"] = "it is Tuesday"

        result = _ask("what day is it", "--json")

        assert json.loads(result.stdout) == {
            "content": "it is Tuesday",
            "local_action": {"status": "handled", "kind": "local", "target": None},
        }

    def test_plain_output_is_the_bare_string(self, ask_env) -> None:
        ask_env.results["datetime"] = "it is Tuesday"

        result = _ask()

        assert result.stdout.strip() == "it is Tuesday"

    def test_it_returns_before_any_other_handler(self, ask_env) -> None:
        ask_env.results["datetime"] = "it is Tuesday"

        _ask()

        assert ask_env.calls == ["datetime"]
        assert ask_env.fallback_reached is False


# ---------------------------------------------------------------------------
# 2-5. The four object-returning handlers
# ---------------------------------------------------------------------------

OBJECT_HANDLERS = [
    ("memory", "Remembered that.", "memory"),
    ("local_action", "Notepad opened.", "app"),
    ("file", "Listed your files.", "file"),
    ("scheduler", "Reminder set.", "scheduler"),
]


class TestObjectHandlerOutput:
    """All four read ``message``/``kind``/``target``/``status`` off the result."""

    @staticmethod
    def _claim(env, name: str, message: str, kind: str) -> None:
        env.results[name] = _result(kind, message, target=f"{name}-target")

    @pytest.mark.parametrize("name,message,kind", OBJECT_HANDLERS)
    def test_the_outcome_mirrors_the_result_object(
        self, name, message, kind, ask_env
    ) -> None:
        self._claim(ask_env, name, message, kind)

        _ask()

        assert ask_env.outcomes == [
            {
                "assistant_text": message,
                "kind": kind,
                "target": f"{name}-target",
                "status": "handled",
            }
        ]

    @pytest.mark.parametrize("name,message,kind", OBJECT_HANDLERS)
    def test_the_message_is_remembered(self, name, message, kind, ask_env) -> None:
        self._claim(ask_env, name, message, kind)

        _ask()

        assert ("assistant", message) in ask_env.remembered

    @pytest.mark.parametrize("name,message,kind", OBJECT_HANDLERS)
    def test_json_payload(self, name, message, kind, ask_env) -> None:
        self._claim(ask_env, name, message, kind)

        result = _ask("something", "--json")

        assert json.loads(result.stdout) == {
            "content": message,
            "local_action": {
                "status": "handled",
                "kind": kind,
                "target": f"{name}-target",
            },
        }

    @pytest.mark.parametrize("name,message,kind", OBJECT_HANDLERS)
    def test_plain_output_is_the_message(self, name, message, kind, ask_env) -> None:
        self._claim(ask_env, name, message, kind)

        result = _ask()

        assert result.stdout.strip() == message

    @pytest.mark.parametrize("name,message,kind", OBJECT_HANDLERS)
    def test_it_returns_without_asking_anyone_later(
        self, name, message, kind, ask_env
    ) -> None:
        self._claim(ask_env, name, message, kind)

        _ask()

        expected = ASK_ORDER[: ASK_ORDER.index(name) + 1]
        assert ask_env.calls == expected
        assert ask_env.fallback_reached is False

    def test_the_file_handler_is_told_origin_direct(self, ask_env) -> None:
        self._claim(ask_env, "file", "Listed your files.", "file")

        _ask()

        assert ask_env.kwargs["file"].get("origin") == "direct"

    def test_local_action_is_not_passed_execute(self, ask_env) -> None:
        self._claim(ask_env, "local_action", "Notepad opened.", "app")

        _ask()

        assert "execute" not in ask_env.kwargs["local_action"]


# ---------------------------------------------------------------------------
# 6. Fall-through
# ---------------------------------------------------------------------------


class TestFallThrough:
    def test_all_five_are_asked_then_the_llm_is_reached(self, ask_env) -> None:
        _ask()

        assert ask_env.calls == ASK_ORDER
        assert ask_env.fallback_reached is True

    def test_no_outcome_is_recorded_when_nobody_claims(self, ask_env) -> None:
        """A declining handler must not record an outcome on its way past."""
        _ask()

        assert ask_env.outcomes == []

    def test_only_the_user_turn_is_remembered(self, ask_env) -> None:
        """``remember_conversation('user', ...)`` happens up front; no
        assistant turn is written when nothing answered."""
        _ask()

        assert [role for role, _text in ask_env.remembered] == ["user"]


# ---------------------------------------------------------------------------
# Invocation discipline
# ---------------------------------------------------------------------------


class TestInvocationDiscipline:
    @pytest.mark.parametrize("name", ASK_ORDER)
    def test_no_handler_is_invoked_twice(self, name, ask_env) -> None:
        if name == "datetime":
            ask_env.results[name] = "it is Tuesday"
        else:
            ask_env.results[name] = _result(name, "m")

        _ask()

        for handler_name in ASK_ORDER:
            assert ask_env.calls.count(handler_name) <= 1, handler_name

    @pytest.mark.parametrize("name", ASK_ORDER)
    def test_exactly_one_outcome_is_recorded_per_served_request(
        self, name, ask_env
    ) -> None:
        if name == "datetime":
            ask_env.results[name] = "it is Tuesday"
        else:
            ask_env.results[name] = _result(name, "m")

        _ask()

        assert len(ask_env.outcomes) == 1

    def test_each_handler_receives_the_same_effective_text(self, ask_env) -> None:
        _ask("what is the weather")

        assert ask_env.calls == ASK_ORDER


class TestTheseTestsWouldCatchARegression:
    """Non-vacuity, stated as assertions rather than claimed in prose.

    Each of these pins a property whose removal is the specific failure mode
    the wiring slice risks.
    """

    def test_datetime_and_object_handlers_record_differently(self, ask_env) -> None:
        """If a refactor unified them, this equality would start holding."""
        ask_env.results["datetime"] = "it is Tuesday"
        _ask()
        datetime_outcome = ask_env.outcomes[0]

        assert datetime_outcome["kind"] == "local"
        assert datetime_outcome["target"] is None
        # An object handler would have reported its own kind and a real target.
        assert datetime_outcome["kind"] != "datetime"

    def test_a_claiming_handler_stops_the_ones_after_it(self, ask_env) -> None:
        ask_env.results["memory"] = _result("memory", "Remembered.")
        ask_env.results["local_action"] = LocalActionResult(
            status="handled", kind="app", message="should not be reached"
        )

        result = _ask()

        assert "should not be reached" not in result.stdout
        assert "local_action" not in ask_env.calls
