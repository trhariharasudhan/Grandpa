"""SQLite storage for declarative user-defined Grandpa skills."""

from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

DEFAULT_USER_SKILLS_DB = Path("runtime") / "skills" / "user_skills.db"


class UserSkillStore:
    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(
            db_path or os.getenv("GRANDPA_USER_SKILLS_DB") or DEFAULT_USER_SKILLS_DB
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
                CREATE TABLE IF NOT EXISTS user_skills (
                    skill_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    description TEXT NOT NULL,
                    trigger_phrases TEXT NOT NULL,
                    workflow_steps TEXT NOT NULL,
                    approval_requirements TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    usage_count INTEGER NOT NULL DEFAULT 0,
                    success_count INTEGER NOT NULL DEFAULT 0,
                    deleted INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_user_skills_deleted_updated ON user_skills(deleted, updated_at DESC)"
            )

    def create(self, data: dict[str, Any]) -> dict[str, Any]:
        now = time.time()
        skill_id = data.get("skill_id") or f"user_skill_{uuid.uuid4().hex[:12]}"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO user_skills (
                    skill_id, name, description, trigger_phrases, workflow_steps,
                    approval_requirements, created_at, updated_at, usage_count, success_count, deleted
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0)
                """,
                (
                    skill_id,
                    data["name"],
                    data["description"],
                    json.dumps(data["trigger_phrases"]),
                    json.dumps(data["workflow_steps"]),
                    json.dumps(data["approval_requirements"]),
                    now,
                    now,
                ),
            )
        return self.get(skill_id)

    def get(self, skill_id_or_name: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM user_skills
                WHERE deleted = 0 AND (skill_id = ? OR lower(name) = lower(?))
                """,
                (skill_id_or_name, skill_id_or_name),
            ).fetchone()
        if row is None:
            raise KeyError(f"Unknown user skill: {skill_id_or_name}")
        return _row_to_skill(row)

    def list(self, *, limit: int = 100, query: str = "") -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 500))
        pattern = f"%{query.strip()}%"
        with self._connect() as conn:
            if query.strip():
                rows = conn.execute(
                    """
                    SELECT * FROM user_skills
                    WHERE deleted = 0
                      AND (name LIKE ? OR description LIKE ? OR trigger_phrases LIKE ?)
                    ORDER BY updated_at DESC LIMIT ?
                    """,
                    (pattern, pattern, pattern, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM user_skills WHERE deleted = 0 ORDER BY updated_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [_row_to_skill(row) for row in rows]

    def delete(self, skill_id_or_name: str) -> dict[str, Any]:
        skill = self.get(skill_id_or_name)
        with self._connect() as conn:
            conn.execute(
                "UPDATE user_skills SET deleted = 1, updated_at = ? WHERE skill_id = ?",
                (time.time(), skill["skill_id"]),
            )
        return {**skill, "deleted": True}

    def record_usage(self, skill_id: str, *, success: bool) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE user_skills
                SET usage_count = usage_count + 1,
                    success_count = success_count + ?,
                    updated_at = ?
                WHERE skill_id = ?
                """,
                (1 if success else 0, time.time(), skill_id),
            )

    def diagnostics(self) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS count,
                       COALESCE(SUM(usage_count), 0) AS usage_count,
                       COALESCE(SUM(success_count), 0) AS success_count
                FROM user_skills
                WHERE deleted = 0
                """
            ).fetchone()
        usage = int(row["usage_count"])
        success = int(row["success_count"])
        return {
            "status": "ready",
            "db_path": str(self.db_path),
            "skill_count": int(row["count"]),
            "usage_count": usage,
            "success_count": success,
            "success_rate": round(success / usage, 3) if usage else 0.0,
            "local_only": True,
        }


def _row_to_skill(row: sqlite3.Row) -> dict[str, Any]:
    usage = int(row["usage_count"])
    success = int(row["success_count"])
    return {
        "skill_id": row["skill_id"],
        "name": row["name"],
        "description": row["description"],
        "trigger_phrases": _loads(row["trigger_phrases"], []),
        "workflow_steps": _loads(row["workflow_steps"], []),
        "approval_requirements": _loads(row["approval_requirements"], {}),
        "created_at": float(row["created_at"]),
        "updated_at": float(row["updated_at"]),
        "usage_count": usage,
        "success_count": success,
        "success_rate": round(success / usage, 3) if usage else 0.0,
    }


def _loads(raw: str, fallback: Any) -> Any:
    try:
        return json.loads(raw)
    except Exception:
        return fallback


__all__ = ["DEFAULT_USER_SKILLS_DB", "UserSkillStore"]
