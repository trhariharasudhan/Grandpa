"""The real file and scheduler handlers, as ``ask`` actually calls them.

The two chain characterizations next to this file stub these handlers out --
deliberately, since they pin ordering. That left the last gap in ``ask``'s
coverage: what the real handlers do when asked. This file closes it, with the
real ``handle_file_command`` and ``handle_scheduler_command`` running and only
their stores and actuator boundary replaced.

The finding that matters for the dispatcher work is recorded here rather than
argued: **both handlers act while deciding whether they claim.** Not as a
side effect afterwards -- as the same step.

``handle_file_command`` runs ``build_file_automation(...).handle(text)``
*before* it looks at any of its own patterns, so a mutating file command
reaches the actuator boundary during what a dispatcher would call ``claims()``.
``handle_scheduler_command`` matches first and mutates inside the matched
branch, so ``create a morning routine`` upserts a routine as it claims. Both
also initialise a SQLite database in their store constructor, before any
claim decision, for any non-empty text.

**Isolation.** Stores are injected through the ``db_path`` and ``store=``
parameters the handlers already expose. The file actuator is replaced with a
recording ``mutation_runner`` supplied through ``build_file_automation``, which
is the seam ``composition`` exists to provide -- so mutations are observed, not
performed. Activity recording is stubbed. No user filesystem, no real
scheduler persistence, no subprocess, browser or network.
"""

from __future__ import annotations

import pytest

from grandpa.pc_control import LocalActionResponse

# --- file -------------------------------------------------------------------

FILE_READ_ONLY = ["show recent files", "find pdf files", "file diagnostics"]
FILE_MUTATING = [
    ("create folder notes", "file_create"),
    ("rename report.pdf to final.pdf", "file_rename"),
    ("copy report.pdf to notes", "file_copy"),
    ("move report.pdf to notes", "file_move"),
]
NOT_A_FILE_COMMAND = ["what is the weather", "hello there", "tell me a joke"]

# --- scheduler --------------------------------------------------------------

SCHEDULER_READ_ONLY = ["what routines do i have", "list routines", "show routines"]
SCHEDULER_MUTATING = ["create a morning routine", "create morning routine"]
NOT_A_SCHEDULER_COMMAND = ["what is the weather", "open notepad", "find pdf files"]


def _ok_response() -> LocalActionResponse:
    """What the real boundary returns on success, so status stays realistic."""
    return LocalActionResponse(
        ok=True,
        action_id=None,
        status="completed",
        message="done",
        approval_required=False,
        risk_level="LOW",
    )


@pytest.fixture
def file_env(tmp_path, monkeypatch):
    """Real ``handle_file_command`` with an injected store and actuator."""
    import grandpa.composition as composition
    from grandpa.file_assistant import FileAssistantStore

    root = tmp_path / "root"
    root.mkdir()
    (root / "report.pdf").write_text("x", encoding="utf-8")

    boundary: list[dict] = []
    real_build = composition.build_file_automation

    def runner(payload):
        boundary.append(dict(payload))
        return _ok_response()

    def build_spy(**kwargs):
        # Force the roots and the runner; everything else is the real thing,
        # so the parser and the claim decision are production code.
        kwargs["roots"] = (root,)
        kwargs["mutation_runner"] = runner
        return real_build(**kwargs)

    monkeypatch.setattr(composition, "build_file_automation", build_spy)

    return type(
        "FileEnv",
        (),
        {
            "root": root,
            "boundary": boundary,
            "store": FileAssistantStore(db_path=tmp_path / "files.db"),
        },
    )()


@pytest.fixture
def scheduler_env(tmp_path, monkeypatch):
    """Real ``handle_scheduler_command`` with an injected store."""
    import grandpa.task_scheduler as task_scheduler
    from grandpa.task_scheduler import SchedulerStore

    activity: list[tuple] = []
    monkeypatch.setattr(
        task_scheduler,
        "_record_scheduler_activity",
        lambda *a: activity.append(a),
    )

    return type(
        "SchedEnv",
        (),
        {
            "store": SchedulerStore(db_path=tmp_path / "sched.db"),
            "activity": activity,
        },
    )()


# ---------------------------------------------------------------------------
# File: what claims, and what that costs
# ---------------------------------------------------------------------------


