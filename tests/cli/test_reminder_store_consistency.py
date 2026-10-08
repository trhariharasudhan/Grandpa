"""Two stores, one answer -- across every command, not just ``list``.

``reminders list`` was taught to read both stores in an earlier round. The
commands that *act* on a reminder were not, and the inconsistency was
user-visible:

* ``cancel`` read ``reminders.db`` only, so an id ``list`` had just printed
  answered "Reminder not found" and exited 1 -- and nothing anywhere could
  cancel a recurring reminder, because ``scheduler.db``'s ``reminders`` table
  had an ``enabled`` column that no code ever wrote 0 to.
* ``clear --all`` said "all reminders, including pending reminders" and left
  every recurring one in place.

Also here: the delivery guarantee. ``scheduler.enabled`` is False by default,
and the tick used to mark anything more than ten minutes overdue *failed*
without delivering it -- so on a default install a reminder was lost unless
``run-due`` happened to run inside a ten-minute window. That is findings 11
and 12.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from click.testing import CliRunner

from grandpa.cli import cli

pytestmark = pytest.mark.core


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("GRANDPA_HOME", str(tmp_path))
    return tmp_path


def _one_shot(message: str = "one shot", minutes: int = 120):
    from grandpa.reminders import ReminderStore

    return ReminderStore().create(
        message, datetime.now().astimezone() + timedelta(minutes=minutes)
    )


def _recurring(text: str = "water the plants"):
    from grandpa.task_scheduler import SchedulerStore

    return SchedulerStore().add_reminder(text, "every day at 17:00")


# --- list already answered for both -----------------------------------------------


def test_list_shows_both_kinds(home) -> None:
    _one_shot("take the bins out")
    _recurring("water the plants")

    result = CliRunner().invoke(cli, ["reminders", "list"])

    assert "take the bins out" in result.output
    assert "water the plants" in result.output


# --- cancel now does too ----------------------------------------------------------


def test_cancelling_an_id_that_list_printed_succeeds(home) -> None:
    """The defect: a recurring id was listed and then refused by cancel."""
    recurring = _recurring()

    result = CliRunner().invoke(cli, ["reminders", "cancel", str(recurring["id"])])

    assert result.exit_code == 0, result.output
    assert "paused" in result.output


def test_a_cancelled_recurring_reminder_is_actually_disabled(home) -> None:
    """``enabled`` had never been written 0 by any code path."""
    from grandpa.task_scheduler import SchedulerStore

    recurring = _recurring()

    CliRunner().invoke(cli, ["reminders", "cancel", str(recurring["id"])])

    saved = SchedulerStore().get_reminder(recurring["id"])
    assert saved is not None
    assert not saved["enabled"]


def test_cancelling_a_one_shot_still_works(home) -> None:
    reminder = _one_shot()

    result = CliRunner().invoke(cli, ["reminders", "cancel", reminder.id])

    assert result.exit_code == 0
    assert "cancelled" in result.output


def test_an_id_in_neither_store_still_fails_loudly(home) -> None:
    """Softening this would hide a typo rather than report it."""
    result = CliRunner().invoke(cli, ["reminders", "cancel", "rem_nonexistent"])

    assert result.exit_code == 1
    assert "not found" in result.output
    assert "list" in result.output, "it should say where to find the ids"


def test_a_numeric_id_that_is_not_a_recurring_reminder_fails(home) -> None:
    result = CliRunner().invoke(cli, ["reminders", "cancel", "99999"])

    assert result.exit_code == 1


# --- clear --all means both -------------------------------------------------------


def test_clear_all_names_the_recurring_reminders_in_its_confirmation(home) -> None:
    _recurring()

    result = CliRunner().invoke(cli, ["reminders", "clear", "--all", "--yes"])

    assert "recurring" in result.output


def test_clear_all_actually_removes_the_recurring_reminders(home) -> None:
    """It said "all reminders" and left them, which is the command lying."""
    from grandpa.task_scheduler import SchedulerStore

    _one_shot()
    _recurring("first")
    _recurring("second")

    CliRunner().invoke(cli, ["reminders", "clear", "--all", "--yes"])

    assert SchedulerStore().list_reminders() == []


def test_clear_without_all_leaves_recurring_alone(home) -> None:
    """``clear`` with no flags prunes finished one-shots. Nothing else."""
    from grandpa.task_scheduler import SchedulerStore

    _recurring()

    CliRunner().invoke(cli, ["reminders", "clear"])

    assert len(SchedulerStore().list_reminders()) == 1


# --- the delivery guarantee -------------------------------------------------------


def test_a_reminder_created_with_the_scheduler_off_is_warned_about(home) -> None:
    due = (datetime.now().astimezone() + timedelta(hours=1)).isoformat()

    result = CliRunner().invoke(
        cli, ["reminders", "create", "test", "--due-at", due]
    )

    assert "Nothing is running" in result.output


def test_the_warning_names_a_command_that_actually_delivers(home) -> None:
    """It used to recommend ``grandpa scheduler start``, which cannot.

    That command polls scheduled *tasks* out of scheduler.db and never reads
    reminders.db at all, so following the advice delivered nothing.
    """
    due = (datetime.now().astimezone() + timedelta(hours=1)).isoformat()

    result = CliRunner().invoke(
        cli, ["reminders", "create", "test", "--due-at", due]
    )

    assert "reminders watch" in result.output
    assert "scheduler start" not in result.output


def test_the_task_scheduler_really_cannot_deliver_a_reminder() -> None:
    """Pinned, so the advice above cannot drift back to the wrong command."""
    import inspect

    from grandpa.scheduler.scheduler import TaskScheduler

    assert "reminder" not in inspect.getsource(TaskScheduler).lower()


def test_the_warning_says_nothing_is_lost_by_waiting(home) -> None:
    """Because that is now true, and it was the user's actual question."""
    due = (datetime.now().astimezone() + timedelta(hours=1)).isoformat()

    result = CliRunner().invoke(
        cli, ["reminders", "create", "test", "--due-at", due]
    )

    assert "lost by waiting" in result.output


