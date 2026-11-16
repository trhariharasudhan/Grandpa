"""Read the text of the window in front from the accessibility tree (C2).

Windows exposes what an application shows through UI Automation: a browser's
page, Notepad's document, a dialog's labels. Reading that is better than OCR --
it is the real text, not a guess at pixels -- and it lets us skip password
fields by their ``IsPassword`` property instead of hoping redaction catches
what they hold.

The tree walk is the only Windows-specific part (``read_uia_nodes``); turning
nodes into text (``collect_text``) is plain Python, so it is what the tests
exercise.
"""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass

logger = logging.getLogger(__name__)

MAX_NODES = 400
"""Elements visited per read. A long web page has thousands; the first few
hundred in tree order are the top of the page, which is what "read this page"
means, and the walk stays well under a second."""

DEFAULT_MAX_CHARS = 6000

# Window furniture every application has. Reading it aloud is noise.
_FURNITURE = frozenset(
    {
        "minimize",
        "maximize",
        "restore",
        "close",
        "system",
        "system menu",
        "application",
        "title bar",
        "scroll up",
        "scroll down",
        "page up",
        "page down",
        "line up",
        "line down",
        "vertical",
        "horizontal",
        "vertical scroll bar",
        "horizontal scroll bar",
    }
)

# Controls whose own text is the content (documents, edit boxes, text).
_TEXT_CONTROLS = frozenset({"document", "edit"})


@dataclass(frozen=True)
class UiNode:
    """One accessibility element, reduced to what reading needs."""

    control: str
    name: str = ""
    text: str = ""
    is_password: bool = False


NodeReader = Callable[[int], list[UiNode]]


def collect_text(
    nodes: Iterable[UiNode], *, max_chars: int = DEFAULT_MAX_CHARS
) -> tuple[str, bool]:
    """Join the readable text of ``nodes`` in order. Returns (text, truncated).

    Password fields are skipped whole -- their label too, since a label next to
    nothing reads as a sentence cut off. Repeats are dropped: UI Automation
    often reports the same string on a text element and on its parent.
    """
    lines: list[str] = []
    seen: set[str] = set()
    total = 0
    truncated = False
    for node in nodes:
        if node.is_password:
            continue
        control = node.control.casefold()
        chunk = node.text if control in _TEXT_CONTROLS and node.text else node.name
        for raw in chunk.splitlines():
            line = " ".join(raw.split())
            if not line or line.casefold() in _FURNITURE or line in seen:
                continue
            if total + len(line) > max_chars:
                truncated = True
                break
            seen.add(line)
            lines.append(line)
            total += len(line) + 1
        if truncated:
            break
    return "\n".join(lines), truncated


def live_desktop_enabled() -> bool:
    """The same switch browser_control uses: off in tests unless asked for."""
    if os.environ.get("GRANDPA_DISABLE_LIVE_DESKTOP") == "1":
        return False
    if (
        "PYTEST_CURRENT_TEST" in os.environ
        and os.environ.get("GRANDPA_ENABLE_LIVE_DESKTOP") != "1"
    ):
        return False
    return True


def read_uia_nodes(hwnd: int, *, limit: int = MAX_NODES) -> list[UiNode]:
    """Walk the window's UI Automation tree. Empty when UIA is not available.

    A browser shows its page inside a Document element; when there is one, only
    that subtree is read, so the tab strip and address bar are left out.
    """
    if not hwnd or sys.platform != "win32" or not live_desktop_enabled():
        return []
    try:
        import comtypes.client  # type: ignore

        uia_module = comtypes.client.GetModule("UIAutomationCore.dll")
        uia = comtypes.client.CreateObject(uia_module.CUIAutomation)
        window = uia.ElementFromHandle(hwnd)
        if not window:
            return []
        root = window
        try:
            documents = window.FindAll(
                uia_module.TreeScope_Subtree,
                uia.CreatePropertyCondition(
                    uia_module.UIA_ControlTypePropertyId,
                    uia_module.UIA_DocumentControlTypeId,
                ),
            )
            if documents and documents.Length > 0:
                root = documents.GetElement(0)
        except Exception:
            root = window
        elements = root.FindAll(uia_module.TreeScope_Subtree, uia.CreateTrueCondition())
        names = {
            uia_module.UIA_DocumentControlTypeId: "document",
            uia_module.UIA_EditControlTypeId: "edit",
        }
        nodes: list[UiNode] = []
        if root is not window:
            nodes.append(_uia_node(root, uia_module, names))
        for index in range(min(limit, elements.Length)):
            try:
                nodes.append(_uia_node(elements.GetElement(index), uia_module, names))
            except Exception:
                continue
        return nodes
    except Exception as exc:
        logger.debug("UI Automation read failed: %s", exc)
        return []


def _uia_node(element, uia_module, names: dict[int, str]) -> UiNode:  # type: ignore[no-untyped-def]
    control = names.get(int(element.CurrentControlType), "other")
    is_password = bool(element.CurrentIsPassword)
    text = ""
    if control in _TEXT_CONTROLS and not is_password:
        text = _pattern_text(element, uia_module)
    return UiNode(
        control=control,
        name=str(element.CurrentName or ""),
        text=text,
        is_password=is_password,
    )


def _pattern_text(element, uia_module) -> str:  # type: ignore[no-untyped-def]
    """A document's or edit box's own text, via TextPattern then ValuePattern."""
    try:
        pattern = element.GetCurrentPattern(uia_module.UIA_TextPatternId)
        if pattern:
            text_pattern = pattern.QueryInterface(uia_module.IUIAutomationTextPattern)
            return str(text_pattern.DocumentRange.GetText(DEFAULT_MAX_CHARS) or "")
    except Exception:
        pass
    try:
        pattern = element.GetCurrentPattern(uia_module.UIA_ValuePatternId)
        if pattern:
            value_pattern = pattern.QueryInterface(uia_module.IUIAutomationValuePattern)
            return str(value_pattern.CurrentValue or "")
    except Exception:
        pass
    return ""


__all__ = [
    "DEFAULT_MAX_CHARS",
    "MAX_NODES",
    "NodeReader",
    "UiNode",
    "collect_text",
    "live_desktop_enabled",
    "read_uia_nodes",
]
