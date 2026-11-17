"""Act on what Grandpa sees: press a named control in the window in front (C3).

"Click Save", "press the OK button", "click on Don't Save". The control is found
by its visible name in the window's UI Automation tree -- the same tree C2
reads -- and pressed through UI Automation's own patterns (Invoke, Toggle,
Select). No synthetic mouse: nothing moves the pointer, and a press lands on the
element that was named, not on whatever happens to be at a screen position.

Safety, in the order it runs:

* the action is on the always-confirm list; nothing here asks the user, the
  caller does, and it names the control and the window;
* a credential screen is refused by its title before the tree is walked, and by
  its text after;
* password fields are never pressed, and neither is a disabled control;
* controls that spend money, sign in, submit, or delete are refused whatever
  was approved (``RISKY_CLICK_WORDS``);
* an unclear name (no match, or several) presses nothing and lists what there is.

The tree walk and the press are the only Windows-specific parts
(``read_uia_controls``, ``press``); matching is plain Python, which is what the
tests exercise.
"""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from grandpa.screen.window_text import MAX_NODES, live_desktop_enabled

logger = logging.getLogger(__name__)

RISKY_CLICK_WORDS: tuple[str, ...] = (
    "submit",
    "checkout",
    "check out",
    "payment",
    "pay",
    "purchase",
    "buy",
    "order",
    "login",
    "log in",
    "sign in",
    "sign up",
    "password",
    "delete",
    "remove",
    "uninstall",
    "format",
    "erase",
    "transfer",
    "send",
)
"""A press on one of these is refused even after a yes. The browser click path
(grandpa.local.permissions) refuses the first six for the same reason; a model
picks the name here, so the list is longer."""

# The control types a person means by "click". Text, images and panes are not
# pressable, and matching their names would turn "click Weather" into a guess.
CLICKABLE = frozenset(
    {
        "button",
        "hyperlink",
        "menuitem",
        "tabitem",
        "checkbox",
        "radiobutton",
        "listitem",
        "splitbutton",
        "treeitem",
    }
)

_SUFFIXES = (
    "button",
    "link",
    "tab",
    "menu item",
    "menu",
    "option",
    "checkbox",
    "check box",
    "box",
    "item",
)


@dataclass(frozen=True)
class UiControl:
    """One pressable accessibility element. ``element`` is the live COM object."""

    control: str
    name: str
    is_password: bool = False
    is_enabled: bool = True
    element: Any = field(default=None, compare=False, repr=False)

    @property
    def label(self) -> str:
        kind = {
            "hyperlink": "link",
            "menuitem": "menu item",
            "tabitem": "tab",
            "checkbox": "check box",
            "radiobutton": "option",
            "listitem": "item",
            "splitbutton": "button",
            "treeitem": "item",
        }.get(self.control, self.control)
        return f'the "{self.name}" {kind}'


ControlReader = Callable[[int], list[UiControl]]
Presser = Callable[[UiControl], bool]


def normalize_name(name: str) -> str:
    """How two names are compared: no accelerators, case, quotes or dots."""
    text = name.replace("&", "").casefold()
    text = text.replace("’", "'").replace("…", "")
    text = re.sub(r"[\"“”]", "", text)
    text = re.sub(r"\.{2,}$", "", text.strip())
    return " ".join(text.split()).strip(" .:")


def clean_target(target: str) -> str:
    """'the Save button' -> 'save'. What the user said, minus the furniture."""
    text = normalize_name(target)
    text = re.sub(r"^(on\s+)?(the\s+)?", "", text)
    for suffix in _SUFFIXES:
        if text.endswith(" " + suffix):
            text = text[: -len(suffix) - 1].strip()
            break
    return text


def is_risky(name: str) -> bool:
    words = normalize_name(name)
    return any(
        re.search(rf"(^|\W){re.escape(word)}($|\W)", words)
        for word in RISKY_CLICK_WORDS
    )


@dataclass(frozen=True)
class Match:
    """The result of looking for a name: one control, or why not."""

    control: UiControl | None
    candidates: tuple[UiControl, ...] = ()

    @property
    def ambiguous(self) -> bool:
        return self.control is None and len(self.candidates) > 1


