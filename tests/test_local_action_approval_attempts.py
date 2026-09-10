"""The failed-attempt counter, and the store primitives 4.13D's endpoint needs.

An eight-hex-character code is a 2^32 space. Inside a 120-second TTL that is
already a poor target, but "poor" is not a security argument, so the store
counts failed attempts per pending action and refuses a sixth.

The counter is deliberately **persistent**, not in-memory: a cap that resets
when the process restarts is not a cap. It lives in the same table as the code
it protects, added by the same additive-migration pattern 4.13B established.

Three properties carry the weight:

* **Only real guesses count.** An attempt against a missing, expired, decided or
  legacy row must not consume the budget of anything -- otherwise an attacker
  can exhaust a victim's budget, or a typo against an expired action can lock a
  later one.
* **Success does not reset it.** Nothing in the approval path clears the
  counter; a row that reached the cap stays refused even if the correct code
  arrives afterwards.
* **The counter never reaches HTTP.** Same rule as the code itself.

``mark`` also becomes atomic here. It was read-then-write, so two concurrent
approvals could both observe ``pending``. The fix is the conditional
``UPDATE ... WHERE status = 'pending'`` plus a ``rowcount`` check that
``pc_control._mark_pending_decision`` already uses -- the repository's existing
mechanism, not a new lock.
"""

from __future__ import annotations

import sqlite3
import threading

import pytest

from grandpa.local_action_approvals import (
    MAX_APPROVAL_ATTEMPTS,
    LocalActionApprovalStore,
)

LEGACY_SCHEMA = """
CREATE TABLE IF NOT EXISTS pending_actions (
    id TEXT PRIMARY KEY,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    source_text TEXT NOT NULL,
    kind TEXT NOT NULL,
    target TEXT NOT NULL,
    message TEXT NOT NULL,
    tts_text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
)
"""


