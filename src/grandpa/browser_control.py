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
    acquisition_source: str = "unavailable"
    confidence: str = "Low"
    status: str = "unavailable"
    hwnd: int = 0
    process_name: str = ""

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
            "acquisition_source": self.acquisition_source,
            "confidence": self.confidence,
            "status": self.status,
            "hwnd": self.hwnd,
            "process_name": self.process_name,
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
                "CREATE INDEX IF NOT EXISTS idx_browser_activity_created "
                "ON browser_activity(created_at)"
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

def get_visible_browser_context() -> BrowserContext:
    """Return context for the active visible Chrome/Edge window."""

    if sys.platform != "win32":
        return BrowserContext(
            supported=False,
            message="Visible browser context is currently available only on Windows.",
        )

    browser_info = _find_visible_browser_window()
    if not browser_info:
        return BrowserContext(
            supported=False,
            message="I could not find an active visible Chrome or Edge browser webpage.",
        )

    hwnd, browser, title = browser_info
    page_title = _strip_browser_suffix(title)
    uia_url = _get_address_bar_url_for_hwnd(hwnd)
    dom = _load_visible_dom_context(hwnd)
    final_url = uia_url or dom.get("url") or os.environ.get("GRANDPA_BROWSER_ACTIVE_URL") or None

    pname = _get_process_name_for_hwnd(hwnd) if hwnd else ""
    acq_source = str(dom.get("acquisition_source") or ("accessibility_tree" if (dom.get("headings") or dom.get("paragraphs")) else ("uia_text" if dom.get("visible_text") else "unavailable")))
    confidence = str(dom.get("confidence") or ("High" if acq_source in ("full_dom", "accessibility_tree") else ("Medium" if acq_source == "uia_text" else "Low")))
    status = str(dom.get("status") or ("success" if acq_source in ("full_dom", "accessibility_tree") else ("partial_success" if dom.get("visible_text") else "unavailable")))

    context = BrowserContext(
        supported=True,
        browser=browser,
        title=dom.get("title") or page_title or title,
        url=final_url,
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
        acquisition_source=acq_source,
        confidence=confidence,
        status=status,
        hwnd=hwnd,
        process_name=pname,
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
        recent = BrowserContextStore().recent(limit=10)
        details = {
            "context_available": context.supported,
            "capture_source": "visible_context" if context.supported else None,
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
        return BrowserActionResult(
            "handled",
            action,
            json.dumps(details),
            "Browser diagnostics are ready.",
            context=context,
        )

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
                "I do not see any links in the current visible browser context.",
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
                "I do not see any buttons in the current visible browser context.",
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

    if action == "task":
        store = BrowserContextStore()
        store.record("task", query=target, status="handled")
        return BrowserActionResult("handled", action, target, f"Browser task noted: {target}.")

    if action == "open" or action == "navigate":
        url = target if (target.startswith("http://") or target.startswith("https://")) else f"https://{target}" if target else "about:blank"
        webbrowser.open(url)
        BrowserContextStore().record("navigate", url=url, status="handled")
        return BrowserActionResult("handled", action, target, f"Navigated browser to {url}.")

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


def _get_process_name_for_hwnd(hwnd: int) -> str:
    if not hwnd or sys.platform != "win32":
        return ""
    try:
        import ctypes

        import psutil

        pid = ctypes.c_ulong()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value:
            return psutil.Process(pid.value).name().lower()
    except Exception:
        pass
    return ""


_REJECT_URL_WORDS = (
    "uv run",
    "pytest",
    "powershell",
    "cmd.exe",
    "git ",
    "python",
    "python.exe",
    "cd ",
    "dir ",
    "\n",
    "\r",
)


def _is_valid_url_address(val: str) -> bool:
    val = val.strip()
    if not val or len(val) > 1000:
        return False
    if any(w in val.lower() for w in _REJECT_URL_WORDS):
        return False
    if " " in val:
        return False

    target_url = val if (val.startswith("http://") or val.startswith("https://")) else "https://" + val
    try:
        parsed = urllib.parse.urlparse(target_url)
        if not parsed.scheme or parsed.scheme not in ("http", "https"):
            return False
        netloc = parsed.netloc.split(":")[0]
        if not netloc:
            return False
        if "." not in netloc and netloc != "localhost":
            return False
        if any(c in netloc for c in ("\\", "/", ";", "|", "<", ">", '"', "'")):
            return False
        return True
    except Exception:
        return False


def _is_live_desktop_enabled() -> bool:
    if os.environ.get("GRANDPA_DISABLE_LIVE_DESKTOP") == "1":
        return False
    if "PYTEST_CURRENT_TEST" in os.environ and os.environ.get("GRANDPA_ENABLE_LIVE_DESKTOP") != "1":
        return False
    return True


def _get_address_bar_url_for_hwnd(hwnd: int) -> str:
    if not hwnd or sys.platform != "win32" or not _is_live_desktop_enabled():
        return ""
    try:
        import comtypes.client

        UIAutomationClient = comtypes.client.GetModule("UIAutomationCore.dll")
        uia = comtypes.client.CreateObject(UIAutomationClient.CUIAutomation)
        elem = uia.ElementFromHandle(hwnd)
        if not elem:
            return ""

        cond_edit = uia.CreatePropertyCondition(
            UIAutomationClient.UIA_ControlTypePropertyId,
            UIAutomationClient.UIA_EditControlTypeId,
        )
        edits = elem.FindAll(UIAutomationClient.TreeScope_Subtree, cond_edit)
        for i in range(edits.Length):
            ed_elem = edits.GetElement(i)
            try:
                val = str(ed_elem.GetCurrentPropertyValue(UIAutomationClient.UIA_ValueValuePropertyId) or "").strip()
                if val and _is_valid_url_address(val):
                    if not val.startswith("http://") and not val.startswith("https://"):
                        val = "https://" + val
                    return val
            except Exception:
                pass
    except Exception:
        pass
    return ""


def _find_visible_browser_window() -> tuple[int, str, str] | None:
    if sys.platform != "win32":
        return None

    try:
        from grandpa.windows_window_control import (
            _get_foreground_window,
            _get_window_title,
        )
    except Exception:
        return None

    # 1. Check if active window title ends with a valid browser suffix (handles monkeypatching & active browsers)
    title = _active_window_title()
    if title:
        browser = _browser_from_title(title)
        if browser:
            try:
                fg_hwnd = _get_foreground_window()
            except Exception:
                fg_hwnd = 0
            return (fg_hwnd or 0, browser, title)

    # 2. Check process name for foreground window
    allowed = {"chrome.exe", "msedge.exe", "firefox.exe"}
    try:
        fg_hwnd = _get_foreground_window()
        if fg_hwnd:
            fg_title = _get_window_title(fg_hwnd)
            fg_pname = _get_process_name_for_hwnd(fg_hwnd)
            if fg_pname in allowed:
                bname = "Chrome" if fg_pname == "chrome.exe" else ("Firefox" if fg_pname == "firefox.exe" else "Microsoft Edge")
                return (fg_hwnd, bname, fg_title)

        # 3. Foreground window is terminal/IDE -> enumerate desktop windows for visible Chrome/Edge if live desktop enabled
        if not _is_live_desktop_enabled():
            return None
        import ctypes

        user32 = ctypes.windll.user32
        match = None

        def callback(hwnd: int, _lparam: int) -> bool:
            nonlocal match
            if user32.IsWindowVisible(hwnd):
                wtitle = _get_window_title(int(hwnd))
                pname = _get_process_name_for_hwnd(int(hwnd))
                if pname in allowed and wtitle and not wtitle.startswith("DevTools"):
                    bname = "Chrome" if pname == "chrome.exe" else ("Firefox" if pname == "firefox.exe" else "Microsoft Edge")
                    match = (int(hwnd), bname, wtitle)
                    return False
            return True

        cb_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        user32.EnumWindows(cb_type(callback), 0)
        if match:
            return match
    except Exception:
        pass

    # 4. Environment context payload override (for tests/mocks)
    if os.environ.get("GRANDPA_BROWSER_CONTEXT_JSON") or os.environ.get("GRANDPA_BROWSER_CONTEXT_FILE"):
        return (0, "Chrome", "Browser Page")

    return None


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
    value = title.strip()
    for suffix in _BROWSER_SUFFIXES:
        if value.endswith(suffix):
            return "Chrome" if "Chrome" in suffix else "Microsoft Edge"
    return None


def _strip_browser_suffix(title: str) -> str:
    value = title.strip()
    for suffix in _BROWSER_SUFFIXES:
        if value.endswith(suffix):
            return value[: -len(suffix)].strip()
    return value


_BROWSER_CHROME_KEYWORDS = (
    "google chrome",
    "microsoft edge",
    "open tab in split view",
    "new tab",
    "close tab",
    "reload page",
    "bookmark",
    "address and search bar",
    "extension:",
    "minimize",
    "maximize",
    "restore",
    "app menu",
    "system menu",
    "downloads",
    "chrome web store",
)


def _is_browser_chrome_node(text: str) -> bool:
    tlower = text.strip().lower()
    if not tlower:
        return True
    return any(ck in tlower for ck in _BROWSER_CHROME_KEYWORDS)


def _extract_uia_dom_context(hwnd: int) -> dict[str, Any]:
    """Extract structured DOM context from a visible Chrome or Edge browser window handle via UIA Accessibility tree."""
    if not hwnd or sys.platform != "win32":
        return {}

    try:
        import comtypes.client

        UIAutomationClient = comtypes.client.GetModule("UIAutomationCore.dll")
        uia = comtypes.client.CreateObject(UIAutomationClient.CUIAutomation)
        elem = uia.ElementFromHandle(hwnd)
        if not elem:
            return {}

        # 1. Locate Webpage Document Root Element (ControlType.Document = 50030)
        doc_root = None
        try:
            cond_doc = uia.CreatePropertyCondition(
                UIAutomationClient.UIA_ControlTypePropertyId,
                UIAutomationClient.UIA_DocumentControlTypeId,
            )
            doc_elems = elem.FindAll(UIAutomationClient.TreeScope_Subtree, cond_doc)
            if doc_elems and doc_elems.Length > 0:
                doc_root = doc_elems.GetElement(0)
        except Exception:
            pass

        target_elem = doc_root or elem
        scope = "webpage_document" if doc_root else "browser_chrome_fallback"

        headings: list[str] = []
        paragraphs: list[str] = []
        buttons: list[str] = []
        links: list[dict[str, str]] = []
        inputs: list[dict[str, str]] = []
        all_text_chunks: list[str] = []
        elements: list[dict[str, Any]] = []

        # 2. Extract Hyperlinks under target_elem
        try:
            cond_link = uia.CreatePropertyCondition(
                UIAutomationClient.UIA_ControlTypePropertyId,
                UIAutomationClient.UIA_HyperlinkControlTypeId,
            )
            link_elems = target_elem.FindAll(UIAutomationClient.TreeScope_Subtree, cond_link)
            for i in range(min(50, link_elems.Length)):
                le = link_elems.GetElement(i)
                try:
                    name = str(le.CurrentName or "").strip()
                    if name and not _is_browser_chrome_node(name):
                        links.append({"text": _redact_sensitive_visible_text(name)[:160], "href": ""})
                except Exception:
                    pass
        except Exception:
            pass

        # 3. Extract Text & Custom controls under target_elem
        try:
            cond_true = uia.CreateTrueCondition()
            all_elems = target_elem.FindAll(UIAutomationClient.TreeScope_Subtree, cond_true)
            max_count = min(350, all_elems.Length)
            for i in range(max_count):
                el_node = all_elems.GetElement(i)
                try:
                    ctype = el_node.CurrentControlType
                    name = str(el_node.CurrentName or "").strip()
                    if not name or _is_browser_chrome_node(name):
                        continue
                    clean_txt = _redact_sensitive_visible_text(name)[:500]

                    role = "text"
                    if ctype == UIAutomationClient.UIA_HyperlinkControlTypeId:
                        role = "link"
                    elif ctype == UIAutomationClient.UIA_ButtonControlTypeId:
                        role = "button"
                    elif ctype == UIAutomationClient.UIA_ListItemControlTypeId or clean_txt.startswith("•") or clean_txt.startswith("-"):
                        role = "list_item"
                    elif "pip install" in clean_txt.lower() or "python" in clean_txt.lower() or clean_txt.startswith("$"):
                        role = "code_block"
                    elif len(clean_txt) < 80 and not clean_txt.endswith(".") and not clean_txt.startswith("<"):
                        role = "heading"

                    all_text_chunks.append(clean_txt)
                    if role == "heading" and clean_txt not in headings:
                        headings.append(clean_txt)
                    elif role in ("paragraph", "text") and (len(clean_txt) >= 30 or clean_txt.endswith(".")):
                        if clean_txt not in paragraphs:
                            paragraphs.append(clean_txt)

                    elements.append({
                        "role": role,
                        "text": clean_txt,
                        "level": 2 if role == "heading" else 0,
                        "order": len(elements),
                        "scope": scope,
                    })
                except Exception:
                    pass
        except Exception:
            pass

        visible_text = "\n\n".join(all_text_chunks[:60])
        acquisition_source = "accessibility_tree" if (headings or paragraphs or links) else ("uia_text" if visible_text else "unavailable")
        confidence = "High" if acquisition_source == "accessibility_tree" else ("Medium" if acquisition_source == "uia_text" else "Low")
        status = "success" if acquisition_source in ("accessibility_tree", "full_dom") else ("partial_success" if visible_text else "unavailable")

        return {
            "headings": headings[:30],
            "paragraphs": paragraphs[:40],
            "buttons": buttons[:30],
            "links": links[:40],
            "inputs": inputs[:15],
            "visible_text": visible_text,
            "elements": elements[:200],
            "acquisition_source": acquisition_source,
            "confidence": confidence,
            "status": status,
            "scope": scope,
        }
    except Exception:
        return {}


def _load_visible_dom_context(hwnd: int = 0) -> dict[str, Any]:
    raw = os.environ.get("GRANDPA_BROWSER_CONTEXT_JSON")
    if raw:
        try:
            data = json.loads(raw)
            sanitized = _sanitize_dom_context(data)
            sanitized.setdefault("acquisition_source", "full_dom")
            sanitized.setdefault("confidence", "High")
            sanitized.setdefault("status", "success")
            return sanitized
        except Exception:
            return {}

    path = os.environ.get("GRANDPA_BROWSER_CONTEXT_FILE")
    if path:
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            sanitized = _sanitize_dom_context(data)
            sanitized.setdefault("acquisition_source", "full_dom")
            sanitized.setdefault("confidence", "High")
            sanitized.setdefault("status", "success")
            return sanitized
        except Exception:
            return {}

    if hwnd:
        uia_context = _extract_uia_dom_context(hwnd)
        if uia_context and (uia_context.get("headings") or uia_context.get("visible_text")):
            return uia_context

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
    }
    if isinstance(value, dict):
        session["visibility"] = str(value.get("visibility") or "")[:40]
        session["focused"] = bool(value.get("focused", False))
    return session


def _browser_media_action(target: str, context: BrowserContext) -> BrowserActionResult:
    if not context.media:
        message = "I do not see visible media controls in the current browser context."
    else:
        message = "Visible-page media controls require a browser adapter and are unavailable."
    return BrowserActionResult("unsupported", "media", target, message, context=context)


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
]
