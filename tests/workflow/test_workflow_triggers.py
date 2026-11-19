"""Workflow triggers: time, a new file, an app starting, a phrase (F2).

Actions are mocked at ``executor._call``; the trigger store lives in the
per-test home; app lists are injected, so no process is inspected.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from grandpa.action_layer import executor
from grandpa.action_layer.model import ActionResult
from grandpa.cli.workflow_cmd import workflow
from grandpa.workflow.triggers import (
    TriggerError,
    TriggerStore,
    check_triggers,
    match_phrase,
    normalise_phrase,
)

SIMPLE = """
name: morning
vars:
  file: ""
steps:
  - id: v
    action: volume_get
  - id: note
    action: clipboard_write
    params: {content: "{{ vars.file }}"}
    when: vars.file != ''
"""

RISKY = """
name: wipe
steps:
  - id: bin
    action: empty_recycle_bin
"""


@pytest.fixture(autouse=True)
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    audit = tmp_path / "audit" / "local_actions.jsonl"
    folder = tmp_path / "workflows"
    folder.mkdir()
    monkeypatch.setenv("GRANDPA_LOCAL_ACTION_LOG", str(audit))
    monkeypatch.setenv("GRANDPA_WORKFLOWS_DIR", str(folder))
    default_db = tmp_path / "home" / "workflow_triggers.db"
    monkeypatch.setattr(
        "grandpa.workflow.triggers.triggers_db_path", lambda: default_db
    )
    (folder / "morning.yaml").write_text(SIMPLE, encoding="utf-8")
    (folder / "wipe.yaml").write_text(RISKY, encoding="utf-8")
    return {"audit": audit, "workflows": folder}


@pytest.fixture()
def store(tmp_path: Path) -> TriggerStore:
    return TriggerStore(tmp_path / "triggers.db")


class Calls(list):
    def __call__(self, spec, parameters, *, confirmed, confirm_callback):
        self.append((spec.name, dict(parameters)))
        return ActionResult.ok(f"{spec.name} done")


@pytest.fixture()
def calls(monkeypatch: pytest.MonkeyPatch) -> Calls:
    fake = Calls()
    monkeypatch.setattr(executor, "_call", fake)
    return fake


def workflow_audit(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]
    return [r for r in rows if r.get("source") == "workflow"]


def test_normalise_phrase() -> None:
    assert normalise_phrase("Hey Grandpa, run my morning routine!") == (
        "run my morning routine"
    )
    assert normalise_phrase("grandpa please run my morning routine please") == (
        "run my morning routine"
    )


def test_time_trigger_fires_once_when_due(
    store: TriggerStore, calls: Calls, env: dict[str, Path]
) -> None:
    trig = store.add("morning", "time", {"schedule": "07:30"})
    assert trig.spec["schedule"] == "daily:07:30"
    assert check_triggers(trig.next_run_at - 5, store=store) == []
    fired = check_triggers(trig.next_run_at + 1, store=store)
    assert len(fired) == 1 and fired[0]["ok"]
    assert calls == [("volume_get", {})]
    # Moved on by a day, so the next tick does not fire it again.
    after = store.get(trig.id)
    assert after.next_run_at > trig.next_run_at + 86000
    assert check_triggers(trig.next_run_at + 2, store=store) == []
    audit = workflow_audit(env["audit"])
    assert audit[-1]["workflow"] == "morning"
    assert audit[-1]["origin"] == "trigger:time"
    assert audit[-1]["trigger_id"] == trig.id and audit[-1]["ok"] is True


@pytest.mark.parametrize("bad", ["25:00", "tomorrow", "daily:7"])
def test_bad_schedule_is_refused(store: TriggerStore, bad: str) -> None:
    with pytest.raises(TriggerError):
        store.add("morning", "time", {"schedule": bad})


def test_file_trigger_fires_for_a_new_file_only(
    store: TriggerStore, calls: Calls, tmp_path: Path
) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "old.pdf").write_text("x")
    trig = store.add("morning", "file", {"folder": str(inbox), "pattern": "*.pdf"})

    assert check_triggers(store=store) == []  # first look: snapshot only
    (inbox / "notes.txt").write_text("x")  # does not match
    (inbox / "half.pdf.crdownload").write_text("x")  # still downloading
    assert check_triggers(store=store) == []
    (inbox / "new.pdf").write_text("x")
    fired = check_triggers(store=store)
    assert len(fired) == 1
    assert calls[-1] == ("clipboard_write", {"content": str(inbox / "new.pdf")})
    assert check_triggers(store=store) == []
    assert store.get(trig.id).last_status == "completed"


def test_app_trigger_fires_when_the_app_starts(
    store: TriggerStore, calls: Calls
) -> None:
    store.add("morning", "app", {"app": "Code.exe"})
    running: set[str] = {"code"}
    apps = lambda: set(running)  # noqa: E731

    assert check_triggers(store=store, running_apps=apps) == []  # already open
    running.clear()
    assert check_triggers(store=store, running_apps=apps) == []  # closed
    running.add("code")
    assert len(check_triggers(store=store, running_apps=apps)) == 1  # started
    assert check_triggers(store=store, running_apps=apps) == []  # still open


def test_pause_resume_remove(store: TriggerStore, calls: Calls) -> None:
    trig = store.add("morning", "time", {"schedule": "hourly"})
    store.set_enabled(trig.id, False)
    later = trig.next_run_at + 10
    assert check_triggers(later, store=store) == []
    resumed = store.set_enabled(trig.id, True)
    assert resumed.enabled and resumed.next_run_at is not None
    assert store.remove(trig.id)
    assert store.list() == []
    assert not store.remove(trig.id)


def test_triggered_run_cannot_confirm_risky_steps(
    store: TriggerStore, calls: Calls, env: dict[str, Path]
) -> None:
    trig = store.add("wipe", "time", {"schedule": "hourly"})
    fired = check_triggers(trig.next_run_at + 1, store=store)
    assert fired[0]["ok"] is False
    assert calls == []  # the recycle bin was not emptied
    audit = workflow_audit(env["audit"])
    assert audit[-1]["steps"][0]["error"] == "confirmation_required"


def test_missing_workflow_is_audited(
    store: TriggerStore, calls: Calls, env: dict[str, Path]
) -> None:
    trig = store.add("gone", "time", {"schedule": "hourly"})
    fired = check_triggers(trig.next_run_at + 1, store=store)
    assert fired[0]["status"] == "not_runnable"
    assert workflow_audit(env["audit"])[-1]["status"] == "not_runnable"


def test_phrase_trigger(store: TriggerStore) -> None:
    store.add("morning", "phrase", {"phrase": "Run my morning routine"})
    assert match_phrase("Hey Grandpa, run my morning routine.", store=store)
    assert match_phrase("run my evening routine", store=store) is None
    with pytest.raises(TriggerError):
        store.add("wipe", "phrase", {"phrase": "run my MORNING routine"})
    with pytest.raises(TriggerError):
        store.add("wipe", "phrase", {"phrase": "go"})


def test_phrase_runs_through_the_local_router(
    calls: Calls, env: dict[str, Path]
) -> None:
    """Chat, ask, voice and the phone all go through handle_local_action."""
    from grandpa.local import handle_local_action

    TriggerStore().add("morning", "phrase", {"phrase": "run my morning routine"})
    result = handle_local_action("Hey Grandpa, run my morning routine")
    assert result.status == "handled"
    assert result.kind == "workflow"
    assert calls == [("volume_get", {})]
    assert workflow_audit(env["audit"])[-1]["origin"] == "trigger:phrase:chat"

    # Without execute, nothing runs.
    calls.clear()
    handle_local_action("run my morning routine", execute=False)
    assert calls == []


def test_cli_trigger_commands(calls: Calls, tmp_path: Path) -> None:
    runner = CliRunner()
    added = runner.invoke(workflow, ["trigger", "add", "morning", "--at", "07:30"])
    assert added.exit_code == 0, added.output
    assert "Trigger 1: run morning at daily:07:30" in added.output

    risky = runner.invoke(workflow, ["trigger", "add", "wipe", "--app", "code.exe"])
    assert risky.exit_code == 0, risky.output
    assert "will be refused: bin (empty_recycle_bin)" in risky.output

    both = runner.invoke(
        workflow, ["trigger", "add", "morning", "--at", "07:30", "--app", "x"]
    )
    assert both.exit_code != 0

    listed = runner.invoke(workflow, ["trigger", "list"])
    assert "morning" in listed.output and "when code.exe starts" in listed.output

    assert "paused" in runner.invoke(workflow, ["trigger", "pause", "1"]).output
    assert "paused" in runner.invoke(workflow, ["trigger", "list"]).output
    assert "resumed" in runner.invoke(workflow, ["trigger", "resume", "1"]).output
    assert "removed" in runner.invoke(workflow, ["trigger", "remove", "2"]).output
    assert runner.invoke(workflow, ["trigger", "remove", "2"]).exit_code != 0
    check = runner.invoke(workflow, ["trigger", "check"])
    assert check.exit_code == 0


def test_cli_run_yes_is_audited(calls: Calls, env: dict[str, Path]) -> None:
    result = CliRunner().invoke(workflow, ["run", "morning", "--yes"])
    assert result.exit_code == 0, result.output
    entry = workflow_audit(env["audit"])[-1]
    assert entry["origin"] == "user_cli" and entry["ok"] is True


def test_daemon_tick_checks_triggers(
    calls: Calls, monkeypatch: pytest.MonkeyPatch
) -> None:
    from grandpa import scheduler_daemon

    seen: list[float] = []
    monkeypatch.setattr(
        "grandpa.workflow.triggers.check_triggers",
        lambda now: seen.append(now) or [{"trigger": 1}],
    )
    assert scheduler_daemon.BackgroundSchedulerDaemon._check_workflow_triggers(5.0) == [
        {"trigger": 1}
    ]
    assert seen == [5.0]

    def boom(now: float) -> list:
        raise RuntimeError("broken store")

    monkeypatch.setattr("grandpa.workflow.triggers.check_triggers", boom)
    assert (
        scheduler_daemon.BackgroundSchedulerDaemon._check_workflow_triggers(1.0) == []
    )


def test_next_run_is_in_the_future() -> None:
    from grandpa.workflow.triggers import _next_run

    now = datetime(2026, 11, 20, 8, 0).timestamp()
    nxt = datetime.fromtimestamp(_next_run("daily:07:30", now))
    assert nxt - datetime.fromtimestamp(now) < timedelta(days=1)
    assert nxt.hour == 7 and nxt.minute == 30
