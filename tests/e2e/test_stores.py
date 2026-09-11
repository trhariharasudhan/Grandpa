"""Memory, reminders and scheduler commands, checked against their databases."""

from __future__ import annotations

import importlib.util
import re
from datetime import datetime, timedelta, timezone

import pytest

from tests.e2e.harness import sqlite_execute, sqlite_rows

pytestmark = pytest.mark.e2e


# 14 --------------------------------------------------------------------------
def test_memory_remember_stores_a_row_that_search_returns(cli, make_nonce) -> None:
    fact = f"e2e favourite okapi {make_nonce('')}"
    token = fact.split()[-1]

    stored = cli("memory", "remember", fact)

    assert stored.returncode == 0, stored.text
    rows = [r for r in sqlite_rows(cli.grandpa_home / "memory.db", "memories")]
    assert [r["content"] for r in rows] == [fact], (
        f"memory.db does not hold exactly the fact; CLI said: {stored.tail()}"
    )
    found = cli("memory", "search", token)
    assert token in found.text, found.text
    missing = cli("memory", "search", make_nonce("absent"))
    assert token not in missing.text, (
        f"search returned an unrelated memory: {missing.text}"
    )


# 15 --------------------------------------------------------------------------
def test_reminders_add_persists_a_future_reminder_that_list_shows(
    cli, make_nonce
) -> None:
    message = f"water the plants {make_nonce('')}"
    before = datetime.now(timezone.utc)

    added = cli("reminders", "add", f"remind me in 30 minutes to {message}")

    assert added.returncode == 0, added.text
    rows = sqlite_rows(cli.grandpa_home / "reminders.db", "reminders")
    assert len(rows) == 1 and rows[0]["message"] == message, (
        f"reminders.db rows {rows}; CLI said: {added.tail()}"
    )
    due = datetime.fromisoformat(rows[0]["due_at"])
    assert timedelta(minutes=29) < due - before < timedelta(minutes=31), rows[0]
    assert rows[0]["status"] == "pending"
    listing = cli("reminders", "list", "--all")
    assert rows[0]["id"] in listing.text and message in listing.text, listing.text


# 16 --------------------------------------------------------------------------
def test_reminders_run_due_records_failed_delivery_instead_of_claiming_it(
    cli, make_nonce
) -> None:
    """PARTIAL: delivery needs winotify, absent by default. The failure must be recorded."""
    if importlib.util.find_spec("winotify") is not None:
        pytest.skip("winotify is installed; delivery would raise a real toast")
    message = f"stretch {make_nonce('')}"
    cli("reminders", "add", f"remind me in 30 minutes to {message}")
    db = cli.grandpa_home / "reminders.db"
    (reminder,) = sqlite_rows(db, "reminders")
    # Let one minute "pass": due, but inside the 10-minute overdue grace period.
    overdue = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    sqlite_execute(
        db, "UPDATE reminders SET due_at = ? WHERE id = ?", (overdue, reminder["id"])
    )

    ran = cli("reminders", "run-due")

    assert ran.returncode == 0, ran.text
    assert re.search(r"Triggered:\s*0\b", ran.text) and re.search(
        r"failed:\s*1\b", ran.text
    ), f"run-due did not report the failed delivery: {ran.text}"
    (after,) = sqlite_rows(db, "reminders")
    assert after["status"] == "failed", after
    assert "windows-notifications" in (after.get("failure_reason") or ""), after


# 17 --------------------------------------------------------------------------
def test_scheduler_create_list_cancel_round_trip_through_the_store(
    cli, make_nonce
) -> None:
    prompt = make_nonce("e2e-digest-")
    db = cli.grandpa_home / "scheduler.db"

    created = cli(
        "scheduler", "create", prompt, "--type", "interval", "--value", "3600"
    )

    assert created.returncode == 0, created.text
    rows = [r for r in sqlite_rows(db, "scheduled_tasks") if r["prompt"] == prompt]
    assert len(rows) == 1, f"no scheduled_tasks row; CLI said: {created.tail()}"
    task = rows[0]
    assert (task["schedule_type"], task["schedule_value"], task["status"]) == (
        "interval",
        "3600",
        "active",
    ), task
    assert task["id"] in created.text
    assert task["id"] in cli("scheduler", "list").text

    cancelled = cli("scheduler", "cancel", task["id"])

    assert cancelled.returncode == 0, cancelled.text
    (after,) = [r for r in sqlite_rows(db, "scheduled_tasks") if r["id"] == task["id"]]
    assert after["status"] == "cancelled", (
        f"task still {after['status']!r} after cancel; CLI said: {cancelled.tail()}"
    )
