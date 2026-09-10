"""Exactly one confirmer executes a pending action, however many arrive at once.

4.13D made the *state transition* atomic: ``mark`` claims through a conditional
``UPDATE ... WHERE status = 'pending'`` and only one caller wins. But
``approve_pending_action`` discarded that answer, so every racer walked past the
claim and into ``_execute``. The row moved once; the desktop moved N times.

The gap is narrow and entirely inside ``approve_pending_action``:

    if pending["status"] != "pending": ...   # read
    store.mark(pending["id"], "approved")    # claim -- result ignored
    ...
    executed = _execute(result)              # everyone gets here

``claim_pending`` is the primitive that answers "did I win", and it already
exists. ``mark``'s return cannot: when two callers both ask for ``"approved"``,
the winner and the loser are handed rows that look identical -- same id, same
``status == "approved"``. Ownership needs a boolean, not a row.

This file is deliberately narrow. It says nothing about *who* may approve --
that is the unresolved ``/v1/voice/confirm`` question -- only that whoever does,
does it once.
"""

from __future__ import annotations

import os
import threading
import webbrowser
from typing import Any

import pytest

from grandpa.local_action_approvals import LocalActionApprovalStore

STAGING = {
    "source_text": "open https://example.com",
    "kind": "url",
    "target": "https://example.com",
    "message": "Confirmation required.",
    "tts_text": "Please confirm.",
}


@pytest.fixture
def store(tmp_path, monkeypatch):
    """An isolated store, shared with ``local_actions``.

    The real ``~/.grandpa`` database is never constructed by this file.
    """
    import grandpa.local_actions as local_actions

    isolated = LocalActionApprovalStore(tmp_path / "approvals.db")
    monkeypatch.setattr(local_actions, "LocalActionApprovalStore", lambda: isolated)
    return isolated


@pytest.fixture
def actuated(monkeypatch):
    """Count real actuator invocations, thread-safely."""
    seen: list[Any] = []
    lock = threading.Lock()

    def recorder(*args, **kwargs):
        with lock:
            seen.append(args[:1])
        return True

    monkeypatch.setattr(webbrowser, "open", recorder)
    monkeypatch.setattr(webbrowser, "open_new_tab", recorder)
    if hasattr(os, "startfile"):
        monkeypatch.setattr(os, "startfile", recorder)
    return seen


def _stage(store, **overrides):
    payload = dict(STAGING)
    payload.update(overrides)
    return store.create_pending(**payload)


def _approve(action_id):
    from grandpa.local_actions import approve_pending_action

    return approve_pending_action(action_id)


