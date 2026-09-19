"""Deferred consent: staged by a caller that opted in, approved only by it.

A caller that cannot ask mid-action -- voice -- opts in by naming its origin.
The action is staged in the kernel's approval store and runs when the same
origin's next turn is a yes. Three rules, each pinned here:

* it is opted into, never inferred: no callback and no origin refuses, and
  stages nothing
* it is bound to its origin: no other origin, no approval code, and no
  rejection from pc_control's side can resolve it
* it expires on pc_control's PENDING_TTL_SECONDS, and one yes resolves exactly
  one action

Window closing is recorded, never performed.
"""

from __future__ import annotations

import pytest

from grandpa import pc_control
from grandpa.desktop.kernel import approvals
from grandpa.local_actions import handle_local_action
from grandpa.natural_actions import run_parsed


@pytest.fixture(autouse=True)
def _audit_log(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GRANDPA_LOCAL_ACTION_LOG", str(tmp_path / "actions.jsonl"))


@pytest.fixture
def closed(monkeypatch) -> list[tuple[str, str]]:
    import grandpa.windows_window_control as wc

    calls: list[tuple[str, str]] = []

    class _Done:
        status = "handled"
        message = "done"

    monkeypatch.setattr(
        wc,
        "control_window",
        lambda action, target="active": calls.append((action, target)) or _Done(),
    )
    assert wc.control_window("probe", "x").status == "handled", "mock did not hold"
    calls.clear()
    return calls


def _deferred_rows() -> list[dict]:
    with pc_control._connect_approval_db() as conn:
        return [
            dict(row)
            for row in conn.execute(
                "SELECT action_id, action_type, status, decision, origin "
                "FROM pc_control_approvals WHERE consent = 'deferred' "
                "ORDER BY created_at"
            ).fetchall()
        ]


def _all_rows() -> list[dict]:
    with pc_control._connect_approval_db() as conn:
        return [
            dict(row)
            for row in conn.execute("SELECT * FROM pc_control_approvals").fetchall()
        ]


# --- opted into, never inferred ----------------------------------------------


def test_no_callback_and_no_opt_in_refuses_and_stages_nothing(closed) -> None:
    result = run_parsed("window", "close|notepad")

    assert result.status == "blocked"
    assert "nothing was run" in result.message
    assert result.pending_action is None
    assert closed == []
    assert _all_rows() == []


def test_the_same_through_local_actions(closed) -> None:
    # What `grandpa ask` non-interactively, the scheduler and agents reach.
    result = handle_local_action("close notepad")

    assert result.status == "blocked"
    assert result.pending_action is None
    assert closed == []
    assert _all_rows() == []


def test_a_legacy_shape_without_opt_in_is_refused_too() -> None:
    # "type hello" is still on the legacy dispatch; its old store staged it for
    # anyone's yes. Now: no opt-in, nothing staged.
    result = handle_local_action("type hello")

    assert result.status == "blocked"
    assert result.pending_action is None
    assert _all_rows() == []


def test_a_yes_with_no_origin_approves_nothing(closed) -> None:
    handle_local_action("close notepad", deferred_origin="voice")

    result = handle_local_action("yes")

    assert result.status == "unsupported"
    assert closed == []
    assert [row["status"] for row in _deferred_rows()] == ["pending"]


def test_a_dry_run_stages_nothing_even_when_opted_in(closed) -> None:
    result = handle_local_action(
        "close notepad", execute=False, deferred_origin="voice"
    )

    assert result.status == "requires_confirmation"
    assert _all_rows() == []


# --- the voice path ------------------------------------------------------------


def test_voice_stages_and_the_next_turn_yes_runs_it(closed) -> None:
    staged = handle_local_action("close notepad", deferred_origin="voice")

    assert staged.status == "requires_confirmation"
    assert closed == []
    assert [(r["action_type"], r["origin"]) for r in _deferred_rows()] == [
        ("close_window", "voice")
    ]

    approved = handle_local_action("yes", deferred_origin="voice")

    assert approved.status == "handled"
    assert closed == [("close", "notepad")]
    assert [row["status"] for row in _deferred_rows()] == ["approved"]


def test_voice_no_cancels_and_nothing_closes(closed) -> None:
    handle_local_action("close notepad", deferred_origin="voice")

    denied = handle_local_action("cancel", deferred_origin="voice")

    assert denied.status == "cancelled"
    assert closed == []
    assert [row["status"] for row in _deferred_rows()] == ["rejected"]


# --- bound to its origin -------------------------------------------------------


@pytest.mark.parametrize("other", ["chat", "http"])
def test_a_voice_action_cannot_be_approved_from_another_origin(closed, other) -> None:
    staged = handle_local_action("close notepad", deferred_origin="voice")
    action_id = staged.pending_action["id"]

    by_yes = handle_local_action("yes", deferred_origin=other)
    by_id = approvals.approve_deferred(origin=other, action_id=action_id)

    assert by_yes.status == "unsupported"
    assert by_id is None
    assert closed == []
    assert [row["status"] for row in _deferred_rows()] == ["pending"]


def test_a_voice_action_cannot_be_approved_or_rejected_with_a_code(closed) -> None:
    # The CLI's `grandpa approve` and the HTTP pc-control endpoints both land
    # here. An approval code is not the yes voice asked for, and the model has
    # no way in but these.
    staged = handle_local_action("close notepad", deferred_origin="voice")
    action_id = staged.pending_action["id"]

    approved = approvals.approve(action_id, "")
    rejected = approvals.reject(action_id)

    assert approved.status == "blocked"
    assert approved.error == "wrong_origin"
    assert rejected.ok is False
    assert closed == []
    assert [row["status"] for row in _deferred_rows()] == ["pending"]


def test_deferred_actions_are_not_listed_as_waiting_for_a_code() -> None:
    handle_local_action("close notepad", deferred_origin="voice")

    assert approvals.pending() == []
    assert [row["origin"] for row in approvals.pending_deferred("voice")] == ["voice"]
    assert approvals.pending_deferred("http") == []


# --- expiry, and one yes for one action -----------------------------------------


def test_a_staged_action_past_its_expiry_cannot_be_approved(
    closed, monkeypatch
) -> None:
    staged = handle_local_action("close notepad", deferred_origin="voice")
    assert staged.pending_action["expires_at"] == pytest.approx(
        _deferred_created_at() + pc_control.PENDING_TTL_SECONDS
    ), "a second expiry policy crept in"

    later = staged.pending_action["expires_at"] + 1
    monkeypatch.setattr(pc_control.time, "time", lambda: later)
    result = handle_local_action("yes", deferred_origin="voice")

    assert result.status == "unsupported"
    assert closed == []
    assert [row["status"] for row in _deferred_rows()] == ["expired"]


def _deferred_created_at() -> float:
    with pc_control._connect_approval_db() as conn:
        return float(
            conn.execute(
                "SELECT created_at FROM pc_control_approvals WHERE consent = 'deferred'"
            ).fetchone()[0]
        )


def test_one_yes_resolves_exactly_one_action(closed) -> None:
    handle_local_action("close notepad", deferred_origin="voice")
    handle_local_action("close calculator", deferred_origin="voice")

    first = handle_local_action("yes", deferred_origin="voice")
    second = handle_local_action("yes", deferred_origin="voice")

    # Staging the second superseded the first: there is never a queue.
    assert first.status == "handled"
    assert second.status == "unsupported"
    assert closed == [("close", "calculator")]
    assert [row["decision"] for row in _deferred_rows()] == ["superseded", "approved"]


def test_two_claims_for_one_row_cannot_both_win() -> None:
    staged = approvals.stage_deferred(
        origin="voice",
        action="close_window",
        target="close|notepad",
        parameters={"window": "notepad"},
        payload={"kind": "window", "target": "close|notepad"},
        risk_level="medium",
    )

    first = approvals.approve_deferred(origin="voice", action_id=staged["id"])
    second = approvals.approve_deferred(origin="voice", action_id=staged["id"])

    assert first is not None and first["id"] == staged["id"]
    assert second is None


def test_staging_without_an_origin_is_an_error() -> None:
    with pytest.raises(ValueError):
        approvals.stage_deferred(
            origin="",
            action="close_window",
            target="",
            parameters={},
            payload={},
            risk_level="medium",
        )
