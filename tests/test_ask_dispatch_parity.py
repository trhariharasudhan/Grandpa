"""The live ``ask`` chain and the dispatcher composition, compared directly.

Before ``ask.py`` is wired to ``build_ask_dispatcher()``, this proves the swap
would change nothing: for every input in the corpus, both routes select the same
handler and produce the same observable result.

**Both sides run the real five handlers.** Nothing is reimplemented. The live
side is a test helper that mirrors ``ask.py``'s order and its exact claim
predicates -- ``if dt_resp:`` for datetime and ``not result.should_fallback``
for the other four -- and calls the same public functions with the same
arguments. The dispatcher side calls ``build_ask_dispatcher().dispatch(...)``.

**Independence.** The two routes run against separate freshly-built stores, so
a stateful handler cannot let the first run influence the second. Object
identity is therefore not asserted between routes; the observable value is.

Safety, and how each side effect is stopped:

``local_action``
    ``local_actions._execute`` -- the actuator leaf -- is replaced by a recorder
    that returns the routing verdict unchanged. Every gate above it still runs,
    including the dangerous-pattern filter and the approval staging, so the
    claim decision is production's. Nothing launches. The approval database is
    redirected with ``GRANDPA_PC_CONTROL_DB``, the seam the product provides.
``memory``
    ``MemoryStore`` replaced by a recording double at the constructor
    ``handle_memory_command`` uses when no ``store=`` is passed.
``file``
    Store redirected to a temporary database, and ``build_file_automation``
    given temporary roots plus a recording ``mutation_runner`` -- the seam
    ``composition`` exists to provide.
``scheduler``
    Store redirected to a temporary database; activity recording stubbed.
``LLM``
    Never reached. "Nobody claimed" is represented by a sentinel on both sides.

No production file is modified, and no handler is given a seam it did not
already have.
"""

from __future__ import annotations

import re

import pytest

from grandpa.dispatch import NOT_HANDLED, RequestContext
from grandpa.pc_control import LocalActionResponse

ASK_ORDER = ["datetime", "memory", "local_action", "file", "scheduler"]

#: Represents the LLM fallback: the chain ran out of handlers.
FELL_THROUGH = "__fell_through__"


# ---------------------------------------------------------------------------
# Corpus
# ---------------------------------------------------------------------------

DATETIME_ONLY = [
    "what day is it today",
    "what is the date today",
    "what time is it now",
]
MEMORY_ONLY = [
    "remember my project is grandpa",
    "forget my project",
    "what do you remember about me",
]
LOCAL_ACTION_ONLY = [
    "open notepad",
    "open calculator",
    "what is my battery level",
]
FILE_ONLY = [
    "show recent files",
    "find pdf files",
    "file diagnostics",
    "create folder notes",
    "rename report.pdf to final.pdf",
    "copy report.pdf to notes",
    "move report.pdf to notes",
]
SCHEDULER_ONLY = [
    "create a morning routine",
    "every morning open chrome",
    "list routines",
    "what routines do i have",
]
#: Inputs more than one handler recognises. The first four are the ratified
#: GAP-22 overlap; ``open notepad`` is the local_action/file overlap found in
#: 4.5B-C.
CONTESTED = [
    "remember what day it is today",
    "forget what day it is today",
    "remember the current time",
    "forget the current date",
    "open notepad",
]
UNHANDLED = [
    "tell me a joke",
    "what is the weather",
    "who wrote hamlet",
    "hello there",
]
#: Safety-sensitive. ``delete report.pdf`` is included precisely because the
#: chain's answer is not the obvious one -- see ``TestSafetySensitiveInputs``.
SAFETY = [
    "delete report.pdf",
    "delete everything",
    "open terminal",
    "open task manager",
]

CORPUS = (
    DATETIME_ONLY
    + MEMORY_ONLY
    + LOCAL_ACTION_ONLY
    + FILE_ONLY
    + SCHEDULER_ONLY
    + CONTESTED
    + UNHANDLED
    + SAFETY
)


# ---------------------------------------------------------------------------
# Test-side doubles for the stores only
# ---------------------------------------------------------------------------


class RecordingMemoryStore:
    """The real ``MemoryStore`` on a throwaway database, recording mutations.

    A hand-rolled double was tried first and rejected: ``handle_memory_command``
    reaches ``db_path``, ``search_memories`` and ``list_memories`` on its recall
    paths, so a partial double changed which branch the handler took. Wrapping
    the real store keeps every branch production's while still isolating the
    file and making mutations observable.
    """

    def __init__(self, db_path) -> None:
        from grandpa.memory_context import MemoryStore as _RealMemoryStore

        self._store = _RealMemoryStore(db_path=db_path)
        self.mutations: list = []

    def __getattr__(self, item):
        return getattr(self._store, item)

    def remember(self, category, key, value):
        self.mutations.append(("remember", category, key, value))
        return self._store.remember(category, key, value)

    def forget(self, target):
        self.mutations.append(("forget", target))
        return self._store.forget(target)

    def clear_all(self):
        self.mutations.append(("clear_all",))
        return self._store.clear_all()