class TestFileClaiming:
    @pytest.mark.parametrize("text", FILE_READ_ONLY)
    def test_read_only_commands_claim(self, text: str, file_env) -> None:
        from grandpa.file_assistant import handle_file_command

        result = handle_file_command(text, store=file_env.store, origin="direct")

        assert result.should_fallback is False
        assert result.kind == "file"
        assert result.status == "handled"

    @pytest.mark.parametrize("text", FILE_READ_ONLY)
    def test_read_only_commands_do_not_reach_the_actuator(
        self, text: str, file_env
    ) -> None:
        from grandpa.file_assistant import handle_file_command

        handle_file_command(text, store=file_env.store, origin="direct")

        assert file_env.boundary == []

    @pytest.mark.parametrize("text", NOT_A_FILE_COMMAND)
    def test_unrelated_text_falls_through(self, text: str, file_env) -> None:
        from grandpa.file_assistant import handle_file_command

        result = handle_file_command(text, store=file_env.store, origin="direct")

        assert result.should_fallback is True
        assert result.status == "no_match"
        assert file_env.boundary == []

    def test_the_result_carries_the_fields_ask_consumes(self, file_env) -> None:
        from grandpa.file_assistant import handle_file_command

        result = handle_file_command(
            "show recent files", store=file_env.store, origin="direct"
        )

        for field in ("status", "kind", "target", "message", "should_fallback"):
            assert hasattr(result, field), field
        assert result.message


class TestFileClaimingReachesTheActuator:
    """The characterization the dispatcher work needs.

    ``handle_file_command`` runs the automation before consulting any of its own
    patterns, so deciding whether it claims is the same act as performing the
    mutation. A ``claims()`` wrapper around this function would actuate.
    """

    @pytest.mark.parametrize("text,action_type", FILE_MUTATING)
    def test_a_mutating_command_dispatches_to_the_boundary(
        self, text: str, action_type: str, file_env
    ) -> None:
        from grandpa.file_assistant import handle_file_command

        result = handle_file_command(text, store=file_env.store, origin="direct")

        assert result.should_fallback is False
        assert len(file_env.boundary) == 1
        assert file_env.boundary[0]["action_type"] == action_type

    @pytest.mark.parametrize("text,_action", FILE_MUTATING)
    def test_the_boundary_call_carries_the_callers_origin(
        self, text: str, _action: str, file_env
    ) -> None:
        """``origin="direct"`` is what ``ask`` passes; it must survive the trip."""
        from grandpa.file_assistant import handle_file_command

        handle_file_command(text, store=file_env.store, origin="direct")

        assert file_env.boundary[0]["origin"] == "direct"

    def test_a_delete_stages_confirmation_before_reaching_the_actuator(
        self, file_env
    ) -> None:
        """The approval gate holds: nothing is dispatched until confirmed."""
        from grandpa.file_assistant import handle_file_command

        result = handle_file_command(
            "delete report.pdf", store=file_env.store, origin="direct"
        )

        assert result.status == "needs_confirmation"
        assert result.permission == "requires_confirmation"
        assert file_env.boundary == []
        assert (file_env.root / "report.pdf").exists()

    def test_nothing_on_the_real_filesystem_moved(self, file_env) -> None:
        """The runner records; it does not act. Guards the fixture itself."""
        from grandpa.file_assistant import handle_file_command

        handle_file_command(
            "move report.pdf to notes", store=file_env.store, origin="direct"
        )

        assert (file_env.root / "report.pdf").exists()
        assert not (file_env.root / "notes").exists()


class TestFileStoreIsEager:
    def test_constructing_the_store_creates_its_database(self, tmp_path) -> None:
        """A cost paid before any claim decision, for any non-empty text."""
        from grandpa.file_assistant import FileAssistantStore

        db = tmp_path / "nested" / "files.db"
        assert not db.exists()

        FileAssistantStore(db_path=db)

        assert db.exists()


# ---------------------------------------------------------------------------
# Scheduler: claiming and persisting are the same step
# ---------------------------------------------------------------------------


