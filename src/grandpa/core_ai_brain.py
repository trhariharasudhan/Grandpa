"""Local conversational brain state for Grandpa.

The brain layer keeps lightweight local context around recent turns, habits,
tone, and language continuity. It is intentionally deterministic and local-only:
no cloud calls, no hidden profiling, and no guessing when confidence is low.
"""

from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from grandpa.core.config import DEFAULT_CONFIG_DIR


DEFAULT_BRAIN_DB = DEFAULT_CONFIG_DIR / "core_brain.db"
TAMIL_RE = re.compile(r"[\u0B80-\u0BFF]")

Tone = Literal["casual", "frustrated", "confused", "urgent", "neutral"]


@dataclass(frozen=True)
class BrainAnalysis:
    original_text: str
    effective_text: str
    language: str
    tone: Tone
    confidence: float
    follow_up_resolved: bool
    reason: str = ""


class BrainStore:
    """SQLite-backed local profile, habit, and turn-state store."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = Path(db_path or DEFAULT_BRAIN_DB)
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
                CREATE TABLE IF NOT EXISTS brain_turns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at REAL NOT NULL,
                    user_text TEXT NOT NULL,
                    effective_text TEXT NOT NULL,
                    assistant_text TEXT,
                    kind TEXT,
                    target TEXT,
                    status TEXT,
                    language TEXT NOT NULL,
                    tone TEXT NOT NULL,
                    confidence REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS brain_habits (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    updated_at REAL NOT NULL,
                    habit_type TEXT NOT NULL,
                    key TEXT NOT NULL,
                    label TEXT NOT NULL,
                    count INTEGER NOT NULL DEFAULT 1,
                    last_seen_at REAL NOT NULL,
                    UNIQUE(habit_type, key)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_brain_turns_created ON brain_turns(created_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_brain_habits_lookup ON brain_habits(habit_type, key)"
            )

    def last_action(self) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT user_text, effective_text, assistant_text, kind, target, status,
                       language, tone, confidence, created_at
                FROM brain_turns
                WHERE kind IS NOT NULL AND target IS NOT NULL AND target != ''
                ORDER BY created_at DESC
                LIMIT 1
                """
            ).fetchone()
        return _row_to_dict(row) if row else None

    def recent_turns(self, limit: int = 8) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT user_text, effective_text, assistant_text, kind, target, status,
                       language, tone, confidence, created_at
                FROM brain_turns
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [_row_to_dict(row) for row in rows]

    def record_turn(
        self,
        *,
        analysis: BrainAnalysis,
        assistant_text: str | None = None,
        kind: str | None = None,
        target: str | None = None,
        status: str | None = None,
    ) -> None:
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO brain_turns(
                    created_at, user_text, effective_text, assistant_text, kind, target,
                    status, language, tone, confidence
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    now,
                    analysis.original_text,
                    analysis.effective_text,
                    assistant_text,
                    kind,
                    target,
                    status,
                    analysis.language,
                    analysis.tone,
                    analysis.confidence,
                ),
            )
        self._learn_habits(analysis.effective_text, kind=kind, target=target, status=status)

    def _learn_habits(
        self,
        text: str,
        *,
        kind: str | None,
        target: str | None,
        status: str | None,
    ) -> None:
        if status not in {None, "handled", "completed", "dry_run"}:
            return
        lowered = text.lower()
        habits: list[tuple[str, str, str]] = []
        if kind in {"app", "window"} and target:
            habits.append(("preferred_app", _habit_key(target), _friendly_target(target)))
        if kind in {"url", "browser"} and target:
            site = _site_from_target(target)
            if site:
                habits.append(("common_site", _habit_key(site), site))
        if "vs code" in lowered or "vscode" in lowered:
            habits.append(("preferred_tool", "vs_code", "VS Code"))
        if "chrome" in lowered:
            habits.append(("preferred_app", "chrome", "Chrome"))
        if "youtube" in lowered:
            habits.append(("common_site", "youtube", "YouTube"))
        for habit_type, key, label in dict.fromkeys(habits):
            self.upsert_habit(habit_type, key, label)

    def upsert_habit(self, habit_type: str, key: str, label: str) -> None:
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO brain_habits(updated_at, habit_type, key, label, count, last_seen_at)
                VALUES (?, ?, ?, ?, 1, ?)
                ON CONFLICT(habit_type, key)
                DO UPDATE SET updated_at=excluded.updated_at,
                              count=brain_habits.count + 1,
                              last_seen_at=excluded.last_seen_at,
                              label=excluded.label
                """,
                (now, habit_type, key, label, now),
            )

    def habit_score(self, text: str) -> float:
        tokens = {token for token in re.findall(r"[a-z0-9]+", text.lower()) if len(token) > 1}
        if not tokens:
            return 0.0
        score = 0.0
        for habit in self.habits(limit=50):
            habit_tokens = set(re.findall(r"[a-z0-9]+", f"{habit['key']} {habit['label']}".lower()))
            if tokens & habit_tokens:
                score += min(0.12, 0.03 * int(habit["count"]))
        return min(score, 0.3)

    def habits(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT habit_type, key, label, count, last_seen_at, updated_at
                FROM brain_habits
                ORDER BY count DESC, last_seen_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [_row_to_dict(row) for row in rows]


def analyze_user_text(text: str, *, store: BrainStore | None = None) -> BrainAnalysis:
    store = store or BrainStore()
    original = text.strip()
    language = detect_language(original)
    tone = detect_tone(original)
    resolved, confidence, reason = resolve_follow_up(original, store=store)
    return BrainAnalysis(
        original_text=original,
        effective_text=resolved,
        language=language,
        tone=tone,
        confidence=confidence,
        follow_up_resolved=resolved != original,
        reason=reason,
    )


def resolve_follow_up(text: str, *, store: BrainStore | None = None) -> tuple[str, float, str]:
    store = store or BrainStore()
    lower = text.lower().strip(" ?!.")
    last = store.last_action()
    if not last:
        return text, 0.35, "no previous action"

    kind = str(last.get("kind") or "")
    target = str(last.get("target") or "")
    if lower in {"open it", "open that", "launch it"} and target:
        if kind in {"app", "window"}:
            return f"open {_friendly_target(target)}", 0.82, "resolved app follow-up"
        if kind in {"url", "browser"}:
            return f"open {target}", 0.74, "resolved browser follow-up"

    if lower in {"close it", "close that"} and target:
        if kind in {"app", "window"}:
            return f"close {_friendly_target(target)}", 0.82, "resolved close follow-up"
        return text, 0.42, "last target is not safely closable"

    if lower in {"summarize again", "summarise again", "summarize it", "summarise it"}:
        if kind in {"browser", "screen"}:
            return "summarize this webpage", 0.8, "resolved browser summary follow-up"
        if kind == "file":
            return "summarize this document", 0.66, "resolved file summary follow-up"

    if lower in {"do that again", "again"}:
        effective = str(last.get("effective_text") or "")
        if effective:
            return effective, 0.7, "repeat previous command"

    return text, 0.5, "direct request"


def detect_language(text: str) -> str:
    has_tamil = bool(TAMIL_RE.search(text))
    has_ascii_words = bool(re.search(r"[A-Za-z]{2,}", text))
    if has_tamil and has_ascii_words:
        return "ta-en"
    if has_tamil:
        return "ta"
    return "en"


def detect_tone(text: str) -> Tone:
    lower = text.lower()
    if any(word in lower for word in ("urgent", "asap", "quick", "immediately", "now")):
        return "urgent"
    if any(word in lower for word in ("confused", "don't understand", "what happened", "why", "enna", "epdi")):
        return "confused"
    if any(word in lower for word in ("annoying", "frustrated", "not working", "broken", "again?", "dei")):
        return "frustrated"
    if any(word in lower for word in ("da", "bro", "haha", "lol", "seri", "okay")):
        return "casual"
    return "neutral"


def build_brain_context(analysis: BrainAnalysis, *, store: BrainStore | None = None) -> str:
    store = store or BrainStore()
    habits = store.habits(limit=5)
    lines = [
        "Grandpa local brain context:",
        f"- Language continuity: {analysis.language}. If the user mixes Tamil and English, reply naturally in the same mixed style when useful.",
        f"- User tone: {analysis.tone}. Adjust warmth and brevity without over-explaining.",
        f"- Follow-up confidence: {analysis.confidence:.0%}. Do not invent context when confidence is low.",
    ]
    if analysis.follow_up_resolved:
        lines.append(f"- Resolved follow-up: {analysis.original_text!r} -> {analysis.effective_text!r}.")
    if habits:
        lines.append("- Learned local habits:")
        for habit in habits:
            lines.append(f"  - {habit['habit_type']}: {habit['label']} used {habit['count']} times")
    lines.append("- Keep responses concise, practical, safe, and Grandpa-branded.")
    return "\n".join(lines)


def process_user_message(text: str, *, store: BrainStore | None = None) -> BrainAnalysis:
    analysis = analyze_user_text(text, store=store)
    (store or BrainStore()).record_turn(analysis=analysis)
    return analysis


def record_assistant_outcome(
    analysis: BrainAnalysis,
    *,
    assistant_text: str,
    kind: str | None = None,
    target: str | None = None,
    status: str | None = None,
    store: BrainStore | None = None,
) -> None:
    (store or BrainStore()).record_turn(
        analysis=analysis,
        assistant_text=assistant_text,
        kind=kind,
        target=target,
        status=status,
    )


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def _habit_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")[:80] or "unknown"


def _friendly_target(target: str) -> str:
    target = target.split("|")[-1]
    target = target.replace("_", " ").strip()
    aliases = {
        "vscode": "VS Code",
        "vs code": "VS Code",
        "chrome": "Chrome",
        "edge": "Edge",
        "notepad": "Notepad",
        "calculator": "Calculator",
        "explorer": "File Explorer",
    }
    return aliases.get(target.lower(), target)


def _site_from_target(target: str) -> str | None:
    lower = target.lower()
    if "youtube" in lower:
        return "YouTube"
    if "google" in lower:
        return "Google"
    if "gmail" in lower:
        return "Gmail"
    if lower.startswith(("http://", "https://")):
        return lower.split("//", 1)[-1].split("/", 1)[0]
    return None


__all__ = [
    "BrainAnalysis",
    "BrainStore",
    "analyze_user_text",
    "build_brain_context",
    "detect_language",
    "detect_tone",
    "process_user_message",
    "record_assistant_outcome",
    "resolve_follow_up",
]
