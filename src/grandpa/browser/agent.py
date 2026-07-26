"""Safe visible-page browser agent for Grandpa.

The browser agent plans and summarizes using only local visible-page context.
It never opens hidden browser sessions, reads hidden tabs, or submits
forms. Medium-risk workflows are represented as approval-required plans.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from grandpa.browser_control import execute_browser_action, get_visible_browser_context

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_BROWSER_AGENT_DB = ROOT / "runtime" / "browser" / "browser_agent.db"

BrowserTaskStatus = Literal["planned", "completed", "requires_approval", "blocked", "unsupported"]
RiskLevel = Literal["LOW", "MEDIUM", "HIGH", "BLOCKED"]

_PASSWORD_PAYMENT_RE = re.compile(
    r"\b(password|passcode|otp|token|api\s*key|secret|credit\s*card|card\s*number|cvv|payment|checkout|purchase|pay|login|sign\s*in)\b",
    re.IGNORECASE,
)
_MESSAGE_RE = re.compile(r"\b(send|message|whatsapp|telegram|gmail|email|reply)\b", re.IGNORECASE)


@dataclass(frozen=True)
class BrowserTask:
    task_id: str
    goal: str
    page_title: str
    page_url: str
    steps: list[dict[str, Any]]
    risk_level: RiskLevel
    approval_required: bool
    status: BrowserTaskStatus
    created_at: float
    updated_at: float
    result_summary: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["created_at_iso"] = _iso(self.created_at)
        payload["updated_at_iso"] = _iso(self.updated_at)
        return payload


class BrowserAgentStore:
    """SQLite store for browser-agent workflow history."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = Path(db_path or os.environ.get("GRANDPA_BROWSER_AGENT_DB") or DEFAULT_BROWSER_AGENT_DB)
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
                CREATE TABLE IF NOT EXISTS browser_agent_tasks (
                    task_id TEXT PRIMARY KEY,
                    goal TEXT NOT NULL,
                    page_title TEXT NOT NULL,
                    page_url TEXT NOT NULL,
                    steps_json TEXT NOT NULL,
                    risk_level TEXT NOT NULL,
                    approval_required INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    result_summary TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_browser_agent_tasks_updated "
                "ON browser_agent_tasks(updated_at)"
            )

    def save(self, task: BrowserTask) -> BrowserTask:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO browser_agent_tasks(
                    task_id, goal, page_title, page_url, steps_json, risk_level,
                    approval_required, status, created_at, updated_at, result_summary
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    goal=excluded.goal,
                    page_title=excluded.page_title,
                    page_url=excluded.page_url,
                    steps_json=excluded.steps_json,
                    risk_level=excluded.risk_level,
                    approval_required=excluded.approval_required,
                    status=excluded.status,
                    updated_at=excluded.updated_at,
                    result_summary=excluded.result_summary
                """,
                (
                    task.task_id,
                    task.goal,
                    task.page_title,
                    task.page_url,
                    json.dumps(task.steps, ensure_ascii=True),
                    task.risk_level,
                    1 if task.approval_required else 0,
                    task.status,
                    task.created_at,
                    task.updated_at,
                    task.result_summary,
                ),
            )
        return task

    def list(self, limit: int = 30) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM browser_agent_tasks
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [_row_to_task(row).to_dict() for row in rows]

    def get(self, task_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM browser_agent_tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        return _row_to_task(row).to_dict() if row else None

    def count(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM browser_agent_tasks").fetchone()
        return int(row["count"] if row else 0)


def analyze_browser_task(goal: str) -> dict[str, Any]:
    """Classify a browser request without executing browser automation."""

    clean = _clean(goal)
    context = get_visible_browser_context()
    if _PASSWORD_PAYMENT_RE.search(clean):
        intent = "unsafe_sensitive"
        risk: RiskLevel = "BLOCKED"
        approval = False
    elif "download" in clean:
        intent = "download"
        risk = "MEDIUM"
        approval = True
    elif _MESSAGE_RE.search(clean):
        intent = "message"
        risk = "MEDIUM"
        approval = True
    elif "fill" in clean or "search box" in clean or "form" in clean:
        intent = "form_fill"
        risk = "MEDIUM"
        approval = True
    elif "link" in clean:
        intent = "links"
        risk = "LOW"
        approval = False
    elif "button" in clean:
        intent = "buttons"
        risk = "LOW"
        approval = False
    elif "summar" in clean or "page" in clean or "webpage" in clean:
        intent = "summary"
        risk = "LOW"
        approval = False
    elif "youtube" in clean or "search" in clean or "research" in clean:
        intent = "search"
        risk = "LOW"
        approval = False
    else:
        intent = "browser_task"
        risk = "LOW"
        approval = False
    return {
        "goal": goal,
        "intent": intent,
        "risk_level": risk,
        "approval_required": approval,
        "page_title": context.title or "",
        "page_url": context.url or "",
        "context_available": bool(context.supported),
        "local_only": True,
    }


def plan_browser_workflow(goal: str, *, store: BrowserAgentStore | None = None) -> dict[str, Any]:
    """Create and persist a safe browser-agent task plan."""

    analysis = analyze_browser_task(goal)
    context = get_visible_browser_context()
    now = time.time()
    risk = analysis["risk_level"]
    approval = bool(analysis["approval_required"])
    if risk == "BLOCKED":
        status: BrowserTaskStatus = "blocked"
        steps = [_step("blocked", "Blocked sensitive browser automation request.", risk="BLOCKED")]
        summary = "I blocked this browser task for safety."
    else:
        steps = _steps_for_intent(str(analysis["intent"]), goal)
        status = "requires_approval" if approval else "planned"
        summary = _plan_summary(str(analysis["intent"]), approval)
    task = BrowserTask(
        task_id="brw_" + uuid.uuid4().hex[:12],
        goal=goal.strip(),
        page_title=context.title or "",
        page_url=context.url or "",
        steps=steps,
        risk_level=risk,
        approval_required=approval,
        status=status,
        created_at=now,
        updated_at=now,
        result_summary=summary,
    )
    saved = (store or BrowserAgentStore()).save(task)
    return {"status": saved.status, "task": saved.to_dict(), "analysis": analysis}


def summarize_current_page(*, store: BrowserAgentStore | None = None) -> dict[str, Any]:
    result = execute_browser_action("summary", "visible")
    status = "completed" if result.status == "handled" else result.status
    task = _record_result("summarize this webpage", result.message, status, result.risk_level, False, "browser.page_summary", store)
    return {"status": status, "message": result.message, "summary": result.message, "task": task.to_dict(), "context": result.context.to_dict() if result.context else {}}


def extract_visible_links(*, store: BrowserAgentStore | None = None) -> dict[str, Any]:
    context = get_visible_browser_context()
    links = list(context.links)
    result = execute_browser_action("links", "visible")
    status = "completed" if result.status == "handled" else result.status
    task = _record_result("show links on this page", result.message, status, result.risk_level, False, "browser.visible_links", store)
    return {"status": status, "message": result.message, "links": links, "task": task.to_dict(), "context": context.to_dict()}


def extract_visible_buttons(*, store: BrowserAgentStore | None = None) -> dict[str, Any]:
    context = get_visible_browser_context()
    buttons = list(context.buttons)
    result = execute_browser_action("buttons", "visible")
    status = "completed" if result.status == "handled" else result.status
    task = _record_result("what buttons are visible?", result.message, status, result.risk_level, False, "browser.visible_buttons", store)
    return {"status": status, "message": result.message, "buttons": buttons, "task": task.to_dict(), "context": context.to_dict()}


def search_web_plan(query: str, *, store: BrowserAgentStore | None = None) -> dict[str, Any]:
    clean = query.strip()
    if not clean:
        clean = "search"
    goal = f"search {clean}"
    plan = plan_browser_workflow(goal, store=store)
    task = plan["task"]
    return {"status": "planned", "message": f"Prepared a safe browser search plan for {clean}.", "query": clean, "task": task}


def fill_form_plan(field: str, value: str = "", *, store: BrowserAgentStore | None = None) -> dict[str, Any]:
    text = f"{field} {value}".strip()
    if _PASSWORD_PAYMENT_RE.search(text):
        plan = plan_browser_workflow(f"fill form {text}", store=store)
        return {"status": "blocked", "message": "I blocked this form plan because it looks sensitive.", "task": plan["task"]}
    plan = plan_browser_workflow(f"fill this search box with {text}", store=store)
    return {"status": "requires_approval", "message": "Prepared a form-fill plan. Approval is required before changing a visible page.", "task": plan["task"]}


def download_plan(target: str, *, store: BrowserAgentStore | None = None) -> dict[str, Any]:
    if _PASSWORD_PAYMENT_RE.search(target):
        plan = plan_browser_workflow(f"download {target}", store=store)
        return {"status": "blocked", "message": "I blocked this download plan for safety.", "task": plan["task"]}
    plan = plan_browser_workflow(f"download {target or 'this file'}", store=store)
    return {"status": "requires_approval", "message": "Prepared a download plan. Approval is required before downloading.", "task": plan["task"]}


def list_browser_tasks(limit: int = 30, *, store: BrowserAgentStore | None = None) -> dict[str, Any]:
    return {"tasks": (store or BrowserAgentStore()).list(limit=limit), "local_only": True}


def get_browser_task(task_id: str, *, store: BrowserAgentStore | None = None) -> dict[str, Any] | None:
    return (store or BrowserAgentStore()).get(task_id)


def browser_agent_diagnostics(*, store: BrowserAgentStore | None = None) -> dict[str, Any]:
    context = get_visible_browser_context()
    agent_store = store or BrowserAgentStore()
    return {
        "status": "ready",
        "ready": True,
        "db_path": str(agent_store.db_path),
        "task_count": agent_store.count(),
        "context_available": context.supported,
        "capture_source": "visible_context" if context.supported else None,
        "current_title": context.title,
        "current_url": context.url,
        "counts": {
            "headings": len(context.headings),
            "links": len(context.links),
            "buttons": len(context.buttons),
            "inputs": len(context.inputs),
        },
        "safety": {
            "hidden_tabs": False,
            "password_extraction": False,
            "payment_automation": False,
            "auto_submit": False,
            "downloads_require_approval": True,
            "messages_require_approval": True,
        },
        "recent_tasks": agent_store.list(limit=8),
        "local_only": True,
    }


def _record_result(
    goal: str,
    summary: str,
    status: str,
    risk_level: str,
    approval_required: bool,
    skill: str,
    store: BrowserAgentStore | None,
) -> BrowserTask:
    context = get_visible_browser_context()
    now = time.time()
    task = BrowserTask(
        task_id="brw_" + uuid.uuid4().hex[:12],
        goal=goal,
        page_title=context.title or "",
        page_url=context.url or "",
        steps=[_step(skill, summary, risk=risk_level)],
        risk_level=_risk(risk_level),
        approval_required=approval_required,
        status=_status(status),
        created_at=now,
        updated_at=now,
        result_summary=summary,
    )
    return (store or BrowserAgentStore()).save(task)


def _steps_for_intent(intent: str, goal: str) -> list[dict[str, Any]]:
    if intent == "summary":
        return [_step("browser.page_summary", "Read and summarize the current visible page context.")]
    if intent == "links":
        return [_step("browser.visible_links", "Extract links from the current visible page context.")]
    if intent == "buttons":
        return [_step("browser.visible_buttons", "Extract buttons from the current visible page context.")]
    if intent == "search":
        skill = "browser.search_plan"
        if "youtube" in _clean(goal):
            return [_step(skill, "Prepare a visible YouTube search workflow.", params={"site": "youtube", "query": _extract_query(goal)})]
        return [_step(skill, "Prepare a safe web search workflow.", params={"query": _extract_query(goal)})]
    if intent == "form_fill":
        return [_step("browser.form_fill_plan", "Plan a visible form fill without submitting.", risk="MEDIUM", approval=True)]
    if intent == "download":
        return [_step("browser.download_plan", "Plan a visible download after approval.", risk="MEDIUM", approval=True)]
    if intent == "message":
        return [_step("browser.message_plan", "Plan messaging action; sending requires approval.", risk="MEDIUM", approval=True)]
    return [_step("browser.agent_diagnostics", "Inspect browser agent readiness.")]


def _step(skill: str, title: str, *, params: dict[str, Any] | None = None, risk: str = "LOW", approval: bool = False) -> dict[str, Any]:
    return {
        "id": "step_" + uuid.uuid4().hex[:6],
        "title": title,
        "skill": skill,
        "params": params or {},
        "risk_level": risk,
        "approval_required": approval,
        "status": "queued",
    }


def _plan_summary(intent: str, approval: bool) -> str:
    if approval:
        return "Prepared a browser workflow plan. Approval is required before changing the visible page."
    return f"Prepared a safe browser {intent.replace('_', ' ')} workflow plan."


def _row_to_task(row: sqlite3.Row) -> BrowserTask:
    return BrowserTask(
        task_id=row["task_id"],
        goal=row["goal"],
        page_title=row["page_title"],
        page_url=row["page_url"],
        steps=_json_list(row["steps_json"]),
        risk_level=_risk(row["risk_level"]),
        approval_required=bool(row["approval_required"]),
        status=_status(row["status"]),
        created_at=float(row["created_at"]),
        updated_at=float(row["updated_at"]),
        result_summary=row["result_summary"],
    )


def _extract_query(goal: str) -> str:
    clean = re.sub(r"\b(open|search|google|youtube|for|and|summarize|summarise|research)\b", " ", goal, flags=re.IGNORECASE)
    clean = _clean(clean)
    return clean or goal.strip()


def _clean(text: str) -> str:
    return " ".join(text.strip().lower().split())


def _json_list(text: str) -> list[dict[str, Any]]:
    try:
        value = json.loads(text)
        return value if isinstance(value, list) else []
    except Exception:
        return []


def _risk(value: str) -> RiskLevel:
    clean = str(value).upper()
    return clean if clean in {"LOW", "MEDIUM", "HIGH", "BLOCKED"} else "LOW"  # type: ignore[return-value]


def _status(value: str) -> BrowserTaskStatus:
    if value == "handled":
        return "completed"
    clean = str(value)
    return clean if clean in {"planned", "completed", "requires_approval", "blocked", "unsupported"} else "unsupported"  # type: ignore[return-value]


def _iso(timestamp: float) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()
