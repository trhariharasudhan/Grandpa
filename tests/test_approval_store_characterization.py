"""What the third approval store does today, recorded on its own terms.

``tools/approval_store.py`` is the third live approval system in the tree. The
other two are characterised already -- ``local_action_approvals`` by the
``test_local_action_approval_*`` suites, and ``pc_control``'s by the approval
and identity-binding suites. This one had 29 route-level tests covering HTTP
shape and nothing covering the state machine underneath: no test pinned
``expire_stale``, the absence of replay protection, or the fact that
``approved`` authorises nothing.

**This file describes one store and compares it to nothing.** No assertion here
mentions ``local_action_approvals`` or ``pc_control``, and none claims any of
the three is canonical, stricter, or equivalent to another. Choosing between
them is an open architecture decision; a test that implied a choice would be
making it.

**Isolation.** Every case builds ``ApprovalStore(db_path=<tmp_path>/...)``.
``~/.grandpa/approvals.db`` -- the path the constructor defaults to -- is never
opened, and no actuator, executor or real approval route is called.

**Deterministic time without touching production time logic.**
``queue_action`` takes ``ttl_hours``, so a row that is already past its TTL is
made by passing a negative value and a boundary row by passing zero. Nothing
here monkeypatches ``datetime``.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from grandpa.tools.approval_store import (
    STATUS_APPROVED,
    STATUS_DENIED,
    STATUS_EXECUTED,
    STATUS_EXPIRED,
    STATUS_PENDING,
    TIER_HIGH,
    TIER_LOW,
    TIER_MEDIUM,
    TIER_TRIVIAL,
    ApprovalStore,
    PendingAction,
)

SRC = Path(__file__).resolve().parents[1] / "src" / "grandpa"
STORE_SOURCE = SRC / "tools" / "approval_store.py"

ALL_TIERS = (TIER_TRIVIAL, TIER_LOW, TIER_MEDIUM, TIER_HIGH)
ALL_TIER_NAMES = ("TIER_TRIVIAL", "TIER_LOW", "TIER_MEDIUM", "TIER_HIGH")


@pytest.fixture
def db_file(tmp_path) -> Path:
    return tmp_path / "isolated_approvals.db"


@pytest.fixture
def store(db_file):
    """A store on a temporary database, never the user's own."""
    instance = ApprovalStore(db_path=str(db_file))
    try:
        yield instance
    finally:
        instance.close()


def _queue(store, **overrides) -> PendingAction:
    kwargs = {
        "action_type": "email_delete",
        "description": "Delete a newsletter",
        "payload": {"message_id": "abc123"},
        "permission_key": "email_delete:domain:noreply.example.com",
        "tier": TIER_MEDIUM,
    }
    kwargs.update(overrides)
    return store.queue_action(**kwargs)


def _raw(db_file: Path, sql: str, params: tuple = ()):
    conn = sqlite3.connect(db_file)
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 1. Queue and creation
# ---------------------------------------------------------------------------


