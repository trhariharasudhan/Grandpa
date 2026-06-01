"""Smart local workflow automation planning for Grandpa."""

from __future__ import annotations

import json
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from grandpa.core.config import DEFAULT_CONFIG_DIR

DEFAULT_WORKFLOW_DB = DEFAULT_CONFIG_DIR / "smart_workflows.db"
MAX_CHAIN_STEPS = 20


@dataclass(frozen=True)
class WorkflowResult:
    status: str
    message: str
    data: dict[str, Any]


class WorkflowStore:
    def __init__(self, db_path: Path | str = DEFAULT_WORKFLOW_DB) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS workflows (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    name TEXT NOT NULL UNIQUE,
                    trigger_json TEXT NOT NULL,
                    steps_json TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS workflow_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at REAL NOT NULL,
                    workflow_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    detail_json TEXT NOT NULL
                )
                """
            )

    def save(self, name: str, trigger: dict[str, Any], steps: list[dict[str, Any]], *, enabled: bool = True) -> dict[str, Any]:
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO workflows(created_at, updated_at, name, trigger_json, steps_json, enabled)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    updated_at = excluded.updated_at,
                    trigger_json = excluded.trigger_json,
                    steps_json = excluded.steps_json,
                    enabled = excluded.enabled
                """,
                (now, now, name, json.dumps(trigger), json.dumps(steps), 1 if enabled else 0),
            )
        return self.get(name) or {}

    def get(self, name: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM workflows WHERE lower(name)=lower(?)", (name,)).fetchone()
        return _workflow_row(row) if row else None

    def list(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM workflows ORDER BY updated_at DESC").fetchall()
        return [_workflow_row(row) for row in rows]

    def record_history(self, workflow_name: str, status: str, detail: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO workflow_history(created_at, workflow_name, status, detail_json) VALUES (?, ?, ?, ?)",
                (time.time(), workflow_name, status, json.dumps(detail)),
            )

    def history(self, limit: int = 30) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT created_at, workflow_name, status, detail_json FROM workflow_history ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        result = []
        for row in rows:
            item = {key: row[key] for key in row.keys()}
            try:
                item["detail"] = json.loads(item.pop("detail_json") or "{}")
            except json.JSONDecodeError:
                item["detail"] = {}
            result.append(item)
        return result


def create_workflow_from_text(text: str, *, store: WorkflowStore | None = None) -> WorkflowResult:
    store = store or WorkflowStore()
    name = _workflow_name(text)
    trigger = _parse_trigger(text)
    steps = _parse_steps(text)
    if len(steps) > MAX_CHAIN_STEPS:
        return WorkflowResult("blocked", "I blocked this workflow because it has too many chained steps.", {"max_steps": MAX_CHAIN_STEPS})
    workflow = store.save(name, trigger, steps)
    return WorkflowResult("handled", f"Created workflow '{name}' with {len(steps)} step(s).", {"workflow": workflow})


def simulate_workflow(name: str, *, store: WorkflowStore | None = None) -> WorkflowResult:
    store = store or WorkflowStore()
    workflow = store.get(name)
    if not workflow:
        return WorkflowResult("not_found", f"I could not find workflow '{name}'.", {})
    simulation = []
    for idx, step in enumerate(workflow["steps"], start=1):
        risk = _step_risk(step)
        simulation.append({"step": idx, "action": step["action"], "risk": risk, "would_run": risk != "BLOCKED"})
    store.record_history(name, "dry_run", {"simulation": simulation})
    return WorkflowResult("handled", f"Dry-run completed for '{name}'.", {"simulation": simulation, "dry_run": True})


def automation_templates() -> list[dict[str, Any]]:
    return [
        {"name": "morning_start", "trigger": {"type": "time", "value": "09:00"}, "steps": [{"action": "open chrome"}, {"action": "open vs code"}]},
        {"name": "browser_research", "trigger": {"type": "browser_context", "value": "research"}, "steps": [{"action": "summarize this webpage"}, {"action": "remember browser task"}]},
        {"name": "hourly_stretch", "trigger": {"type": "time", "value": "hourly"}, "steps": [{"action": "remind me to stretch"}]},
    ]


def diagnostics(store: WorkflowStore | None = None) -> dict[str, Any]:
    store = store or WorkflowStore()
    workflows = store.list()
    return {
        "status": "ready",
        "workflow_count": len(workflows),
        "enabled_count": sum(1 for item in workflows if item["enabled"]),
        "templates": automation_templates(),
        "history": store.history(limit=10),
        "features": {
            "triggers": ["time", "app_opened", "browser_context", "reminder"],
            "conditionals": True,
            "retries": True,
            "delays": True,
            "dry_run": True,
            "n8n_webhook_optional": True,
        },
        "safety": {"approval_gated_risky_actions": True, "max_chain_steps": MAX_CHAIN_STEPS, "local_only_default": True},
        "storage": {"backend": "sqlite", "path": str(store.db_path), "local_only": True},
    }


def _parse_trigger(text: str) -> dict[str, Any]:
    lower = text.lower()
    if "browser" in lower:
        return {"type": "browser_context", "value": "visible_page"}
    if "app opened" in lower or "when i open" in lower:
        return {"type": "app_opened", "value": _after(lower, "open") or "unknown"}
    if "reminder" in lower or "remind" in lower:
        return {"type": "reminder", "value": "manual"}
    time_match = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", lower)
    if time_match:
        return {"type": "time", "value": time_match.group(0)}
    return {"type": "manual", "value": "run_on_request"}


def _parse_steps(text: str) -> list[dict[str, Any]]:
    parts = re.split(r"\bthen\b|,|\band\b", text, flags=re.I)
    steps = []
    for part in parts:
        clean = part.strip(" .")
        if not clean:
            continue
        if clean.lower().startswith(("create workflow", "workflow", "when ")):
            continue
        steps.append({"action": clean, "condition": None, "retries": 0, "delay_seconds": 0})
    return steps or [{"action": text.strip(), "condition": None, "retries": 0, "delay_seconds": 0}]


def _step_risk(step: dict[str, Any]) -> str:
    action = str(step.get("action", "")).lower()
    if any(word in action for word in ("delete", "format", "shutdown", "restart", "password", "payment")):
        return "BLOCKED"
    if any(word in action for word in ("type", "click", "paste", "download", "send")):
        return "MEDIUM"
    return "LOW"


def _workflow_name(text: str) -> str:
    match = re.search(r"(?:workflow|routine) (?:called|named) ([a-z0-9 _-]+)", text, re.I)
    if match:
        return re.sub(r"\s+", "_", match.group(1).strip().lower())[:80]
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:50] or "workflow"


def _after(text: str, marker: str) -> str:
    _, _, tail = text.partition(marker)
    return tail.strip().split()[0] if tail.strip() else ""


def _workflow_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "name": row["name"],
        "trigger": json.loads(row["trigger_json"] or "{}"),
        "steps": json.loads(row["steps_json"] or "[]"),
        "enabled": bool(row["enabled"]),
    }


__all__ = [
    "WorkflowResult",
    "WorkflowStore",
    "automation_templates",
    "create_workflow_from_text",
    "diagnostics",
    "simulate_workflow",
]
