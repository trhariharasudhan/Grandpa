"""Persistent autonomous goal mode for Grandpa.

This module implements a deterministic Observe -> Plan -> Act -> Reflect loop.
It is local-first, approval-safe, and intentionally bounded: no hidden browser
automation, no destructive execution, and no claim of general autonomy.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from grandpa.core.config import DEFAULT_CONFIG_DIR
from grandpa.planner import PlannerAnalysis, analyze_request
from grandpa.skills.registry import ensure_default_skills_registered, execute_skill
from grandpa.skills.runtime import SkillExecutionContext

AgentGoalStatus = Literal[
    "queued",
    "planning",
    "running",
    "waiting_approval",
    "observing",
    "reflecting",
    "completed",
    "failed",
    "cancelled",
]

DEFAULT_GOAL_DB = DEFAULT_CONFIG_DIR / "agents" / "agent_goals.db"


@dataclass
class AgentGoal:
    goal_id: str
    user_request: str
    status: AgentGoalStatus
    priority: str = "normal"
    current_phase: str = "queued"
    plan: dict[str, Any] = field(default_factory=dict)
    steps: list[dict[str, Any]] = field(default_factory=list)
    observations: list[dict[str, Any]] = field(default_factory=list)
    actions_taken: list[dict[str, Any]] = field(default_factory=list)
    approvals_needed: list[dict[str, Any]] = field(default_factory=list)
    result_summary: str = ""
    memory_updates: list[dict[str, Any]] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    completed_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal_id": self.goal_id,
            "user_request": self.user_request,
            "status": self.status,
            "priority": self.priority,
            "current_phase": self.current_phase,
            "plan": self.plan,
            "steps": self.steps,
            "observations": self.observations,
            "actions_taken": self.actions_taken,
            "approvals_needed": self.approvals_needed,
            "result_summary": self.result_summary,
            "memory_updates": self.memory_updates,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
        }


class AgentGoalStore:
    """SQLite store for persistent autonomous goals and events."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = Path(
            db_path or os.getenv("GRANDPA_AGENT_GOALS_DB") or DEFAULT_GOAL_DB
        )
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
                CREATE TABLE IF NOT EXISTS agent_goals (
                    goal_id TEXT PRIMARY KEY,
                    user_request TEXT NOT NULL,
                    status TEXT NOT NULL,
                    priority TEXT NOT NULL,
                    current_phase TEXT NOT NULL,
                    plan TEXT NOT NULL,
                    steps TEXT NOT NULL,
                    observations TEXT NOT NULL,
                    actions_taken TEXT NOT NULL,
                    approvals_needed TEXT NOT NULL,
                    result_summary TEXT NOT NULL,
                    memory_updates TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    completed_at REAL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_goal_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    goal_id TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    phase TEXT NOT NULL,
                    status TEXT NOT NULL,
                    message TEXT NOT NULL,
                    data TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_agent_goals_status ON agent_goals(status)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_agent_goal_events_goal ON agent_goal_events(goal_id, timestamp)"
            )

    def save(self, goal: AgentGoal) -> AgentGoal:
        goal.updated_at = time.time()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_goals(
                    goal_id, user_request, status, priority, current_phase, plan,
                    steps, observations, actions_taken, approvals_needed,
                    result_summary, memory_updates, created_at, updated_at, completed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(goal_id)
                DO UPDATE SET status=excluded.status,
                              priority=excluded.priority,
                              current_phase=excluded.current_phase,
                              plan=excluded.plan,
                              steps=excluded.steps,
                              observations=excluded.observations,
                              actions_taken=excluded.actions_taken,
                              approvals_needed=excluded.approvals_needed,
                              result_summary=excluded.result_summary,
                              memory_updates=excluded.memory_updates,
                              updated_at=excluded.updated_at,
                              completed_at=excluded.completed_at
                """,
                (
                    goal.goal_id,
                    goal.user_request,
                    goal.status,
                    goal.priority,
                    goal.current_phase,
                    _json(goal.plan),
                    _json(goal.steps),
                    _json(goal.observations),
                    _json(goal.actions_taken),
                    _json(goal.approvals_needed),
                    goal.result_summary,
                    _json(goal.memory_updates),
                    goal.created_at,
                    goal.updated_at,
                    goal.completed_at,
                ),
            )
        return goal

    def get(self, goal_id: str) -> AgentGoal | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM agent_goals WHERE goal_id = ?", (goal_id,)
            ).fetchone()
        return _goal_from_row(row) if row else None

    def list(self, limit: int = 50) -> list[AgentGoal]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM agent_goals ORDER BY updated_at DESC LIMIT ?",
                (max(1, min(limit, 200)),),
            ).fetchall()
        return [_goal_from_row(row) for row in rows]

    def add_event(
        self,
        goal_id: str,
        phase: str,
        status: str,
        message: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_goal_events(goal_id, timestamp, phase, status, message, data)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (goal_id, time.time(), phase, status, message, _json(data or {})),
            )

    def events(self, goal_id: str, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, goal_id, timestamp, phase, status, message, data
                FROM agent_goal_events
                WHERE goal_id = ?
                ORDER BY timestamp ASC
                LIMIT ?
                """,
                (goal_id, max(1, min(limit, 500))),
            ).fetchall()
        events: list[dict[str, Any]] = []
        for row in rows:
            item = {key: row[key] for key in row.keys() if key != "data"}
            item["data"] = _loads(row["data"], {})
            events.append(item)
        return events

    def diagnostics(self) -> dict[str, Any]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS count FROM agent_goals GROUP BY status"
            ).fetchall()
            total = conn.execute(
                "SELECT COUNT(*) AS count FROM agent_goals"
            ).fetchone()["count"]
        return {
            "status": "ready",
            "goal_count": total,
            "status_counts": {row["status"]: row["count"] for row in rows},
            "database": str(self.db_path),
            "local_only": True,
            "loop": "deterministic-observe-plan-act-reflect",
        }


