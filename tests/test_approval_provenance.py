"""Who asked survives the wait for approval.

``LocalActionRequest`` carries ``origin`` (AD-022), and the audit record reads
it, so a spoken action is meant to be traceable to speech. But the approval
record never stored it: ``_request_from_row`` rebuilt the request without an
origin, so the field fell back to its default and every approved action was
recorded as ``direct`` regardless of who asked for it.

That is a provenance defect, not a privilege one. Origin does not affect risk,
approval, or the emergency stop -- ``test_the_gate_does_not_depend_on_who_asked``
pins that -- so nothing became more permissive. What broke is the audit trail's
ability to answer "who asked for this?", which is the single question AD-022
exists to answer, and it broke precisely for the actions important enough to
need a human decision.

The fix is at the persistence seam only. The request model is unchanged, the
origin vocabulary is unchanged, and origin is deliberately kept out of the
action digest: identity binding answers *what* was approved and provenance
answers *who asked*, and folding them together would make an approval fail
because the caller changed rather than because the action did.

Legacy rows written before the column existed carry no origin. They coerce to
``direct`` through the existing ``_coerce_origin`` contract, which documents
that as the least-privileged label -- an unknown caller is never recorded as a
trusted one.

Nothing launches: the launcher is replaced by a recorder.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from grandpa import pc_control
from grandpa.apps.inventory import AppInventoryRecord
from grandpa.apps.resolver import normalize_app_name, resolve_app
from grandpa.pc_control import ACTION_ORIGINS, LocalActionRequest


@pytest.fixture
def audit_log(tmp_path, monkeypatch):
    path = tmp_path / "audit.log"
    monkeypatch.setenv("GRANDPA_LOCAL_ACTION_LOG", str(tmp_path / "actions.jsonl"))
    monkeypatch.setenv("GRANDPA_PC_CONTROL_DB", str(tmp_path / "approvals.db"))
    monkeypatch.setattr(pc_control, "get_audit_log_path", lambda: path)
    pc_control.reset_emergency_stop()
    yield path
    pc_control.reset_emergency_stop()


class Inventory:
    def __init__(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / "git-bash.exe"
        target.write_text("", encoding="utf-8")
        self.rows = [
            AppInventoryRecord(
                "Git",
                normalize_app_name("Git"),
                str(target),
                "test",
                ("bash", "git", "git bash"),
                1.0,
            )
        ]
        self.launched: list[str] = []

    def find_app(self, name: str, **_kwargs):
        return resolve_app(name, self.rows)

    def launch(self, record) -> str:
        self.launched.append(record.path)
        return f"Opening {record.display_name}."


@pytest.fixture
def inventory(tmp_path, monkeypatch):
    store = Inventory(tmp_path / "apps")
    monkeypatch.setattr("grandpa.apps.inventory.find_app", store.find_app)
    monkeypatch.setattr("grandpa.apps.inventory.launch_inventory_app", store.launch)
    return store


def _stage(origin: str) -> tuple[str, str]:
    response = pc_control.run_local_action(
        {
            "action_type": "open_app",
            "target": "bash",
            "require_approval": True,
            "origin": origin,
        }
    )
    assert response.status == "approval_required"
    action_id = response.action_id or ""
    record = pc_control._load_pending_record(action_id)
    assert record is not None
    return action_id, record.approval_token


def _audit_records(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


# ---------------------------------------------------------------------------
# A, B, C -- the round trip
# ---------------------------------------------------------------------------


class TestOriginSurvivesApproval:
    @pytest.mark.parametrize("origin", ACTION_ORIGINS)
    def test_the_reloaded_request_keeps_it(self, origin, audit_log, inventory):
        action_id, _code = _stage(origin)

        record = pc_control._load_pending_record(action_id)

        assert record is not None
        assert record.request.origin == origin

    @pytest.mark.parametrize("origin", ACTION_ORIGINS)
    def test_the_executed_request_keeps_it(self, origin, audit_log, inventory):
        """Through the real approval boundary, not a unit test of the row
        mapper: what executes must carry what was staged."""
        seen: list[str] = []
        original = pc_control._execute

        def spy(request, risk, **kwargs):
            seen.append(request.origin)
            return original(request, risk, **kwargs)

        pc_control._execute = spy
        try:
            action_id, code = _stage(origin)
            approved = pc_control.approve_local_action(action_id, code)
        finally:
            pc_control._execute = original

        assert approved.ok is True
        assert seen == [origin]

    @pytest.mark.parametrize("origin", ACTION_ORIGINS)
    def test_the_audit_trail_keeps_it(self, origin, audit_log, inventory):
        """The question AD-022 exists to answer, asked after approval."""
        action_id, code = _stage(origin)
        pc_control.approve_local_action(action_id, code)

        approved = [
            record
            for record in _audit_records(audit_log)
            if record.get("approval_status") == "approved"
        ]

        assert approved, "no approved audit record was written"
        assert approved[-1]["origin"] == origin

    def test_staging_and_approval_agree(self, audit_log, inventory):
        action_id, code = _stage("voice")
        pc_control.approve_local_action(action_id, code)

        origins = {
            record["origin"]
            for record in _audit_records(audit_log)
            if record.get("action_type") == "open_app"
        }

        assert origins == {"voice"}


# ---------------------------------------------------------------------------
# D, E -- unknown and invalid values
# ---------------------------------------------------------------------------


class TestUnknownProvenance:
    def test_a_legacy_row_without_an_origin_reads_as_direct(self, audit_log, inventory):
        """The existing ``_coerce_origin`` contract: unknown falls back to the
        least-privileged label, so an unknown caller is never recorded as a
        trusted one. Not a fabricated provenance -- the documented default."""
        action_id, _code = _stage("voice")
        with pc_control._connect_approval_db() as conn:
            conn.execute(
                "UPDATE pc_control_approvals SET origin = '' WHERE action_id = ?",
                (action_id,),
            )

        record = pc_control._load_pending_record(action_id)

        assert record is not None
        assert record.request.origin == "direct"

    @pytest.mark.parametrize("stored", ["", "root", "VOICE ", "admin", "system"])
    def test_only_a_known_origin_is_restored(self, stored, audit_log, inventory):
        action_id, _code = _stage("agent")
        with pc_control._connect_approval_db() as conn:
            conn.execute(
                "UPDATE pc_control_approvals SET origin = ? WHERE action_id = ?",
                (stored, action_id),
            )

        record = pc_control._load_pending_record(action_id)

        assert record is not None
        assert record.request.origin in ACTION_ORIGINS

    def test_a_stored_value_cannot_invent_a_new_origin(self, audit_log, inventory):
        action_id, _code = _stage("voice")
        with pc_control._connect_approval_db() as conn:
            conn.execute(
                "UPDATE pc_control_approvals SET origin = 'superuser' "
                "WHERE action_id = ?",
                (action_id,),
            )

        record = pc_control._load_pending_record(action_id)

        assert record is not None
        assert record.request.origin == "direct"

    def test_the_vocabulary_is_unchanged(self):
        assert ACTION_ORIGINS == (
            "voice",
            "agent",
            "direct",
            "api",
            "scheduler",
            "skill",
        )
        assert pc_control.DEFAULT_ACTION_ORIGIN == "direct"


# ---------------------------------------------------------------------------
# G, H -- everything else is untouched
# ---------------------------------------------------------------------------


class TestIndependenceFromIdentityBinding:
    def test_origin_does_not_change_the_action_digest(self):
        """Identity binding answers what was approved; provenance answers who
        asked. Folding them together would make an approval fail because the
        caller changed rather than because the action did."""
        digests = {
            pc_control._action_digest(
                LocalActionRequest(
                    action_type="open_app", target="bash", origin=origin
                ),
                "git-bash.exe",
                "C:/x/git-bash.exe",
            )
            for origin in ACTION_ORIGINS
        }

        assert len(digests) == 1

    def test_the_digest_payload_has_no_origin_field(self):
        import inspect

        source = inspect.getsource(pc_control._action_digest)

        assert '"origin"' not in source

    @pytest.mark.parametrize("origin", ACTION_ORIGINS)
    def test_the_binding_still_refuses_a_changed_identity(
        self, origin, audit_log, inventory, tmp_path
    ):
        action_id, code = _stage(origin)
        other = tmp_path / "apps" / "notepad.exe"
        other.write_text("", encoding="utf-8")
        inventory.rows = [
            AppInventoryRecord(
                "Bash Notes",
                normalize_app_name("Bash Notes"),
                str(other),
                "test",
                ("bash",),
                1.0,
            )
        ]

        approved = pc_control.approve_local_action(action_id, code)

        assert approved.ok is False
        assert approved.error == "approved_action_changed"
        assert inventory.launched == []


class TestApprovalMechanicsUnchanged:
    def test_the_token_is_still_required(self, audit_log, inventory):
        action_id, _code = _stage("voice")

        approved = pc_control.approve_local_action(action_id, "DEADBEEF")

        assert approved.ok is False
        assert approved.error == "invalid_approval_token"

    def test_expiry_still_refuses(self, audit_log, inventory, monkeypatch):
        action_id, code = _stage("voice")
        monkeypatch.setattr(pc_control.time, "time", lambda: 1e12)

        approved = pc_control.approve_local_action(action_id, code)

        assert approved.ok is False
        assert inventory.launched == []

    def test_an_emergency_stop_still_cancels(self, audit_log, inventory):
        action_id, code = _stage("voice")
        pc_control.emergency_stop()

        assert pc_control.approve_local_action(action_id, code).ok is False
        assert inventory.launched == []

    def test_origin_does_not_change_the_tier(self, audit_log):
        tiers = {
            pc_control.classify_risk(
                LocalActionRequest(
                    action_type="open_app", target="terminal", origin=origin
                )
            )
            for origin in ACTION_ORIGINS
        }

        assert tiers == {"MEDIUM"}


# ---------------------------------------------------------------------------
# Direct path, and the shape of the change
# ---------------------------------------------------------------------------


class TestAnActualLegacyDatabase:
    """The migration path, exercised against a database that really lacks the
    columns.

    Every other test here starts from a fresh database, where ``CREATE TABLE``
    already includes ``origin`` -- so deleting the ``ALTER TABLE`` migration
    changed nothing and no test noticed. That is the one place a real upgrade
    differs from a new install, and it is the only place the migration runs.
    """

    @staticmethod
    def _legacy_database(path):
        """A table shaped the way it was before provenance and identity
        binding were stored."""
        import sqlite3

        conn = sqlite3.connect(path)
        conn.execute(
            """
            CREATE TABLE pc_control_approvals (
                action_id TEXT PRIMARY KEY,
                action_type TEXT NOT NULL,
                target TEXT NOT NULL,
                args_json TEXT NOT NULL,
                risk_level TEXT NOT NULL,
                created_at REAL NOT NULL,
                expires_at REAL NOT NULL,
                status TEXT NOT NULL,
                approval_required INTEGER NOT NULL,
                decision TEXT NOT NULL,
                decision_timestamp REAL,
                approval_token TEXT NOT NULL DEFAULT ''
            )
            """
        )
        conn.execute(
            "INSERT INTO pc_control_approvals VALUES "
            "('legacy1', 'open_app', 'bash', '{}', 'LOW', 0, 1e12, 'pending', "
            "1, 'pending', NULL, 'ABCD1234')"
        )
        conn.commit()
        conn.close()

    def test_the_migration_adds_the_missing_columns(self, tmp_path, monkeypatch):
        database = tmp_path / "legacy.db"
        self._legacy_database(database)
        monkeypatch.setenv("GRANDPA_PC_CONTROL_DB", str(database))

        with pc_control._connect_approval_db() as conn:
            columns = {
                str(row["name"])
                for row in conn.execute("PRAGMA table_info(pc_control_approvals)")
            }

        assert "origin" in columns
        assert "action_digest" in columns

    def test_a_row_written_before_the_column_reads_as_direct(
        self, tmp_path, monkeypatch
    ):
        database = tmp_path / "legacy.db"
        self._legacy_database(database)
        monkeypatch.setenv("GRANDPA_PC_CONTROL_DB", str(database))

        record = pc_control._load_pending_record("legacy1")

        assert record is not None
        assert record.request.origin == "direct"

    def test_such_a_row_still_cannot_be_approved(self, tmp_path, monkeypatch):
        """It carries no identity binding either, so it is refused rather than
        rebound -- unchanged from the previous slice."""
        database = tmp_path / "legacy.db"
        self._legacy_database(database)
        monkeypatch.setenv("GRANDPA_PC_CONTROL_DB", str(database))
        monkeypatch.setenv("GRANDPA_LOCAL_ACTION_LOG", str(tmp_path / "a.jsonl"))
        monkeypatch.setattr(
            pc_control, "get_audit_log_path", lambda: tmp_path / "audit.log"
        )

        approved = pc_control.approve_local_action("legacy1", "ABCD1234")

        assert approved.ok is False
        assert approved.error == "approval_binding_missing"

    def test_the_migration_runs_only_once(self, tmp_path, monkeypatch):
        database = tmp_path / "legacy.db"
        self._legacy_database(database)
        monkeypatch.setenv("GRANDPA_PC_CONTROL_DB", str(database))

        for _ in range(3):
            with pc_control._connect_approval_db() as conn:
                columns = [
                    str(row["name"])
                    for row in conn.execute("PRAGMA table_info(pc_control_approvals)")
                ]

        assert columns.count("origin") == 1
        assert columns.count("action_digest") == 1


class TestDirectPathUnchanged:
    @pytest.mark.parametrize("origin", ACTION_ORIGINS)
    def test_an_unapproved_launch_still_audits_its_origin(
        self, origin, audit_log, inventory
    ):
        pc_control.run_local_action(
            {"action_type": "open_app", "target": "bash", "origin": origin}
        )

        records = _audit_records(audit_log)

        assert records
        assert records[-1]["origin"] == origin

    def test_the_migration_is_idempotent(self, audit_log, inventory):
        for _ in range(3):
            with pc_control._connect_approval_db() as conn:
                columns = [
                    str(row["name"])
                    for row in conn.execute("PRAGMA table_info(pc_control_approvals)")
                ]

        assert columns.count("origin") == 1

    def test_the_frozen_request_contract_is_unchanged(self):
        from dataclasses import fields

        assert [f.name for f in fields(LocalActionRequest)] == [
            "action_type",
            "target",
            "args",
            "require_approval",
            "dry_run",
            "origin",
        ]
