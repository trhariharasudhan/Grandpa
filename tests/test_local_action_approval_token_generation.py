"""Every new pending action gets a code, and the code goes only to the console.

4.13B added the ``approval_token`` column and the rule that an empty one means
"legacy, unbound, not approvable". This slice fills it: ``create_pending`` mints
a fresh code and logs it, and nothing else changes.

Two properties carry the security weight, and both are easy to lose by accident:

* **The code is generated server-side, never supplied.** 4.13B briefly accepted
  one as a parameter so a bound row could be created for testing. That was a
  caller-supplied credential channel -- the same shape as the client-supplied
  ``source`` and ``confirmed`` fields closed in 4.12E-5/E-6 and 4.12K-B -- so
  this slice removes it. There is now no way to hand the store a code.

* **The console is the only place it appears.** The whole point of an
  out-of-band code is that the HTTP caller who stages an action cannot read it.
  ``TestTheTokenNeverReachesHttp`` walks every projection and every user-visible
  string field rather than trusting the column list.

No endpoint consults the code yet -- ``/v1/local-actions/{id}/approve`` and
``/v1/voice/confirm`` still approve on an id alone. 4.13D does that. Rate
limiting belongs there too, with the attempts it counts.
"""

from __future__ import annotations

import logging
import re
import sqlite3

import pytest

from grandpa.local_action_approvals import LocalActionApprovalStore

#: ``secrets.token_hex(4).upper()`` -- eight uppercase hex characters.
TOKEN_PATTERN = re.compile(r"^[0-9A-F]{8}$")

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
# A/B/C/D -- generation
# ---------------------------------------------------------------------------


class TestEveryNewActionGetsACode:
    def test_a_new_pending_action_is_bound(self, store) -> None:
        """A: the property 4.13D will rely on for every row it can approve."""
        pending = _pending(store)

        assert store.approval_token(pending["id"])
        assert store.is_token_bound(pending["id"]) is True

    def test_the_code_is_eight_uppercase_hex_characters(self, store) -> None:
        """B: ``secrets.token_hex(4).upper()``."""
        pending = _pending(store)

        token = store.approval_token(pending["id"])

        assert TOKEN_PATTERN.match(token), token

    def test_two_actions_get_different_codes(self, store, monkeypatch) -> None:
        """C, deterministically: the generator is consulted per action.

        Randomness is characterized separately below; here the generator is
        replaced so the assertion cannot pass by luck.
        """
        from grandpa import local_action_approvals

        codes = iter(["AAAAAAAA", "BBBBBBBB"])
        monkeypatch.setattr(
            local_action_approvals.secrets, "token_hex", lambda n: next(codes)
        )

        first = _pending(store, source_text="first")
        second = _pending(store, source_text="second")

        assert store.approval_token(first["id"]) == "AAAAAAAA"
        assert store.approval_token(second["id"]) == "BBBBBBBB"

    def test_real_generation_does_not_repeat(self, store) -> None:
        """C, for real: twenty live codes, no collisions and all well-formed."""
        tokens = {
            store.approval_token(_pending(store, source_text=f"cmd {i}")["id"])
            for i in range(20)
        }

        assert len(tokens) == 20
        assert all(TOKEN_PATTERN.match(t) for t in tokens)

    def test_the_code_is_persisted_against_that_exact_action(self, store) -> None:
        """D: bound to one row, and readable back through the store API."""
        first = _pending(store, source_text="first")
        second = _pending(store, source_text="second")

        assert store.approval_token(first["id"]) != store.approval_token(second["id"])
        assert store.approval_token(first["id"]) == store.approval_token(first["id"])

    def test_the_persisted_code_verifies(self, store) -> None:
        """Non-vacuity: created, retrieved and verified through the real API."""
        pending = _pending(store)

        token = store.approval_token(pending["id"])

        assert store.verify_approval_token(pending["id"], token) is True
        assert store.verify_approval_token(pending["id"], "00000000") is False

    def test_the_code_survives_a_reopen(self, store, tmp_path) -> None:
        pending = _pending(store)
        token = store.approval_token(pending["id"])

        reopened = LocalActionApprovalStore(tmp_path / "approvals.db")

        assert reopened.approval_token(pending["id"]) == token