def create_goal(
    user_request: str,
    *,
    priority: str = "normal",
    execute: bool = True,
    store: AgentGoalStore | None = None,
) -> AgentGoal:
    store = store or AgentGoalStore()
    request = user_request.strip()
    if not request:
        raise ValueError("user_request is required")
    goal = AgentGoal(
        goal_id=f"goal_{uuid.uuid4().hex[:12]}",
        user_request=request,
        status="queued",
        priority=priority or "normal",
    )
    store.save(goal)
    store.add_event(
        goal.goal_id, "queued", "queued", "Goal queued.", {"request": request}
    )
    if execute:
        return continue_goal(goal.goal_id, store=store) or goal
    return goal


def continue_goal(
    goal_id: str, *, store: AgentGoalStore | None = None
) -> AgentGoal | None:
    store = store or AgentGoalStore()
    goal = store.get(goal_id)
    if goal is None or goal.status in {"completed", "failed", "cancelled"}:
        return goal
    _observe(goal, store)
    analysis = _plan(goal, store)
    _act(goal, analysis, store)
    if goal.status not in {"waiting_approval", "failed", "cancelled"}:
        _reflect(goal, store)
    store.save(goal)
    return goal


def cancel_goal(
    goal_id: str, *, store: AgentGoalStore | None = None
) -> AgentGoal | None:
    store = store or AgentGoalStore()
    goal = store.get(goal_id)
    if goal is None:
        return None
    if goal.status not in {"completed", "failed"}:
        goal.status = "cancelled"
        goal.current_phase = "cancelled"
        goal.result_summary = "Goal cancelled by user."
        goal.completed_at = time.time()
        store.save(goal)
        store.add_event(goal.goal_id, "cancelled", "cancelled", goal.result_summary)
    return goal


def list_goals(
    limit: int = 50, *, store: AgentGoalStore | None = None
) -> list[dict[str, Any]]:
    store = store or AgentGoalStore()
    return [goal.to_dict() for goal in store.list(limit)]


def get_goal(
    goal_id: str, *, store: AgentGoalStore | None = None
) -> dict[str, Any] | None:
    store = store or AgentGoalStore()
    goal = store.get(goal_id)
    return goal.to_dict() if goal else None


def goal_events(
    goal_id: str, *, store: AgentGoalStore | None = None
) -> list[dict[str, Any]]:
    store = store or AgentGoalStore()
    return store.events(goal_id)


def agent_goal_diagnostics(*, store: AgentGoalStore | None = None) -> dict[str, Any]:
    store = store or AgentGoalStore()
    info = store.diagnostics()
    try:
        from grandpa.planner import planner_diagnostics
        from grandpa.skills.registry import (
            ensure_default_skills_registered,
            registry_diagnostics,
        )

        ensure_default_skills_registered()
        info["planner"] = planner_diagnostics()
        info["skills"] = {"skill_count": registry_diagnostics().get("skill_count", 0)}
    except Exception:
        info["planner"] = {"status": "unavailable"}
        info["skills"] = {"status": "unavailable"}
    return info