def test_watch_exists_and_is_documented(home) -> None:
    result = CliRunner().invoke(cli, ["reminders", "watch", "--help"])

    assert result.exit_code == 0
    assert "Blocks this terminal" in result.output


def test_run_due_delivers_a_reminder_that_is_days_overdue(home) -> None:
    """The guarantee: being late is not a reason to lose it.

    A reminder three days overdue was marked failed and never delivered, which
    with the scheduler off by default was every reminder.
    """
    from grandpa.reminders import ReminderStore

    store = ReminderStore()
    reminder = store.create(
        "call Arjun", datetime.now().astimezone() - timedelta(days=3)
    )

    result = CliRunner().invoke(cli, ["reminders", "run-due"])

    assert result.exit_code == 0
    saved = store.get(reminder.id)
    assert saved is not None
    assert saved.status == "triggered", f"status was {saved.status}"


def test_a_late_delivery_is_recorded_durably_under_grandpa_home(home) -> None:
    """A daemon's stdout goes nowhere. The log is how it reaches a person."""
    from grandpa.reminders import ReminderStore

    ReminderStore().create(
        "call Arjun", datetime.now().astimezone() - timedelta(hours=3)
    )

    CliRunner().invoke(cli, ["reminders", "run-due"])

    log = home / "reminders-delivered.log"
    assert log.exists(), "nothing durable was written"
    text = log.read_text(encoding="utf-8")
    assert "call Arjun" in text
    assert "late" in text, "a late delivery must say it is late"


# --- where the databases live -----------------------------------------------------
#
# Found by the final run of this round: a pre-existing test asserting "No
# pending reminders found." got a table of recurring ones instead, because
# ``_recurring_reminders()`` builds ``SchedulerStore()`` and that store's default
# path was bound at import *and* again as a default argument. A GRANDPA_HOME set
# afterwards was ignored, so every test in a process shared one scheduler.db.
# That is audit finding P14 in the two stores it had not yet reached.


def test_the_scheduler_database_follows_grandpa_home(tmp_path, monkeypatch) -> None:
    from grandpa.task_scheduler import default_scheduler_db

    monkeypatch.setenv("GRANDPA_HOME", str(tmp_path / "first"))
    assert default_scheduler_db() == tmp_path / "first" / "scheduler.db"

    # Moved mid-process, which is what a test does and what used to be ignored.
    monkeypatch.setenv("GRANDPA_HOME", str(tmp_path / "second"))
    assert default_scheduler_db() == tmp_path / "second" / "scheduler.db"


def test_the_reminder_database_follows_grandpa_home(tmp_path, monkeypatch) -> None:
    from grandpa.reminders import default_reminder_db

    monkeypatch.setenv("GRANDPA_HOME", str(tmp_path / "first"))
    assert default_reminder_db() == tmp_path / "first" / "reminders.db"

    monkeypatch.setenv("GRANDPA_HOME", str(tmp_path / "second"))
    assert default_reminder_db() == tmp_path / "second" / "reminders.db"


def test_neither_store_binds_its_path_as_a_default_argument() -> None:
    """A default argument is evaluated once, at definition.

    Checked on the signature rather than by behaviour, because the behaviour it
    produces -- one shared database per process -- is precisely what is hard to
    notice.
    """
    import inspect

    from grandpa.reminders import ReminderStore
    from grandpa.task_scheduler import SchedulerStore

    for store in (ReminderStore, SchedulerStore):
        default = inspect.signature(store.__init__).parameters["db_path"].default
        assert default is None, f"{store.__name__} binds {default!r} at definition"


def test_the_two_stores_are_still_separate_files(tmp_path, monkeypatch) -> None:
    """The split is deliberate: a due time and a schedule are different things."""
    from grandpa.reminders import default_reminder_db
    from grandpa.task_scheduler import default_scheduler_db

    monkeypatch.setenv("GRANDPA_HOME", str(tmp_path))

    assert default_reminder_db() != default_scheduler_db()
