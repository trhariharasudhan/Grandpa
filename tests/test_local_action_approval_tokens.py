"""The approval-token storage contract for ``local_action_approvals``.

4.13A established that ``pc_control_approvals`` already carries an
``approval_token`` and refuses an empty one, while ``local_action_approvals`` --
the store behind ``POST /v1/local-actions/{id}/approve`` and
``POST /v1/voice/confirm`` -- has no credential column at all. Those two routes
approve on an ``action_id`` alone.

This slice added only the *storage* for a code.

**Amended by 4.13C**, which added generation and delivery: ``create_pending``
now mints a code for every new row and no longer accepts one from its caller, so
the tests below use the generated value instead of a literal. The property this
file exists to pin is unchanged and is what legacy rows still exercise --

    an empty ``approval_token`` means "legacy, unbound, not approvable",
    never "no code required".

That is the same reading ``pc_control`` gives an empty ``action_digest``: a row
written before the binding existed is refused, not recomputed. Getting it the
other way round would turn every pre-migration row into a free approval.

The store had no migration path before this slice -- its schema was
``CREATE TABLE IF NOT EXISTS`` only -- so the migration itself is new, and
``TestMigration`` exercises a real pre-migration database rather than trusting
that the ``ALTER`` is unnecessary.
"""

from __future__ import annotations

import sqlite3

import pytest

from grandpa.local_action_approvals import LocalActionApprovalStore

#: The schema a database created before this slice would have on disk. Written
#: out in full rather than derived, so the test still describes the old shape
#: after the production statement changes.
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

LEGACY_ROW = (
    "legacyaction0001",
    1_700_000_000.0,
    4_000_000_000.0,  # far future, so expiry does not interfere
    "close notepad",
    "window",
    "close|notepad",
    "Confirmation required.",
    "Please confirm.",
    "pending",
)


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


def _write_legacy_db(db_path) -> None:
    """Create a database in the pre-4.13B shape, with one pending row."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(LEGACY_SCHEMA)
        conn.execute(
            "INSERT INTO pending_actions(id, created_at, expires_at, source_text,"
            " kind, target, message, tts_text, status)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            LEGACY_ROW,
        )
        conn.commit()
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
# A -- the column exists on a fresh schema
# ---------------------------------------------------------------------------


class TestFreshSchema:
    def test_the_table_has_an_approval_token_column(self, store, tmp_path) -> None:
        assert "approval_token" in _columns(tmp_path / "approvals.db")

    def test_the_existing_columns_are_untouched(self, store, tmp_path) -> None:
        """G: each additive change adds columns and moves nothing.

        ``failed_attempts`` joined in 4.13D, by the same additive migration.
        """
        assert _columns(tmp_path / "approvals.db") == {
            "id",
            "created_at",
            "expires_at",
            "source_text",
            "kind",
            "target",
            "message",
            "tts_text",
            "status",
            "approval_token",
            "failed_attempts",
        }


# ---------------------------------------------------------------------------
# B/C/H -- migrating a real pre-4.13B database
# ---------------------------------------------------------------------------


class TestMigration:
    def test_a_legacy_database_gains_the_column(self, tmp_path) -> None:
        db = tmp_path / "legacy.db"
        _write_legacy_db(db)
        assert "approval_token" not in _columns(db), "fixture is not pre-migration"

        LocalActionApprovalStore(db)

        assert "approval_token" in _columns(db)

    def test_a_legacy_row_survives_the_migration(self, tmp_path) -> None:
        db = tmp_path / "legacy.db"
        _write_legacy_db(db)

        store = LocalActionApprovalStore(db)
        row = store.get_pending("legacyaction0001")

        assert row is not None
        assert row["source_text"] == "close notepad"
        assert row["kind"] == "window"
        assert row["target"] == "close|notepad"
        assert row["status"] == "pending"

    def test_a_migrated_legacy_row_has_an_empty_token(self, tmp_path) -> None:
        """C: the migration does not invent a credential for old rows."""
        db = tmp_path / "legacy.db"
        _write_legacy_db(db)

        store = LocalActionApprovalStore(db)

        assert store.approval_token("legacyaction0001") == ""

    def test_migration_is_idempotent(self, tmp_path) -> None:
        """H: opening the store repeatedly must not fail or duplicate."""
        db = tmp_path / "legacy.db"
        _write_legacy_db(db)

        for _ in range(3):
            LocalActionApprovalStore(db)

        assert "approval_token" in _columns(db)
        assert LocalActionApprovalStore(db).get_pending("legacyaction0001") is not None

    def test_opening_a_fresh_database_repeatedly_is_safe(self, tmp_path) -> None:
        db = tmp_path / "fresh.db"
        first = LocalActionApprovalStore(db)
        _pending(first)

        second = LocalActionApprovalStore(db)

        assert len(second.list_pending()) == 1


# ---------------------------------------------------------------------------
# D/E -- bound rows vs legacy rows, and what an empty token means
# ---------------------------------------------------------------------------


class TestTokenBinding:
    def test_a_new_row_is_bound(self, store) -> None:
        """Since 4.13C every new row carries a code; only legacy rows do not."""
        pending = _pending(store)

        assert store.approval_token(pending["id"])
        assert store.is_token_bound(pending["id"]) is True

    def test_bound_and_unbound_rows_are_distinguishable(self, tmp_path) -> None:
        """D: the property 4.13D keys on.

        The unbound side is now a migrated legacy row rather than a new one --
        the only way an unbound row can exist since 4.13C.
        """
        db = tmp_path / "legacy.db"
        _write_legacy_db(db)
        store = LocalActionApprovalStore(db)
        fresh = _pending(store)

        assert store.is_token_bound("legacyaction0001") is False
        assert store.is_token_bound(fresh["id"]) is True

    def test_a_missing_action_has_no_token(self, store) -> None:
        assert store.approval_token("nosuchaction") is None
        assert store.is_token_bound("nosuchaction") is False


class TestAnEmptyTokenIsNeverAValidCredential:
    """E -- the property this slice exists for."""

    def test_an_unbound_row_rejects_an_empty_token(self, store) -> None:
        pending = _pending(store)

        assert store.verify_approval_token(pending["id"], "") is False

    def test_an_unbound_row_rejects_any_token(self, store) -> None:
        """A legacy row is not approvable by guessing, either."""
        pending = _pending(store)

        assert store.verify_approval_token(pending["id"], "A1B2C3D4") is False
        assert store.verify_approval_token(pending["id"], "anything") is False

    def test_a_bound_row_rejects_an_empty_token(self, store) -> None:
        pending = _pending(store)

        assert store.verify_approval_token(pending["id"], "") is False

    def test_a_bound_row_rejects_a_wrong_token(self, store) -> None:
        pending = _pending(store)

        assert store.verify_approval_token(pending["id"], "00000000") is False

    def test_a_bound_row_accepts_its_own_token(self, store) -> None:
        pending = _pending(store)

        assert (
            store.verify_approval_token(
                pending["id"], store.approval_token(pending["id"])
            )
            is True
        )

    def test_a_missing_action_rejects_every_token(self, store) -> None:
        assert store.verify_approval_token("nosuchaction", "A1B2C3D4") is False
        assert store.verify_approval_token("nosuchaction", "") is False

    def test_a_migrated_legacy_row_cannot_be_approved_by_token(self, tmp_path) -> None:
        """The migration's whole point: old rows are unbound, not unguarded."""
        db = tmp_path / "legacy.db"
        _write_legacy_db(db)
        store = LocalActionApprovalStore(db)

        assert store.verify_approval_token("legacyaction0001", "") is False
        assert store.verify_approval_token("legacyaction0001", "A1B2C3D4") is False

    def test_the_comparison_is_constant_time(self) -> None:
        """Structural: a short code invites timing analysis."""
        import inspect

        from grandpa import local_action_approvals

        source = inspect.getsource(local_action_approvals.LocalActionApprovalStore)

        assert "compare_digest" in source
        assert "secrets" in inspect.getsource(local_action_approvals)


