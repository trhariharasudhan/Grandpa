"""Execution layer for safe browser automation."""

from __future__ import annotations

import webbrowser
from collections.abc import Callable

from grandpa.browser.models import BrowserAction, BrowserOperationResult
from grandpa.browser.safety import validate_browser_url
from grandpa.browser.urls import search_url

OpenCallback = Callable[[str], bool]
HotkeyCallback = Callable[[tuple[str, ...]], bool]

PAGE_URLS = {
    "history": "chrome://history",
    "downloads": "chrome://downloads",
    "bookmarks": "chrome://bookmarks",
    "settings": "chrome://settings",
}

HOTKEYS: dict[str, tuple[str, ...]] = {
    "new_tab": ("ctrl", "t"),
    "close_tab": ("ctrl", "w"),
    "refresh": ("ctrl", "r"),
    "back": ("alt", "left"),
    "forward": ("alt", "right"),
    "reopen_closed_tab": ("ctrl", "shift", "t"),
    "focus_address_bar": ("ctrl", "l"),
}


class BrowserExecutor:
    """Execute browser actions using safe URL opening or injected hotkeys."""

    def __init__(
        self,
        opener: OpenCallback | None = None,
        hotkey_runner: HotkeyCallback | None = None,
    ) -> None:
        self.opener = opener or _default_open
        self.hotkey_runner = hotkey_runner or _default_hotkey

    def execute(self, action: BrowserAction) -> BrowserOperationResult:
        if action.action == "open_url":
            return self._open_url(
                action, action.url or action.target, label=action.target or "Website"
            )
        if action.action == "search":
            return self._search(action)
        if action.action == "open_page":
            return self._open_page(action)
        if action.action in HOTKEYS:
            return self._hotkey(action)
        return BrowserOperationResult(
            "unsupported", "That browser action is not supported yet.", action
        )

    def _open_url(
        self, action: BrowserAction, url: str, *, label: str
    ) -> BrowserOperationResult:
        ok, normalized, message = validate_browser_url(url)
        if not ok:
            return BrowserOperationResult("blocked", message, action, error=message)
        try:
            opened = self.opener(normalized)
        except Exception as exc:
            return BrowserOperationResult(
                "error", f"Could not open {label}.", action, normalized, str(exc)
            )
        if not opened:
            return BrowserOperationResult(
                "error", f"Could not open {label}.", action, normalized
            )
        return BrowserOperationResult("handled", f"{label} opened.", action, normalized)

    def _search(self, action: BrowserAction) -> BrowserOperationResult:
        result = search_url(action.provider, action.query)
        if result is None:
            return BrowserOperationResult(
                "unsupported", "That search provider is not supported yet.", action
            )
        label, url = result
        opened = self._open_url(action, url, label=label)
        if opened.status != "handled":
            return opened
        return BrowserOperationResult(
            "handled", f"Searching {label} for {action.query}.", action, opened.url
        )

    def _open_page(self, action: BrowserAction) -> BrowserOperationResult:
        url = PAGE_URLS.get(action.target)
        if url is None:
            return BrowserOperationResult(
                "unsupported", "That browser page is not supported yet.", action
            )
        try:
            opened = self.opener(url)
        except Exception as exc:
            return BrowserOperationResult(
                "error",
                f"Could not open browser {action.target}.",
                action,
                url,
                str(exc),
            )
        if not opened:
            return BrowserOperationResult(
                "error", f"Could not open browser {action.target}.", action, url
            )
        return BrowserOperationResult(
            "handled", f"Browser {action.target} opened.", action, url
        )

    def _hotkey(self, action: BrowserAction) -> BrowserOperationResult:
        keys = HOTKEYS[action.action]
        try:
            ok = self.hotkey_runner(keys)
        except Exception as exc:
            return BrowserOperationResult(
                "error", "Could not send that browser shortcut.", action, error=str(exc)
            )
        if not ok:
            return BrowserOperationResult(
                "error", "Could not send that browser shortcut.", action
            )
        messages = {
            "new_tab": "Opened a new browser tab.",
            "close_tab": "Closed the current browser tab.",
            "refresh": "Refreshed the page.",
            "back": "Went back.",
            "forward": "Went forward.",
            "reopen_closed_tab": "Reopened the last closed tab.",
            "focus_address_bar": "Focused the address bar.",
        }
        return BrowserOperationResult("handled", messages[action.action], action)


def _default_open(url: str) -> bool:
    return bool(webbrowser.open(url, new=2))


def _default_hotkey(keys: tuple[str, ...]) -> bool:
    from grandpa.pc_control import run_local_action

    response = run_local_action(
        {
            "action_type": "keyboard_hotkey",
            "target": "+".join(keys),
            "args": {"keys": list(keys)},
        }
    )
    return bool(getattr(response, "ok", False))


__all__ = ["BrowserExecutor", "HOTKEYS", "OpenCallback", "PAGE_URLS"]