def _ok_response() -> LocalActionResponse:
    return LocalActionResponse(
        ok=True,
        action_id=None,
        status="completed",
        message="done",
        approval_required=False,
        risk_level="LOW",
    )


class Env:
    """One isolated run: fresh stores, and a record of what was invoked."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.actuator_calls: list[str] = []
        self.file_boundary: list[dict] = []
        self.memory_store: RecordingMemoryStore | None = None
        self.file_origins: list[str] = []


_GENERATED_ID = re.compile(r"(goal|action|task)_[0-9a-f]{6,}")


def _stable(value):
    """Blank out identifiers a fresh execution necessarily generates anew.

    ``_parse_agent_plan_action`` mints a goal id per call, so two independent
    runs of the same input differ in that field alone. Comparing it would
    assert non-determinism rather than parity.
    """
    if isinstance(value, str):
        return _GENERATED_ID.sub(r"<generated-id>", value)
    return value


def _observable(name: str, result) -> tuple:
    """What a caller can see, without requiring object identity.

    ``ask`` reads ``status``, ``kind``, ``target`` and ``message`` off the four
    object-returning handlers, and the bare string from datetime.
    """
    if result is NOT_HANDLED or result is FELL_THROUGH:
        return (name, FELL_THROUGH)
    if isinstance(result, str):
        return (name, type(result).__name__, result)
    return (
        name,
        type(result).__name__,
        getattr(result, "status", None),
        getattr(result, "kind", None),
        _stable(getattr(result, "target", None)),
        _stable(getattr(result, "message", None)),
    )


@pytest.fixture
def run_routes(tmp_path, monkeypatch):
    """Return a callable running both routes for one input, isolated."""
    import grandpa.composition as composition
    import grandpa.file_assistant as file_assistant
    import grandpa.local_actions as local_actions
    import grandpa.memory_context as memory_context
    import grandpa.task_scheduler as task_scheduler
    from grandpa.composition.ask_handlers import build_ask_dispatcher
    from grandpa.core import runtime_context
    from grandpa.file_assistant import FileAssistantStore
    from grandpa.task_scheduler import SchedulerStore

    monkeypatch.setenv("GRANDPA_PC_CONTROL_DB", str(tmp_path / "approvals.db"))
    root = tmp_path / "root"
    root.mkdir()
    (root / "report.pdf").write_text("x", encoding="utf-8")

    real = {
        "datetime": runtime_context.handle_datetime_intent,
        "memory": memory_context.handle_memory_command,
        "local_action": local_actions.handle_local_action,
        "file": file_assistant.handle_file_command,
        "scheduler": task_scheduler.handle_scheduler_command,
    }
    real_build = composition.build_file_automation
    state: dict = {}

    def counted(name):
        def wrapper(*args, **kwargs):
            state["env"].calls.append(name)
            if name == "file":
                state["env"].file_origins.append(kwargs.get("origin"))
            return real[name](*args, **kwargs)

        return wrapper

    def stub_execute(result):
        state["env"].actuator_calls.append(result.kind or "")
        return result

    def build_spy(**kwargs):
        kwargs["roots"] = (root,)
        kwargs["mutation_runner"] = lambda payload: (
            state["env"].file_boundary.append(dict(payload)),
            _ok_response(),
        )[1]
        return real_build(**kwargs)

    monkeypatch.setattr(runtime_context, "handle_datetime_intent", counted("datetime"))
    monkeypatch.setattr(memory_context, "handle_memory_command", counted("memory"))
    monkeypatch.setattr(local_actions, "handle_local_action", counted("local_action"))
    monkeypatch.setattr(file_assistant, "handle_file_command", counted("file"))
    monkeypatch.setattr(
        task_scheduler, "handle_scheduler_command", counted("scheduler")
    )
    monkeypatch.setattr(local_actions, "_execute", stub_execute)
    monkeypatch.setattr(composition, "build_file_automation", build_spy)
    monkeypatch.setattr(task_scheduler, "_record_scheduler_activity", lambda *a: None)

    counter = {"n": 0}

    def fresh_stores() -> Env:
        """A new Env plus new stores, so the two routes cannot interact."""
        counter["n"] += 1
        env = Env()
        env.memory_store = RecordingMemoryStore(tmp_path / f"mem-{counter['n']}.db")
        state["env"] = env
        monkeypatch.setattr(
            memory_context, "MemoryStore", lambda *a, **k: env.memory_store
        )
        monkeypatch.setattr(
            file_assistant,
            "FileAssistantStore",
            lambda *a, **k: FileAssistantStore(
                db_path=tmp_path / f"files-{counter['n']}.db"
            ),
        )
        monkeypatch.setattr(
            task_scheduler,
            "SchedulerStore",
            lambda *a, **k: SchedulerStore(
                db_path=tmp_path / f"sched-{counter['n']}.db"
            ),
        )
        return env

    def live_chain(text: str) -> tuple[str, object, Env]:
        """``ask.py``'s order and claim predicates, calling the real handlers."""
        env = fresh_stores()

        dt_resp = runtime_context.handle_datetime_intent(text)
        if dt_resp:  # ask.py:681 -- truthiness, not ``is not None``
            return "datetime", dt_resp, env

        memory_result = memory_context.handle_memory_command(text)
        if not memory_result.should_fallback:
            return "memory", memory_result, env

        local_action = local_actions.handle_local_action(text)
        if not local_action.should_fallback:
            return "local_action", local_action, env

        file_action = file_assistant.handle_file_command(text, origin="direct")
        if not file_action.should_fallback:
            return "file", file_action, env

        scheduler_action = task_scheduler.handle_scheduler_command(text)
        if not scheduler_action.should_fallback:
            return "scheduler", scheduler_action, env

        return FELL_THROUGH, FELL_THROUGH, env

    def via_dispatcher(text: str) -> tuple[str, object, Env]:
        env = fresh_stores()
        result = build_ask_dispatcher().dispatch(
            RequestContext(text=text, origin="direct")
        )
        if not result.claimed:
            return FELL_THROUGH, FELL_THROUGH, env
        return result.handler_name, result.result, env

    def _run(text: str):
        return live_chain(text), via_dispatcher(text)

    return _run


