"""Safe visible-browser control and page awareness for Grandpa.

This module is deliberately conservative. It never launches hidden/headless
browser sessions and never reads password-like fields. Rich DOM extraction is
available only from explicit visible-page context supplied by a trusted local
adapter; otherwise Grandpa reports that DOM access is unavailable.
"""

from __future__ import annotations

import html.parser
import json
import os
import sqlite3
import sys
import time
import urllib.parse
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from grandpa.core.config import DEFAULT_CONFIG_DIR

DEFAULT_BROWSER_DB = DEFAULT_CONFIG_DIR / "browser_context.db"
_BROWSER_SUFFIXES = (
    " - Google Chrome",
    " - Microsoft Edge",
    " - Chrome",
    " - Edge",
)
_BROWSER_KEYWORDS = {
    "chrome": ("chrome", "google chrome"),
    "edge": ("edge", "microsoft edge"),
}
_SAFE_ELEMENT_ROLES = {"link", "button", "heading", "input"}
_HIGH_RISK_WORDS = (
    "password",
    "login",
    "sign in",
    "submit",
    "checkout",
    "credit card",
    "card number",
    "cvv",
    "payment",
    "purchase",
    "buy",
    "pay",
)
_SNAPSHOT_MAX_AGE_SECONDS = 180
_SECRET_VALUE_RE = (
    r"(?i)\b(?:api[_-]?key|token|secret|password|passwd|bearer)\b\s*[:=]\s*['\"]?[\w\-\.]{8,}",
    r"\b(?:sk|pk|xoxp|xoxb|ghp|gho|github_pat)_[A-Za-z0-9_\-]{10,}",
    r"\b[A-Za-z0-9_\-]{24,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b",
    r"\b(?:\d[ -]*?){13,19}\b",
)

BrowserActionStatus = Literal[
    "handled",
    "requires_confirmation",
    "blocked",
    "unsupported",
    "error",
]


@dataclass(frozen=True)
class BrowserContext:
    supported: bool
    browser: str | None = None
    title: str | None = None
    url: str | None = None
    active_window_title: str | None = None
    headings: tuple[str, ...] = ()
    buttons: tuple[str, ...] = ()
    links: tuple[dict[str, str], ...] = ()
    inputs: tuple[dict[str, str], ...] = ()
    visible_text: str = ""
    media: tuple[dict[str, Any], ...] = ()
    forms: tuple[dict[str, Any], ...] = ()
    elements: tuple[dict[str, Any], ...] = ()
    session: dict[str, Any] | None = None
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "supported": self.supported,
            "browser": self.browser,
            "title": self.title,
            "url": self.url,
            "active_window_title": self.active_window_title,
            "headings": list(self.headings),
            "buttons": list(self.buttons),
            "links": list(self.links),
            "inputs": list(self.inputs),
            "visible_text": self.visible_text,
            "media": list(self.media),
            "forms": list(self.forms),
            "elements": list(self.elements),
            "session": self.session or {},
            "message": self.message,
            "local_only": True,
        }


@dataclass(frozen=True)
class BrowserActionResult:
    status: BrowserActionStatus
    action: str
    target: str
    message: str
    risk_level: str = "LOW"
    context: BrowserContext | None = None