class TestTheGeneratorIsCryptographic:
    """The primitive matters; a predictable code is no code at all."""

    def test_secrets_token_hex_is_used(self, store, monkeypatch) -> None:
        from grandpa import local_action_approvals

        seen: list[int] = []
        real = local_action_approvals.secrets.token_hex

        def spy(n):
            seen.append(n)
            return real(n)

        monkeypatch.setattr(local_action_approvals.secrets, "token_hex", spy)

        _pending(store)

        assert seen == [4], "expected exactly one token_hex(4) call per action"

    def test_the_token_is_assigned_from_secrets(self) -> None:
        """Structural, scoped to the assignment.

        Scanning the whole function would be the wrong instrument:
        ``create_pending`` legitimately uses ``uuid.uuid4().hex`` for the action
        id and ``time.time()`` for timestamps. What must come from ``secrets``
        is the credential, so that is the line asserted.
        """
        import inspect

        from grandpa import local_action_approvals

        source = inspect.getsource(local_action_approvals.LocalActionApprovalStore)
        assignments = [
            line.strip()
            for line in source.splitlines()
            if line.strip().startswith("approval_token =")
        ]

        assert assignments == ["approval_token = secrets.token_hex(4).upper()"]

    @pytest.mark.parametrize("banned", ("uuid", "random", "time.time", "action_id"))
    def test_the_assignment_uses_no_predictable_source(self, banned: str) -> None:
        import inspect

        from grandpa import local_action_approvals

        source = inspect.getsource(local_action_approvals.LocalActionApprovalStore)
        assignment = next(
            line
            for line in source.splitlines()
            if line.strip().startswith("approval_token =")
        )

        assert banned not in assignment, banned

    def test_the_code_is_not_derived_from_the_action_id(self, store) -> None:
        pending = _pending(store)

        token = store.approval_token(pending["id"])

        assert token not in pending["id"].upper()
        assert token.lower() not in pending["id"]


class TestTheCodeCannotBeSupplied:
    """F: there is no caller-supplied credential channel."""

    def test_create_pending_takes_no_token_parameter(self) -> None:
        import inspect

        assert (
            "approval_token"
            not in inspect.signature(LocalActionApprovalStore.create_pending).parameters
        )

    def test_a_supplied_token_is_rejected_outright(self, store) -> None:
        with pytest.raises(TypeError):
            _pending(store, approval_token="ATTACKER")

    def test_no_user_field_can_become_the_code(self, store) -> None:
        """Even text that looks like a code is not adopted as one."""
        pending = _pending(store, source_text="DEADBEEF", message="DEADBEEF")

        assert store.approval_token(pending["id"]) != "DEADBEEF"


# ---------------------------------------------------------------------------
# E/J -- legacy rows
# ---------------------------------------------------------------------------


class TestLegacyRowsAreNotBackfilled:
    def test_a_migrated_legacy_row_stays_empty(self, tmp_path) -> None:
        """E: generation applies to new rows, never retroactively."""
        db = tmp_path / "legacy.db"
        _write_legacy_db(db)

        store = LocalActionApprovalStore(db)

        assert store.approval_token("legacyaction0001") == ""

    def test_a_legacy_row_stays_empty_after_new_rows_are_created(
        self, tmp_path
    ) -> None:
        db = tmp_path / "legacy.db"
        _write_legacy_db(db)
        store = LocalActionApprovalStore(db)

        _pending(store, source_text="new one")

        assert store.approval_token("legacyaction0001") == ""

    def test_legacy_and_new_rows_stay_distinguishable(self, tmp_path) -> None:
        """J."""
        db = tmp_path / "legacy.db"
        _write_legacy_db(db)
        store = LocalActionApprovalStore(db)

        fresh = _pending(store, source_text="new one")

        assert store.is_token_bound("legacyaction0001") is False
        assert store.is_token_bound(fresh["id"]) is True

    def test_a_legacy_row_is_still_unapprovable(self, tmp_path) -> None:
        db = tmp_path / "legacy.db"
        _write_legacy_db(db)
        store = LocalActionApprovalStore(db)

        assert store.verify_approval_token("legacyaction0001", "") is False
        assert store.verify_approval_token("legacyaction0001", "00000000") is False


# ---------------------------------------------------------------------------
# G -- out-of-band delivery
# ---------------------------------------------------------------------------


class TestTheCodeIsDeliveredToTheConsole:
    def test_the_code_is_logged(self, store, caplog) -> None:
        """G: the console is the delivery channel, following pc_control."""
        with caplog.at_level(logging.WARNING, logger="grandpa.local_action_approvals"):
            pending = _pending(store)

        token = store.approval_token(pending["id"])

        assert token in caplog.text

    def test_the_log_names_the_action_it_belongs_to(self, store, caplog) -> None:
        with caplog.at_level(logging.WARNING, logger="grandpa.local_action_approvals"):
            pending = _pending(store)

        assert pending["id"] in caplog.text

    def test_the_log_identifies_the_value_as_an_approval_code(
        self, store, caplog
    ) -> None:
        with caplog.at_level(logging.WARNING, logger="grandpa.local_action_approvals"):
            _pending(store)

        assert "approval code" in caplog.text.lower()

    def test_the_log_is_at_warning_level(self, store, caplog) -> None:
        """As pc_control does -- a code the operator must actually see."""
        with caplog.at_level(logging.WARNING, logger="grandpa.local_action_approvals"):
            _pending(store)

        assert any(r.levelno >= logging.WARNING for r in caplog.records)


