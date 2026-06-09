"""Desktop Operator v2 for Grandpa.

This layer plans and records visible-desktop tasks without pretending to have
pixel-perfect automation. It uses current screen/desktop services where
available, blocks low-confidence visual actions, and routes real OS actions
through the existing PC-control approval kernel.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

OperatorStatus = Literal["planned", "running", "waiting_approval", "completed", "failed", "blocked"]
RiskLevel = Literal["LOW", "MEDIUM", "HIGH", "BLOCKED"]

DEFAULT_OPERATOR_DB = Path("runtime") / "desktop" / "operator.db"
MIN_VISUAL_CONFIDENCE = 0.72
MAX_RETRIES = 2


@dataclass(frozen=True)
class AppProfile:
    app_name: str
    known_windows: tuple[str, ...]
    common_actions: tuple[str, ...]
    visual_anchors: tuple[str, ...]
    safe_shortcuts: dict[str, str]
    blocked_actions: tuple[str, ...]
    approval_required_actions: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["known_windows"] = list(self.known_windows)
        data["common_actions"] = list(self.common_actions)
        data["visual_anchors"] = list(self.visual_anchors)
        data["blocked_actions"] = list(self.blocked_actions)
        data["approval_required_actions"] = list(self.approval_required_actions)
        return data


@dataclass(frozen=True)
class OperatorStep:
    step_id: str
    title: str
    action_type: str
    target: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    risk_level: RiskLevel = "LOW"
    approval_required: bool = False
    visual_target: dict[str, Any] = field(default_factory=dict)
    status: str = "planned"
    retry_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OperatorTask:
    task_id: str
    user_request: str
    app: str
    status: OperatorStatus
    steps: tuple[OperatorStep, ...]
    visual_targets: tuple[dict[str, Any], ...] = ()
    approvals: tuple[dict[str, Any], ...] = ()
    result_summary: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "user_request": self.user_request,
            "app": self.app,
            "status": self.status,
            "steps": [step.to_dict() for step in self.steps],
            "visual_targets": list(self.visual_targets),
            "approvals": list(self.approvals),
            "result_summary": self.result_summary,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


APP_PROFILES: dict[str, AppProfile] = {
    "vscode": AppProfile(
        app_name="VS Code",
        known_windows=("Visual Studio Code", "VS Code"),
        common_actions=("open terminal", "open extensions", "search files", "run task"),
        visual_anchors=("Terminal", "Explorer", "Search", "Extensions", "Problems"),
        safe_shortcuts={"open terminal": "ctrl+`", "command palette": "ctrl+shift+p", "search files": "ctrl+p"},
        blocked_actions=("delete project", "run unknown script", "commit secrets"),
        approval_required_actions=("type command", "run terminal command"),
    ),
    "chrome": AppProfile(
        app_name="Chrome",
        known_windows=("Google Chrome", "Chrome"),
        common_actions=("search", "new tab", "summarize page", "scroll"),
        visual_anchors=("Address and search bar", "Back", "Reload", "Search"),
        safe_shortcuts={"new tab": "ctrl+t", "focus address bar": "ctrl+l", "reload": "ctrl+r"},
        blocked_actions=("read password", "submit payment", "purchase"),
        approval_required_actions=("click button", "fill form", "download file", "send message"),
    ),
    "edge": AppProfile(
        app_name="Microsoft Edge",
        known_windows=("Microsoft Edge", "Edge"),
        common_actions=("search", "new tab", "summarize page", "scroll"),
        visual_anchors=("Address and search bar", "Back", "Reload", "Search"),
        safe_shortcuts={"new tab": "ctrl+t", "focus address bar": "ctrl+l", "reload": "ctrl+r"},
        blocked_actions=("read password", "submit payment", "purchase"),
        approval_required_actions=("click button", "fill form", "download file", "send message"),
    ),
    "explorer": AppProfile(
        app_name="File Explorer",
        known_windows=("File Explorer", "Downloads", "Documents"),
        common_actions=("open downloads", "search files", "copy path"),
        visual_anchors=("Downloads", "Search", "Address bar", "Navigation pane"),
        safe_shortcuts={"focus address bar": "ctrl+l", "search": "ctrl+f"},
        blocked_actions=("delete files", "format drive", "overwrite files"),
        approval_required_actions=("move files", "rename files", "bulk organize"),
    ),
    "notepad": AppProfile(
        app_name="Notepad",
        known_windows=("Notepad",),
        common_actions=("create note", "type text", "save note"),
        visual_anchors=("Edit", "Save", "File"),
        safe_shortcuts={"save": "ctrl+s", "new": "ctrl+n"},
        blocked_actions=("overwrite file", "delete file"),
        approval_required_actions=("type text", "save file", "create note"),
    ),
    "settings": AppProfile(
        app_name="Windows Settings",
        known_windows=("Settings", "Windows Settings"),
        common_actions=("open settings page", "read current panel"),
        visual_anchors=("Search", "System", "Bluetooth", "Network"),
        safe_shortcuts={},
        blocked_actions=("change security setting", "reset pc", "remove account"),
        approval_required_actions=("toggle setting", "change configuration"),
    ),
}


class OperatorTaskStore:
    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = Path(db_path or os.getenv("GRANDPA_DESKTOP_OPERATOR_DB") or DEFAULT_OPERATOR_DB)
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
                CREATE TABLE IF NOT EXISTS operator_tasks (
                    task_id TEXT PRIMARY KEY,
                    user_request TEXT NOT NULL,
                    app TEXT NOT NULL,
                    status TEXT NOT NULL,
                    steps TEXT NOT NULL,
                    visual_targets TEXT NOT NULL,
                    approvals TEXT NOT NULL,
                    result_summary TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_operator_tasks_updated ON operator_tasks(updated_at DESC)")

    def save(self, task: OperatorTask) -> OperatorTask:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO operator_tasks(
                    task_id, user_request, app, status, steps, visual_targets,
                    approvals, result_summary, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id)
                DO UPDATE SET app=excluded.app,
                              status=excluded.status,
                              steps=excluded.steps,
                              visual_targets=excluded.visual_targets,
                              approvals=excluded.approvals,
                              result_summary=excluded.result_summary,
                              updated_at=excluded.updated_at
                """,
                (
                    task.task_id,
                    task.user_request,
                    task.app,
                    task.status,
                    json.dumps([step.to_dict() for step in task.steps]),
                    json.dumps(list(task.visual_targets)),
                    json.dumps(list(task.approvals)),
                    task.result_summary,
                    task.created_at,
                    task.updated_at,
                ),
            )
        return task

    def list(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM operator_tasks ORDER BY updated_at DESC LIMIT ?",
                (max(1, min(limit, 200)),),
            ).fetchall()
        return [_task_row_to_dict(row) for row in rows]

    def diagnostics(self) -> dict[str, Any]:
        with self._connect() as conn:
            rows = conn.execute("SELECT status, COUNT(*) AS count FROM operator_tasks GROUP BY status").fetchall()
            total = conn.execute("SELECT COUNT(*) AS count FROM operator_tasks").fetchone()["count"]
        return {
            "db_path": str(self.db_path),
            "task_count": int(total),
            "counts": {str(row["status"]): int(row["count"]) for row in rows},
            "storage": "sqlite",
            "local_only": True,
        }