class BrowserContextStore:
    """SQLite-backed local browser activity memory."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = Path(db_path or os.environ.get("GRANDPA_BROWSER_DB") or DEFAULT_BROWSER_DB)
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
                CREATE TABLE IF NOT EXISTS browser_activity (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at REAL NOT NULL,
                    action TEXT NOT NULL,
                    title TEXT,
                    url TEXT,
                    query TEXT,
                    status TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS browser_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at REAL NOT NULL,
                    title TEXT,
                    url TEXT,
                    headings_json TEXT NOT NULL,
                    links_json TEXT NOT NULL,
                    buttons_json TEXT NOT NULL,
                    inputs_json TEXT NOT NULL,
                    visible_text TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'extension',
                    media_json TEXT NOT NULL DEFAULT '[]',
                    forms_json TEXT NOT NULL DEFAULT '[]',
                    elements_json TEXT NOT NULL DEFAULT '[]',
                    session_json TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            _ensure_snapshot_columns(conn)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_browser_activity_created "
                "ON browser_activity(created_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_browser_snapshots_created "
                "ON browser_snapshots(created_at)"
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS browser_commands (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at REAL NOT NULL,
                    completed_at REAL,
                    action TEXT NOT NULL,
                    target TEXT NOT NULL,
                    page_url TEXT,
                    status TEXT NOT NULL,
                    result_json TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_browser_commands_status "
                "ON browser_commands(status, created_at)"
            )

    def record(
        self,
        action: str,
        *,
        title: str | None = None,
        url: str | None = None,
        query: str | None = None,
        status: str = "handled",
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO browser_activity(created_at, action, title, url, query, status)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (time.time(), action, title, url, query, status),
            )

    def recent(self, limit: int = 10) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, created_at, action, title, url, query, status
                FROM browser_activity
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [{key: row[key] for key in row.keys()} for row in rows]

    def store_snapshot(self, payload: dict[str, Any]) -> dict[str, Any]:
        snapshot = _sanitize_dom_context(payload)
        created_at = time.time()
        title = snapshot.get("title") or ""
        url = snapshot.get("url") or ""
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO browser_snapshots(
                    created_at, title, url, headings_json, links_json,
                    buttons_json, inputs_json, visible_text, source,
                    media_json, forms_json, elements_json, session_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    created_at,
                    title,
                    url,
                    json.dumps(snapshot.get("headings") or []),
                    json.dumps(snapshot.get("links") or []),
                    json.dumps(snapshot.get("buttons") or []),
                    json.dumps(snapshot.get("inputs") or []),
                    snapshot.get("visible_text") or "",
                    str(payload.get("source") or "extension")[:80],
                    json.dumps(snapshot.get("media") or []),
                    json.dumps(snapshot.get("forms") or []),
                    json.dumps(snapshot.get("elements") or []),
                    json.dumps(snapshot.get("session") or {}),
                ),
            )
            conn.execute(
                """
                INSERT INTO browser_activity(created_at, action, title, url, query, status)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (created_at, "snapshot", title, url, None, "handled"),
            )
            snapshot_id = int(cur.lastrowid)
        latest = self.latest_snapshot(max_age_seconds=None) or {}
        latest["id"] = snapshot_id
        return latest

    def latest_snapshot(self, *, max_age_seconds: int | None = _SNAPSHOT_MAX_AGE_SECONDS) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, created_at, title, url, headings_json, links_json,
                       buttons_json, inputs_json, visible_text, source,
                       media_json, forms_json, elements_json, session_json
                FROM browser_snapshots
                ORDER BY created_at DESC
                LIMIT 1
                """
            ).fetchone()
        if not row:
            return None
        age_seconds = time.time() - float(row["created_at"])
        if max_age_seconds is not None and age_seconds > max_age_seconds:
            return None
        return {
            "id": row["id"],
            "created_at": row["created_at"],
            "age_seconds": age_seconds,
            "title": row["title"],
            "url": row["url"],
            "headings": _json_list(row["headings_json"]),
            "links": _json_list(row["links_json"]),
            "buttons": _json_list(row["buttons_json"]),
            "inputs": _json_list(row["inputs_json"]),
            "visible_text": row["visible_text"],
            "source": row["source"],
            "media": _json_list(row["media_json"]),
            "forms": _json_list(row["forms_json"]),
            "elements": _json_list(row["elements_json"]),
            "session": _json_dict(row["session_json"]),
            "connected": True,
        }

    def clear_snapshots(self) -> int:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM browser_snapshots")
            return int(cur.rowcount or 0)

    def enqueue_command(self, action: str, target: str, *, page_url: str | None = None) -> dict[str, Any]:
        now = time.time()
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO browser_commands(created_at, action, target, page_url, status, result_json)
                VALUES (?, ?, ?, ?, 'pending', '{}')
                """,
                (now, action, target, page_url),
            )
            command_id = int(cur.lastrowid)
        return {"id": command_id, "action": action, "target": target, "page_url": page_url, "status": "pending"}

    def next_command(self, *, page_url: str = "") -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, created_at, action, target, page_url, status
                FROM browser_commands
                WHERE status = 'pending'
                  AND (? = '' OR page_url IS NULL OR page_url = '' OR page_url = ?)
                ORDER BY created_at ASC
                LIMIT 1
                """,
                (page_url, page_url),
            ).fetchone()
            if not row:
                return None
            conn.execute(
                "UPDATE browser_commands SET status = 'claimed' WHERE id = ? AND status = 'pending'",
                (row["id"],),
            )
        return {key: row[key] for key in row.keys()}

    def complete_command(self, command_id: int, *, status: str, result: dict[str, Any] | None = None) -> dict[str, Any]:
        clean_status = "completed" if status == "completed" else "failed"
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE browser_commands
                SET status = ?, completed_at = ?, result_json = ?
                WHERE id = ?
                """,
                (clean_status, time.time(), json.dumps(result or {}, ensure_ascii=True), command_id),
            )
        return {"id": command_id, "status": clean_status}


