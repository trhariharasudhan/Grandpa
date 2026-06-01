"""Safe real-world task planning for Grandpa."""

from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from grandpa.core.config import DEFAULT_CONFIG_DIR


DEFAULT_REAL_WORLD_DB = DEFAULT_CONFIG_DIR / "real_world_tasks.db"
PURCHASE_RISK = re.compile(r"\b(checkout|buy now|purchase|pay|payment|card|place order|book now|confirm booking)\b", re.I)


@dataclass(frozen=True)
class RealWorldResult:
    status: str
    message: str
    data: dict[str, Any]


class RealWorldStore:
    def __init__(self, db_path: Path | str = DEFAULT_REAL_WORLD_DB) -> None:
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
                CREATE TABLE IF NOT EXISTS real_world_workflows (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at REAL NOT NULL,
                    kind TEXT NOT NULL,
                    query TEXT NOT NULL,
                    status TEXT NOT NULL,
                    plan_json TEXT NOT NULL
                )
                """
            )

    def record(self, kind: str, query: str, status: str, plan: dict[str, Any]) -> dict[str, Any]:
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO real_world_workflows(created_at, kind, query, status, plan_json) VALUES (?, ?, ?, ?, ?)",
                (time.time(), kind, query, status, _json(plan)),
            )
        return {"id": cursor.lastrowid, "kind": kind, "query": query, "status": status, "plan": plan}

    def recent(self, limit: int = 30) -> list[dict[str, Any]]:
        import json

        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM real_world_workflows ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        result = []
        for row in rows:
            item = {key: row[key] for key in row.keys()}
            item["plan"] = json.loads(item.pop("plan_json") or "{}")
            result.append(item)
        return result


def purchase_risk(text: str) -> dict[str, Any]:
    matches = sorted(set(match.group(0).lower() for match in PURCHASE_RISK.finditer(text)))
    return {"risk": "HIGH" if matches else "LOW", "matches": matches, "checkout_blocked": bool(matches)}


def shopping_plan(query: str, *, store: RealWorldStore | None = None) -> RealWorldResult:
    store = store or RealWorldStore()
    risk = purchase_risk(query)
    plan = {
        "steps": ["clarify requirements", "compare options", "summarize prices", "stop before checkout"],
        "price_comparison": {"fields": ["price", "delivery", "rating", "return policy"]},
        "checkout_requires_approval": True,
        "purchase_risk": risk,
    }
    status = "blocked" if risk["checkout_blocked"] else "handled"
    record = store.record("shopping", query, status, plan)
    message = "I blocked checkout/payment. I can still help compare options." if status == "blocked" else "Prepared shopping research workflow."
    return RealWorldResult(status, message, {"workflow": record})


def booking_plan(kind: str, query: str, *, store: RealWorldStore | None = None) -> RealWorldResult:
    store = store or RealWorldStore()
    kind = kind if kind in {"flights", "trains", "cabs"} else "booking"
    plan = {
        "kind": kind,
        "steps": ["collect dates and route", "compare providers", "summarize options", "require approval before booking"],
        "fields": ["price", "time", "cancellation", "baggage/route details"],
        "booking_requires_approval": True,
    }
    record = store.record(kind, query, "handled", plan)
    return RealWorldResult("handled", f"Prepared {kind} research plan.", {"workflow": record})


def reminder_linked_task(text: str) -> RealWorldResult:
    return RealWorldResult(
        "handled",
        "Prepared reminder-linked task plan.",
        {"task": text, "suggested_reminder": "Ask Grandpa to schedule this once date/time is clear."},
    )


def diagnostics(store: RealWorldStore | None = None) -> dict[str, Any]:
    store = store or RealWorldStore()
    return {
        "status": "ready",
        "active_workflows": store.recent(),
        "features": {
            "shopping_research": True,
            "price_comparison": True,
            "booking_planner": ["flights", "trains", "cabs"],
            "reminder_linked_tasks": True,
            "checkout_protection": True,
        },
        "safety": {"never_auto_purchase": True, "payment_requires_approval": True, "no_silent_submissions": True},
        "storage": {"backend": "sqlite", "path": str(store.db_path), "local_only": True},
    }


def _json(value: dict[str, Any]) -> str:
    import json

    return json.dumps(value)


__all__ = [
    "RealWorldResult",
    "RealWorldStore",
    "booking_plan",
    "diagnostics",
    "purchase_risk",
    "reminder_linked_task",
    "shopping_plan",
]