def analyze_desktop_task(user_request: str) -> dict[str, Any]:
    """Analyze a desktop task without executing it."""
    text = _normalise(user_request)
    app = _detect_app(text)
    intent = _detect_intent(text)
    risk = _estimate_risk(text, intent, app)
    return {
        "request": user_request,
        "intent": intent,
        "app": app,
        "query": _extract_search_query(user_request, text),
        "note_text": _extract_note_text(user_request, text),
        "profile": APP_PROFILES.get(app).to_dict() if app in APP_PROFILES else None,
        "risk_level": risk,
        "approval_required": risk in {"MEDIUM", "HIGH"},
        "confidence": _confidence(text, app, intent),
        "supported": app in APP_PROFILES or intent in {"summarize_desktop", "active_app_actions"},
    }


def build_ui_navigation_plan(user_request: str, *, persist: bool = True) -> dict[str, Any]:
    """Build a deterministic operator plan for a supported desktop task."""
    analysis = analyze_desktop_task(user_request)
    steps = _steps_for_analysis(analysis)
    status: OperatorStatus = "planned"
    approvals = [
        {"step_id": step.step_id, "risk_level": step.risk_level, "reason": step.title}
        for step in steps
        if step.approval_required
    ]
    if any(step.risk_level == "BLOCKED" for step in steps):
        status = "blocked"
    elif approvals:
        status = "waiting_approval"
    summary = summarize_operator_task(analysis, steps)
    task = OperatorTask(
        task_id=f"desktop_op_{uuid.uuid4().hex[:12]}",
        user_request=user_request,
        app=analysis.get("app") or "desktop",
        status=status,
        steps=tuple(steps),
        visual_targets=tuple(step.visual_target for step in steps if step.visual_target),
        approvals=tuple(approvals),
        result_summary=summary,
    )
    if persist:
        OperatorTaskStore().save(task)
    return {"analysis": analysis, "task": task.to_dict(), "plan": [step.to_dict() for step in steps]}