def get_visible_browser_context() -> BrowserContext:
    """Return context for the active visible Chrome/Edge window."""

    snapshot = BrowserContextStore().latest_snapshot()
    if snapshot:
        context = _context_from_snapshot(snapshot)
        try:
            BrowserContextStore().record("context", title=context.title, url=context.url)
        except Exception:
            pass
        return context

    if sys.platform != "win32":
        return BrowserContext(
            supported=False,
            message=(
                "Browser extension is not connected yet. Load the Grandpa browser "
                "extension in Chrome or Edge, then refresh the page."
            ),
        )

    title = _active_window_title()
    browser = _browser_from_title(title)
    if not browser:
        return BrowserContext(
            supported=False,
            active_window_title=title or None,
            message="I could not find Chrome or Edge as the active visible browser.",
        )

    page_title = _strip_browser_suffix(title)
    dom = _load_visible_dom_context()
    context = BrowserContext(
        supported=True,
        browser=browser,
        title=dom.get("title") or page_title or title,
        url=dom.get("url") or os.environ.get("GRANDPA_BROWSER_ACTIVE_URL"),
        active_window_title=title,
        headings=tuple(dom.get("headings") or ()),
        buttons=tuple(dom.get("buttons") or ()),
        links=tuple(dom.get("links") or ()),
        inputs=tuple(dom.get("inputs") or ()),
        visible_text=str(dom.get("visible_text") or ""),
        media=tuple(dom.get("media") or ()),
        forms=tuple(dom.get("forms") or ()),
        elements=tuple(dom.get("elements") or ()),
        session=dom.get("session") or {},
        message="Visible browser context is available.",
    )
    try:
        BrowserContextStore().record("context", title=context.title, url=context.url)
    except Exception:
        pass
    return context