# ---------------------------------------------------------------------------
# F -- the token must not reach any HTTP-facing projection
# ---------------------------------------------------------------------------


class TestTheTokenIsNotExposed:
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

    def test_pending_metadata_does_not_carry_the_token(self, store) -> None:
        from grandpa.local_actions import _pending_metadata

        pending = _pending(store)
        token = store.approval_token(pending["id"])

        assert token not in str(_pending_metadata(pending))

    @pytest.mark.parametrize(
        "projection", ("list_pending", "latest_pending", "get_pending")
    )
    def test_no_row_projection_returns_the_token(self, projection: str, store) -> None:
        """The store's own readers must not hand it out either.

        ``approval_token`` is reachable only through the explicit accessor, so a
        caller has to ask for it by name.
        """
        pending = _pending(store)
        token = store.approval_token(pending["id"])

        if projection == "list_pending":
            rows = store.list_pending()
        elif projection == "latest_pending":
            rows = [store.latest_pending()]
        else:
            rows = [store.get_pending(pending["id"])]

        for row in rows:
            assert row is not None
            assert "approval_token" not in row, projection
            assert token not in str(row), projection

    def test_the_audit_log_does_not_record_the_token(self, store) -> None:
        pending = _pending(store)
        token = store.approval_token(pending["id"])

        assert token not in str(store.list_audit())
        assert pending["id"] in str(store.list_audit())


# ---------------------------------------------------------------------------
# G -- nothing else moved
# ---------------------------------------------------------------------------


class TestExistingBehaviourIsUnchanged:
    def test_create_pending_still_returns_the_row(self, store) -> None:
        pending = _pending(store)

        assert pending["status"] == "pending"
        assert pending["kind"] == "window"
        assert pending["target"] == "close|notepad"
        assert pending["id"]

    def test_status_transitions_are_unchanged(self, store) -> None:
        pending = _pending(store)

        marked = store.mark(pending["id"], "approved")

        assert marked is not None
        assert marked["status"] == "approved"
        assert store.get_pending(pending["id"])["status"] == "approved"

    def test_a_decided_row_is_not_re_marked(self, store) -> None:
        pending = _pending(store)
        store.mark(pending["id"], "approved")

        again = store.mark(pending["id"], "denied")

        assert again["status"] == "approved"

    def test_expiry_still_works(self, store) -> None:
        pending = _pending(store)

        expired = store.expire_old(now=9_999_999_999.0)

        assert expired == 1
        assert store.get_pending(pending["id"])["status"] == "expired"

    def test_latest_pending_still_returns_the_newest(self, store) -> None:
        _pending(store, source_text="first")
        second = _pending(store, source_text="second")

        latest = store.latest_pending()

        assert latest is not None
        assert latest["id"] == second["id"]

    def test_the_token_does_not_change_any_other_field(self, store) -> None:
        """The column is inert for every existing behaviour."""
        first = _pending(store, source_text="first")
        second = _pending(store, source_text="second")

        assert {
            k: v
            for k, v in first.items()
            if k not in {"id", "created_at", "expires_at", "source_text"}
        } == {
            k: v
            for k, v in second.items()
            if k not in {"id", "created_at", "expires_at", "source_text"}
        }