class TestQueueAction:
    def test_a_queued_action_starts_pending(self, store):
        action = _queue(store)

        assert action.status == STATUS_PENDING
        assert store.get_action(action.id).status == STATUS_PENDING

    def test_the_id_is_a_twelve_character_hex_string(self, store):
        action = _queue(store)

        assert len(action.id) == 12
        assert all(character in "0123456789abcdef" for character in action.id)

    def test_every_field_round_trips(self, store):
        action = _queue(store)
        loaded = store.get_action(action.id)

        assert loaded.action_type == "email_delete"
        assert loaded.description == "Delete a newsletter"
        assert loaded.permission_key == "email_delete:domain:noreply.example.com"
        assert loaded.tier == TIER_MEDIUM
        assert loaded.decision_at is None
        assert loaded.notification_sent is False

    def test_the_payload_round_trips_as_a_dict(self, store):
        action = _queue(store, payload={"message_id": "m1", "nested": {"a": [1, 2]}})
        loaded = store.get_action(action.id)

        assert loaded.payload == {"message_id": "m1", "nested": {"a": [1, 2]}}

    def test_the_payload_is_stored_as_json_text(self, store, db_file):
        action = _queue(store, payload={"message_id": "m1"})

        (row,) = _raw(
            db_file, "SELECT payload FROM pending_actions WHERE id = ?", (action.id,)
        )
        assert json.loads(row[0]) == {"message_id": "m1"}

    def test_an_empty_payload_round_trips_as_an_empty_dict(self, store):
        action = _queue(store, payload={})

        assert store.get_action(action.id).payload == {}

    def test_created_and_expiry_timestamps_are_iso_strings(self, store):
        action = _queue(store)

        assert isinstance(action.created_at, str)
        assert isinstance(action.expires_at, str)
        assert action.expires_at > action.created_at

    def test_the_default_ttl_is_twenty_four_hours(self, store):
        from datetime import datetime, timedelta

        action = _queue(store)
        created = datetime.fromisoformat(action.created_at)
        expires = datetime.fromisoformat(action.expires_at)

        assert expires - created == timedelta(hours=24)

    @pytest.mark.parametrize("hours", [1, 6, 48])
    def test_the_ttl_is_caller_supplied(self, store, hours):
        from datetime import datetime, timedelta

        action = _queue(store, ttl_hours=hours)
        created = datetime.fromisoformat(action.created_at)
        expires = datetime.fromisoformat(action.expires_at)

        assert expires - created == timedelta(hours=hours)

    def test_a_queued_action_appears_in_the_pending_list(self, store):
        action = _queue(store)

        assert [a.id for a in store.list_pending()] == [action.id]

    def test_a_freshly_queued_action_is_not_in_the_approved_list(self, store):
        _queue(store)

        assert store.list_approved() == []

    def test_get_action_returns_none_for_an_unknown_id(self, store):
        assert store.get_action("does-not-exist") is None


class TestQueueingDoesNotDeduplicate:
    """``INSERT OR REPLACE`` is present but unreachable in ordinary use.

    Every call mints a fresh ``uuid4().hex[:12]`` primary key, so the conflict
    clause has nothing to conflict with. Two identical requests therefore
    become two independent rows -- the store does not collapse them on
    ``permission_key``, ``action_type`` or payload.
    """

    def test_identical_requests_create_separate_rows(self, store):
        first = _queue(store)
        second = _queue(store)

        assert first.id != second.id
        assert len(store.list_pending()) == 2

    def test_they_are_independently_decidable(self, store):
        first = _queue(store)
        second = _queue(store)

        store.update_status(first.id, STATUS_APPROVED)

        assert store.get_action(first.id).status == STATUS_APPROVED
        assert store.get_action(second.id).status == STATUS_PENDING

    def test_the_same_permission_key_does_not_merge_rows(self, store):
        key = "email_delete:domain:example.com"
        _queue(store, permission_key=key)
        _queue(store, permission_key=key)

        rows = store.list_pending()
        assert len(rows) == 2
        assert {r.permission_key for r in rows} == {key}


# ---------------------------------------------------------------------------
# 2. Status transitions
# ---------------------------------------------------------------------------


class TestStatusTransitions:
    @pytest.mark.parametrize(
        "status", [STATUS_APPROVED, STATUS_DENIED, STATUS_EXPIRED, STATUS_EXECUTED]
    )
    def test_pending_moves_to_any_status(self, store, status):
        action = _queue(store)

        store.update_status(action.id, status)

        assert store.get_action(action.id).status == status

    def test_a_decision_stamps_decision_at(self, store):
        action = _queue(store)
        assert store.get_action(action.id).decision_at is None

        store.update_status(action.id, STATUS_APPROVED)

        assert store.get_action(action.id).decision_at is not None

    def test_approved_moves_to_executed(self, store):
        action = _queue(store)
        store.update_status(action.id, STATUS_APPROVED)

        store.update_status(action.id, STATUS_EXECUTED)

        assert store.get_action(action.id).status == STATUS_EXECUTED

    def test_an_approved_action_leaves_the_pending_list(self, store):
        action = _queue(store)
        store.update_status(action.id, STATUS_APPROVED)

        assert store.list_pending() == []
        assert [a.id for a in store.list_approved()] == [action.id]

    def test_an_executed_action_leaves_the_approved_list(self, store):
        action = _queue(store)
        store.update_status(action.id, STATUS_APPROVED)
        store.update_status(action.id, STATUS_EXECUTED)

        assert store.list_approved() == []

    def test_notification_sent_is_only_written_when_supplied(self, store):
        action = _queue(store)

        store.update_status(action.id, STATUS_APPROVED)
        assert store.get_action(action.id).notification_sent is False

        store.update_status(action.id, STATUS_EXECUTED, notification_sent=True)
        assert store.get_action(action.id).notification_sent is True

    def test_an_unknown_id_is_silently_ignored(self, store):
        """No exception, no row, no return value."""
        assert store.update_status("no-such-id", STATUS_APPROVED) is None
        assert store.get_action("no-such-id") is None

    def test_updating_an_unknown_id_does_not_touch_other_rows(self, store):
        action = _queue(store)

        store.update_status("no-such-id", STATUS_DENIED)

        assert store.get_action(action.id).status == STATUS_PENDING

    def test_an_arbitrary_status_string_is_accepted(self, store):
        """There is no enumeration check; the column takes any text."""
        action = _queue(store)

        store.update_status(action.id, "not_a_real_status")

        assert store.get_action(action.id).status == "not_a_real_status"


