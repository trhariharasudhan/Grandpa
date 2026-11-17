"""Apps Grandpa never looks at, and password boxes he never photographs (C4).

One list, checked before a single pixel is grabbed or a single accessibility
element is read -- by every screen path: screenshots, OCR, "what's on my
screen" (grandpa-eyes sees only what the capture gives it), reading the window
in front, and pressing a button in it.

The list is the built-in one below plus the user's own file,
``~/.grandpa/screen-private.txt`` (one entry per line: an executable such as
``whatsapp.exe``, or words from a window title such as ``salary``). The user's
entries can be added and removed with ``grandpa screen private``; the built-in
ones cannot be removed from there, and there is no catalogue action for this
list, so a model can never take an app off it.

Full-screen captures refuse when a listed app is anywhere on screen (visible
and not minimised), not just when it is in front: a screenshot of the whole
desktop shows every window. And a capture is refused while the keyboard focus
is in a password box, which UI Automation reports as ``IsPassword``.
"""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from grandpa.screen.errors import SensitiveScreenDetectedError
from grandpa.screen.models import WindowInfo

logger = logging.getLogger(__name__)

BLOCKLIST_FILENAME = "screen-private.txt"

DEFAULT_BLOCKED_APPS: frozenset[str] = frozenset(
    {
        # password managers
        "1password.exe",
        "bitwarden.exe",
        "keepass.exe",
        "keepassxc.exe",
        "lastpass.exe",
        "dashlane.exe",
        "enpass.exe",
        "nordpass.exe",
        "roboform.exe",
        "proton pass.exe",
        "keeper.exe",
        # Windows' own credential prompts
        "credentialuibroker.exe",
        "consent.exe",
    }
)

DEFAULT_BLOCKED_TITLES: tuple[str, ...] = (
    "password manager",
    "1password",
    "bitwarden",
    "keepass",
    "lastpass",
    "inprivate",
    "incognito",
    "private browsing",
)
"""Title words. Private-browsing windows are on the list because the user
opened them to keep what they show to themselves."""

PASSWORD_FOCUS_MESSAGE = (
    "The cursor is in a password box, so Grandpa did not look at the screen. "
    "Try again once you have left it."
)


class PrivateWindowError(SensitiveScreenDetectedError):
    """A listed app is on screen, or a password box has the focus."""


@dataclass(frozen=True)
class Blocklist:
    apps: frozenset[str]
    titles: tuple[str, ...]

    def reason(self, window: WindowInfo) -> str:
        """Why ``window`` must not be looked at, or "" if it may be."""
        process = (window.process_name or "").strip().casefold()
        if process and (process in self.apps or f"{process}.exe" in self.apps):
            return window.process_name
        title = (window.title or "").casefold()
        for words in self.titles:
            if words and re.search(rf"(^|\W){re.escape(words)}($|\W)", title):
                return window.title
        return ""


def blocklist_path() -> Path:
    from grandpa.core.config import DEFAULT_CONFIG_DIR

    return DEFAULT_CONFIG_DIR / BLOCKLIST_FILENAME


def _normalise_entry(entry: str) -> str:
    return " ".join(entry.strip().casefold().split())


def read_user_entries(path: Path | None = None) -> list[str]:
    """The user's own entries, in file order. Missing file: none."""
    path = path or blocklist_path()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    except OSError as exc:
        logger.warning("Could not read %s: %s", path, exc)
        return []
    entries: list[str] = []
    for line in lines:
        entry = _normalise_entry(line.split("#", 1)[0])
        if entry and entry not in entries:
            entries.append(entry)
    return entries


def load_blocklist(path: Path | None = None) -> Blocklist:
    apps = set(DEFAULT_BLOCKED_APPS)
    titles = list(DEFAULT_BLOCKED_TITLES)
    for entry in read_user_entries(path):
        if entry.endswith(".exe"):
            apps.add(entry)
        elif entry not in titles:
            titles.append(entry)
    return Blocklist(frozenset(apps), tuple(titles))