# ---------------------------------------------------------------------------
# Parity
# ---------------------------------------------------------------------------


class TestCorpusIsPopulated:
    def test_every_category_has_cases(self) -> None:
        for name, cases in [
            ("datetime", DATETIME_ONLY),
            ("memory", MEMORY_ONLY),
            ("local_action", LOCAL_ACTION_ONLY),
            ("file", FILE_ONLY),
            ("scheduler", SCHEDULER_ONLY),
            ("contested", CONTESTED),
            ("unhandled", UNHANDLED),
            ("safety", SAFETY),
        ]:
            assert cases, name

    def test_the_corpus_size_is_pinned(self) -> None:
        assert len(CORPUS) == 33


class TestParity:
    @pytest.mark.parametrize("text", CORPUS)
    def test_the_same_handler_wins(self, text: str, run_routes) -> None:
        (live_name, _lr, _le), (disp_name, _dr, _de) = run_routes(text)

        assert disp_name == live_name, text

    @pytest.mark.parametrize("text", CORPUS)
    def test_the_observable_result_matches(self, text: str, run_routes) -> None:
        (live_name, live_result, _le), (disp_name, disp_result, _de) = run_routes(text)

        assert _observable(disp_name, disp_result) == _observable(
            live_name, live_result
        )

    @pytest.mark.parametrize("text", CORPUS)
    def test_handled_or_unhandled_agrees(self, text: str, run_routes) -> None:
        (live_name, _lr, _le), (disp_name, _dr, _de) = run_routes(text)

        assert (live_name == FELL_THROUGH) == (disp_name == FELL_THROUGH), text

    @pytest.mark.parametrize("text", CORPUS)
    def test_the_result_type_matches(self, text: str, run_routes) -> None:
        (_ln, live_result, _le), (_dn, disp_result, _de) = run_routes(text)

        assert type(disp_result) is type(live_result), text


# ---------------------------------------------------------------------------
# Invocation
# ---------------------------------------------------------------------------


class TestInvocation:
    @pytest.mark.parametrize("text", CORPUS)
    def test_no_handler_is_called_twice_on_either_route(
        self, text: str, run_routes
    ) -> None:
        (_ln, _lr, live_env), (_dn, _dr, disp_env) = run_routes(text)

        for env, label in ((live_env, "live"), (disp_env, "dispatcher")):
            for name in ASK_ORDER:
                assert env.calls.count(name) <= 1, (text, label, name)

    @pytest.mark.parametrize("text", CORPUS)
    def test_both_routes_invoke_the_same_handlers_in_the_same_order(
        self, text: str, run_routes
    ) -> None:
        (_ln, _lr, live_env), (_dn, _dr, disp_env) = run_routes(text)

        assert disp_env.calls == live_env.calls, text

    @pytest.mark.parametrize("text", CORPUS)
    def test_nothing_after_the_winner_is_invoked(self, text: str, run_routes) -> None:
        (live_name, _lr, _le), (disp_name, _dr, disp_env) = run_routes(text)

        if disp_name is FELL_THROUGH or disp_name == FELL_THROUGH:
            assert disp_env.calls == ASK_ORDER, text
        else:
            expected = ASK_ORDER[: ASK_ORDER.index(disp_name) + 1]
            assert disp_env.calls == expected, text

    @pytest.mark.parametrize("text", UNHANDLED)
    def test_unclaimed_input_tries_all_five_then_falls_through(
        self, text: str, run_routes
    ) -> None:
        (live_name, _lr, live_env), (disp_name, _dr, disp_env) = run_routes(text)

        assert live_name == FELL_THROUGH
        assert disp_name == FELL_THROUGH
        assert live_env.calls == ASK_ORDER
        assert disp_env.calls == ASK_ORDER