class TestSchedulerClaiming:
    @pytest.mark.parametrize("text", SCHEDULER_READ_ONLY)
    def test_read_only_commands_claim_without_persisting(
        self, text: str, scheduler_env
    ) -> None:
        from grandpa.task_scheduler import handle_scheduler_command

        before = len(scheduler_env.store.list_routines())
        result = handle_scheduler_command(text, store=scheduler_env.store)

        assert result.should_fallback is False
        assert result.kind == "scheduler"
        assert len(scheduler_env.store.list_routines()) == before

    @pytest.mark.parametrize("text", NOT_A_SCHEDULER_COMMAND)
    def test_unrelated_text_falls_through(self, text: str, scheduler_env) -> None:
        from grandpa.task_scheduler import handle_scheduler_command

        result = handle_scheduler_command(text, store=scheduler_env.store)

        assert result.should_fallback is True
        assert result.status == "no_match"
        assert scheduler_env.store.list_routines() == []

    def test_the_result_carries_the_fields_ask_consumes(self, scheduler_env) -> None:
        from grandpa.task_scheduler import handle_scheduler_command

        result = handle_scheduler_command(
            "what routines do i have", store=scheduler_env.store
        )

        for field in ("status", "kind", "target", "message", "should_fallback"):
            assert hasattr(result, field), field
        assert result.message


class TestSchedulerPersistsWhileClaiming:
    """``create a morning routine`` upserts as it claims, not afterwards."""

    @pytest.mark.parametrize("text", SCHEDULER_MUTATING)
    def test_claiming_upserts_a_routine(self, text: str, scheduler_env) -> None:
        from grandpa.task_scheduler import handle_scheduler_command

        assert scheduler_env.store.list_routines() == []

        result = handle_scheduler_command(text, store=scheduler_env.store)

        assert result.should_fallback is False
        assert len(scheduler_env.store.list_routines()) == 1

    def test_claiming_also_records_activity(self, scheduler_env) -> None:
        from grandpa.task_scheduler import handle_scheduler_command

        handle_scheduler_command("create a morning routine", store=scheduler_env.store)

        assert scheduler_env.activity, "no activity recorded"
        assert scheduler_env.activity[0][0] == "routine"

    def test_a_regex_routine_command_also_persists(self, scheduler_env) -> None:
        from grandpa.task_scheduler import handle_scheduler_command

        result = handle_scheduler_command(
            "every morning open chrome", store=scheduler_env.store
        )

        assert result.should_fallback is False
        assert len(scheduler_env.store.list_routines()) == 1

    def test_execute_defaults_to_true(self) -> None:
        """Recorded because it is part of what ``ask`` inherits by not passing it."""
        import inspect

        from grandpa.task_scheduler import handle_scheduler_command

        params = inspect.signature(handle_scheduler_command).parameters
        assert params["execute"].default is True


class TestSchedulerStoreIsEager:
    def test_constructing_the_store_creates_its_database(self, tmp_path) -> None:
        from grandpa.task_scheduler import SchedulerStore

        db = tmp_path / "nested" / "sched.db"
        assert not db.exists()

        SchedulerStore(db_path=db)

        assert db.exists()


# ---------------------------------------------------------------------------
# Tripwires -- the predicates themselves
# ---------------------------------------------------------------------------


class TestClaimPredicateTripwires:
    """Near-misses that must not claim.

    These are exact-match and full-regex predicates. A loosening to substring
    or prefix matching would change which handler serves a request, and these
    are what turn that into a failure rather than a drift.
    """

    @pytest.mark.parametrize(
        "text",
        [
            "show recent file",
            "show recent files please",
            "please show recent files",
        ],
    )
    def test_file_near_misses_do_not_claim(self, text: str, file_env) -> None:
        from grandpa.file_assistant import handle_file_command

        result = handle_file_command(text, store=file_env.store, origin="direct")

        assert result.should_fallback is True, text

    @pytest.mark.parametrize(
        "text",
        [
            "list routine",
            "what routines do i have please",
            "create a morning routines",
        ],
    )
    def test_scheduler_near_misses_do_not_claim(self, text: str, scheduler_env) -> None:
        from grandpa.task_scheduler import handle_scheduler_command

        result = handle_scheduler_command(text, store=scheduler_env.store)

        assert result.should_fallback is True, text
        assert scheduler_env.store.list_routines() == []

    def test_the_corpora_are_populated(self) -> None:
        """Guards every parametrized test above from a vacuous empty list."""
        assert len(FILE_READ_ONLY) == 3
        assert len(FILE_MUTATING) == 4
        assert len(SCHEDULER_READ_ONLY) == 3
        assert len(SCHEDULER_MUTATING) == 2


# ---------------------------------------------------------------------------
# The chain, with these two handlers real
# ---------------------------------------------------------------------------