def execute_browser_action(action: str, target: str = "") -> BrowserActionResult:
    """Execute a guarded browser action against the visible browser surface."""

    if action == "context":
        context = get_visible_browser_context()
        if not context.supported:
            return BrowserActionResult("unsupported", action, target, context.message, context=context)
        details = [f"You are on {context.title or 'an active browser page'}."]
        if context.url:
            details.append(f"URL: {context.url}")
        details.append(f"Browser: {context.browser}.")
        return BrowserActionResult("handled", action, target, " ".join(details), context=context)

    if action == "tabs":
        context = get_visible_browser_context()
        recent = BrowserContextStore().recent(limit=8)
        if not context.supported and not recent:
            return BrowserActionResult("unsupported", action, target, context.message, context=context)
        lines = ["Recent visible browser activity:"]
        if context.supported:
            lines.append(f"- Active: {context.title or context.active_window_title}")
        for item in recent[:6]:
            label = item.get("title") or item.get("query") or item.get("url") or item["action"]
            lines.append(f"- {label}")
        return BrowserActionResult("handled", action, target, "\n".join(lines), context=context)

    if action == "diagnostics":
        context = get_visible_browser_context()
        latest = latest_browser_snapshot()
        recent = BrowserContextStore().recent(limit=10)
        message = "Browser diagnostics are ready."
        if not latest.get("connected"):
            message = "Browser diagnostics are ready, but the extension is not connected."
        details = {
            "extension_connected": bool(latest.get("connected")),
            "snapshot_age_seconds": latest.get("snapshot", {}).get("age_seconds") if latest.get("snapshot") else None,
            "current_title": context.title,
            "current_url": context.url,
            "counts": {
                "headings": len(context.headings),
                "links": len(context.links),
                "buttons": len(context.buttons),
                "inputs": len(context.inputs),
                "media": len(context.media),
                "forms": len(context.forms),
                "elements": len(context.elements),
            },
            "recent_activity": recent,
            "local_only": True,
        }
        return BrowserActionResult("handled", action, json.dumps(details), message, context=context)

    if action == "headings":
        context = get_visible_browser_context()
        if not context.supported:
            return BrowserActionResult("unsupported", action, target, context.message, context=context)
        if not context.headings:
            return BrowserActionResult(
                "unsupported",
                action,
                target,
                "I can see the browser window, but DOM headings are not available yet.",
                context=context,
            )
        headings = "\n".join(f"- {heading}" for heading in context.headings[:10])
        return BrowserActionResult("handled", action, target, f"Visible headings:\n{headings}", context=context)

    if action == "links":
        context = get_visible_browser_context()
        if not context.supported:
            return BrowserActionResult("unsupported", action, target, context.message, context=context)
        if not context.links:
            return BrowserActionResult(
                "unsupported",
                action,
                target,
                "I do not see any visible links in the latest browser snapshot.",
                context=context,
            )
        lines = []
        for link in context.links[:12]:
            text = link.get("text") or link.get("href") or "Untitled link"
            href = link.get("href") or ""
            lines.append(f"- {text}" + (f" ({href})" if href else ""))
        return BrowserActionResult("handled", action, target, "Visible links:\n" + "\n".join(lines), context=context)

    if action == "buttons":
        context = get_visible_browser_context()
        if not context.supported:
            return BrowserActionResult("unsupported", action, target, context.message, context=context)
        if not context.buttons:
            return BrowserActionResult(
                "unsupported",
                action,
                target,
                "I do not see any visible buttons in the latest browser snapshot.",
                context=context,
            )
        buttons = "\n".join(f"- {button}" for button in context.buttons[:12])
        return BrowserActionResult("handled", action, target, f"Visible buttons:\n{buttons}", context=context)

    if action == "summary":
        context = get_visible_browser_context()
        if not context.supported:
            return BrowserActionResult("unsupported", action, target, context.message, context=context)
        text = context.visible_text.strip()
        if not text:
            return BrowserActionResult(
                "unsupported",
                action,
                target,
                "I can see the browser window, but readable page text is not available yet.",
                context=context,
            )
        summary = _summarize_visible_text(text)
        return BrowserActionResult("handled", action, target, summary, context=context)

    if action == "media":
        context = get_visible_browser_context()
        if not context.supported:
            return BrowserActionResult("unsupported", action, target, context.message, context=context)
        return _browser_media_action(target, context)

    if action == "form_fill":
        if _looks_high_risk(target):
            return BrowserActionResult("blocked", action, target, "I blocked this form action for safety.", risk_level="BLOCKED")
        context = get_visible_browser_context()
        if not context.supported:
            return BrowserActionResult("unsupported", action, target, context.message, context=context)
        return BrowserActionResult(
            "requires_confirmation",
            action,
            target,
            "Confirmation required before filling a visible form field.",
            risk_level="MEDIUM",
            context=context,
        )

    if action == "download":
        if _looks_high_risk(target):
            return BrowserActionResult("blocked", action, target, "I blocked this download action for safety.", risk_level="BLOCKED")
        context = get_visible_browser_context()
        return BrowserActionResult(
            "requires_confirmation",
            action,
            target,
            "Confirmation required before starting a browser download.",
            risk_level="MEDIUM",
            context=context,
        )

    if action == "whatsapp":
        context = get_visible_browser_context()
        if "send" in target.lower() or "message" in target.lower():
            return BrowserActionResult(
                "requires_confirmation",
                action,
                target,
                "Confirmation required before interacting with WhatsApp Web.",
                risk_level="MEDIUM",
                context=context,
            )
        webbrowser.open("https://web.whatsapp.com")
        BrowserContextStore().record("whatsapp_open", url="https://web.whatsapp.com", status="handled")
        return BrowserActionResult("handled", action, target, "Opening WhatsApp Web.", context=context)

    if action == "task":
        store = BrowserContextStore()
        store.record("task", query=target, status="handled")
        return BrowserActionResult("handled", action, target, f"Browser task noted: {target}.")

    if action == "open":
        webbrowser.open(target)
        BrowserContextStore().record("open", url=target, status="handled")
        return BrowserActionResult("handled", action, target, f"Opening {target}.")

    if action == "new_tab":
        webbrowser.open_new_tab(target or "about:blank")
        BrowserContextStore().record("new_tab", url=target or "about:blank", status="handled")
        return BrowserActionResult("handled", action, target, "Opening a new browser tab.")

    if action == "search":
        url = _search_url(target)
        webbrowser.open(url)
        BrowserContextStore().record("search", url=url, query=target, status="handled")
        return BrowserActionResult("handled", action, target, f"Searching Google for {target}.")

    if action == "youtube_search":
        url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(target)
        webbrowser.open(url)
        BrowserContextStore().record("youtube_search", url=url, query=target, status="handled")
        return BrowserActionResult("handled", action, target, f"Opening YouTube and searching for {target}.")

    if action in {"back", "forward", "reload", "focus_search", "click"}:
        if action == "click" and _looks_high_risk(target):
            return BrowserActionResult(
                "blocked",
                action,
                target,
                "I blocked this browser action for safety.",
                risk_level="BLOCKED",
            )
        return BrowserActionResult(
            "requires_confirmation",
            action,
            target,
            "Confirmation required before controlling the visible browser.",
            risk_level="MEDIUM",
        )

    return BrowserActionResult("unsupported", action, target, "That browser action is not supported yet.")


