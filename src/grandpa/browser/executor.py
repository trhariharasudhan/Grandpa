"""Execution layer for safe browser automation."""

from __future__ import annotations

import webbrowser
from collections.abc import Callable
from functools import partial
from typing import Any

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
        *,
        origin: str = "direct",
    ) -> None:
        self.opener = opener or _default_open
        #: Who asked for these browser actions (AD-022). Bound into the default
        #: hotkey runner so the callback contract stays ``(keys) -> bool`` for
        #: callers that substitute their own.
        self.origin = origin
        self.hotkey_runner = hotkey_runner or partial(_default_hotkey, origin=origin)

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


def run_browser_action(
    action_type: str,
    target: str,
    *,
    origin: str = "direct",
    runner: Callable[[dict[str, Any]], Any] | None = None,
    dry_run: bool = False,
) -> Any:
    """Run a browser action through the one actuator boundary.

    Browser execution in this module opens URLs directly with
    ``webbrowser.open``, which is a real side effect with no risk tier,
    approval gate, emergency stop, dry-run or audit record. Callers that need
    those -- the executive planner first among them, because its steps can be
    reached by voice -- come through here instead.

    ``action_type`` must already exist in the pc_control risk table;
    ``browser_open`` and ``browser_search`` do. Nothing is classified here: the
    boundary recomputes risk from the action whatever a caller passes.

    ``runner`` lets a caller substitute the actuator, exactly as the desktop
    path allows, so a test can prove what would have run without running it.
    It defaults to the real one, so existing callers are unaffected.
    """
    payload = {
        "action_type": action_type,
        "target": target,
        "args": {},
        "dry_run": dry_run,
        "require_approval": False,
        "origin": origin,
    }
    if runner is not None:
        return runner(payload)
    from grandpa.pc_control import run_local_action

    return run_local_action(payload)


def _default_open(url: str) -> bool:
    return bool(webbrowser.open(url, new=2))


def _default_hotkey(keys: tuple[str, ...], origin: str = "direct") -> bool:
    from grandpa.pc_control import run_local_action

    response = run_local_action(
        {
            "action_type": "keyboard_hotkey",
            "target": "+".join(keys),
            "args": {"keys": list(keys)},
            # Provenance (AD-022). Browser shortcuts are MEDIUM risk and
            # approval-gated, and this payload stated nothing -- so a shortcut
            # a person spoke was filed as an anonymous direct call. "direct"
            # is pc_control.DEFAULT_ACTION_ORIGIN, spelled out because the
            # kernel baseline guard counts references to that module.
            "origin": origin,
        }
    )
    return bool(getattr(response, "ok", False))


__all__ = [
    "BrowserExecutor",
    "HOTKEYS",
    "OpenCallback",
    "PAGE_URLS",
    "run_browser_action",
]