def add_user_entry(entry: str, path: Path | None = None) -> bool:
    """Add one entry. False when it was already there (or built in)."""
    entry = _normalise_entry(entry)
    if not entry:
        raise ValueError("Give an app (e.g. whatsapp.exe) or words from a title.")
    if entry in DEFAULT_BLOCKED_APPS or entry in DEFAULT_BLOCKED_TITLES:
        return False
    path = path or blocklist_path()
    entries = read_user_entries(path)
    if entry in entries:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join([*entries, entry]) + "\n", encoding="utf-8")
    return True


def remove_user_entry(entry: str, path: Path | None = None) -> bool:
    """Remove one of the user's own entries. Built-in ones cannot be removed."""
    entry = _normalise_entry(entry)
    path = path or blocklist_path()
    entries = read_user_entries(path)
    if entry not in entries:
        return False
    remaining = [item for item in entries if item != entry]
    path.write_text("\n".join(remaining) + ("\n" if remaining else ""), "utf-8")
    return True


def _overlaps(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


# --- the one check every capture makes ---------------------------------------


def focus_is_password() -> bool:
    """Is the keyboard focus in a password box right now? False off Windows."""
    from grandpa.screen.window_text import live_desktop_enabled

    if sys.platform != "win32" or not live_desktop_enabled():
        return False
    try:
        import comtypes.client  # type: ignore

        uia_module = comtypes.client.GetModule("UIAutomationCore.dll")
        uia = comtypes.client.CreateObject(uia_module.CUIAutomation)
        element = uia.GetFocusedElement()
        return bool(element and element.CurrentIsPassword)
    except Exception as exc:
        logger.debug("Focused-element check unavailable: %s", exc)
        return False


def _visible_windows() -> list[WindowInfo]:
    from grandpa.screen.windows import list_windows

    return list_windows()


def check_window(window: WindowInfo, blocklist: Blocklist | None = None) -> None:
    """Refuse to read or press anything in ``window`` if it is listed."""
    reason = (blocklist or load_blocklist()).reason(window)
    if reason:
        logger.warning("Private window refused: %s", reason)
        raise PrivateWindowError(_private_message(reason))


def check_capture(
    *,
    region: tuple[int, int, int, int] | None = None,
    window: WindowInfo | None = None,
    windows: Callable[[], Iterable[WindowInfo]] = _visible_windows,
    password_focus: Callable[[], bool] = focus_is_password,
    blocklist: Blocklist | None = None,
) -> None:
    """Raise PrivateWindowError if this capture would show something private.

    ``window``: capturing one window, so only it matters. Otherwise every
    visible, non-minimised window overlapping ``region`` (the whole desktop when
    None) is checked.
    """
    if password_focus():
        logger.warning("Capture refused: focus is in a password box")
        raise PrivateWindowError(PASSWORD_FOCUS_MESSAGE)
    blocklist = blocklist or load_blocklist()
    if window is not None:
        check_window(window, blocklist)
        return
    for item in windows():
        if item.is_minimized or not item.is_visible:
            continue
        if region is not None and not _overlaps(item.bounds, region):
            continue
        reason = blocklist.reason(item)
        if reason:
            logger.warning("Capture refused: private window on screen: %s", reason)
            raise PrivateWindowError(_private_message(reason))


def _private_message(reason: str) -> str:
    return (
        f"{reason} is on your private list, so Grandpa did not look at the "
        "screen. Nothing was captured. (See `grandpa screen private`.)"
    )


__all__ = [
    "BLOCKLIST_FILENAME",
    "Blocklist",
    "DEFAULT_BLOCKED_APPS",
    "DEFAULT_BLOCKED_TITLES",
    "PASSWORD_FOCUS_MESSAGE",
    "PrivateWindowError",
    "add_user_entry",
    "blocklist_path",
    "check_capture",
    "check_window",
    "focus_is_password",
    "load_blocklist",
    "read_user_entries",
    "remove_user_entry",
]
