"""Reminders arrive, and "at 5pm" means once.

Three defects, all of them things a user would notice immediately:

* nothing delivered a reminder on a default install. ``scheduler.enabled`` is
  False, so no thread ran; and when one did, the toast backend needed the
  optional ``winotify``, so every reminder was marked *failed*;
* "remind me to X at 5pm" was read as ``daily:17:00`` -- a standing
  appointment for someone who asked for one reminder; and
* the phrase landed in whichever of two stores claimed it first, so a reminder
  a person had just created could be missing from ``reminders list``.

These assert on the effect: a row that changed status, a file that got written,
a listing that contains what was created. Not that a function returned.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from tests.e2e.harness import sqlite_rows

pytestmark = [pytest.mark.e2e]


def _pending(cli):
    return [
        row
        for row in sqlite_rows(cli.grandpa_home / "reminders.db", "reminders")
        if row["status"] == "pending"
    ]


@pytest.mark.real_actions(reason="reaches the real subprocess.Popen")
def test_a_due_reminder_actually_fires(cli) -> None:
    """The whole point of finding 11: created, due, run, delivered.

    Due a minute in the past so ``run-due`` has something to do and the overdue
    grace period has not expired.
    """
    due = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()

    created = cli("reminders", "create", "drink water", "--due-at", due)
    assert created.returncode == 0, created.text
    assert len(_pending(cli)) == 1

    fired = cli("reminders", "run-due")

    assert fired.returncode == 0, fired.text
    # The row moved off pending, which is the store's record that it was
    # delivered rather than merely attempted.
    rows = sqlite_rows(cli.grandpa_home / "reminders.db", "reminders")
    assert [row["status"] for row in rows] == ["triggered"], rows
    # And it was delivered somewhere a person could see, with no optional
    # package installed.
    log = cli.grandpa_home / "reminders-delivered.log"
    assert log.exists(), "nothing recorded the delivery"
    assert "drink water" in log.read_text(encoding="utf-8")


@pytest.mark.real_actions(reason="reaches the real subprocess.Popen")
def test_creating_one_says_that_nothing_will_deliver_it(cli) -> None:
    """The scheduler stays off by default, so the CLI has to say so."""
    due = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()

    created = cli("reminders", "create", "stand up", "--due-at", due)

    assert created.returncode == 0, created.text
    assert "Nothing is running to deliver this" in created.text
    assert "reminders run-due" in created.text


@pytest.mark.real_actions(reason="reaches the real subprocess.Popen")
def test_at_five_pm_is_one_shot(cli) -> None:
    """It used to become daily:17:00 in the other store."""
    added = cli("reminders", "add", "remind me to call mom at 5pm")

    assert added.returncode == 0, added.text
    rows = _pending(cli)
    assert len(rows) == 1, rows
    assert rows[0]["message"] == "call mom"

    # Nothing recurring was created for it.
    listed = cli("reminders", "list")
    assert "call mom" in listed.text
    assert "recurring" not in listed.text


@pytest.mark.real_actions(reason="reaches the real subprocess.Popen")
def test_every_day_at_five_pm_is_recurring(cli) -> None:
    """The same clock time, with a recurrence word, is a routine."""
    added = cli("reminders", "add", "remind me to call mom every day at 5pm")

    # The one-shot parser declines it, so this phrasing is not a one-shot
    # reminder -- it is the scheduler's, and `reminders add` says so rather
    # than storing a single 5pm that would never repeat.
    assert added.returncode != 0, added.text
    assert _pending(cli) == []


@pytest.mark.real_actions(reason="reaches the real subprocess.Popen")
def test_a_recurring_reminder_still_shows_up_in_the_list(cli) -> None:
    """One question, one answer, without migrating anything.

    There are three tables, not two: reminders.db/reminders (one-shot),
    scheduler.db/reminders (recurring) and scheduler.db/routines (morning
    routines). Chat's "every day at 5pm" writes the middle one, and
    `reminders list` read neither of the others -- so a reminder chat had just
    confirmed creating was missing from the list.

    A recurring reminder has a schedule rather than a due time, so there is
    nothing to migrate it *to*. It is listed alongside, labelled, and still
    managed with `grandpa scheduler`.
    """
    made = cli("chat", stdin="remind me to call mom every day at 5pm\nexit\n")
    assert made.returncode == 0, made.text
    assert "call mom" in made.text

    listed = cli("reminders", "list")

    assert listed.returncode == 0, listed.text
    assert "recurring" in listed.text, listed.text
    assert "call mom" in listed.text


@pytest.mark.real_actions(reason="reaches the real subprocess.Popen")
def test_ask_creates_the_same_one_shot_reminder_chat_does(cli) -> None:
    """`grandpa ask` consulted only the scheduler, so it disagreed with chat.

    Before this, "remind me to call mom at 5pm" typed at `ask` was stored as a
    daily 17:00 routine; once that phrasing became one-shot, `ask` would have
    matched nothing and asked the model instead. Two commands, one answer, and
    no model needed to reach it.
    """
    asked = cli("ask", "remind me to call mom at 5pm")

    assert asked.returncode == 0, asked.text
    assert "Reminder created" in asked.text
    rows = _pending(cli)
    assert [row["message"] for row in rows] == ["call mom"], rows

    listed = cli("reminders", "list")
    assert "call mom" in listed.text
    assert "recurring" not in listed.text
