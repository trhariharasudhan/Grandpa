"""Things that start a workflow on their own (F2).

Four kinds, all stored in one small SQLite file and all ending in
:func:`run_workflow`:

* ``time``   -- a schedule in the scheduler's format (``daily:07:30``,
  ``weekly:0:09:00``, ``hourly``), checked on the scheduler daemon's tick.
* ``file``   -- a new file matching a pattern appears in a folder.
* ``app``    -- a program starts (it was not running at the last check).
* ``phrase`` -- someone says or types the phrase ("Hey Grandpa, run my morning
  routine"); checked by ``grandpa.local.handle_local_action``, which chat,
  ``ask``, voice and the phone all go through.

A triggered run has nobody to ask, so it is given **no** confirmation callback:
any step whose action needs a yes is refused by the action executor, exactly as
it would be for any other unattended caller. Every run, and every trigger that
could not start its workflow, writes one line to the action audit log.

File and app triggers remember what they saw at the last check. The first check
after a trigger is added (or resumed) only takes that snapshot, so a folder that
already holds files or an app that is already open does not fire it.
"""

from __future__ import annotations

import fnmatch
import json
import logging
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable

logger = logging.getLogger(__name__)

__all__ = [
    "KINDS",
    "Trigger",
    "TriggerError",
    "TriggerStore",
    "check_triggers",
    "match_phrase",
    "normalise_phrase",
    "record_run",
    "run_workflow",
    "triggers_db_path",
]

KINDS = ("time", "file", "app", "phrase")
POLLED_KINDS = ("time", "file", "app")
MAX_SEEN_FILES = 5000
# Half-written downloads; the finished file fires the trigger instead.
_PARTIAL_SUFFIXES = (".crdownload", ".part", ".partial", ".tmp", ".download")
_WAKE = re.compile(
    r"^(?:(?:hey|hi|ok|okay)\s+)?(?:grandpa\s+)?(?:(?:please|can you|could you)\s+)?"
)


class TriggerError(ValueError):
    """A trigger that cannot be added as asked."""


@dataclass(frozen=True)
class Trigger:
    id: int
    workflow: str
    kind: str
    spec: dict[str, Any]
    enabled: bool
    created_at: float
    next_run_at: float | None
    last_fired_at: float | None
    last_status: str | None
    state: Any

    def describe(self) -> str:
        if self.kind == "time":
            return f"at {self.spec['schedule']}"
        if self.kind == "file":
            return f"new {self.spec.get('pattern', '*')} in {self.spec['folder']}"
        if self.kind == "app":
            return f"when {self.spec['app']} starts"
        return f'when you say "{self.spec["phrase"]}"'


def triggers_db_path() -> Path:
    from grandpa.runtime_paths import grandpa_home

    return grandpa_home() / "workflow_triggers.db"


def normalise_phrase(text: str) -> str:
    """Lower case, no punctuation, no "hey grandpa" / "please" around it."""
    cleaned = re.sub(r"[^\w\s']", " ", (text or "").lower())
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = _WAKE.sub("", cleaned).strip()
    cleaned = re.sub(r"\s+please$", "", cleaned).strip()
    return cleaned


def _schedule(raw: str) -> str:
    from grandpa.task_scheduler import _next_run_timestamp

    text = raw.strip().lower()
    if re.fullmatch(r"[0-9]{1,2}:[0-9]{2}", text):
        hour, minute = text.split(":")
        text = f"daily:{int(hour):02d}:{minute}"
    hour_minute = re.findall(r"([0-9]{2}):([0-9]{2})$", text)
    if hour_minute and (int(hour_minute[0][0]) > 23 or int(hour_minute[0][1]) > 59):
        raise TriggerError(f"{raw!r} is not a time of day.")
    if _next_run_timestamp(text) is None:
        raise TriggerError(
            f"{raw!r} is not a schedule. Use HH:MM, daily:HH:MM, "
            "weekly:<0-6 Mon-Sun>:HH:MM or hourly."
        )
    return text