class TestThereIsNoTransitionGuard:
    """Any status may follow any other, in either direction.

    ``update_status`` is an unconditional ``UPDATE ... WHERE id = ?``. It does
    not read the current status, so nothing prevents a decided row being
    re-decided, or an approval being withdrawn to ``pending``.
    """

    def test_a_denied_action_can_be_approved(self, store):
        action = _queue(store)
        store.update_status(action.id, STATUS_DENIED)

        store.update_status(action.id, STATUS_APPROVED)

        assert store.get_action(action.id).status == STATUS_APPROVED

    def test_an_approved_action_can_be_denied(self, store):
        action = _queue(store)
        store.update_status(action.id, STATUS_APPROVED)

        store.update_status(action.id, STATUS_DENIED)

        assert store.get_action(action.id).status == STATUS_DENIED

    def test_an_executed_action_can_return_to_pending(self, store):
        action = _queue(store)
        store.update_status(action.id, STATUS_EXECUTED)

        store.update_status(action.id, STATUS_PENDING)

        assert store.get_action(action.id).status == STATUS_PENDING
        assert [a.id for a in store.list_pending()] == [action.id]

    def test_an_expired_action_can_be_approved(self, store):
        action = _queue(store, ttl_hours=-1)
        store.expire_stale()
        assert store.get_action(action.id).status == STATUS_EXPIRED

        store.update_status(action.id, STATUS_APPROVED)

        assert store.get_action(action.id).status == STATUS_APPROVED


# ---------------------------------------------------------------------------
# 3. Expiry
# ---------------------------------------------------------------------------


class TestExpiry:
    def test_a_past_ttl_row_is_expired(self, store):
        action = _queue(store, ttl_hours=-1)

        assert store.expire_stale() == 1
        assert store.get_action(action.id).status == STATUS_EXPIRED

    def test_a_live_row_is_untouched(self, store):
        action = _queue(store)

        assert store.expire_stale() == 0
        assert store.get_action(action.id).status == STATUS_PENDING

    def test_a_zero_ttl_row_is_expired(self, store):
        """The comparison is ``expires_at <= now``, so the boundary expires."""
        action = _queue(store, ttl_hours=0)

        assert store.expire_stale() == 1
        assert store.get_action(action.id).status == STATUS_EXPIRED

    def test_expiry_only_touches_pending_rows(self, store):
        stale_approved = _queue(store, ttl_hours=-1)
        store.update_status(stale_approved.id, STATUS_APPROVED)
        stale_pending = _queue(store, ttl_hours=-1)

        assert store.expire_stale() == 1
        assert store.get_action(stale_approved.id).status == STATUS_APPROVED
        assert store.get_action(stale_pending.id).status == STATUS_EXPIRED

    def test_expiring_twice_is_a_no_op_the_second_time(self, store):
        _queue(store, ttl_hours=-1)

        assert store.expire_stale() == 1
        assert store.expire_stale() == 0

    def test_the_count_is_the_number_of_rows_changed(self, store):
        for _ in range(3):
            _queue(store, ttl_hours=-1)
        _queue(store)

        assert store.expire_stale() == 3

    def test_an_expired_row_leaves_the_pending_list(self, store):
        _queue(store, ttl_hours=-1)
        store.expire_stale()

        assert store.list_pending() == []

    def test_a_stale_row_is_hidden_from_the_pending_list_before_it_is_marked(
        self, store
    ):
        """``list_pending`` filters on ``expires_at > now`` as well as status.

        So a past-TTL row disappears from the listing even though its stored
        status is still ``pending`` -- listing and stored state disagree until
        ``expire_stale`` runs.
        """
        action = _queue(store, ttl_hours=-1)

        assert store.list_pending() == []
        assert store.get_action(action.id).status == STATUS_PENDING

    def test_expiry_does_not_stamp_decision_at(self, store):
        action = _queue(store, ttl_hours=-1)
        store.expire_stale()

        assert store.get_action(action.id).decision_at is None

    def test_the_approved_list_is_not_expiry_filtered(self, store):
        """``list_approved`` has no ``expires_at`` clause, so an approval that
        is long past its TTL is still listed."""
        action = _queue(store, ttl_hours=-1)
        store.update_status(action.id, STATUS_APPROVED)

        assert [a.id for a in store.list_approved()] == [action.id]