def execute_visual_step(step: dict[str, Any], *, dry_run: bool = True) -> dict[str, Any]:
    """Execute one bounded visual/desktop step through PC control if safe."""
    target = step.get("visual_target") or {}
    confidence = float(target.get("confidence", step.get("confidence", 1.0)) or 0.0)
    risk = str(step.get("risk_level", "LOW")).upper()
    approval_required = bool(step.get("approval_required")) or risk in {"MEDIUM", "HIGH"}
    if confidence and confidence < MIN_VISUAL_CONFIDENCE:
        return {
            "ok": False,
            "status": "blocked",
            "message": "Visual target confidence is too low, so I did not click.",
            "risk_level": risk,
            "approval_required": approval_required,
            "evidence": {"confidence": confidence, "minimum": MIN_VISUAL_CONFIDENCE},
        }
    if approval_required and not dry_run:
        return {
            "ok": False,
            "status": "approval_required",
            "message": "Confirmation required before running this desktop operator step.",
            "risk_level": risk,
            "approval_required": True,
            "evidence": {"step": step},
        }
    action_type = str(step.get("action_type") or "")
    if not action_type or action_type == "observe":
        return {
            "ok": True,
            "status": "dry_run" if dry_run else "completed",
            "message": "Observed desktop state.",
            "risk_level": "LOW",
            "approval_required": False,
            "evidence": _desktop_observation(),
        }
    try:
        from grandpa.pc_control import run_local_action

        response = run_local_action(
            {
                "action_type": action_type,
                "target": str(step.get("target") or ""),
                "args": dict(step.get("params") or {}),
                "dry_run": dry_run,
            }
        )
        return response.to_dict()
    except Exception as exc:
        return {
            "ok": False,
            "status": "failed",
            "message": "Desktop operator step failed safely.",
            "risk_level": risk,
            "approval_required": approval_required,
            "error": exc.__class__.__name__,
        }


