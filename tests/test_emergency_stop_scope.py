"""An emergency stop must stop everything that acts.

The three gates in ``pc_control`` were written as
``if _EMERGENCY_STOP_ACTIVE and risk in {"MEDIUM", "HIGH"}``, so the 36 LOW-risk
actions carried on running. That included the ones a person would most expect a
stop to catch: ``open_app``, ``open_folder``, ``file_create``, ``system_lock``,
``browser_open``, ``browser_new_tab``, ``browser_search`` and nine other
``browser_*`` actions.

Risk tiers rank *consequence*, not whether something is an action. Someone who
hits stop is not asking for the dangerous half to pause; they are asking for
the assistant to stop touching the machine. A tier filter answers a question
nobody asked.

Dry run keeps working, and deliberately so: it is checked before this gate,
actuates nothing, and is how a user finds out what *would* happen while the
stop is in force. Refusing previews would remove the safest thing available
during an incident.

Nothing here executes: ``_execute`` is replaced with a spy that fails the test
if it is ever reached while a stop is active.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from grandpa import pc_control

LOW_ACTIONS = (
    "open_app",
    "open_folder",
    "file_create",
    "system_lock",
    "browser_open",
    "browser_new_tab",
    "browser_search",
    "volume_up",
    "clipboard_read",
)
MEDIUM_ACTIONS = ("file_move", "file_copy", "focus_window", "browser_reload")
HIGH_ACTIONS = ("file_delete", "system_shutdown", "empty_recycle_bin")
BLOCKED_ACTIONS = ("shell_run", "script_run", "file_permanent_delete")


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "GRANDPA_LOCAL_ACTION_LOG", str(tmp_path / "local_actions.jsonl")
    )
    monkeypatch.setenv(
        "GRANDPA_PC_CONTROL_DB", str(tmp_path / "pc_control_approvals.db")
    )
    monkeypatch.setattr(
        pc_control, "get_audit_log_path", lambda: tmp_path / "audit.log"
    )
    pc_control.reset_emergency_stop()
    yield
    pc_control.reset_emergency_stop()


@pytest.fixture
def stopped(monkeypatch):
    """An active emergency stop, with execution made impossible."""

    def explode(request, risk):
        raise AssertionError(
            f"{request.action_type} ({risk}) executed during an emergency stop"
        )

    monkeypatch.setattr(pc_control, "_execute", explode)
    monkeypatch.setattr(pc_control, "_EMERGENCY_STOP_ACTIVE", True)


@pytest.fixture
def running(monkeypatch):
    """No emergency stop; execution recorded rather than performed."""
    seen: list[Any] = []

    def spy(request, risk):
        seen.append(request)
        return pc_control.LocalActionResponse(
            ok=True,
            action_id=None,
            status="completed",
            message="ok",
            approval_required=False,
            risk_level=risk,
            evidence={},
        )

    monkeypatch.setattr(pc_control, "_execute", spy)
    return seen


def _run(action_type: str, **extra):
    return pc_control.run_local_action(
        {"action_type": action_type, "target": "x", **extra}
    )


# ---------------------------------------------------------------------------
# Gate 1: the ordinary request path
# ---------------------------------------------------------------------------


class TestNothingActsDuringAStop:
    @pytest.mark.parametrize("action", LOW_ACTIONS)
    def test_a_low_risk_action_is_stopped(self, action, stopped):
        """The gap: these ran straight through a stop."""
        response = _run(action)

        assert response.ok is False
        assert response.status == "blocked"
        assert response.error == "emergency_stop_active"

    @pytest.mark.parametrize("action", MEDIUM_ACTIONS)
    def test_a_medium_risk_action_is_still_stopped(self, action, stopped):
        assert _run(action).error == "emergency_stop_active"

    @pytest.mark.parametrize("action", HIGH_ACTIONS)
    def test_a_high_risk_action_is_stopped_before_approval(self, action, stopped):
        """HIGH stages for approval first, so a stop must catch it there."""
        response = _run(action)

        assert response.ok is False
        assert response.status in {"blocked", "approval_required"}

    @pytest.mark.parametrize("action", BLOCKED_ACTIONS)
    def test_a_blocked_action_stays_blocked(self, action, stopped):
        """Blocked outranks the stop; the reason must stay the policy one."""
        response = _run(action)

        assert response.status == "blocked"
        assert response.error != "emergency_stop_active"

    def test_the_message_no_longer_promises_only_medium_and_high(self, stopped):
        response = _run("open_app")

        assert "medium and high" not in response.message.lower()
        assert "emergency stop" in response.message.lower()


# ---------------------------------------------------------------------------
# Dry run survives
# ---------------------------------------------------------------------------


class TestDryRunStillWorks:
    @pytest.mark.parametrize("action", LOW_ACTIONS + MEDIUM_ACTIONS)
    def test_a_preview_is_still_available(self, action, stopped):
        """Checked before the gate, actuates nothing, and is the safest thing
        a user can do while a stop is in force."""
        response = _run(action, dry_run=True)

        assert response.status == "dry_run"
        assert response.ok is True

    def test_a_preview_does_not_execute(self, stopped):
        """The ``stopped`` fixture fails the test if ``_execute`` is reached."""
        assert _run("file_move", dry_run=True).status == "dry_run"

    def test_dry_run_precedence_is_unchanged_without_a_stop(self, running):
        assert _run("open_app", dry_run=True).status == "dry_run"
        assert running == []


# ---------------------------------------------------------------------------
# Gates 2 and 3: the approval path
# ---------------------------------------------------------------------------


class TestPendingActionsAreStopped:
    """The approval path, which has two defences rather than one.

    ``emergency_stop()`` cancels every pending action as it activates, so an
    approval arriving afterwards is refused as ``already_cancelled`` and never
    reaches the gates below. The gates are the second line: they cover a raised
    stop flag whose sweep did not run, or did not cover this record.

    Approval also needs the out-of-band code, and that check runs before either
    defence -- so a test that omits the code proves nothing about a stop. These
    supply the real code, the way the operator console does.
    """

    def _stage(self, action_type: str) -> tuple[str, str]:
        response = pc_control.run_local_action(
            {"action_type": action_type, "target": "x", "require_approval": True}
        )
        assert response.status == "approval_required"
        action_id = response.action_id or ""
        record = pc_control._load_pending_record(action_id)
        assert record is not None and record.approval_token
        return action_id, record.approval_token

    @staticmethod
    def _status_of(action_id: str) -> str:
        """``_load_pending_record`` only finds rows still marked pending, so a
        cancelled one has to be read through the full listing."""
        for record in pc_control.list_approval_records():
            if record["action_id"] == action_id:
                return str(record["status"])
        raise AssertionError(f"no approval record for {action_id}")

    @staticmethod
    def _forbid_execution(monkeypatch):
        def explode(request, risk):
            raise AssertionError("executed during an emergency stop")

        monkeypatch.setattr(pc_control, "_execute", explode)

    # -- first defence: the sweep -------------------------------------------

    @pytest.mark.parametrize("action", ["open_app", "file_delete"])
    def test_a_pending_action_is_cancelled_by_the_stop_itself(
        self, action, monkeypatch
    ):
        action_id, code = self._stage(action)
        self._forbid_execution(monkeypatch)

        pc_control.emergency_stop()

        assert self._status_of(action_id) == "cancelled"

    @pytest.mark.parametrize("action", ["open_app", "file_delete"])
    def test_approving_a_cancelled_action_does_not_run_it(self, action, monkeypatch):
        action_id, code = self._stage(action)
        self._forbid_execution(monkeypatch)
        pc_control.emergency_stop()

        approved = pc_control.approve_local_action(action_id, code)

        assert approved.ok is False
        assert approved.error == "already_cancelled"

    # -- second defence: the gates ------------------------------------------

    @pytest.mark.parametrize("action", ["open_app", "file_move", "file_delete"])
    def test_the_gate_stops_a_pending_action_the_sweep_missed(
        self, action, monkeypatch
    ):
        """The stop flag raised without the sweep -- ``open_app`` is the gap:
        being LOW, it used to be approved and run straight through."""
        action_id, code = self._stage(action)
        self._forbid_execution(monkeypatch)
        monkeypatch.setattr(pc_control, "_EMERGENCY_STOP_ACTIVE", True)

        approved = pc_control.approve_local_action(action_id, code)

        assert approved.ok is False
        assert approved.error == "emergency_stop_active"

    def test_the_gate_cancels_rather_than_leaving_it_pending(self, monkeypatch):
        action_id, code = self._stage("open_app")
        self._forbid_execution(monkeypatch)
        monkeypatch.setattr(pc_control, "_EMERGENCY_STOP_ACTIVE", True)

        pc_control.approve_local_action(action_id, code)

        assert self._status_of(action_id) == "cancelled"

    def test_a_stop_landing_after_approval_is_still_caught(self, monkeypatch):
        """The last gate is a re-check after ``_STORE_LOCK`` is released.

        The gate above runs while holding the store lock; this one runs just
        after it is dropped, so a stop raised by another thread in that window
        -- approved, not yet executed -- still lands before the actuator. The
        stop is triggered from inside ``_mark_pending_decision`` to put it at
        exactly that moment.
        """
        action_id, code = self._stage("open_app")
        self._forbid_execution(monkeypatch)
        original = pc_control._mark_pending_decision

        def mark_then_stop(*args, **kwargs):
            result = original(*args, **kwargs)
            monkeypatch.setattr(pc_control, "_EMERGENCY_STOP_ACTIVE", True)
            return result

        monkeypatch.setattr(pc_control, "_mark_pending_decision", mark_then_stop)

        approved = pc_control.approve_local_action(action_id, code)

        assert approved.ok is False
        assert approved.error == "emergency_stop_active"

    def test_an_expired_pending_action_still_reports_expiry(self, monkeypatch):
        """Expiry is checked before the gate and keeps its own reason."""
        action_id, code = self._stage("open_app")
        self._forbid_execution(monkeypatch)
        monkeypatch.setattr(pc_control.time, "time", lambda: 1e12)
        monkeypatch.setattr(pc_control, "_EMERGENCY_STOP_ACTIVE", True)

        approved = pc_control.approve_local_action(action_id, code)

        assert approved.error in {"already_expired", "approval_expired"}
        assert approved.error != "emergency_stop_active"

    def test_staging_is_still_allowed_during_a_stop(self, stopped):
        """Deliberately unchanged: the approval gate is checked before the stop
        gate, so a request that asks for approval is staged rather than
        refused.

        Staging touches nothing -- it writes a pending row and returns a code.
        The action cannot run while the stop holds, because approving it meets
        the gate above. Reordering the two would refuse the staging outright,
        which is a bigger change than this slice, and no safer.
        """
        response = pc_control.run_local_action(
            {"action_type": "file_delete", "target": "x", "require_approval": True}
        )

        assert response.status == "approval_required"

        record = pc_control._load_pending_record(response.action_id or "")
        assert record is not None
        approved = pc_control.approve_local_action(
            response.action_id or "", record.approval_token
        )
        assert approved.ok is False
        assert approved.error == "emergency_stop_active"


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------


class TestReset:
    def test_a_low_risk_action_runs_again_after_reset(self, running, monkeypatch):
        monkeypatch.setattr(pc_control, "_EMERGENCY_STOP_ACTIVE", True)
        assert _run("open_app").error == "emergency_stop_active"

        pc_control.reset_emergency_stop()

        assert _run("open_app").status == "completed"
        assert len(running) == 1

    def test_reset_clears_the_stop(self):
        """``reset_emergency_stop`` returns None; the effect is the contract."""
        pc_control.emergency_stop()
        assert pc_control._EMERGENCY_STOP_ACTIVE is True

        pc_control.reset_emergency_stop()

        assert pc_control._EMERGENCY_STOP_ACTIVE is False


# ---------------------------------------------------------------------------
# The audit trail
# ---------------------------------------------------------------------------


class TestAudit:
    def test_a_stopped_low_risk_action_is_recorded(self, stopped, tmp_path):
        _run("open_app", origin="voice")

        record = json.loads(
            [
                line
                for line in (tmp_path / "audit.log")
                .read_text(encoding="utf-8")
                .splitlines()
                if line
            ][-1]
        )

        assert record["action_type"] == "open_app"
        assert record["status"] == "blocked"
        assert record["approval_status"] == "blocked"
        assert record["origin"] == "voice"


# ---------------------------------------------------------------------------
# Scope
# ---------------------------------------------------------------------------


class TestScope:
    def test_no_risk_table_changed(self):
        assert "open_app" in pc_control.LOW_RISK_ACTIONS
        assert "file_delete" in pc_control.HIGH_RISK_ACTIONS
        assert "shell_run" in pc_control.BLOCKED_ACTIONS

    def test_risk_is_still_reported_on_the_stopped_response(self, stopped):
        assert _run("open_app").risk_level == "LOW"
        assert _run("file_move").risk_level == "MEDIUM"

    @pytest.mark.parametrize("origin", ["voice", "agent", "direct"])
    def test_the_stop_does_not_depend_on_who_asked(self, origin, stopped):
        assert _run("open_app", origin=origin).error == "emergency_stop_active"

    def test_ordinary_operation_is_untouched(self, running):
        for action in LOW_ACTIONS[:3]:
            assert _run(action).status == "completed"

        assert len(running) == 3