# ---------------------------------------------------------------------------
# 4. Replay and overwrite
# ---------------------------------------------------------------------------


class TestThereIsNoReplayProtection:
    """Recorded as an absence, because the absence is the behaviour.

    Nothing in this store reports whether a caller was the first to decide a
    row. ``update_status`` returns ``None`` whether it changed a row or not,
    so two concurrent approvers both believe they succeeded.
    """

    def test_repeated_approval_succeeds_every_time(self, store):
        action = _queue(store)

        assert store.update_status(action.id, STATUS_APPROVED) is None
        assert store.update_status(action.id, STATUS_APPROVED) is None
        assert store.get_action(action.id).status == STATUS_APPROVED

    def test_repeated_denial_succeeds_every_time(self, store):
        action = _queue(store)

        store.update_status(action.id, STATUS_DENIED)
        store.update_status(action.id, STATUS_DENIED)

        assert store.get_action(action.id).status == STATUS_DENIED

    def test_repeated_execution_succeeds_every_time(self, store):
        action = _queue(store)
        store.update_status(action.id, STATUS_APPROVED)

        store.update_status(action.id, STATUS_EXECUTED)
        store.update_status(action.id, STATUS_EXECUTED)

        assert store.get_action(action.id).status == STATUS_EXECUTED

    def test_a_later_decision_silently_overwrites_an_earlier_one(self, store):
        action = _queue(store)
        store.update_status(action.id, STATUS_APPROVED)
        first_decision = store.get_action(action.id).decision_at

        store.update_status(action.id, STATUS_DENIED)
        second_decision = store.get_action(action.id).decision_at

        assert store.get_action(action.id).status == STATUS_DENIED
        assert second_decision >= first_decision

    def test_the_row_count_never_grows_from_re_deciding(self, store, db_file):
        action = _queue(store)
        for status in (STATUS_APPROVED, STATUS_DENIED, STATUS_EXECUTED):
            store.update_status(action.id, status)

        (row,) = _raw(db_file, "SELECT COUNT(*) FROM pending_actions")
        assert row[0] == 1


# ---------------------------------------------------------------------------
# 5. Credentials -- what is absent
# ---------------------------------------------------------------------------


class TestThereIsNoCredential:
    """Approval here is by id alone. Recorded, not judged."""

    def test_the_row_carries_no_credential_columns(self, store, db_file):
        _queue(store)
        columns = {
            row[1] for row in _raw(db_file, "PRAGMA table_info(pending_actions)")
        }

        assert "approval_token" not in columns
        assert "action_digest" not in columns
        assert "failed_attempts" not in columns

    def test_the_schema_columns_are_exactly_these(self, store, db_file):
        _queue(store)
        columns = [
            row[1] for row in _raw(db_file, "PRAGMA table_info(pending_actions)")
        ]

        assert columns == [
            "id",
            "action_type",
            "description",
            "payload",
            "permission_key",
            "tier",
            "status",
            "created_at",
            "expires_at",
            "notification_sent",
            "decision_at",
        ]

    def test_the_dataclass_carries_no_credential_fields(self):
        from dataclasses import fields

        names = {f.name for f in fields(PendingAction)}

        assert "approval_token" not in names
        assert "action_digest" not in names
        assert "failed_attempts" not in names

    def test_approving_needs_only_an_id(self, store):
        action = _queue(store)

        store.update_status(action.id, STATUS_APPROVED)

        assert store.get_action(action.id).status == STATUS_APPROVED

    def test_the_module_contains_no_credential_machinery(self):
        source = STORE_SOURCE.read_text(encoding="utf-8")

        for absent in ("compare_digest", "secrets", "hmac", "hashlib"):
            assert absent not in source, absent

    def test_the_store_exposes_no_verification_method(self):
        for absent in (
            "verify_approval_token",
            "authorize_approval",
            "approval_token",
            "attempts_exhausted",
        ):
            assert not hasattr(ApprovalStore, absent), absent