def verify_action_result(step: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """Refresh desktop context and verify a step's outcome conservatively."""
    observation = _desktop_observation()
    ok = bool(result.get("ok")) and result.get("status") in {"completed", "dry_run"}
    return {
        "ok": ok,
        "status": "verified" if ok else "unverified",
        "message": "Step result verified conservatively." if ok else "Step result could not be verified from current desktop context.",
        "step": step,
        "result": result,
        "observation": observation,
    }


def recover_failed_action(step: dict[str, Any], result: dict[str, Any], *, retry_count: int = 0) -> dict[str, Any]:
    """Return a bounded recovery plan for failed visual actions."""
    if retry_count >= MAX_RETRIES:
        return {
            "status": "failed",
            "retry_allowed": False,
            "message": "Retry limit reached. I stopped instead of repeatedly acting on the desktop.",
            "retry_count": retry_count,
        }
    if result.get("status") == "blocked":
        return {
            "status": "blocked",
            "retry_allowed": False,
            "message": "The action is blocked by safety policy and will not be retried.",
            "retry_count": retry_count,
        }
    return {
        "status": "retry_planned",
        "retry_allowed": True,
        "message": "A bounded retry can refresh screen context and try one safer alternate target.",
        "retry_count": retry_count + 1,
        "next_step": {**step, "retry_count": retry_count + 1},
    }


def summarize_operator_task(analysis: dict[str, Any], steps: list[OperatorStep] | tuple[OperatorStep, ...]) -> str:
    app_name = analysis.get("profile", {}).get("app_name") if isinstance(analysis.get("profile"), dict) else analysis.get("app")
    if not steps:
        return "No supported desktop operator steps were found."
    approval_count = sum(1 for step in steps if step.approval_required)
    return (
        f"Prepared {len(steps)} desktop operator step(s) for {app_name or 'the current desktop'}. "
        f"{approval_count} step(s) require approval. Risk: {analysis.get('risk_level', 'LOW')}."
    )


def operator_diagnostics() -> dict[str, Any]:
    store = OperatorTaskStore()
    return {
        "status": "ready",
        "ready": True,
        "profiles": list_app_profiles()["profiles"],
        "profile_count": len(APP_PROFILES),
        "storage": store.diagnostics(),
        "visual_targeting": {
            "mode": "screen_awareness_heuristic",
            "minimum_confidence": MIN_VISUAL_CONFIDENCE,
            "max_retries": MAX_RETRIES,
            "pixel_perfect_claimed": False,
        },
        "safety": {
            "approval_required_for_risky_actions": True,
            "low_confidence_blocked": True,
            "protected_windows_blocked": True,
            "blind_clicking_allowed": False,
        },
        "local_only": True,
    }


def list_app_profiles() -> dict[str, Any]:
    return {"profiles": [profile.to_dict() for profile in APP_PROFILES.values()], "count": len(APP_PROFILES)}


def list_operator_tasks(limit: int = 50) -> dict[str, Any]:
    return {"tasks": OperatorTaskStore().list(limit=limit), **OperatorTaskStore().diagnostics()}


def active_app_actions() -> dict[str, Any]:
    observation = _desktop_observation()
    app = _detect_app(f"{observation.get('app_name', '')} {observation.get('window_title', '')}")
    profile = APP_PROFILES.get(app)
    return {
        "active_app": profile.app_name if profile else observation.get("app_name") or "unknown",
        "window_title": observation.get("window_title", ""),
        "supported": bool(profile),
        "suggested_actions": list(profile.common_actions) if profile else ["summarize current desktop state", "screen diagnostics"],
        "profile": profile.to_dict() if profile else None,
        "observation": observation,
    }


def _steps_for_analysis(analysis: dict[str, Any]) -> list[OperatorStep]:
    intent = analysis["intent"]
    app = analysis["app"]
    if intent == "summarize_desktop":
        return [
            OperatorStep("observe_desktop", "Summarize current desktop state", "observe", risk_level="LOW"),
        ]
    if intent == "active_app_actions":
        return [
            OperatorStep("detect_active_app", "Detect active app and suggest safe actions", "observe", risk_level="LOW"),
        ]
    if intent == "open_vscode_terminal":
        return [
            OperatorStep("focus_vscode", "Focus VS Code", "focus_window", "vscode", risk_level="MEDIUM", approval_required=True),
            OperatorStep(
                "open_terminal_shortcut",
                "Open integrated terminal with VS Code shortcut",
                "keyboard_hotkey",
                "ctrl+`",
                {"keys": ["ctrl", "`"]},
                risk_level="MEDIUM",
                approval_required=True,
                visual_target={"label": "Terminal", "confidence": 0.78},
            ),
        ]
    if intent == "open_explorer_downloads":
        return [
            OperatorStep("open_downloads", "Open Downloads folder in File Explorer", "open_app", "explorer", {"path": "downloads"}, risk_level="LOW"),
        ]
    if intent == "search_browser":
        query = analysis.get("query") or "search"
        browser = "chrome" if app not in {"edge"} else "edge"
        return [
            OperatorStep("open_browser", f"Open {browser.title()}", "open_app", browser, risk_level="LOW"),
            OperatorStep(
                "focus_address_bar",
                "Focus browser address bar",
                "keyboard_hotkey",
                "ctrl+l",
                {"keys": ["ctrl", "l"]},
                risk_level="MEDIUM",
                approval_required=True,
                visual_target={"label": "Address and search bar", "confidence": 0.76},
            ),
            OperatorStep("type_search", f"Type search query: {query}", "keyboard_type", str(query), {"text": query}, risk_level="MEDIUM", approval_required=True),
        ]
    if intent == "create_notepad_note":
        return [
            OperatorStep("open_notepad", "Open Notepad", "open_app", "notepad", risk_level="LOW"),
            OperatorStep("type_note", "Type note text into Notepad", "keyboard_type", "", {"text": analysis.get("note_text", "")}, risk_level="MEDIUM", approval_required=True),
        ]
    return [
        OperatorStep(
            "unsupported",
            "Unsupported desktop operator task",
            "",
            risk_level="BLOCKED",
            status="blocked",
            visual_target={"confidence": 0.0},
        )
    ]


def _desktop_observation() -> dict[str, Any]:
    try:
        from grandpa.screen_awareness import get_active_window_info

        context = get_active_window_info()
        return {
            "supported": context.supported,
            "window_title": context.window_title,
            "app_name": context.app_name,
            "message": context.message,
        }
    except Exception as exc:
        return {"supported": False, "message": "Desktop observation unavailable.", "error": exc.__class__.__name__}


def _detect_app(text: str) -> str:
    if re.search(r"\b(vs\s*code|vscode|visual studio code)\b", text):
        return "vscode"
    if "edge" in text:
        return "edge"
    if "chrome" in text or "browser" in text:
        return "chrome"
    if "explorer" in text or "downloads" in text or "folder" in text:
        return "explorer"
    if "notepad" in text or "note" in text:
        return "notepad"
    if "settings" in text:
        return "settings"
    return "desktop"


def _detect_intent(text: str) -> str:
    if "terminal" in text and re.search(r"\b(vs\s*code|vscode|visual studio code)\b", text):
        return "open_vscode_terminal"
    if "downloads" in text and ("explorer" in text or "folder" in text or "open" in text):
        return "open_explorer_downloads"
    if "search" in text and ("chrome" in text or "edge" in text or "browser" in text):
        return "search_browser"
    if ("create" in text or "write" in text or "type" in text) and ("note" in text or "notepad" in text):
        return "create_notepad_note"
    if "detect active app" in text or "suggest actions" in text or "active app" in text:
        return "active_app_actions"
    if "desktop state" in text or "current desktop" in text or "desktop summary" in text:
        return "summarize_desktop"
    return "unsupported"


def _estimate_risk(text: str, intent: str, app: str) -> RiskLevel:
    if re.search(r"\b(delete|format|wipe|password|payment|purchase|checkout|registry)\b", text):
        return "BLOCKED"
    if intent in {"open_vscode_terminal", "search_browser", "create_notepad_note"}:
        return "MEDIUM"
    if intent in {"summarize_desktop", "active_app_actions", "open_explorer_downloads"}:
        return "LOW"
    return "BLOCKED" if intent == "unsupported" else "LOW"


def _confidence(text: str, app: str, intent: str) -> float:
    score = 0.35
    if app in APP_PROFILES:
        score += 0.25
    if intent != "unsupported":
        score += 0.35
    if len(text.split()) >= 3:
        score += 0.05
    return round(min(score, 0.98), 3)


def _extract_search_query(original: str, text: str) -> str:
    if "search" not in text:
        return ""
    cleaned = re.sub(
        r"^(open\s+)?(chrome|edge|browser)\s+and\s+search\s+(for\s+)?",
        "",
        original.strip(),
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"^search\s+(for\s+)?", "", cleaned.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+in\s+(chrome|edge|browser)$", "", cleaned.strip(), flags=re.IGNORECASE)
    return cleaned.strip() or original.strip()


def _extract_note_text(original: str, text: str) -> str:
    if "note" not in text and "notepad" not in text:
        return ""
    match = re.search(r"\b(?:called|with|saying|that says)\s+(.+)$", original.strip(), flags=re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return ""


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _task_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "task_id": row["task_id"],
        "user_request": row["user_request"],
        "app": row["app"],
        "status": row["status"],
        "steps": _loads(row["steps"], []),
        "visual_targets": _loads(row["visual_targets"], []),
        "approvals": _loads(row["approvals"], []),
        "result_summary": row["result_summary"],
        "created_at": float(row["created_at"]),
        "updated_at": float(row["updated_at"]),
    }


def _loads(raw: str, fallback: Any) -> Any:
    try:
        return json.loads(raw)
    except Exception:
        return fallback


__all__ = [
    "APP_PROFILES",
    "AppProfile",
    "OperatorStep",
    "OperatorTask",
    "OperatorTaskStore",
    "active_app_actions",
    "analyze_desktop_task",
    "build_ui_navigation_plan",
    "execute_visual_step",
    "list_app_profiles",
    "list_operator_tasks",
    "operator_diagnostics",
    "recover_failed_action",
    "summarize_operator_task",
    "verify_action_result",
]