def extract_dom_snapshot(html: str, *, title: str = "", url: str = "") -> BrowserContext:
    parser = _VisibleDomParser()
    parser.feed(html)
    return BrowserContext(
        supported=True,
        browser=None,
        title=title,
        url=url,
        headings=tuple(parser.headings),
        buttons=tuple(parser.buttons),
        links=tuple(parser.links),
        inputs=tuple(parser.inputs),
        visible_text=_clean_text(" ".join(parser.text_chunks))[:4000],
        media=(),
        forms=(),
        elements=(),
        session={"origin": urllib.parse.urlparse(url).netloc if url else ""},
        message="DOM snapshot extracted from visible page context.",
    )


def store_browser_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    """Persist a local-only visible page snapshot from the browser extension."""

    return BrowserContextStore().store_snapshot(payload)


def latest_browser_snapshot() -> dict[str, Any]:
    snapshot = BrowserContextStore().latest_snapshot(max_age_seconds=None)
    return {
        "connected": snapshot is not None,
        "snapshot": snapshot,
        "max_age_seconds": _SNAPSHOT_MAX_AGE_SECONDS,
        "local_only": True,
    }


def clear_browser_snapshot() -> dict[str, Any]:
    removed = BrowserContextStore().clear_snapshots()
    return {"status": "ok", "removed": removed}