# ---------------------------------------------------------------------------
# H -- the code must not reach HTTP
# ---------------------------------------------------------------------------


class TestTheTokenNeverReachesHttp:
    @pytest.mark.parametrize(
        "projection", ("list_pending", "latest_pending", "get_pending")
    )
    def test_no_store_projection_carries_it(self, projection: str, store) -> None:
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

    def test_the_returned_row_does_not_carry_it(self, store) -> None:
        """``create_pending``'s own return value is what reaches the caller."""
        pending = _pending(store)

        assert "approval_token" not in pending
        assert store.approval_token(pending["id"]) not in str(pending)

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

    def test_pending_metadata_does_not_carry_it(self, store) -> None:
        from grandpa.local_actions import _pending_metadata

        pending = _pending(store)
        token = store.approval_token(pending["id"])

        assert token not in str(_pending_metadata(pending))

    @pytest.mark.parametrize("field", ("source_text", "message", "tts_text"))
    def test_no_user_visible_field_carries_it(self, field: str, store) -> None:
        """The convenient mistake: putting the code where the prompt is."""
        pending = _pending(store)
        token = store.approval_token(pending["id"])

        assert token not in pending[field], field

    def test_the_audit_log_does_not_carry_it(self, store) -> None:
        pending = _pending(store)
        token = store.approval_token(pending["id"])

        assert token not in str(store.list_audit())
        assert pending["id"] in str(store.list_audit())

    def test_the_http_pending_route_does_not_expose_it(self, store) -> None:
        """End to end through the projection the HTTP route actually returns."""
        pending = _pending(store)
        token = store.approval_token(pending["id"])

        payload = {"actions": store.list_pending()}

        assert token not in str(payload)
        assert pending["id"] in str(payload)


# ---------------------------------------------------------------------------
# I/K/L -- nothing else moved, and generation happens once
# ---------------------------------------------------------------------------


class TestGenerationHappensOnceAtCreation:
    def test_reading_does_not_regenerate(self, store) -> None:
        """K."""
        pending = _pending(store)
        first = store.approval_token(pending["id"])

        store.get_pending(pending["id"])
        store.list_pending()
        store.latest_pending()

        assert store.approval_token(pending["id"]) == first

    def test_verifying_does_not_regenerate(self, store) -> None:
        pending = _pending(store)
        first = store.approval_token(pending["id"])

        store.verify_approval_token(pending["id"], "00000000")
        store.is_token_bound(pending["id"])

        assert store.approval_token(pending["id"]) == first

    def test_the_generator_runs_once_per_action(self, store, monkeypatch) -> None:
        """L: not once per read, not once per verification."""
        from grandpa import local_action_approvals

        calls: list[int] = []
        real = local_action_approvals.secrets.token_hex
        monkeypatch.setattr(
            local_action_approvals.secrets,
            "token_hex",
            lambda n: (calls.append(n), real(n))[1],
        )

        pending = _pending(store)
        store.get_pending(pending["id"])
        store.list_pending()
        store.approval_token(pending["id"])
        store.verify_approval_token(pending["id"], "00000000")

        assert len(calls) == 1


class TestExistingBehaviourIsUnchanged:
    """I."""

    def test_every_other_field_is_as_before(self, store) -> None:
        pending = _pending(store)

        assert pending["kind"] == "window"
        assert pending["target"] == "close|notepad"
        assert pending["source_text"] == "close notepad"
        assert pending["message"] == "Confirmation required."
        assert pending["tts_text"] == "Please confirm."
        assert pending["status"] == "pending"
        assert pending["created_at"] < pending["expires_at"]

    def test_the_ttl_is_unchanged(self, store) -> None:
        from grandpa.local_action_approvals import PENDING_TTL_SECONDS

        pending = _pending(store)

        assert pending["expires_at"] - pending["created_at"] == PENDING_TTL_SECONDS

    def test_status_transitions_are_unchanged(self, store) -> None:
        pending = _pending(store)

        marked = store.mark(pending["id"], "approved")

        assert marked["status"] == "approved"

    def test_expiry_is_unchanged(self, store) -> None:
        pending = _pending(store)

        assert store.expire_old(now=9_999_999_999.0) == 1
        assert store.get_pending(pending["id"])["status"] == "expired"

    def test_an_expired_row_keeps_its_code(self, store) -> None:
        """Expiry is a status change, not a credential change."""
        pending = _pending(store)
        token = store.approval_token(pending["id"])

        store.expire_old(now=9_999_999_999.0)

        assert store.approval_token(pending["id"]) == token