# ---------------------------------------------------------------------------
# The ratified invariants
# ---------------------------------------------------------------------------


class TestRatifiedInvariants:
    @pytest.mark.parametrize("text", CONTESTED[:4])
    def test_datetime_wins_and_memory_never_runs(self, text: str, run_routes) -> None:
        """GAP-22: memory mutates as it matches, so it must not be asked."""
        (live_name, _lr, live_env), (disp_name, _dr, disp_env) = run_routes(text)

        assert live_name == "datetime"
        assert disp_name == "datetime"
        assert "memory" not in live_env.calls
        assert "memory" not in disp_env.calls
        assert live_env.memory_store.mutations == []
        assert disp_env.memory_store.mutations == []

    def test_open_notepad_is_served_by_local_action_not_file(self, run_routes) -> None:
        """4.5B-C: both claim it; only position decides."""
        (live_name, _lr, _le), (disp_name, _dr, disp_env) = run_routes("open notepad")

        assert live_name == "local_action"
        assert disp_name == "local_action"
        assert "file" not in disp_env.calls

    @pytest.mark.parametrize("text", ["show recent files", "create folder notes"])
    def test_the_file_handler_receives_origin_direct(
        self, text: str, run_routes
    ) -> None:
        (_ln, _lr, live_env), (_dn, _dr, disp_env) = run_routes(text)

        assert live_env.file_origins == ["direct"]
        assert disp_env.file_origins == ["direct"]

    def test_request_context_carries_only_three_fields(self) -> None:
        import dataclasses

        assert [f.name for f in dataclasses.fields(RequestContext)] == [
            "text",
            "origin",
            "dry_run",
        ]

    def test_action_origin_is_unchanged(self) -> None:
        from grandpa.pc_control import ACTION_ORIGINS

        assert ACTION_ORIGINS == (
            "voice",
            "agent",
            "direct",
            "api",
            "scheduler",
            "skill",
        )

    def test_execute_defaults_are_still_true(self) -> None:
        """Neither route passes ``execute``; both inherit the default."""
        import inspect

        from grandpa.local_actions import handle_local_action
        from grandpa.task_scheduler import handle_scheduler_command

        assert (
            inspect.signature(handle_local_action).parameters["execute"].default is True
        )
        assert (
            inspect.signature(handle_scheduler_command).parameters["execute"].default
            is True
        )


class TestSafetySensitiveInputs:
    """What the chain actually does with the dangerous corpus.

    Recorded rather than assumed. The notable one is ``delete report.pdf``:
    ``local_actions._DANGEROUS_PATTERNS`` contains ``\\bdelete\\b``, so
    ``handle_local_action`` blocks it and claims -- the file handler is never
    reached, and its ``needs_confirmation`` path is unreachable from ``ask``
    for that phrasing. The file-side confirmation behaviour is characterized in
    ``tests/cli/test_ask_file_scheduler_handlers.py``, where the handler is
    called directly.
    """

    @pytest.mark.parametrize("text", SAFETY)
    def test_both_routes_agree_on_safety_sensitive_input(
        self, text: str, run_routes
    ) -> None:
        (live_name, live_result, _le), (disp_name, disp_result, _de) = run_routes(text)

        assert disp_name == live_name, text
        assert _observable(disp_name, disp_result) == _observable(
            live_name, live_result
        )

    def test_delete_is_claimed_and_blocked_by_local_action(self, run_routes) -> None:
        (live_name, live_result, live_env), (disp_name, disp_result, disp_env) = (
            run_routes("delete report.pdf")
        )

        assert live_name == disp_name == "local_action"
        assert live_result.status == "blocked"
        assert disp_result.status == "blocked"
        assert "file" not in disp_env.calls
        assert disp_env.file_boundary == []

    @pytest.mark.parametrize("text", SAFETY)
    def test_no_actuation_escaped_the_stub(self, text: str, run_routes) -> None:
        """The filesystem fixture must be untouched by either route."""
        (_ln, _lr, live_env), (_dn, _dr, disp_env) = run_routes(text)

        assert live_env.file_boundary == []
        assert disp_env.file_boundary == []