def _write_legacy_db(db_path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(LEGACY_SCHEMA)
        conn.execute(
            "INSERT INTO pending_actions(id, created_at, expires_at, source_text,"
            " kind, target, message, tts_text, status)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "legacyaction0001",
                1_700_000_000.0,
                4_000_000_000.0,
                "close notepad",
                "window",
                "close|notepad",
                "Confirmation required.",
                "Please confirm.",
                "pending",
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _columns(db_path) -> set[str]:
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        return {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(pending_actions)")
        }
    finally:
        conn.close()


def _pending(store, **overrides):
    payload = {
        "source_text": "close notepad",
        "kind": "window",
        "target": "close|notepad",
        "message": "Confirmation required.",
        "tts_text": "Please confirm.",
    }
    payload.update(overrides)
    return store.create_pending(**payload)


@pytest.fixture
def store(tmp_path):
    return LocalActionApprovalStore(tmp_path / "approvals.db")


# ---------------------------------------------------------------------------
# 1-4 -- schema, migration, initial value
# ---------------------------------------------------------------------------


class TestSchemaAndMigration:
    def test_fresh_schema_has_the_counter(self, store, tmp_path) -> None:
        assert "failed_attempts" in _columns(tmp_path / "approvals.db")

    def test_a_legacy_database_gains_the_counter_at_zero(self, tmp_path) -> None:
        db = tmp_path / "legacy.db"
        _write_legacy_db(db)
        assert "failed_attempts" not in _columns(db), "fixture is not pre-migration"

        store = LocalActionApprovalStore(db)

        assert "failed_attempts" in _columns(db)
        assert store.failed_attempts("legacyaction0001") == 0

    def test_migration_is_idempotent(self, tmp_path) -> None:
        db = tmp_path / "legacy.db"
        _write_legacy_db(db)

        for _ in range(3):
            LocalActionApprovalStore(db)

        assert "failed_attempts" in _columns(db)
        assert LocalActionApprovalStore(db).failed_attempts("legacyaction0001") == 0

    def test_a_new_row_starts_at_zero(self, store) -> None:
        pending = _pending(store)

        assert store.failed_attempts(pending["id"]) == 0

    def test_a_missing_action_has_no_count(self, store) -> None:
        assert store.failed_attempts("nosuchaction") is None


# ---------------------------------------------------------------------------
# 5-7, 11 -- what increments, and what does not
# ---------------------------------------------------------------------------


class TestWhatCounts:
    def test_a_wrong_token_increments(self, store) -> None:
        pending = _pending(store)

        assert store.authorize_approval(pending["id"], "00000000") is False

        assert store.failed_attempts(pending["id"]) == 1

    def test_a_missing_token_increments(self, store) -> None:
        pending = _pending(store)

        assert store.authorize_approval(pending["id"], "") is False

        assert store.failed_attempts(pending["id"]) == 1

    def test_the_correct_token_does_not_increment(self, store) -> None:
        pending = _pending(store)
        token = store.approval_token(pending["id"])

        assert store.authorize_approval(pending["id"], token) is True

        assert store.failed_attempts(pending["id"]) == 0

    def test_attempts_are_scoped_to_the_exact_action(self, store) -> None:
        """11: guessing at A must not consume B's budget."""
        first = _pending(store, source_text="first")
        second = _pending(store, source_text="second")

        for _ in range(3):
            store.authorize_approval(first["id"], "00000000")

        assert store.failed_attempts(first["id"]) == 3
        assert store.failed_attempts(second["id"]) == 0

    def test_an_unknown_action_consumes_nothing(self, store) -> None:
        pending = _pending(store)

        assert store.authorize_approval("nosuchaction", "00000000") is False

        assert store.failed_attempts(pending["id"]) == 0

    def test_an_expired_action_does_not_count(self, store) -> None:
        """A lapsed row is refused on status, before any credential is weighed."""
        pending = _pending(store)
        store.expire_old(now=9_999_999_999.0)

        assert store.authorize_approval(pending["id"], "00000000") is False

        assert store.failed_attempts(pending["id"]) == 0

    def test_a_decided_action_does_not_count(self, store) -> None:
        pending = _pending(store)
        token = store.approval_token(pending["id"])
        store.mark(pending["id"], "approved")

        assert store.authorize_approval(pending["id"], token) is False

        assert store.failed_attempts(pending["id"]) == 0

    def test_a_legacy_row_does_not_count(self, tmp_path) -> None:
        """15: unbound rows are refused outright, not guessed at."""
        db = tmp_path / "legacy.db"
        _write_legacy_db(db)
        store = LocalActionApprovalStore(db)

        assert store.authorize_approval("legacyaction0001", "") is False
        assert store.authorize_approval("legacyaction0001", "00000000") is False

        assert store.failed_attempts("legacyaction0001") == 0


# ---------------------------------------------------------------------------
# 8-10, 12 -- the cap
# ---------------------------------------------------------------------------


class TestTheCap:
    def test_the_cap_is_five(self) -> None:
        assert MAX_APPROVAL_ATTEMPTS == 5

    def test_five_failures_reach_the_cap(self, store) -> None:
        pending = _pending(store)

        for _ in range(MAX_APPROVAL_ATTEMPTS):
            assert store.authorize_approval(pending["id"], "00000000") is False

        assert store.failed_attempts(pending["id"]) == MAX_APPROVAL_ATTEMPTS
        assert store.attempts_exhausted(pending["id"]) is True

    def test_below_the_cap_is_not_exhausted(self, store) -> None:
        pending = _pending(store)

        for _ in range(MAX_APPROVAL_ATTEMPTS - 1):
            store.authorize_approval(pending["id"], "00000000")

        assert store.attempts_exhausted(pending["id"]) is False

    def test_the_sixth_attempt_is_refused(self, store) -> None:
        pending = _pending(store)
        for _ in range(MAX_APPROVAL_ATTEMPTS):
            store.authorize_approval(pending["id"], "00000000")

        assert store.authorize_approval(pending["id"], "11111111") is False

    def test_the_correct_token_after_lockout_is_still_refused(self, store) -> None:
        """10: the cap is not a speed bump."""
        pending = _pending(store)
        token = store.approval_token(pending["id"])
        for _ in range(MAX_APPROVAL_ATTEMPTS):
            store.authorize_approval(pending["id"], "00000000")

        assert store.authorize_approval(pending["id"], token) is False

    def test_the_counter_does_not_run_past_the_cap(self, store) -> None:
        """Refused attempts stop consuming; the row is already locked."""
        pending = _pending(store)
        for _ in range(MAX_APPROVAL_ATTEMPTS + 5):
            store.authorize_approval(pending["id"], "00000000")

        assert store.failed_attempts(pending["id"]) == MAX_APPROVAL_ATTEMPTS

    def test_attempts_survive_a_reopen(self, store, tmp_path) -> None:
        """12: an in-memory cap would reset here. A persistent one does not."""
        pending = _pending(store)
        for _ in range(3):
            store.authorize_approval(pending["id"], "00000000")

        reopened = LocalActionApprovalStore(tmp_path / "approvals.db")

        assert reopened.failed_attempts(pending["id"]) == 3
        for _ in range(2):
            reopened.authorize_approval(pending["id"], "00000000")
        assert reopened.attempts_exhausted(pending["id"]) is True

    def test_verification_never_resets_the_counter(self, store) -> None:
        pending = _pending(store)
        token = store.approval_token(pending["id"])
        store.authorize_approval(pending["id"], "00000000")

        store.authorize_approval(pending["id"], token)

        assert store.failed_attempts(pending["id"]) == 1


# ---------------------------------------------------------------------------
# 14 + concurrency -- atomic transitions
# ---------------------------------------------------------------------------


class TestApprovalIsAtomic:
    def test_mark_transitions_once(self, store) -> None:
        pending = _pending(store)

        first = store.mark(pending["id"], "approved")
        second = store.mark(pending["id"], "denied")

        assert first["status"] == "approved"
        assert second["status"] == "approved"
        assert store.get_pending(pending["id"])["status"] == "approved"

    def test_claim_pending_succeeds_once(self, store) -> None:
        pending = _pending(store)

        assert store.claim_pending(pending["id"], "approved") is True
        assert store.claim_pending(pending["id"], "approved") is False

    def test_concurrent_claims_produce_one_winner(self, store) -> None:
        """The conditional UPDATE, exercised by real threads."""
        pending = _pending(store)
        results: list[bool] = []
        barrier = threading.Barrier(8)

        def attempt() -> None:
            barrier.wait()
            results.append(store.claim_pending(pending["id"], "approved"))

        threads = [threading.Thread(target=attempt) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert results.count(True) == 1, results
        assert store.get_pending(pending["id"])["status"] == "approved"

    def test_concurrent_failed_attempts_do_not_exceed_the_cap(self, store) -> None:
        """The counter must not race past its own ceiling."""
        pending = _pending(store)
        barrier = threading.Barrier(12)

        def guess() -> None:
            barrier.wait()
            store.authorize_approval(pending["id"], "00000000")

        threads = [threading.Thread(target=guess) for _ in range(12)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert store.failed_attempts(pending["id"]) <= MAX_APPROVAL_ATTEMPTS
        assert store.attempts_exhausted(pending["id"]) is True

    def test_a_claimed_row_cannot_be_reclaimed_after_reopen(
        self, store, tmp_path
    ) -> None:
        pending = _pending(store)
        store.claim_pending(pending["id"], "approved")

        reopened = LocalActionApprovalStore(tmp_path / "approvals.db")

        assert reopened.claim_pending(pending["id"], "approved") is False


# ---------------------------------------------------------------------------
# 13 -- the counter is not HTTP-facing
# ---------------------------------------------------------------------------


class TestTheCounterIsNotExposed:
    @pytest.mark.parametrize(
        "projection", ("list_pending", "latest_pending", "get_pending")
    )
    def test_no_projection_carries_it(self, projection: str, store) -> None:
        pending = _pending(store)
        store.authorize_approval(pending["id"], "00000000")

        if projection == "list_pending":
            rows = store.list_pending()
        elif projection == "latest_pending":
            rows = [store.latest_pending()]
        else:
            rows = [store.get_pending(pending["id"])]

        for row in rows:
            assert row is not None
            assert "failed_attempts" not in row, projection

    def test_pending_metadata_keeps_its_six_keys(self, store) -> None:
        from grandpa.local_actions import _pending_metadata

        pending = _pending(store)

        assert set(_pending_metadata(pending)) == {
            "id",
            "status",
            "kind",
            "target",
            "source_text",
            "expires_at",
        }

    def test_the_created_row_does_not_carry_it(self, store) -> None:
        pending = _pending(store)

        assert "failed_attempts" not in pending
        assert "approval_token" not in pending


# ---------------------------------------------------------------------------
# 16 -- failures must not leak the credential
# ---------------------------------------------------------------------------


class TestFailuresDoNotLeakTheCredential:
    def test_a_failed_attempt_does_not_log_the_supplied_token(
        self, store, caplog
    ) -> None:
        import logging

        pending = _pending(store)

        with caplog.at_level(logging.DEBUG, logger="grandpa.local_action_approvals"):
            store.authorize_approval(pending["id"], "SUPPLIED0")

        assert "SUPPLIED0" not in caplog.text

    def test_a_failed_attempt_does_not_log_the_expected_token(
        self, store, caplog
    ) -> None:
        import logging

        pending = _pending(store)
        token = store.approval_token(pending["id"])
        caplog.clear()

        with caplog.at_level(logging.DEBUG, logger="grandpa.local_action_approvals"):
            store.authorize_approval(pending["id"], "00000000")

        assert token not in caplog.text

    def test_the_audit_log_records_neither_token(self, store) -> None:
        pending = _pending(store)
        token = store.approval_token(pending["id"])
        store.authorize_approval(pending["id"], "SUPPLIED0")

        audit = str(store.list_audit())

        assert token not in audit
        assert "SUPPLIED0" not in audit


class TestComparisonIsConstantTime:
    """H."""

    def test_authorize_uses_compare_digest(self) -> None:
        import inspect

        from grandpa import local_action_approvals

        source = inspect.getsource(
            local_action_approvals.LocalActionApprovalStore.authorize_approval
        )

        assert "verify_approval_token" in source or "compare_digest" in source

    def test_verify_still_uses_compare_digest(self) -> None:
        import inspect

        from grandpa import local_action_approvals

        assert "compare_digest" in inspect.getsource(
            local_action_approvals.LocalActionApprovalStore.verify_approval_token
        )
