"""Execution layer for safe browser automation."""

from __future__ import annotations

import webbrowser
from collections.abc import Callable

from grandpa.browser.models import BrowserAction, BrowserOperationResult
from grandpa.browser.safety import (
    confirmation_prompt,
    needs_confirmation,
    validate_browser_url,
)
from grandpa.browser.urls import search_url

OpenCallback = Callable[[str], bool]
HotkeyCallback = Callable[[tuple[str, ...]], bool]
# Same shape as desktop_automation's: (what would happen, tier) -> approved.
ConfirmationCallback = Callable[[str, str], bool]

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
        confirm: ConfirmationCallback | None = None,
        confirmed: bool = False,
        trusted_domains: tuple[str, ...] = (),
    ) -> None:
        self.opener = opener or _default_open
        self.hotkey_runner = hotkey_runner or _default_hotkey
        self.confirm = confirm
        self.confirmed = confirmed
        self.trusted_domains = trusted_domains

    def _refused(
        self, action: BrowserAction, url: str, label: str
    ) -> BrowserOperationResult | None:
        """Ask before navigating, or refuse when nobody can be asked."""
        if self.confirmed or not needs_confirmation(action, url, self.trusted_domains):
            return None
        prompt = confirmation_prompt(action, url, label)
        if self.confirm is not None and self.confirm(prompt, "requires_confirmation"):
            return None
        message = (
            f"Confirmation required before I {prompt}."
            if self.confirm is None
            else f"Cancelled: I did not {prompt}."
        )
        return BrowserOperationResult("needs_confirmation", message, action, url)

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
        refused = self._refused(action, normalized, label)
        if refused is not None:
            return refused
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
        refused = self._refused(action, url, action.target)
        if refused is not None:
            return refused
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
        except BrowserNotInFrontError:
            return BrowserOperationResult(
                "blocked",
                "The window in front is not a browser, so I did not send that "
                "shortcut.",
                action,
                error="browser_not_in_front",
            )
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


class BrowserNotInFrontError(RuntimeError):
    """The foreground window is not a browser, so a browser shortcut was not sent."""


class _HotkeyRequest:
    def __init__(self, keys: tuple[str, ...]) -> None:
        self.target = "+".join(keys)
        self.args = {"keys": list(keys)}


def _default_hotkey(keys: tuple[str, ...]) -> bool:
    """Send one of this domain's fixed shortcuts to the browser in front.

    This used to go through pc_control as a generic keyboard_hotkey, which is
    in APPROVAL_REQUIRED_ACTIONS. So every browser shortcut the action layer
    asked for -- back, forward, new tab, refresh, close tab -- was staged for an
    approval that nothing redeemed, and reported "Could not send that browser
    shortcut." They never ran.

    That approval exists because keyboard_hotkey takes *arbitrary* keys, and a
    model choosing keys can reach Win+R. These are a fixed allowlist -- Ctrl+T,
    Ctrl+W, Ctrl+R, Alt+Left, Alt+Right, Ctrl+Shift+T, Ctrl+L -- none of which
    opens anything. The risk they do carry is aim: Ctrl+W sent to a text editor
    closes the document, not a tab. So the guard that matters is that the
    foreground window is a browser, and that is checked first. The automation
    service then applies its own denylist, protected-window check and cooldown.
    """
    import sys

    from grandpa.browser_control import _find_visible_browser_window
    from grandpa.desktop.control.automation import AutomationControlService

    if _find_visible_browser_window() is None:
        raise BrowserNotInFrontError("the foreground window is not a browser")

    response = AutomationControlService().execute(
        _HotkeyRequest(keys), "keyboard_hotkey", platform=sys.platform
    )
    return bool(getattr(response, "ok", False))


__all__ = [
    "BrowserExecutor",
    "BrowserNotInFrontError",
    "HOTKEYS",
    "OpenCallback",
    "PAGE_URLS",
]