class TestChainOrderHoldsWithRealHandlers:
    """The post-fix order, verified without stubbing file or scheduler.

    ``tests/cli/test_ask_chain_order.py`` pins the order with all five handlers
    stubbed. This checks the same order survives when the two this file covers
    are the production functions, reached through ``ask`` itself.
    """

    def test_file_claims_before_scheduler_is_consulted(
        self, tmp_path, monkeypatch
    ) -> None:
        from click.testing import CliRunner

        import grandpa.cli.ask as ask_mod
        import grandpa.composition as composition
        import grandpa.core_ai_brain as brain
        import grandpa.file_assistant as file_assistant
        import grandpa.local_actions as local_actions
        import grandpa.memory_context as memory_context
        import grandpa.task_scheduler as task_scheduler
        from grandpa.cli import cli
        from grandpa.file_assistant import FileAssistantStore
        from grandpa.local_actions import LocalActionResult
        from grandpa.task_scheduler import SchedulerStore

        root = tmp_path / "root"
        root.mkdir()
        scheduler_calls: list[str] = []

        real_build = composition.build_file_automation

        def build_spy(**kwargs):
            kwargs["roots"] = (root,)
            kwargs["mutation_runner"] = lambda payload: _ok_response()
            return real_build(**kwargs)

        real_scheduler = task_scheduler.handle_scheduler_command

        def scheduler_spy(text, *a, **k):
            scheduler_calls.append(text)
            return real_scheduler(text, *a, **k)

        monkeypatch.setattr(composition, "build_file_automation", build_spy)
        monkeypatch.setattr(
            file_assistant,
            "FileAssistantStore",
            lambda *a, **k: FileAssistantStore(db_path=tmp_path / "f.db"),
        )
        monkeypatch.setattr(
            task_scheduler,
            "SchedulerStore",
            lambda *a, **k: SchedulerStore(db_path=tmp_path / "s.db"),
        )
        monkeypatch.setattr(task_scheduler, "handle_scheduler_command", scheduler_spy)
        monkeypatch.setattr(
            local_actions,
            "handle_local_action",
            lambda text, *a, **k: LocalActionResult(status="no_match"),
        )
        monkeypatch.setattr(
            memory_context, "remember_conversation", lambda *a, **k: None
        )
        monkeypatch.setattr(brain, "record_assistant_outcome", lambda *a, **k: None)
        monkeypatch.setattr(
            brain,
            "process_user_message",
            lambda text, **k: type("A", (), {"effective_text": text})(),
        )
        monkeypatch.setattr(ask_mod, "load_config", lambda *a, **k: pytest.fail("LLM"))

        result = CliRunner().invoke(
            cli, ["ask", "show recent files"], catch_exceptions=True
        )

        assert result.exit_code == 0
        assert scheduler_calls == [], "scheduler ran even though file claimed"


class TestFileClaimsMoreThanItsOwnPatterns:
    """The file handler claims text that is not obviously a file command.

    Because ``build_file_automation(...).handle(text)`` runs before the exact
    patterns, the file parser gets first refusal on everything. Two examples
    found while writing this file:

    ``open notepad`` is claimed -- the parser reads it as opening a file named
    "notepad" and returns ``status="error"``. In ``ask`` this is invisible,
    because ``handle_local_action`` sits ahead of the file handler and serves
    app launches first. That masking is purely positional.

    ``find pdf`` is claimed by the search path even though only ``find pdf
    files`` appears in the handler's own exact-match list.

    Recorded, not judged. The reason it belongs here: a dispatcher that
    reordered these two handlers, or asked the file handler to "claim" before
    local_action, would change which one answers ``open notepad`` -- and the
    only thing preventing that today is position.
    """

    def test_open_notepad_is_claimed_by_the_file_handler(self, file_env) -> None:
        from grandpa.file_assistant import handle_file_command

        result = handle_file_command(
            "open notepad", store=file_env.store, origin="direct"
        )

        assert result.should_fallback is False
        assert result.status == "error"

    def test_local_action_is_what_actually_serves_it_in_ask(self) -> None:
        """The masking is positional: local_action is consulted first."""
        from tests.cli.test_ask_chain_order import INVOCATION_ORDER

        assert INVOCATION_ORDER.index("local_action") < INVOCATION_ORDER.index("file")

    def test_find_pdf_is_claimed_by_search_not_the_exact_list(self, file_env) -> None:
        from grandpa.file_assistant import handle_file_command

        assert (
            handle_file_command(
                "find pdf", store=file_env.store, origin="direct"
            ).should_fallback
            is False
        )
        assert file_env.boundary == []
