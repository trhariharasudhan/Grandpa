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
RAW_ACTION_V1 = "raw_action_v1"
SKILL_GRAPH_V2 = "skill_graph_v2"

SAFE_RAW_STEP_SKILLS: dict[str, tuple[str, dict[str, Any], str, bool]] = {
    "desktop summary": ("desktop.summary", {}, "LOW", False),
    "summarize desktop": ("desktop.summary", {}, "LOW", False),
    "pc control diagnostics": ("desktop.diagnostics", {}, "LOW", False),
    "show pc diagnostics": ("desktop.diagnostics", {}, "LOW", False),
    "desktop diagnostics": ("desktop.diagnostics", {}, "LOW", False),
    "browser diagnostics": ("browser.diagnostics", {}, "LOW", False),
    "show browser diagnostics": ("browser.diagnostics", {}, "LOW", False),
    "browser status": ("browser.diagnostics", {}, "LOW", False),
    "visual targeting diagnostics": ("vision.visual_diagnostics", {}, "LOW", False),
    "show visual diagnostics": ("vision.visual_diagnostics", {}, "LOW", False),
    "visual automation diagnostics": ("vision.visual_diagnostics", {}, "LOW", False),
    "screen diagnostics": ("vision.screen_diagnostics", {}, "LOW", False),
    "screen awareness diagnostics": ("vision.screen_diagnostics", {}, "LOW", False),
    "workflow status": ("automation.workflow_status", {}, "LOW", False),
    "workflow diagnostics": ("automation.workflow_status", {}, "LOW", False),
    "readiness checks": ("automation.workflow_status", {}, "LOW", False),
}


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
        normalized_steps = normalize_workflow_steps(steps)
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
                (now, now, name, json.dumps(trigger), json.dumps(normalized_steps), 1 if enabled else 0),
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
        simulation.append(_simulate_step(name, idx, step))
    status = "waiting_approval" if any(item["status"] == "approval_required" for item in simulation) else "dry_run"
    if any(item["status"] == "failed" for item in simulation):
        status = "failed"
    store.record_history(name, status, {"simulation": simulation})
    return WorkflowResult("handled", f"Dry-run completed for '{name}'.", {"simulation": simulation, "dry_run": True, "status": status})


def automation_templates() -> list[dict[str, Any]]:
    return [
        {
            "name": "morning_start",
            "trigger": {"type": "time", "value": "09:00"},
            "steps": normalize_workflow_steps([{"action": "open chrome"}, {"action": "open vs code"}]),
        },
        {
            "name": "browser_research",
            "trigger": {"type": "browser_context", "value": "research"},
            "steps": [
                _skill_step("browser.diagnostics", title="Check browser adapter"),
                {"schema_version": RAW_ACTION_V1, "action": "summarize this webpage", "condition": None, "retries": 0, "delay_seconds": 0},
            ],
        },
        {
            "name": "hourly_stretch",
            "trigger": {"type": "time", "value": "hourly"},
            "steps": [{"schema_version": RAW_ACTION_V1, "action": "remind me to stretch", "condition": None, "retries": 0, "delay_seconds": 0}],
        },
    ]


def diagnostics(store: WorkflowStore | None = None) -> dict[str, Any]:
    store = store or WorkflowStore()
    workflows = store.list()
    schema = workflow_schema_diagnostics(workflows)
    return {
        "status": "ready",
        "workflow_count": len(workflows),
        "enabled_count": sum(1 for item in workflows if item["enabled"]),
        "schema_versions": schema["schema_versions"],
        "skill_backed_workflow_count": schema["skill_backed_workflow_count"],
        "legacy_workflow_count": schema["legacy_workflow_count"],
        "conversion_ready": schema["conversion_ready"],
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
    planned = _parse_planner_steps(text)
    if planned:
        return planned
    parts = re.split(r"\bthen\b|,|\band\b", text, flags=re.I)
    steps = []
    for part in parts:
        clean = part.strip(" .")
        if not clean:
            continue
        if clean.lower().startswith(("create workflow", "workflow", "when ")):
            continue
        steps.append({"schema_version": RAW_ACTION_V1, "action": clean, "condition": None, "retries": 0, "delay_seconds": 0})
    return normalize_workflow_steps(steps or [{"schema_version": RAW_ACTION_V1, "action": text.strip(), "condition": None, "retries": 0, "delay_seconds": 0}])


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
    try:
        steps = json.loads(row["steps_json"] or "[]")
    except json.JSONDecodeError:
        steps = []
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "name": row["name"],
        "trigger": json.loads(row["trigger_json"] or "{}"),
        "steps": normalize_workflow_steps(steps),
        "enabled": bool(row["enabled"]),
    }