def next_browser_command(page_url: str = "") -> dict[str, Any]:
    command = BrowserContextStore().next_command(page_url=page_url)
    return {"command": command, "local_only": True}


def complete_browser_command(command_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    status = str(payload.get("status") or "failed")
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    return BrowserContextStore().complete_command(command_id, status=status, result=result)


def _context_from_snapshot(snapshot: dict[str, Any]) -> BrowserContext:
    return BrowserContext(
        supported=True,
        browser="Chrome/Edge extension",
        title=str(snapshot.get("title") or ""),
        url=str(snapshot.get("url") or ""),
        active_window_title=str(snapshot.get("title") or ""),
        headings=tuple(str(item) for item in snapshot.get("headings") or ()),
        buttons=tuple(str(item) for item in snapshot.get("buttons") or ()),
        links=tuple(snapshot.get("links") or ()),
        inputs=tuple(snapshot.get("inputs") or ()),
        visible_text=str(snapshot.get("visible_text") or ""),
        media=tuple(snapshot.get("media") or ()),
        forms=tuple(snapshot.get("forms") or ()),
        elements=tuple(snapshot.get("elements") or ()),
        session=dict(snapshot.get("session") or {}),
        message="Browser extension snapshot is available.",
    )


def _active_window_title() -> str:
    try:
        from grandpa.windows_window_control import (
            _get_foreground_window,
            _get_window_title,
        )

        return _get_window_title(_get_foreground_window())
    except Exception:
        return ""


def _browser_from_title(title: str) -> str | None:
    lower = title.lower()
    for browser, keywords in _BROWSER_KEYWORDS.items():
        if any(keyword in lower for keyword in keywords):
            return "Chrome" if browser == "chrome" else "Microsoft Edge"
    return None


def _strip_browser_suffix(title: str) -> str:
    value = title.strip()
    for suffix in _BROWSER_SUFFIXES:
        if value.endswith(suffix):
            return value[: -len(suffix)].strip()
    return value


def _load_visible_dom_context() -> dict[str, Any]:
    raw = os.environ.get("GRANDPA_BROWSER_CONTEXT_JSON")
    if raw:
        try:
            data = json.loads(raw)
            return _sanitize_dom_context(data)
        except Exception:
            return {}

    path = os.environ.get("GRANDPA_BROWSER_CONTEXT_FILE")
    if path:
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            return _sanitize_dom_context(data)
        except Exception:
            return {}
    return {}


def _sanitize_dom_context(data: dict[str, Any]) -> dict[str, Any]:
    visible_text = str(data.get("visible_text") or data.get("text") or "")
    if data.get("html") and not visible_text:
        snapshot = extract_dom_snapshot(str(data["html"]), title=str(data.get("title") or ""), url=str(data.get("url") or ""))
        return snapshot.to_dict()
    return {
        "title": str(data.get("title") or "")[:300],
        "url": str(data.get("url") or "")[:1000],
        "headings": _safe_strings(data.get("headings")),
        "buttons": _safe_strings(data.get("buttons")),
        "links": _safe_links(data.get("links")),
        "inputs": _safe_inputs(data.get("inputs")),
        "media": _safe_media(data.get("media")),
        "forms": _safe_forms(data.get("forms")),
        "elements": _safe_elements(data.get("elements")),
        "session": _safe_session(data.get("session"), str(data.get("url") or "")),
        "visible_text": _redact_sensitive_visible_text(visible_text)[:4000],
    }


def _ensure_snapshot_columns(conn: sqlite3.Connection) -> None:
    rows = conn.execute("PRAGMA table_info(browser_snapshots)").fetchall()
    existing = {str(row[1]) for row in rows}
    for name, default in {
        "media_json": "'[]'",
        "forms_json": "'[]'",
        "elements_json": "'[]'",
        "session_json": "'{}'",
    }.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE browser_snapshots ADD COLUMN {name} TEXT NOT NULL DEFAULT {default}")


def _safe_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_redact_sensitive_visible_text(str(item))[:160] for item in value[:25] if str(item).strip()]