def _next_run(schedule: str, after: float) -> float | None:
    from grandpa.task_scheduler import _next_run_timestamp

    return _next_run_timestamp(schedule, after=datetime.fromtimestamp(after))


def _app_name(raw: str) -> str:
    name = raw.strip().lower()
    return name[:-4] if name.endswith(".exe") else name


class TriggerStore:
    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = Path(db_path) if db_path else triggers_db_path()

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS workflow_triggers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at REAL NOT NULL,
                workflow TEXT NOT NULL,
                kind TEXT NOT NULL,
                spec_json TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                next_run_at REAL,
                last_fired_at REAL,
                last_status TEXT,
                state_json TEXT
            )
            """
        )
        return conn

    def add(self, workflow: str, kind: str, spec: dict[str, Any]) -> Trigger:
        if kind not in KINDS:
            raise TriggerError(f"unknown trigger kind {kind!r}")
        spec = dict(spec)
        now = time.time()
        next_run: float | None = None
        if kind == "time":
            spec["schedule"] = _schedule(str(spec.get("schedule", "")))
            next_run = _next_run(spec["schedule"], now)
        elif kind == "file":
            folder = Path(str(spec.get("folder", ""))).expanduser()
            if not folder.is_dir():
                raise TriggerError(f"{folder} is not a folder.")
            spec["folder"] = str(folder.resolve())
            spec["pattern"] = str(spec.get("pattern") or "*")
        elif kind == "app":
            if not str(spec.get("app", "")).strip():
                raise TriggerError("Name the app, e.g. --app code.exe")
            spec["app"] = str(spec["app"]).strip()
        else:
            phrase = normalise_phrase(str(spec.get("phrase", "")))
            if len(phrase.split()) < 2:
                raise TriggerError("A phrase needs at least two words.")
            for other in self.list():
                if other.kind == "phrase" and other.spec["phrase"] == phrase:
                    raise TriggerError(
                        f'"{phrase}" already runs {other.workflow} '
                        f"(trigger {other.id})."
                    )
            spec["phrase"] = phrase
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO workflow_triggers(created_at, workflow, kind, spec_json,"
                " enabled, next_run_at) VALUES (?, ?, ?, ?, 1, ?)",
                (now, workflow, kind, json.dumps(spec), next_run),
            )
            new_id = int(cursor.lastrowid or 0)
        found = self.get(new_id)
        assert found is not None
        return found

    def get(self, trigger_id: int) -> Trigger | None:
        if not self.db_path.exists():
            return None
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM workflow_triggers WHERE id = ?", (trigger_id,)
            ).fetchone()
        return _row(row) if row else None

    def list(self, kinds: Iterable[str] | None = None) -> list[Trigger]:
        if not self.db_path.exists():
            return []
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM workflow_triggers ORDER BY id"
            ).fetchall()
        wanted = set(kinds) if kinds else None
        return [_row(r) for r in rows if wanted is None or r["kind"] in wanted]

    def set_enabled(self, trigger_id: int, enabled: bool) -> Trigger | None:
        trigger = self.get(trigger_id)
        if trigger is None:
            return None
        next_run = trigger.next_run_at
        if enabled and trigger.kind == "time":
            next_run = _next_run(trigger.spec["schedule"], time.time())
        with self._connect() as conn:
            # Resuming forgets the old snapshot: what appeared while the
            # trigger was paused must not all fire at once.
            conn.execute(
                "UPDATE workflow_triggers SET enabled = ?, next_run_at = ?,"
                " state_json = CASE WHEN ? THEN NULL ELSE state_json END"
                " WHERE id = ?",
                (1 if enabled else 0, next_run, 1 if enabled else 0, trigger_id),
            )
        return self.get(trigger_id)

    def remove(self, trigger_id: int) -> bool:
        if not self.db_path.exists():
            return False
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM workflow_triggers WHERE id = ?", (trigger_id,)
            )
        return cursor.rowcount > 0

    def save_state(self, trigger_id: int, state: Any) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE workflow_triggers SET state_json = ? WHERE id = ?",
                (json.dumps(state), trigger_id),
            )

    def mark_fired(
        self, trigger_id: int, status: str, *, next_run_at: float | None = None
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE workflow_triggers SET last_fired_at = ?, last_status = ?,"
                " next_run_at = COALESCE(?, next_run_at) WHERE id = ?",
                (time.time(), status, next_run_at, trigger_id),
            )


def _row(row: sqlite3.Row) -> Trigger:
    state = row["state_json"]
    return Trigger(
        id=int(row["id"]),
        workflow=row["workflow"],
        kind=row["kind"],
        spec=json.loads(row["spec_json"] or "{}"),
        enabled=bool(row["enabled"]),
        created_at=float(row["created_at"]),
        next_run_at=row["next_run_at"],
        last_fired_at=row["last_fired_at"],
        last_status=row["last_status"],
        state=json.loads(state) if state else None,
    )


# --- running and auditing ------------------------------------------------------


def record_run(
    workflow: str,
    *,
    origin: str,
    ok: bool,
    status: str,
    trigger: Trigger | None = None,
    steps: list[dict[str, Any]] | None = None,
    error: str | None = None,
) -> None:
    """One line in the action audit log for one workflow run. Never raises."""
    from grandpa.action_layer.executor import audit_log_path

    record = {
        "timestamp": time.time(),
        "source": "workflow",
        "workflow": workflow,
        "origin": origin,
        "trigger_id": trigger.id if trigger else None,
        "trigger_kind": trigger.kind if trigger else None,
        "ok": ok,
        "status": status,
        "steps": steps or [],
        "error": error,
    }
    try:
        path = audit_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=True) + "\n")
    except OSError as exc:  # pragma: no cover - depends on the filesystem
        logger.warning("could not write the workflow audit entry: %s", exc)


def run_workflow(
    name: str,
    *,
    origin: str,
    trigger: Trigger | None = None,
    variables: dict[str, Any] | None = None,
    confirm_callback: Callable[..., bool] | None = None,
) -> dict[str, Any]:
    """Load and run a workflow for real, and audit the run."""
    from grandpa.workflow.engine import WorkflowEngine
    from grandpa.workflow.loader import (
        WorkflowFileError,
        find_workflow,
        load_yaml_workflow,
    )

    try:
        graph = load_yaml_workflow(find_workflow(name))
    except (FileNotFoundError, WorkflowFileError) as exc:
        record_run(
            name,
            origin=origin,
            ok=False,
            status="not_runnable",
            trigger=trigger,
            error=str(exc),
        )
        return {"ok": False, "status": "not_runnable", "message": str(exc)}

    usable = {k: v for k, v in (variables or {}).items() if k in graph.variables}
    result = WorkflowEngine().run(
        graph, variables=usable, confirm_callback=confirm_callback
    )
    steps = [
        {
            "id": step.node_id,
            "ok": step.success,
            "skipped": bool(step.metadata.get("skipped")),
            "error": step.metadata.get("error"),
        }
        for step in result.steps
    ]
    status = "completed" if result.success else "failed"
    record_run(
        graph.name,
        origin=origin,
        ok=result.success,
        status=status,
        trigger=trigger,
        steps=steps,
    )
    lines = [f"{graph.name}: {'done' if result.success else 'stopped, a step failed'}."]
    lines += [
        f"- {step.node_id}: {step.output}" for step in result.steps if step.output
    ]
    return {
        "ok": result.success,
        "status": status,
        "workflow": graph.name,
        "message": "\n".join(lines),
        "steps": steps,
    }


# --- the checks ----------------------------------------------------------------


def _running_apps() -> set[str]:
    import psutil

    names: set[str] = set()
    for process in psutil.process_iter(["name"]):
        name = (process.info.get("name") or "").strip()
        if name:
            names.add(_app_name(name))
    return names


def _list_files(folder: Path, pattern: str) -> set[str]:
    try:
        entries = list(folder.iterdir())
    except OSError:
        return set()
    return {
        entry.name
        for entry in entries
        if entry.is_file()
        and fnmatch.fnmatch(entry.name.lower(), pattern.lower())
        and not entry.name.lower().endswith(_PARTIAL_SUFFIXES)
    }


def check_triggers(
    now: float | None = None,
    *,
    store: TriggerStore | None = None,
    running_apps: Callable[[], set[str]] | None = None,
) -> list[dict[str, Any]]:
    """One pass over the time, file and app triggers. Returns what fired."""
    store = store or TriggerStore()
    triggers = [t for t in store.list(POLLED_KINDS) if t.enabled]
    if not triggers:
        return []
    now = time.time() if now is None else now
    fired: list[dict[str, Any]] = []
    apps: set[str] | None = None

    for trigger in triggers:
        try:
            if trigger.kind == "time":
                if trigger.next_run_at is None or trigger.next_run_at > now:
                    continue
                # Move the schedule on first, so a slow or failing run
                # cannot make the next tick fire it again.
                store.mark_fired(
                    trigger.id,
                    "running",
                    next_run_at=_next_run(trigger.spec["schedule"], now),
                )
                outcome = run_workflow(
                    trigger.workflow, origin="trigger:time", trigger=trigger
                )
            elif trigger.kind == "file":
                folder = Path(trigger.spec["folder"])
                current = _list_files(folder, trigger.spec.get("pattern", "*"))
                if trigger.state is None:
                    store.save_state(trigger.id, sorted(current)[:MAX_SEEN_FILES])
                    continue
                new = sorted(current - set(trigger.state))
                store.save_state(trigger.id, sorted(current)[:MAX_SEEN_FILES])
                if not new:
                    continue
                outcome = run_workflow(
                    trigger.workflow,
                    origin="trigger:file",
                    trigger=trigger,
                    variables={"file": str(folder / new[0])},
                )
            else:
                if apps is None:
                    apps = (running_apps or _running_apps)()
                running = _app_name(trigger.spec["app"]) in apps
                was_running = trigger.state
                store.save_state(trigger.id, running)
                if was_running is None or was_running or not running:
                    continue
                outcome = run_workflow(
                    trigger.workflow, origin="trigger:app", trigger=trigger
                )
        except Exception as exc:  # noqa: BLE001 - one bad trigger must not stop the rest
            logger.warning("workflow trigger %s failed: %s", trigger.id, exc)
            record_run(
                trigger.workflow,
                origin=f"trigger:{trigger.kind}",
                ok=False,
                status="trigger_error",
                trigger=trigger,
                error=str(exc),
            )
            store.mark_fired(trigger.id, "error")
            continue
        store.mark_fired(trigger.id, outcome["status"])
        fired.append({"trigger": trigger.id, **outcome})
    return fired


def match_phrase(text: str, *, store: TriggerStore | None = None) -> Trigger | None:
    """The enabled phrase trigger ``text`` says, if any."""
    store = store or TriggerStore()
    if not store.db_path.exists():
        return None
    said = normalise_phrase(text)
    if not said:
        return None
    for trigger in store.list(["phrase"]):
        if trigger.enabled and trigger.spec.get("phrase") == said:
            return trigger
    return None


def run_phrase(text: str, *, origin: str) -> dict[str, Any] | None:
    """Run the workflow ``text`` asks for, or ``None`` when it asks for none."""
    store = TriggerStore()
    trigger = match_phrase(text, store=store)
    if trigger is None:
        return None
    outcome = run_workflow(
        trigger.workflow, origin=f"trigger:phrase:{origin}", trigger=trigger
    )
    store.mark_fired(trigger.id, outcome["status"])
    return outcome