def normalize_workflow_steps(steps: list[Any]) -> list[dict[str, Any]]:
    """Return backwards-compatible workflow steps with explicit schema metadata."""
    return [normalize_workflow_step(step) for step in steps]


def normalize_workflow_step(step: Any) -> dict[str, Any]:
    if isinstance(step, str):
        return _convert_raw_step({"action": step, "condition": None, "retries": 0, "delay_seconds": 0})
    if not isinstance(step, dict):
        return _convert_raw_step({"action": str(step), "condition": None, "retries": 0, "delay_seconds": 0})
    if step.get("schema_version") == SKILL_GRAPH_V2 and step.get("skill"):
        normalized = dict(step)
        normalized.setdefault("params", {})
        normalized.setdefault("risk_level", _step_risk(normalized))
        normalized.setdefault("approval_required", normalized["risk_level"] in {"MEDIUM", "HIGH"})
        normalized.setdefault("dependencies", [])
        normalized.setdefault("execution_source", "skill_runtime")
        normalized.setdefault("action", normalized.get("title") or normalized["skill"])
        return normalized
    return _convert_raw_step(step)


def workflow_schema_diagnostics(workflows: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {RAW_ACTION_V1: 0, SKILL_GRAPH_V2: 0}
    skill_workflows = 0
    legacy_workflows = 0
    convertible_legacy_steps = 0
    total_legacy_steps = 0
    for workflow in workflows:
        has_skill = False
        has_legacy = False
        for step in workflow.get("steps", []):
            schema = str(step.get("schema_version") or RAW_ACTION_V1)
            counts[schema] = counts.get(schema, 0) + 1
            if schema == SKILL_GRAPH_V2:
                has_skill = True
            if schema == RAW_ACTION_V1:
                has_legacy = True
                total_legacy_steps += 1
                if _safe_skill_for_action(str(step.get("action", ""))):
                    convertible_legacy_steps += 1
        if has_skill:
            skill_workflows += 1
        if has_legacy:
            legacy_workflows += 1
    return {
        "schema_versions": counts,
        "skill_backed_workflow_count": skill_workflows,
        "legacy_workflow_count": legacy_workflows,
        "conversion_ready": {
            "safe_legacy_steps": convertible_legacy_steps,
            "total_legacy_steps": total_legacy_steps,
            "automatic_safe_conversion": True,
        },
    }


def _parse_planner_steps(text: str) -> list[dict[str, Any]]:
    try:
        from grandpa.planner.engine import analyze_request
    except Exception:
        return []
    analysis = analyze_request(text)
    if not analysis.workflow_suitable or not analysis.steps or analysis.estimated_risk == "BLOCKED":
        return []
    return [
        _skill_step(
            step.skill,
            params=step.params,
            title=step.title,
            risk_level=step.risk_level,
            approval_required=step.approval_required,
            dependencies=list(step.dependencies),
            retries=step.retry_count,
        )
        for step in analysis.steps
    ]


def _convert_raw_step(step: dict[str, Any]) -> dict[str, Any]:
    action = str(step.get("action") or step.get("title") or "").strip()
    mapped = _safe_skill_for_action(action)
    if mapped:
        skill, params, risk, approval_required = mapped
        return _skill_step(
            skill,
            params=params,
            title=action or skill,
            risk_level=risk,
            approval_required=approval_required,
            dependencies=step.get("dependencies") or [],
            retries=int(step.get("retries") or 0),
            delay_seconds=int(step.get("delay_seconds") or 0),
            legacy_action=action,
        )
    normalized = dict(step)
    normalized.setdefault("schema_version", RAW_ACTION_V1)
    normalized.setdefault("action", action)
    normalized.setdefault("condition", None)
    normalized.setdefault("retries", 0)
    normalized.setdefault("delay_seconds", 0)
    normalized.setdefault("risk_level", _step_risk(normalized))
    normalized.setdefault("approval_required", normalized["risk_level"] in {"MEDIUM", "HIGH"})
    normalized.setdefault("execution_source", "legacy")
    return normalized


def _safe_skill_for_action(action: str) -> tuple[str, dict[str, Any], str, bool] | None:
    clean = " ".join(action.lower().strip(" .").split())
    return SAFE_RAW_STEP_SKILLS.get(clean)


def _skill_step(
    skill: str,
    *,
    params: dict[str, Any] | None = None,
    title: str = "",
    risk_level: str = "LOW",
    approval_required: bool = False,
    dependencies: list[str] | None = None,
    retries: int = 0,
    delay_seconds: int = 0,
    legacy_action: str = "",
) -> dict[str, Any]:
    step = {
        "schema_version": SKILL_GRAPH_V2,
        "skill": skill,
        "params": params or {},
        "risk_level": risk_level,
        "approval_required": approval_required,
        "dependencies": dependencies or [],
        "condition": None,
        "retries": retries,
        "delay_seconds": delay_seconds,
        "execution_source": "skill_runtime",
        "action": title or skill,
    }
    if legacy_action:
        step["legacy_action"] = legacy_action
    return step


def _simulate_step(workflow_name: str, idx: int, step: dict[str, Any]) -> dict[str, Any]:
    schema = str(step.get("schema_version") or RAW_ACTION_V1)
    risk = _step_risk(step)
    item: dict[str, Any] = {
        "step": idx,
        "action": step.get("action") or step.get("skill") or "",
        "risk": risk,
        "approval_required": bool(step.get("approval_required") or risk in {"MEDIUM", "HIGH"}),
        "schema_version": schema,
        "execution_source": step.get("execution_source") or ("skill_runtime" if schema == SKILL_GRAPH_V2 else "legacy"),
    }
    if schema == SKILL_GRAPH_V2 and step.get("skill"):
        item["skill"] = step["skill"]
        item["params_summary"] = _params_summary(step.get("params") or {})
        try:
            from grandpa.skills.registry import (
                ensure_default_skills_registered,
                execute_skill,
            )
            from grandpa.skills.runtime import SkillExecutionContext

            ensure_default_skills_registered()
            result = execute_skill(
                str(step["skill"]),
                dict(step.get("params") or {}),
                SkillExecutionContext(
                    workflow_id=workflow_name,
                    user_request=str(step.get("action") or step["skill"]),
                    dry_run=True,
                    source="workflow",
                    metadata={"schema_version": SKILL_GRAPH_V2, "step": idx},
                ),
            )
            item.update(
                {
                    "status": result.status,
                    "would_run": result.ok,
                    "message": result.message,
                    "approval_required": result.approval_required or item["approval_required"],
                }
            )
        except Exception as exc:
            item.update({"status": "failed", "would_run": False, "message": "Skill-backed workflow step failed safely.", "error": exc.__class__.__name__})
        return item
    item.update({"status": "blocked" if risk == "BLOCKED" else "legacy_dry_run", "would_run": risk != "BLOCKED"})
    return item


def _params_summary(params: dict[str, Any]) -> str:
    if not params:
        return "{}"
    safe = {key: "[redacted]" if any(token in key.lower() for token in ("secret", "token", "password", "key")) else value for key, value in params.items()}
    text = json.dumps(safe, sort_keys=True)
    return text[:160] + ("..." if len(text) > 160 else "")


__all__ = [
    "WorkflowResult",
    "WorkflowStore",
    "RAW_ACTION_V1",
    "SKILL_GRAPH_V2",
    "automation_templates",
    "create_workflow_from_text",
    "diagnostics",
    "normalize_workflow_step",
    "normalize_workflow_steps",
    "simulate_workflow",
    "workflow_schema_diagnostics",
]