def _observe(goal: AgentGoal, store: AgentGoalStore) -> None:
    goal.status = "observing"
    goal.current_phase = "observing"
    observations: list[dict[str, Any]] = []
    try:
        from grandpa.memory.intelligence import ranked_memory_context

        observations.append(
            {
                "type": "memory",
                "data": ranked_memory_context(goal.user_request, limit=3),
            }
        )
    except Exception as exc:
        observations.append(
            {"type": "memory", "status": "unavailable", "error": exc.__class__.__name__}
        )
    try:
        from grandpa.browser.agent import browser_agent_diagnostics

        observations.append({"type": "browser", "data": browser_agent_diagnostics()})
    except Exception as exc:
        observations.append(
            {
                "type": "browser",
                "status": "unavailable",
                "error": exc.__class__.__name__,
            }
        )
    try:
        from grandpa.pc_control import run_local_action

        desktop = run_local_action(
            {"action_type": "desktop_summary", "target": "desktop", "dry_run": True}
        )
        observations.append({"type": "desktop", "data": desktop.to_dict()})
    except Exception as exc:
        observations.append(
            {
                "type": "desktop",
                "status": "unavailable",
                "error": exc.__class__.__name__,
            }
        )
    try:
        from grandpa.smart_automation import diagnostics

        observations.append({"type": "workflow", "data": diagnostics()})
    except Exception as exc:
        observations.append(
            {
                "type": "workflow",
                "status": "unavailable",
                "error": exc.__class__.__name__,
            }
        )
    goal.observations = observations
    store.save(goal)
    store.add_event(
        goal.goal_id,
        "observing",
        "observing",
        "Context observed.",
        {"observations": len(observations)},
    )


def _plan(goal: AgentGoal, store: AgentGoalStore) -> PlannerAnalysis:
    goal.status = "planning"
    goal.current_phase = "planning"
    analysis = analyze_request(goal.user_request)
    goal.plan = analysis.to_dict()
    goal.steps = [step.to_dict() for step in analysis.steps]
    goal.approvals_needed = [
        {"step_id": step.id, "skill": step.skill, "risk_level": step.risk_level}
        for step in analysis.steps
        if step.approval_required
    ]
    store.save(goal)
    store.add_event(
        goal.goal_id,
        "planning",
        "planning",
        "Execution plan created.",
        {"steps": len(goal.steps)},
    )
    return analysis


def _act(goal: AgentGoal, analysis: PlannerAnalysis, store: AgentGoalStore) -> None:
    if analysis.estimated_risk == "BLOCKED" or not analysis.steps:
        goal.status = "failed"
        goal.current_phase = "failed"
        goal.result_summary = (
            analysis.unsupported_reason or "No safe local plan is available."
        )
        store.save(goal)
        store.add_event(goal.goal_id, "act", "failed", goal.result_summary)
        return
    goal.status = "running"
    goal.current_phase = "running"
    ensure_default_skills_registered()
    actions: list[dict[str, Any]] = list(goal.actions_taken)
    for step in analysis.steps:
        if step.approval_required:
            goal.status = "waiting_approval"
            goal.current_phase = "waiting_approval"
            approval = {
                "step_id": step.id,
                "skill": step.skill,
                "risk_level": step.risk_level,
                "status": "pending",
            }
            if approval not in goal.approvals_needed:
                goal.approvals_needed.append(approval)
            store.save(goal)
            store.add_event(
                goal.goal_id,
                "act",
                "waiting_approval",
                f"Approval required for {step.skill}.",
                approval,
            )
            return
        result = execute_skill(
            step.skill,
            step.params,
            SkillExecutionContext(
                workflow_id=goal.goal_id,
                user_request=goal.user_request,
                source="autonomous-agent-v2",
                dry_run=True,
            ),
        )
        action = {
            "step_id": step.id,
            "skill": step.skill,
            "status": result.status,
            "ok": result.ok,
            "message": result.message,
        }
        actions.append(action)
        store.add_event(goal.goal_id, "act", result.status, result.message, action)
        if not result.ok and result.status not in {"unsupported", "approval_required"}:
            retry = execute_skill(
                step.skill,
                step.params,
                SkillExecutionContext(
                    workflow_id=goal.goal_id,
                    user_request=goal.user_request,
                    source="autonomous-agent-v2-retry",
                    dry_run=True,
                ),
            )
            retry_action = {
                "step_id": step.id,
                "skill": step.skill,
                "status": retry.status,
                "ok": retry.ok,
                "message": retry.message,
                "retry": True,
            }
            actions.append(retry_action)
            store.add_event(
                goal.goal_id, "act", retry.status, retry.message, retry_action
            )
            if not retry.ok and analysis.goal_class != "diagnostics":
                goal.status = "failed"
                goal.current_phase = "failed"
                goal.actions_taken = actions
                goal.result_summary = f"Goal failed at {step.skill}: {retry.message}"
                store.save(goal)
                return
    goal.actions_taken = actions