# ---------------------------------------------------------------------------
# 6. Approved does not mean executed
# ---------------------------------------------------------------------------


class TestApprovedAuthorisesNothing:
    """The store records a decision; it does not act on one.

    Proved from the call graph rather than by running anything: the three
    production modules that name ``STATUS_APPROVED`` are enumerated, and none
    of them reaches an actuator.
    """

    def test_approving_changes_only_the_row(self, store, db_file):
        action = _queue(store)
        before = _raw(db_file, "SELECT id, action_type, payload FROM pending_actions")

        store.update_status(action.id, STATUS_APPROVED)
        after = _raw(db_file, "SELECT id, action_type, payload FROM pending_actions")

        assert before == after

    def test_executed_is_set_by_a_caller_not_by_the_store(self, store):
        """Approving never advances a row to ``executed`` on its own."""
        action = _queue(store)
        store.update_status(action.id, STATUS_APPROVED)

        assert store.get_action(action.id).status == STATUS_APPROVED
        assert store.list_approved()[0].status == STATUS_APPROVED

    def test_the_store_module_imports_no_executor(self):
        source = STORE_SOURCE.read_text(encoding="utf-8")

        for absent in (
            "subprocess",
            "run_local_action",
            "pc_control",
            "local_actions",
            "os.startfile",
            "pyautogui",
        ):
            assert absent not in source, absent

    def test_only_two_production_modules_name_the_approved_status(self):
        """Pinned so a new consumer is a decision rather than a discovery.

        Three until AD-032 retired the ``/v1/approvals/*`` route family;
        ``server/approval_routes.py`` was the third and is gone with it.
        """
        naming = sorted(
            path.relative_to(SRC).as_posix()
            for path in SRC.rglob("*.py")
            if "STATUS_APPROVED" in path.read_text(encoding="utf-8")
        )

        assert naming == [
            "agent/execution/approval.py",
            "tools/approval_store.py",
        ]

    def test_none_of_those_modules_reaches_an_actuator(self):
        for relative in (
            "agent/execution/approval.py",
            "tools/approval_store.py",
        ):
            source = (SRC / relative).read_text(encoding="utf-8")
            for absent in (
                "subprocess",
                "run_local_action",
                "os.startfile",
                "pyautogui",
            ):
                assert absent not in source, f"{relative}: {absent}"


# ---------------------------------------------------------------------------
# 7. Tier
# ---------------------------------------------------------------------------


