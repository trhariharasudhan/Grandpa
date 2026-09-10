"""A rejection that lost the race must not say it won.

``_mark_pending_decision`` claims a pending row with a compare-and-swap and
reports whether the claim won. The approve path now checks that answer, so only
one caller executes. The reject path did not: it claimed, discarded the result,
and returned "Rejected the pending local action." unconditionally.

So when a reject and an approve met -- two surfaces, two processes, one shared
database -- the approve could win the row and run the action while the person
who pressed reject was told it had been stopped.

Nothing unauthorised runs here. The approve carried a valid out-of-band code
and a matching identity binding, so what executed was genuinely approved. What
failed is the report: a safety decision was acknowledged that never took
effect, which is worse than an error, because an error would have prompted the
user to look.

The fix is the one the approve path already has -- read the answer the database
already gave -- and the loser returns the response this module already had for
an action that is no longer pending.

Separate processes are modelled by replacing the in-process lock, which is
exactly what two processes do not share. Nothing launches: the executor is a
recorder.
"""

from __future__ import annotations

import threading

import pytest

from grandpa import pc_control


class NoSharedLock:
    """Stands in for "these callers are in different processes"."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("GRANDPA_LOCAL_ACTION_LOG", str(tmp_path / "actions.jsonl"))
    monkeypatch.setenv("GRANDPA_PC_CONTROL_DB", str(tmp_path / "approvals.db"))
    monkeypatch.setattr(
        pc_control, "get_audit_log_path", lambda: tmp_path / "audit.log"
    )
    pc_control.reset_emergency_stop()
    yield
    pc_control.reset_emergency_stop()


@pytest.fixture
def executions(monkeypatch):
    """Records what would have run. Never touches a device."""
    seen: list[str] = []

    def recorder(request, risk, **kwargs):
        seen.append(request.target)
        return pc_control.LocalActionResponse(
            ok=True,
            action_id=None,
            status="completed",
            message="recorded",
            approval_required=False,
            risk_level=risk,
            evidence={},
        )

    monkeypatch.setattr(pc_control, "_execute", recorder)
    return seen


def _stage(target: str = "doomed.txt") -> tuple[str, str]:
    response = pc_control.run_local_action(
        {"action_type": "file_delete", "target": target, "require_approval": True}
    )
    assert response.status == "approval_required"
    action_id = response.action_id or ""
    record = pc_control._load_pending_record(action_id)
    assert record is not None
    return action_id, record.approval_token


def _status_of(action_id: str) -> str:
    records = [
        record
        for record in pc_control.list_approval_records()
        if record["action_id"] == action_id
    ]
    assert records, f"no record for {action_id}"
    return str(records[0]["status"])


DECIDED = {"already_approved", "already_completed", "already_rejected"}


# ---------------------------------------------------------------------------
# 1, 2 -- the ordinary paths, unchanged
# ---------------------------------------------------------------------------


class TestOrdinaryRejection:
    def test_rejecting_a_pending_action_succeeds(self, isolated, executions):
        action_id, _code = _stage()

        rejected = pc_control.reject_local_action(action_id)

        assert rejected.ok is True
        assert rejected.status == "rejected"
        assert _status_of(action_id) == "rejected"
        assert executions == []

    def test_a_rejected_action_cannot_then_be_approved(self, isolated, executions):
        action_id, code = _stage()
        pc_control.reject_local_action(action_id)

        approved = pc_control.approve_local_action(action_id, code)

        assert approved.ok is False
        assert approved.error == "already_rejected"
        assert executions == []

    def test_rejecting_twice_reports_the_existing_decision(self, isolated, executions):
        action_id, _code = _stage()
        pc_control.reject_local_action(action_id)

        second = pc_control.reject_local_action(action_id)

        assert second.ok is False
        assert second.error == "already_rejected"

    def test_rejecting_a_completed_action_is_refused(self, isolated, executions):
        action_id, code = _stage()
        pc_control.approve_local_action(action_id, code)

        rejected = pc_control.reject_local_action(action_id)

        assert rejected.ok is False
        assert rejected.error == "already_completed"

    def test_rejecting_an_unknown_action_is_refused(self, isolated, executions):
        rejected = pc_control.reject_local_action("no-such-action")

        assert rejected.ok is False
        assert rejected.error == "missing_pending_action"


# ---------------------------------------------------------------------------
# 3 -- the losing claim
# ---------------------------------------------------------------------------


class TestRejectionThatLosesTheClaim:
    """The row is still pending when reject reads it, and claimed by someone
    else before reject writes -- exactly what a second process does.

    The claim is not stubbed: another caller really takes the row, so the
    compare-and-swap genuinely loses.
    """

    @staticmethod
    def _claim_between_read_and_write(monkeypatch):
        original_load = pc_control._load_pending_record

        def load_then_someone_else_claims(action_id: str):
            record = original_load(action_id)
            if record is not None:
                pc_control._mark_pending_decision(
                    action_id, status="approved", decision="approved"
                )
            return record

        monkeypatch.setattr(
            pc_control, "_load_pending_record", load_then_someone_else_claims
        )

    def test_it_does_not_report_a_successful_rejection(
        self, isolated, executions, monkeypatch
    ):
        """The defect: this said ok=True while the row was not rejected."""
        action_id, _code = _stage()
        self._claim_between_read_and_write(monkeypatch)

        rejected = pc_control.reject_local_action(action_id)

        assert rejected.ok is False
        assert rejected.status != "rejected"

    def test_it_uses_the_existing_decided_vocabulary(
        self, isolated, executions, monkeypatch
    ):
        action_id, _code = _stage()
        self._claim_between_read_and_write(monkeypatch)

        rejected = pc_control.reject_local_action(action_id)

        assert rejected.error in DECIDED
        assert rejected.action_id == action_id

    def test_the_winning_state_is_left_intact(self, isolated, executions, monkeypatch):
        """A losing rejection must not overwrite the decision that won."""
        action_id, _code = _stage()
        self._claim_between_read_and_write(monkeypatch)

        pc_control.reject_local_action(action_id)

        assert _status_of(action_id) == "approved"

    def test_nothing_executes_on_the_losing_path(
        self, isolated, executions, monkeypatch
    ):
        action_id, _code = _stage()
        self._claim_between_read_and_write(monkeypatch)

        pc_control.reject_local_action(action_id)

        assert executions == []


# ---------------------------------------------------------------------------
# 4, 5, 6 -- approve and reject racing
# ---------------------------------------------------------------------------


class TestApproveAndRejectRace:
    @staticmethod
    def _race(action_id: str, token: str, monkeypatch):
        """Both callers read the pending row before either writes, then race
        the database for the claim."""
        barrier = threading.Barrier(2, timeout=10)
        original_load = pc_control._load_pending_record

        def load_then_wait(target_id: str):
            record = original_load(target_id)
            try:
                barrier.wait()
            except threading.BrokenBarrierError:
                pass
            return record

        monkeypatch.setattr(pc_control, "_STORE_LOCK", NoSharedLock())
        monkeypatch.setattr(pc_control, "_load_pending_record", load_then_wait)

        outcomes: dict[str, pc_control.LocalActionResponse] = {}
        guard = threading.Lock()

        def approve() -> None:
            response = pc_control.approve_local_action(action_id, token)
            with guard:
                outcomes["approve"] = response

        def reject() -> None:
            response = pc_control.reject_local_action(action_id)
            with guard:
                outcomes["reject"] = response

        threads = [threading.Thread(target=approve), threading.Thread(target=reject)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)
        return outcomes

    def test_exactly_one_caller_wins(self, isolated, executions, monkeypatch):
        action_id, code = _stage()

        outcomes = self._race(action_id, code, monkeypatch)

        assert len(outcomes) == 2
        assert [response.ok for response in outcomes.values()].count(True) == 1

    def test_the_loser_never_claims_success(self, isolated, executions, monkeypatch):
        """Whichever loses -- and either can -- it must not report that it
        did what it did not do."""
        action_id, code = _stage()

        outcomes = self._race(action_id, code, monkeypatch)

        loser = next(response for response in outcomes.values() if not response.ok)
        assert loser.error in DECIDED
        assert loser.status != "rejected"

    def test_the_outcome_matches_the_record(self, isolated, executions, monkeypatch):
        """The report and the stored decision agree, whichever way it went."""
        action_id, code = _stage()

        outcomes = self._race(action_id, code, monkeypatch)

        status = _status_of(action_id)
        if outcomes["reject"].ok:
            assert status == "rejected"
            assert executions == []
        else:
            assert status == "completed"
            assert executions == ["doomed.txt"]

    def test_the_action_never_runs_twice(self, isolated, executions, monkeypatch):
        action_id, code = _stage()

        self._race(action_id, code, monkeypatch)

        assert len(executions) <= 1

    def test_a_reject_that_wins_keeps_the_action_dead(
        self, isolated, executions, monkeypatch
    ):
        """The reject-wins branch, forced: a later approval cannot revive it."""
        action_id, code = _stage()
        assert pc_control.reject_local_action(action_id).ok is True

        approved = pc_control.approve_local_action(action_id, code)

        assert approved.ok is False
        assert executions == []
        assert _status_of(action_id) == "rejected"


# ---------------------------------------------------------------------------
# Scope
# ---------------------------------------------------------------------------


class TestScope:
    def test_the_claim_still_reports_who_won(self, isolated):
        """``_mark_pending_decision`` is unchanged and already correct."""
        action_id, _code = _stage()

        first = pc_control._mark_pending_decision(
            action_id, status="rejected", decision="rejected"
        )
        second = pc_control._mark_pending_decision(
            action_id, status="rejected", decision="rejected"
        )

        assert first is True
        assert second is False

    def test_no_new_lock_was_introduced(self):
        assert isinstance(pc_control._STORE_LOCK, type(threading.RLock()))

    def test_the_approve_path_is_unchanged(self, isolated, executions):
        action_id, code = _stage()

        approved = pc_control.approve_local_action(action_id, code)

        assert approved.ok is True
        assert executions == ["doomed.txt"]

    def test_the_frozen_request_contract_is_unchanged(self):
        from dataclasses import fields

        assert [f.name for f in fields(pc_control.LocalActionRequest)] == [
            "action_type",
            "target",
            "args",
            "require_approval",
            "dry_run",
            "origin",
        ]