def _reflect(goal: AgentGoal, store: AgentGoalStore) -> None:
    goal.status = "reflecting"
    goal.current_phase = "reflecting"
    completed = [item for item in goal.actions_taken if item.get("ok")]
    failed = [item for item in goal.actions_taken if not item.get("ok")]
    goal.result_summary = _summary_for_goal(goal, completed, failed)
    memory_update = _write_memory(goal)
    if memory_update:
        goal.memory_updates.append(memory_update)
    if failed and "readiness" in goal.user_request.lower():
        goal.status = "completed"
    else:
        goal.status = "completed" if not failed else "failed"
    goal.current_phase = goal.status
    goal.completed_at = time.time()
    store.save(goal)
    store.add_event(
        goal.goal_id,
        "reflecting",
        goal.status,
        goal.result_summary,
        {"memory_updates": len(goal.memory_updates)},
    )
    _notify(goal)


def _summary_for_goal(
    goal: AgentGoal, completed: list[dict[str, Any]], failed: list[dict[str, Any]]
) -> str:
    if failed and "readiness" in goal.user_request.lower():
        return f"Grandpa readiness check completed with {len(failed)} issue(s) and {len(completed)} healthy step(s)."
    if failed:
        return f"Goal finished with {len(failed)} issue(s) after {len(completed)} completed step(s)."
    if (
        "readiness" in goal.user_request.lower()
        or "diagnostic" in goal.user_request.lower()
    ):
        return f"Grandpa readiness check completed with {len(completed)} safe diagnostic step(s)."
    if "research" in goal.user_request.lower():
        return f"Research plan prepared with {len(completed)} safe browser/planner step(s)."
    if "workspace" in goal.user_request.lower():
        return f"Coding workspace preparation plan completed with {len(completed)} safe step(s)."
    return f"Goal completed with {len(completed)} safe step(s)."


def _write_memory(goal: AgentGoal) -> dict[str, Any] | None:
    if not goal.result_summary or _looks_sensitive(goal.result_summary):
        return None
    try:
        from grandpa.memory_context import MemoryStore

        key = f"agent_goal_{goal.goal_id}"
        value = f"{goal.user_request}: {goal.result_summary}"
        MemoryStore().remember("work_context", key, value, source="agent_goal")
        return {"category": "work_context", "key": key, "value": value}
    except Exception as exc:
        return {"status": "failed", "error": exc.__class__.__name__}


def _notify(goal: AgentGoal) -> None:
    try:
        from grandpa.memory_context import record_activity

        record_activity(
            "agent_goal", goal.status, goal.goal_id, goal.result_summary, goal.status
        )
    except Exception:
        return


def _looks_sensitive(text: str) -> bool:
    try:
        from grandpa.memory_context import SENSITIVE_PATTERN

        return bool(SENSITIVE_PATTERN.search(text))
    except Exception:
        return False


def _goal_from_row(row: sqlite3.Row) -> AgentGoal:
    return AgentGoal(
        goal_id=row["goal_id"],
        user_request=row["user_request"],
        status=row["status"],
        priority=row["priority"],
        current_phase=row["current_phase"],
        plan=_loads(row["plan"], {}),
        steps=_loads(row["steps"], []),
        observations=_loads(row["observations"], []),
        actions_taken=_loads(row["actions_taken"], []),
        approvals_needed=_loads(row["approvals_needed"], []),
        result_summary=row["result_summary"],
        memory_updates=_loads(row["memory_updates"], []),
        created_at=float(row["created_at"]),
        updated_at=float(row["updated_at"]),
        completed_at=row["completed_at"],
    )


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _loads(raw: str, fallback: Any) -> Any:
    try:
        return json.loads(raw)
    except Exception:
        return fallback


__all__ = [
    "AgentGoal",
    "AgentGoalStore",
    "agent_goal_diagnostics",
    "cancel_goal",
    "continue_goal",
    "create_goal",
    "get_goal",
    "goal_events",
    "list_goals",
]
