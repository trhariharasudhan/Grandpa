"""Session context manager with sanitized file persistence for Grandpa Browser Intelligence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from grandpa.browser_intelligence.models import BrowserSessionState, ExtractedContent

_SESSION_FILE = Path.home() / ".grandpa" / "browser_session_state.json"


class BrowserSessionMemory:
    """Session manager with sanitized JSON file persistence across CLI processes."""

    _instance: BrowserSessionMemory | None = None

    def __init__(self) -> None:
        self.state = BrowserSessionState()
        self._load_from_disk()

    @classmethod
    def get_instance(cls) -> BrowserSessionMemory:
        if cls._instance is None:
            cls._instance = BrowserSessionMemory()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        cls._instance = BrowserSessionMemory()
        cls._instance._save_to_disk()

    def _save_to_disk(self) -> None:
        try:
            _SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
            data = self.state.to_dict()
            _SESSION_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _load_from_disk(self) -> None:
        if not _SESSION_FILE.exists():
            return
        try:
            raw = json.loads(_SESSION_FILE.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                self.state.visited_pages = raw.get("visited_pages", [])
                self.state.verified_pages = raw.get("verified_pages", [])
                self.state.last_active_tab = raw.get("last_active_tab")
                self.state.navigation_history = raw.get("navigation_history", [])
        except Exception:
            pass

    def record_visit(self, title: str, url: str, domain: str = "") -> None:
        """Record page visit in current session."""
        if not title and not url:
            return
        entry = {"title": title, "url": url, "domain": domain}
        if not any(p.get("url") == url for p in self.state.visited_pages if url):
            self.state.visited_pages.append(entry)
        self.state.last_active_tab = entry
        if url and url not in self.state.navigation_history:
            self.state.navigation_history.append(url)
        self._save_to_disk()

    def record_verification(self, title: str, url: str, is_official: bool, trust_score: float) -> None:
        """Record verified page in session."""
        if not url:
            return
        entry = {
            "title": title,
            "url": url,
            "is_official": is_official,
            "trust_score": trust_score,
        }
        self.state.verified_pages.append(entry)
        self._save_to_disk()

    def record_extracted_section(self, extracted: ExtractedContent) -> None:
        """Record last extracted section."""
        self.state.last_extracted_section = extracted
        self._save_to_disk()

    def get_last_active_tab(self) -> dict[str, Any] | None:
        return self.state.last_active_tab

    def get_last_verified_page(self) -> dict[str, Any] | None:
        if self.state.verified_pages:
            return self.state.verified_pages[-1]
        return None

    def go_back(self) -> dict[str, Any] | None:
        """Pop current page and return previous page from navigation history."""
        if len(self.state.navigation_history) > 1:
            self.state.navigation_history.pop()
            prev_url = self.state.navigation_history[-1]
            for page in reversed(self.state.visited_pages):
                if page.get("url") == prev_url:
                    self.state.last_active_tab = page
                    self._save_to_disk()
                    return page
            return {"url": prev_url, "title": "Previous Page"}
        return None

    def find_visited_page(self, query: str) -> dict[str, Any] | None:
        """Find a previously visited page matching query (e.g. 'FastAPI')."""
        q = query.lower()
        for page in reversed(self.state.visited_pages):
            if q in page.get("title", "").lower() or q in page.get("url", "").lower():
                return page
        return None

    def get_summary_context(self) -> dict[str, Any]:
        """Return snapshot dict of current session memory."""
        return self.state.to_dict()
