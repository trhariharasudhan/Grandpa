"""One approval, one execution -- even from two processes.

``_mark_pending_decision`` claims a pending action with a compare-and-swap:

    UPDATE ... SET status='approved' WHERE action_id=? AND status='pending'

and returns whether that claim won. Exactly one caller can win, because SQLite
settles it. The caller discarded that answer.

Inside one process ``_STORE_LOCK`` hid the consequence: the second approver
serialised behind the first and found the row already decided. But the lock is
a ``threading.RLock``, and the approval database is shared by separate
processes -- ``server/routes.py``, ``cli/jarvis_cmd.py`` and
``voice/operator.py`` all reach ``approve_local_action``. Two of them could
load the same pending row, both pass the token and the identity binding, both
call the compare-and-swap, and both execute, because nothing read the result.
An approved ``file_delete`` ran twice and both callers reported success.

The fix is to listen to the answer that was already there. The database stays
the arbiter -- it always was -- and the loser returns the response the code
already had for an action that is no longer pending.

Separate processes are modelled by replacing the in-process lock, which is
precisely the thing two processes do not share. Nothing launches: the executor
is a recorder.
"""

from __future__ import annotations

import threading

import pytest

from grandpa import pc_control


class NoSharedLock:
    """Stands in for "these callers are in different processes".

    The database is the only thing two processes share, which is exactly the
    condition this file is about.
    """

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


ALREADY_DECIDED = {"already_approved", "already_completed"}


# ---------------------------------------------------------------------------
# A -- the sequential case, unchanged
# ---------------------------------------------------------------------------


class TestSequentialApproval:
    def test_the_first_approval_executes(self, isolated, executions):
        action_id, code = _stage()

        first = pc_control.approve_local_action(action_id, code)

        assert first.ok is True
        assert executions == ["doomed.txt"]

    def test_the_second_approval_does_not(self, isolated, executions):
        action_id, code = _stage()
        pc_control.approve_local_action(action_id, code)

        second = pc_control.approve_local_action(action_id, code)

        assert second.ok is False
        assert second.error == "already_completed"
        assert executions == ["doomed.txt"]

    def test_a_third_attempt_is_also_refused(self, isolated, executions):
        action_id, code = _stage()
        pc_control.approve_local_action(action_id, code)
        pc_control.approve_local_action(action_id, code)

        third = pc_control.approve_local_action(action_id, code)

        assert third.ok is False
        assert len(executions) == 1


# ---------------------------------------------------------------------------
# B -- two callers that do not share a process lock
# ---------------------------------------------------------------------------


class TestConcurrentApproval:
    @staticmethod
    def _approve_together(action_id: str, token: str, monkeypatch):
        """Both callers read the pending row before either writes -- the window
        a cross-process race actually opens -- then race the database."""
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

        results: list[pc_control.LocalActionResponse] = []
        lock = threading.Lock()

        def approve() -> None:
            response = pc_control.approve_local_action(action_id, token)
            with lock:
                results.append(response)

        threads = [threading.Thread(target=approve) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)
        return results

    def test_only_one_caller_executes(self, isolated, executions, monkeypatch):
        """The regression: this ran the delete twice."""
        action_id, code = _stage()

        self._approve_together(action_id, code, monkeypatch)

        assert executions == ["doomed.txt"], (
            f"one approved action executed {len(executions)} times"
        )

    def test_only_one_caller_reports_success(self, isolated, executions, monkeypatch):
        action_id, code = _stage()

        results = self._approve_together(action_id, code, monkeypatch)

        assert len(results) == 2
        assert [r.ok for r in results].count(True) == 1

    def test_the_loser_says_the_action_was_already_decided(
        self, isolated, executions, monkeypatch
    ):
        """The existing vocabulary for an action that is no longer pending;
        which of the two it reports depends on how far the winner has got."""
        action_id, code = _stage()

        results = self._approve_together(action_id, code, monkeypatch)

        loser = next(r for r in results if not r.ok)
        assert loser.error in ALREADY_DECIDED
        assert loser.status in {"failed", "expired"}

    def test_the_loser_does_not_claim_to_have_run(
        self, isolated, executions, monkeypatch
    ):
        action_id, code = _stage()

        results = self._approve_together(action_id, code, monkeypatch)

        loser = next(r for r in results if not r.ok)
        assert loser.status != "completed"

    def test_the_record_ends_in_one_settled_state(
        self, isolated, executions, monkeypatch
    ):
        action_id, code = _stage()
        self._approve_together(action_id, code, monkeypatch)

        records = [
            r for r in pc_control.list_approval_records() if r["action_id"] == action_id
        ]

        assert len(records) == 1
        assert records[0]["status"] == "completed"

    @pytest.mark.parametrize("action_type", ["file_delete", "open_app", "system_lock"])
    def test_it_holds_whatever_the_action_is(
        self, action_type, isolated, executions, monkeypatch
    ):
        response = pc_control.run_local_action(
            {"action_type": action_type, "target": "x", "require_approval": True}
        )
        assert response.status == "approval_required"
        action_id = response.action_id or ""
        record = pc_control._load_pending_record(action_id)
        assert record is not None

        self._approve_together(action_id, record.approval_token, monkeypatch)

        assert len(executions) == 1