def _safe_links(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    links = []
    for item in value[:25]:
        if isinstance(item, dict):
            text = _redact_sensitive_visible_text(str(item.get("text") or ""))[:160]
            href = str(item.get("href") or "")[:1000]
        else:
            text = _redact_sensitive_visible_text(str(item))[:160]
            href = ""
        if text or href:
            links.append({"text": text, "href": href})
    return links


def _safe_inputs(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    inputs = []
    for item in value[:20]:
        if not isinstance(item, dict):
            continue
        input_type = str(item.get("type") or "").lower()
        if input_type in {"password", "hidden"}:
            continue
        raw_label = str(item.get("label") or item.get("name") or item.get("placeholder") or "")
        if _looks_high_risk(raw_label):
            continue
        label = _redact_sensitive_visible_text(raw_label)[:160]
        inputs.append({"label": label, "type": input_type or "text"})
    return inputs


def _safe_media(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    media = []
    for item in value[:20]:
        if not isinstance(item, dict):
            continue
        media.append(
            {
                "kind": str(item.get("kind") or "media")[:30],
                "paused": bool(item.get("paused", False)),
                "muted": bool(item.get("muted", False)),
                "duration": float(item.get("duration") or 0),
                "current_time": float(item.get("current_time") or item.get("currentTime") or 0),
                "label": _redact_sensitive_visible_text(str(item.get("label") or ""))[:160],
            }
        )
    return media


def _safe_forms(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    forms = []
    for item in value[:10]:
        if not isinstance(item, dict):
            continue
        label = _redact_sensitive_visible_text(str(item.get("label") or item.get("name") or "form"))[:160]
        fields = []
        for field in item.get("fields") or []:
            if not isinstance(field, dict):
                continue
            raw = f"{field.get('type', '')} {field.get('label', '')}"
            if _looks_high_risk(raw):
                continue
            fields.append({
                "label": _redact_sensitive_visible_text(str(field.get("label") or ""))[:120],
                "type": str(field.get("type") or "text")[:40],
            })
        forms.append({"label": label, "fields": fields[:20], "submit_count": int(item.get("submit_count") or 0)})
    return forms


def _safe_elements(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    elements = []
    for item in value[:80]:
        if not isinstance(item, dict):
            continue
        text = _redact_sensitive_visible_text(str(item.get("text") or item.get("label") or ""))[:160]
        role = str(item.get("role") or "")[:40].lower()
        if role not in _SAFE_ELEMENT_ROLES and role not in {"media", "form", "tab"}:
            role = "element"
        if _looks_high_risk(text):
            continue
        elements.append({
            "id": str(item.get("id") or "")[:80],
            "role": role,
            "text": text,
            "visible": bool(item.get("visible", True)),
        })
    return elements


def _safe_session(value: Any, url: str) -> dict[str, Any]:
    parsed = urllib.parse.urlparse(url)
    session = {
        "origin": parsed.netloc,
        "path": parsed.path[:240],
        "is_youtube": "youtube.com" in parsed.netloc or "youtu.be" in parsed.netloc,
        "is_whatsapp": "web.whatsapp.com" in parsed.netloc,
    }
    if isinstance(value, dict):
        session["visibility"] = str(value.get("visibility") or "")[:40]
        session["focused"] = bool(value.get("focused", False))
    return session


def _json_dict(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def _browser_media_action(target: str, context: BrowserContext) -> BrowserActionResult:
    command = target.lower().strip()
    if not context.media:
        return BrowserActionResult("unsupported", "media", target, "I do not see visible media controls in the latest browser snapshot.", context=context)
    if any(word in command for word in ("play", "pause", "mute", "unmute", "volume", "seek", "next", "previous")):
        risk = "LOW" if any(word in command for word in ("play", "pause", "mute", "unmute")) else "MEDIUM"
        status: BrowserActionStatus = "handled" if risk == "LOW" else "requires_confirmation"
        store = BrowserContextStore()
        store.record("media", title=context.title, url=context.url, query=target, status=status)
        queued = store.enqueue_command("media", target, page_url=context.url) if status == "handled" else None
        return BrowserActionResult(
            status,
            "media",
            target,
            f"Queued visible media action: {target}." if queued else f"Prepared visible media action: {target}.",
            risk_level=risk,
            context=context,
        )
    return BrowserActionResult("unsupported", "media", target, "That media action is not supported yet.", context=context)


def _redact_sensitive_visible_text(text: str) -> str:
    redacted = " ".join(
        "[redacted]" if _looks_high_risk(part) else part
        for part in text.split()
    )
    import re

    for pattern in _SECRET_VALUE_RE:
        redacted = re.sub(pattern, "[redacted]", redacted)
    return redacted


def _looks_high_risk(text: str) -> bool:
    lower = text.lower()
    return any(word in lower for word in _HIGH_RISK_WORDS)


def _json_list(raw: str) -> list[Any]:
    try:
        value = json.loads(raw or "[]")
    except Exception:
        return []
    return value if isinstance(value, list) else []


def _search_url(query: str) -> str:
    return "https://www.google.com/search?q=" + urllib.parse.quote_plus(query)


def _summarize_visible_text(text: str) -> str:
    cleaned = _clean_text(text)
    sentences = [part.strip() for part in cleaned.replace("\n", " ").split(".") if part.strip()]
    if not sentences:
        return "The visible page text is available, but it is too sparse to summarize."
    summary = ". ".join(sentences[:3])
    if summary and not summary.endswith("."):
        summary += "."
    return f"Visible page summary: {summary}"


def _clean_text(text: str) -> str:
    return " ".join(text.split())


class _VisibleDomParser(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.stack: list[str] = []
        self.current_href = ""
        self.headings: list[str] = []
        self.buttons: list[str] = []
        self.links: list[dict[str, str]] = []
        self.inputs: list[dict[str, str]] = []
        self.text_chunks: list[str] = []
        self._buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {name.lower(): value or "" for name, value in attrs}
        if tag == "input":
            input_type = attr_map.get("type", "text").lower()
            if input_type not in {"password", "hidden"}:
                self.inputs.append({
                    "label": attr_map.get("aria-label") or attr_map.get("placeholder") or attr_map.get("name") or "",
                    "type": input_type,
                })
        if tag == "a":
            self.current_href = attr_map.get("href", "")
        self.stack.append(tag)
        self._buffer = []

    def handle_endtag(self, tag: str) -> None:
        text = _redact_sensitive_visible_text(_clean_text(" ".join(self._buffer)))
        if text:
            if tag in {"h1", "h2", "h3"} and len(self.headings) < 25:
                self.headings.append(text[:160])
            elif tag == "button" and len(self.buttons) < 25:
                self.buttons.append(text[:160])
            elif tag == "a" and len(self.links) < 25:
                self.links.append({"text": text[:160], "href": self.current_href[:1000]})
            self.text_chunks.append(text)
        if self.stack:
            self.stack.pop()
        self._buffer = []
        if tag == "a":
            self.current_href = ""

    def handle_data(self, data: str) -> None:
        if self.stack and self.stack[-1] in {"script", "style", "noscript"}:
            return
        text = data.strip()
        if text:
            self._buffer.append(text)


__all__ = [
    "BrowserActionResult",
    "BrowserContext",
    "BrowserContextStore",
    "execute_browser_action",
    "extract_dom_snapshot",
    "get_visible_browser_context",
    "store_browser_snapshot",
    "latest_browser_snapshot",
    "clear_browser_snapshot",
    "next_browser_command",
    "complete_browser_command",
]