def find_control(controls: Iterable[UiControl], target: str) -> Match:
    """The one clickable control called ``target``.

    An exact name first, then a name that contains it ("save" finds "Save as"
    only when nothing is called just "Save"). Two controls with the same name
    are ambiguous, not a coin toss: nothing is pressed.
    """
    wanted = clean_target(target)
    if not wanted:
        return Match(None)
    pressable = [
        item for item in controls if item.control in CLICKABLE and item.name.strip()
    ]
    exact = [item for item in pressable if normalize_name(item.name) == wanted]
    if len(exact) == 1:
        return Match(exact[0], tuple(exact))
    if exact:
        return Match(None, tuple(exact))
    partial = [item for item in pressable if wanted in normalize_name(item.name)]
    if len(partial) == 1:
        return Match(partial[0], tuple(partial))
    return Match(None, tuple(partial))


def visible_names(controls: Sequence[UiControl], *, limit: int = 12) -> list[str]:
    """Names a person could say instead, for "I could not find ..." replies."""
    names: list[str] = []
    for item in controls:
        if item.control not in CLICKABLE or item.is_password or not item.is_enabled:
            continue
        name = " ".join(item.name.split())
        if name and name not in names and len(name) <= 40:
            names.append(name)
        if len(names) >= limit:
            break
    return names


# --- Windows ----------------------------------------------------------------


def read_uia_controls(hwnd: int, *, limit: int = MAX_NODES) -> list[UiControl]:
    """The window's pressable controls, in tree order. Empty without UIA."""
    if not hwnd or sys.platform != "win32" or not live_desktop_enabled():
        return []
    try:
        import comtypes.client  # type: ignore

        uia_module = comtypes.client.GetModule("UIAutomationCore.dll")
        uia = comtypes.client.CreateObject(uia_module.CUIAutomation)
        window = uia.ElementFromHandle(hwnd)
        if not window:
            return []
        names = {
            uia_module.UIA_ButtonControlTypeId: "button",
            uia_module.UIA_HyperlinkControlTypeId: "hyperlink",
            uia_module.UIA_MenuItemControlTypeId: "menuitem",
            uia_module.UIA_TabItemControlTypeId: "tabitem",
            uia_module.UIA_CheckBoxControlTypeId: "checkbox",
            uia_module.UIA_RadioButtonControlTypeId: "radiobutton",
            uia_module.UIA_ListItemControlTypeId: "listitem",
            uia_module.UIA_SplitButtonControlTypeId: "splitbutton",
            uia_module.UIA_TreeItemControlTypeId: "treeitem",
        }
        elements = window.FindAll(
            uia_module.TreeScope_Subtree, uia.CreateTrueCondition()
        )
        controls: list[UiControl] = []
        for index in range(elements.Length):
            if len(controls) >= limit:
                break
            try:
                element = elements.GetElement(index)
                control = names.get(int(element.CurrentControlType))
                if control is None:
                    continue
                controls.append(
                    UiControl(
                        control=control,
                        name=str(element.CurrentName or ""),
                        is_password=bool(element.CurrentIsPassword),
                        is_enabled=bool(element.CurrentIsEnabled),
                        element=(element, uia_module),
                    )
                )
            except Exception:
                continue
        return controls
    except Exception as exc:
        logger.debug("UI Automation control walk failed: %s", exc)
        return []


def press(control: UiControl) -> bool:
    """Press through the element's own pattern. False when it has none."""
    if not control.element or not live_desktop_enabled():
        return False
    element, uia_module = control.element
    attempts = (
        (uia_module.UIA_InvokePatternId, "IUIAutomationInvokePattern", "Invoke"),
        (uia_module.UIA_TogglePatternId, "IUIAutomationTogglePattern", "Toggle"),
        (
            uia_module.UIA_SelectionItemPatternId,
            "IUIAutomationSelectionItemPattern",
            "Select",
        ),
        (
            uia_module.UIA_LegacyIAccessiblePatternId,
            "IUIAutomationLegacyIAccessiblePattern",
            "DoDefaultAction",
        ),
    )
    for pattern_id, interface, method in attempts:
        try:
            pattern = element.GetCurrentPattern(pattern_id)
            if not pattern:
                continue
            typed = pattern.QueryInterface(getattr(uia_module, interface))
            getattr(typed, method)()
            return True
        except Exception as exc:
            logger.debug("UIA %s failed: %s", method, exc)
            continue
    return False


__all__ = [
    "CLICKABLE",
    "ControlReader",
    "Match",
    "Presser",
    "RISKY_CLICK_WORDS",
    "UiControl",
    "clean_target",
    "find_control",
    "is_risky",
    "normalize_name",
    "press",
    "read_uia_controls",
    "visible_names",
]