class TestTierIsStoredNotEnforced:
    """``tier`` is persisted and served; nothing branches on it.

    The constants document behaviour -- ``trivial`` says "execute immediately,
    no ask" -- that no code implements. Recorded as found.
    """

    @pytest.mark.parametrize("tier", ALL_TIERS)
    def test_every_tier_round_trips(self, store, tier):
        action = _queue(store, tier=tier)

        assert store.get_action(action.id).tier == tier

    @pytest.mark.parametrize("tier", ALL_TIERS)
    def test_the_tier_does_not_change_the_initial_status(self, store, tier):
        action = _queue(store, tier=tier)

        assert action.status == STATUS_PENDING

    @pytest.mark.parametrize("tier", ALL_TIERS)
    def test_the_tier_does_not_change_which_transitions_are_allowed(self, store, tier):
        action = _queue(store, tier=tier)

        store.update_status(action.id, STATUS_APPROVED)

        assert store.get_action(action.id).status == STATUS_APPROVED

    def test_trivial_is_not_auto_executed_despite_its_documented_meaning(self, store):
        action = _queue(store, tier=TIER_TRIVIAL)

        assert store.get_action(action.id).status == STATUS_PENDING
        assert [a.id for a in store.list_pending()] == [action.id]

    def test_high_is_not_treated_differently_from_low(self, store):
        low = _queue(store, tier=TIER_LOW)
        high = _queue(store, tier=TIER_HIGH)

        store.update_status(low.id, STATUS_APPROVED)
        store.update_status(high.id, STATUS_APPROVED)

        assert store.get_action(low.id).status == store.get_action(high.id).status

    def test_an_unrecognised_tier_is_accepted(self, store):
        """There is no validation; the column takes any text."""
        action = _queue(store, tier="not_a_tier")

        assert store.get_action(action.id).tier == "not_a_tier"

    def test_no_production_module_branches_on_a_tier_constant(self):
        """The only production use writes one; none reads one to decide.

        Matched on the four constant names rather than the ``TIER_`` prefix --
        ``core/config.py`` has an unrelated ``_MODEL_TIER_FALLBACK``.
        """
        users = sorted(
            path.relative_to(SRC).as_posix()
            for path in SRC.rglob("*.py")
            if any(name in path.read_text(encoding="utf-8") for name in ALL_TIER_NAMES)
        )

        assert users == ["agent/execution/approval.py", "tools/approval_store.py"]

    def test_the_one_production_writer_hardcodes_a_single_tier(self):
        source = (SRC / "agent" / "execution" / "approval.py").read_text(
            encoding="utf-8"
        )

        assert "tier=TIER_MEDIUM" in source
        for unused in ("TIER_TRIVIAL", "TIER_LOW", "TIER_HIGH"):
            assert unused not in source, unused


# ---------------------------------------------------------------------------
# 8. The remembered-permission subsystem, retired
# ---------------------------------------------------------------------------


class TestRememberedPermissionsStayRetired:
    """AD-031 retired the remembered-permission subsystem. It must stay gone.

    What stood here characterised a dead subsystem: a ``permission_memory``
    table that was created on every init and never read, four CRUD methods with
    no callers, and ``get_seen_ids``, which scanned each payload for a
    ``doc_id`` the only live producer never writes. Those tests recorded the
    deadness; these two prevent its return, which is the only reason this
    section still exists after the deletion.
    """

    def test_the_permission_memory_table_is_not_created(self, store, db_file):
        """A fresh database has one table.

        Existing deployed databases keep an orphaned ``permission_memory`` --
        AD-031 g authorises no ``DROP TABLE`` and no migration, because nothing
        reads it. This is about what a *new* database gets.
        """
        tables = {
            row[0]
            for row in _raw(
                db_file, "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }

        assert "permission_memory" not in tables
        assert "pending_actions" in tables

    def test_the_retired_methods_are_gone(self):
        for name in (
            "get_permission",
            "set_permission",
            "clear_permission",
            "list_permissions",
            "get_seen_ids",
        ):
            assert not hasattr(ApprovalStore, name), (
                f"{name} was retired by AD-031; re-adding it needs a new decision"
            )


# ---------------------------------------------------------------------------
# Isolation
# ---------------------------------------------------------------------------


class TestTheseTestsAreIsolated:
    def test_the_store_writes_to_the_path_it_was_given(self, store, db_file):
        _queue(store)

        assert db_file.exists()
        (row,) = _raw(db_file, "SELECT COUNT(*) FROM pending_actions")
        assert row[0] == 1

    def test_every_store_in_this_file_is_built_with_an_explicit_path(self):
        """``ApprovalStore()`` with no argument defaults to the user's own
        database. This suite must never construct one that way, and this reads
        the file to prove it rather than trusting the fixture.
        """
        import ast

        tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
        constructions = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "ApprovalStore"
        ]

        assert constructions, "the guard would be vacuous with no constructions"
        for call in constructions:
            assert {keyword.arg for keyword in call.keywords} == {"db_path"}, (
                "ApprovalStore must be built with an explicit db_path"
            )

    def test_the_fixture_path_is_inside_the_temporary_directory(
        self, db_file, tmp_path
    ):
        assert db_file.parent == tmp_path