def _race(action_id: str, workers: int = 8):
    """Fire *workers* concurrent approvals released by a barrier."""
    results: list[Any] = []
    lock = threading.Lock()
    barrier = threading.Barrier(workers)

    def attempt() -> None:
        barrier.wait()
        outcome = _approve(action_id)
        with lock:
            results.append(outcome)

    threads = [threading.Thread(target=attempt) for _ in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return results


# ---------------------------------------------------------------------------
# The race
# ---------------------------------------------------------------------------


class TestConcurrentApprovalExecutesOnce:
    def test_only_one_confirmer_executes(self, store, actuated) -> None:
        """The property this slice exists for."""
        pending = _stage(store)

        _race(pending["id"])

        assert len(actuated) == 1

    def test_only_one_confirmer_reports_success(self, store, actuated) -> None:
        pending = _stage(store)

        results = _race(pending["id"])

        handled = [r for r in results if r.status == "handled"]
        assert len(handled) == 1

    def test_every_loser_reports_no_longer_available(self, store, actuated) -> None:
        """Losers get the existing refusal, not a new error shape."""
        pending = _stage(store)

        results = _race(pending["id"])

        losers = [r for r in results if r.status != "handled"]
        assert len(losers) == 7
        for loser in losers:
            assert loser.status == "unsupported"
            assert loser.permission == "unsupported"
            assert "no longer available" in loser.message

    def test_the_row_ends_approved(self, store, actuated) -> None:
        pending = _stage(store)

        _race(pending["id"])

        assert store.get_pending(pending["id"])["status"] == "approved"

    def test_a_larger_race_still_executes_once(self, store, actuated) -> None:
        pending = _stage(store)

        _race(pending["id"], workers=16)

        assert len(actuated) == 1
        assert store.get_pending(pending["id"])["status"] == "approved"

    def test_two_distinct_actions_each_execute_once(self, store, actuated) -> None:
        """The claim is per action, not a global lock."""
        first = _stage(store, source_text="first")
        second = _stage(store, source_text="second", target="https://example.org")

        _race(first["id"], workers=4)
        _race(second["id"], workers=4)

        assert len(actuated) == 2

    def test_the_audit_records_one_approval(self, store, actuated) -> None:
        """A loser must not audit an approval it did not make."""
        pending = _stage(store)

        _race(pending["id"])

        approvals = [
            row
            for row in store.list_audit()
            if row.get("action_id") == pending["id"]
            and row.get("decision") == "approved"
        ]
        assert len(approvals) == 1


# ---------------------------------------------------------------------------
# Sequential behaviour must be exactly as before
# ---------------------------------------------------------------------------


class TestTheLostClaimBranchDeterministically:
    """The narrow window, exercised without relying on thread timing.

    A racer that loses usually refuses at the earlier status read -- by then the
    winner has already flipped the row. The claim-loser branch only fires in the
    tight window where a caller passed that read *before* the winner committed,
    which real threads hit rarely and unpredictably.

    That window is real: the 16-worker race failed before this fix. But an
    assertion that depends on hitting it is an assertion that sometimes tests
    nothing, so the branch is driven directly instead.
    """

    @pytest.fixture
    def losing_claim(self, store, monkeypatch):
        """Make the claim fail while the row still reads ``pending``."""
        monkeypatch.setattr(store, "claim_pending", lambda action_id, decision: False)
        return store

    def test_a_lost_claim_does_not_execute(self, losing_claim, actuated) -> None:
        pending = _stage(losing_claim)

        _approve(pending["id"])

        assert actuated == []

    def test_a_lost_claim_reports_no_longer_available(
        self, losing_claim, actuated
    ) -> None:
        pending = _stage(losing_claim)

        result = _approve(pending["id"])

        assert result.status == "unsupported"
        assert result.permission == "unsupported"
        assert "no longer available" in result.message

    def test_a_lost_claim_still_carries_the_pending_metadata(
        self, losing_claim, actuated
    ) -> None:
        pending = _stage(losing_claim)

        result = _approve(pending["id"])

        assert result.pending_action is not None
        assert result.pending_action["id"] == pending["id"]

    def test_a_lost_claim_audits_no_approval(self, losing_claim, actuated) -> None:
        pending = _stage(losing_claim)

        _approve(pending["id"])

        approvals = [
            row
            for row in losing_claim.list_audit()
            if row.get("action_id") == pending["id"]
            and row.get("decision") == "approved"
        ]
        assert approvals == []


class TestSequentialBehaviourIsUnchanged:
    def test_the_first_approval_succeeds(self, store, actuated) -> None:
        pending = _stage(store)

        result = _approve(pending["id"])

        assert result.status == "handled"
        assert result.permission == "allowed"
        assert result.kind == "url"
        assert result.target == "https://example.com"
        assert len(actuated) == 1

    def test_the_response_shape_is_preserved(self, store, actuated) -> None:
        pending = _stage(store)

        result = _approve(pending["id"])

        assert result.pending_action is not None
        assert result.pending_action["id"] == pending["id"]
        assert set(result.pending_action) == {
            "id",
            "status",
            "kind",
            "target",
            "source_text",
            "expires_at",
        }

    def test_a_replay_is_refused(self, store, actuated) -> None:
        pending = _stage(store)
        _approve(pending["id"])

        replay = _approve(pending["id"])

        assert replay.status == "unsupported"
        assert "no longer available" in replay.message
        assert len(actuated) == 1

    def test_an_unknown_action_is_unchanged(self, store, actuated) -> None:
        result = _approve("deadbeef" * 4)

        assert result.status == "unsupported"
        assert result.kind == "blocked"
        assert "no pending local action" in result.message
        assert actuated == []

    def test_an_expired_action_is_unchanged(self, store, actuated) -> None:
        pending = _stage(store)
        store.expire_old(now=9_999_999_999.0)

        result = _approve(pending["id"])

        assert result.status == "unsupported"
        assert "no longer available" in result.message
        assert actuated == []

    def test_a_denied_action_cannot_then_be_approved(self, store, actuated) -> None:
        from grandpa.local_actions import deny_pending_action

        pending = _stage(store)
        deny_pending_action(pending["id"])

        result = _approve(pending["id"])

        assert result.status == "unsupported"
        assert actuated == []

    def test_denial_behaviour_is_untouched(self, store, actuated) -> None:
        from grandpa.local_actions import deny_pending_action

        pending = _stage(store)

        denied = deny_pending_action(pending["id"])

        assert store.get_pending(pending["id"])["status"] == "denied"
        assert denied.status != "handled"
        assert actuated == []

    def test_the_latest_pending_path_still_works(self, store, actuated) -> None:
        """The CLI/local-voice "yes" route passes no id at all."""
        from grandpa.local_actions import approve_pending_action

        _stage(store)

        result = approve_pending_action()

        assert result.status == "handled"
        assert len(actuated) == 1


# ---------------------------------------------------------------------------
# The primitive used, and what was left alone
# ---------------------------------------------------------------------------


class TestOwnershipUsesTheExistingPrimitive:
    def test_claim_pending_is_consulted(self) -> None:
        """No new lock: the boolean claim added in 4.13D is the mechanism."""
        import inspect

        from grandpa.local_actions import approve_pending_action

        source = inspect.getsource(approve_pending_action)

        assert "claim_pending" in source

    def test_marks_ambiguous_return_is_no_longer_relied_on(self) -> None:
        """``mark`` hands winner and loser identical rows; it cannot own this."""
        import inspect

        from grandpa.local_actions import approve_pending_action

        source = inspect.getsource(approve_pending_action)

        assert 'store.mark(pending["id"], "approved")' not in source

    def test_the_deny_path_still_uses_mark(self) -> None:
        """Denial executes nothing, so it needs no ownership claim."""
        import inspect

        from grandpa.local_actions import deny_pending_action

        assert "mark(" in inspect.getsource(deny_pending_action)

    def test_no_new_locking_primitive_was_introduced(self) -> None:
        import inspect

        from grandpa import local_actions

        source = inspect.getsource(local_actions.approve_pending_action)

        for banned in ("threading.Lock", "filelock", "BEGIN EXCLUSIVE", "fcntl"):
            assert banned not in source, banned