# ---------------------------------------------------------------------------
# C -- the claim is what decides
# ---------------------------------------------------------------------------


class TestTheClaimIsLoadBearing:
    def test_the_compare_and_swap_reports_who_won(self, isolated, executions):
        """``_mark_pending_decision`` is unchanged and already correct: the
        second claim on the same row loses."""
        action_id, _code = _stage()

        first = pc_control._mark_pending_decision(
            action_id, status="approved", decision="approved"
        )
        second = pc_control._mark_pending_decision(
            action_id, status="approved", decision="approved"
        )

        assert first is True
        assert second is False

    def test_losing_the_claim_prevents_execution(self, isolated, executions):
        """Claim the row first, as a winner in another process would, then
        approve. The approve path must find it gone and run nothing."""
        action_id, code = _stage()
        assert pc_control._mark_pending_decision(
            action_id, status="approved", decision="approved"
        )

        response = pc_control.approve_local_action(action_id, code)

        assert response.ok is False
        assert executions == []

    def test_the_claim_happens_before_execution(self, isolated, monkeypatch):
        """Ordering: the row must be claimed before anything runs, or the
        claim cannot prevent anything."""
        order: list[str] = []
        original_mark = pc_control._mark_pending_decision

        def spy_mark(action_id, *, status, decision):
            if status == "approved":
                order.append("claim")
            return original_mark(action_id, status=status, decision=decision)

        def spy_execute(request, risk, **kwargs):
            order.append("execute")
            return pc_control.LocalActionResponse(
                ok=True,
                action_id=None,
                status="completed",
                message="recorded",
                approval_required=False,
                risk_level=risk,
                evidence={},
            )

        monkeypatch.setattr(pc_control, "_mark_pending_decision", spy_mark)
        monkeypatch.setattr(pc_control, "_execute", spy_execute)
        action_id, code = _stage()

        pc_control.approve_local_action(action_id, code)

        assert order == ["claim", "execute"]


# ---------------------------------------------------------------------------
# Scope
# ---------------------------------------------------------------------------


class TestScope:
    def test_the_token_is_still_checked_first(self, isolated, executions):
        action_id, _code = _stage()

        response = pc_control.approve_local_action(action_id, "DEADBEEF")

        assert response.error == "invalid_approval_token"
        assert executions == []

    def test_a_wrong_token_does_not_consume_the_action(self, isolated, executions):
        action_id, code = _stage()
        pc_control.approve_local_action(action_id, "DEADBEEF")

        assert pc_control.approve_local_action(action_id, code).ok is True

    def test_the_identity_binding_still_applies(self, isolated, executions):
        action_id, code = _stage()
        with pc_control._connect_approval_db() as conn:
            conn.execute(
                "UPDATE pc_control_approvals SET target = 'other.txt' "
                "WHERE action_id = ?",
                (action_id,),
            )

        response = pc_control.approve_local_action(action_id, code)

        assert response.ok is False
        assert executions == []

    def test_an_emergency_stop_still_cancels(self, isolated, executions):
        action_id, code = _stage()
        pc_control.emergency_stop()

        assert pc_control.approve_local_action(action_id, code).ok is False
        assert executions == []

    def test_rejection_is_unchanged(self, isolated, executions):
        action_id, _code = _stage()

        rejected = pc_control.reject_local_action(action_id)

        assert rejected.ok is True
        assert executions == []

    def test_the_store_lock_is_untouched(self):
        """No new lock, and the existing one keeps its type."""
        assert isinstance(pc_control._STORE_LOCK, type(threading.RLock()))

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
