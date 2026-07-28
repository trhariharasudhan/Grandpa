"""Deterministic natural-language planner for visible desktop automation."""

from __future__ import annotations

import re

from grandpa.automation.models import AutomationAction

_DESTRUCTIVE_TERMS = {
    "delete",
    "remove",
    "erase",
    "format",
    "shutdown",
    "restart",
    "purchase",
    "buy",
    "pay",
    "transfer",
    "checkout",
    "confirm order",
}
_SENSITIVE_TERMS = {
    "password",
    "passcode",
    "otp",
    "one time password",
    "card number",
    "cvv",
    "bank",
    "authentication",
    "sign in",
    "login",
}
_KEYS = {
    "enter": ["enter"],
    "return": ["enter"],
    "escape": ["esc"],
    "esc": ["esc"],
    "tab": ["tab"],
    "ctrl c": ["ctrl", "c"],
    "control c": ["ctrl", "c"],
    "ctrl v": ["ctrl", "v"],
    "control v": ["ctrl", "v"],
    "ctrl a": ["ctrl", "a"],
    "control a": ["ctrl", "a"],
    "ctrl s": ["ctrl", "s"],
    "control s": ["ctrl", "s"],
    "alt tab": ["alt", "tab"],
}


class AutomationPlanner:
    def parse(self, text: str) -> AutomationAction | None:
        raw = str(text).strip()
        command = _normalize(raw)
        if not command:
            return None

        action = (
            self._parse_locate(command)
            or self._parse_mouse(command)
            or self._parse_keyboard(raw, command)
            or self._parse_window(command)
        )
        return apply_safety_policy(action, command) if action is not None else None

    def _parse_locate(self, command: str) -> AutomationAction | None:
        match = re.fullmatch(r"locate (?:the )?(.+)", command)
        if match:
            return AutomationAction("locate", _clean_element_target(match.group(1)))
        match = re.fullmatch(r"find (?:the )?(.+)", command)
        if match and _looks_like_ui_target(match.group(1)):
            return AutomationAction("locate", _clean_element_target(match.group(1)))
        match = re.fullmatch(r"highlight (?:the )?(.+)", command)
        if match:
            return AutomationAction("highlight", _clean_element_target(match.group(1)))
        return None

    def _parse_mouse(self, command: str) -> AutomationAction | None:
        match = re.fullmatch(r"move (?:the )?mouse(?: to)?[ ,]+(-?\d+)[ ,]+(-?\d+)", command)
        if match:
            return AutomationAction("move", args={"x": int(match.group(1)), "y": int(match.group(2))})
        match = re.fullmatch(r"move (?:the )?mouse to (.+)", command)
        if match:
            return AutomationAction("move", _clean_element_target(match.group(1)))
        if command in {"move mouse", "move the mouse"}:
            return AutomationAction("move", args={"relative_x": 20, "relative_y": 0})
        match = re.fullmatch(r"(double click|right click|middle click|click)(?: (?:the )?(.+))?", command)
        if match:
            kind = match.group(1).replace(" ", "_")
            target = _clean_element_target(match.group(2) or "")
            coordinates = _coordinates(target)
            args = {"x": coordinates[0], "y": coordinates[1]} if coordinates else {}
            return AutomationAction(kind, "" if coordinates else target, args)
        match = re.fullmatch(r"scroll (up|down)(?: (\d+))?", command)
        if match:
            amount = int(match.group(2) or 5)
            if match.group(1) == "down":
                amount = -amount
            return AutomationAction("scroll", match.group(1), {"amount": amount})
        match = re.fullmatch(
            r"drag from[ ,]+(-?\d+)[ ,]+(-?\d+) to[ ,]+(-?\d+)[ ,]+(-?\d+)", command
        )
        if match:
            values = [int(value) for value in match.groups()]
            return AutomationAction(
                "drag",
                args={
                    "start_x": values[0],
                    "start_y": values[1],
                    "end_x": values[2],
                    "end_y": values[3],
                },
            )
        return None

    def _parse_keyboard(self, raw: str, command: str) -> AutomationAction | None:
        if command.startswith("type "):
            text = raw.strip()[len(raw.strip().split(maxsplit=1)[0]) :].strip()
            return AutomationAction("type", args={"text": text})
        if command in {"paste", "paste here"}:
            return AutomationAction("paste", args={"keys": ["ctrl", "v"]})
        shortcut = {
            "select all": ("ctrl a", ["ctrl", "a"]),
            "copy": ("ctrl c", ["ctrl", "c"]),
            "copy this": ("ctrl c", ["ctrl", "c"]),
            "paste this": ("ctrl v", ["ctrl", "v"]),
        }.get(command)
        if shortcut is not None:
            label, keys = shortcut
            return AutomationAction("press", label, {"keys": keys})
        key = command.removeprefix("press ").strip() if command.startswith("press ") else ""
        if key in _KEYS:
            return AutomationAction("press", key, {"keys": _KEYS[key]})
        return None

    def _parse_window(self, command: str) -> AutomationAction | None:
        match = re.fullmatch(r"(?:focus|switch to|bring) (.+?)(?: to front)?", command)
        if match:
            return AutomationAction("focus", match.group(1).strip())
        match = re.fullmatch(r"(maximize|minimize|restore)(?: (?:the )?(.+))?", command)
        if match:
            target = (match.group(2) or "active").replace("this window", "active")
            return AutomationAction(match.group(1), target)
        return None


def apply_safety_policy(action: AutomationAction, command: str) -> AutomationAction:
    text = f"{command} {action.target}".casefold()
    sensitive = any(term in text for term in _SENSITIVE_TERMS) or _contains_sensitive_value(text)
    destructive = any(term in text for term in _DESTRUCTIVE_TERMS)
    interactive_click = action.kind in {"click", "double_click", "right_click", "middle_click", "drag"}
    risky_enter = action.kind == "press" and action.args.get("keys") == ["enter"] and destructive
    needs_confirmation = interactive_click or sensitive or destructive or risky_enter
    reason = ""
    if sensitive:
        reason = "This action may involve authentication or sensitive data."
    elif destructive:
        reason = "This action may cause a destructive or financial change."
    elif interactive_click:
        reason = "Clicks can change the active application."
    return AutomationAction(
        action.kind,
        action.target,
        action.args,
        needs_confirmation,
        reason,
        sensitive,
    )


def _normalize(text: str) -> str:
    value = re.sub(r"[?!;:+]+", " ", text.casefold())
    return re.sub(r"\s+", " ", value).strip()


def _clean_element_target(target: str) -> str:
    value = target.strip().removeprefix("at ")
    return re.sub(r"\s+(button|icon|label|field|box)$", "", value).strip()


def _coordinates(target: str) -> tuple[int, int] | None:
    match = re.fullmatch(r"(?:at )?\(?(-?\d+)[ ,]+(-?\d+)\)?", target)
    return (int(match.group(1)), int(match.group(2))) if match else None


def _looks_like_ui_target(target: str) -> bool:
    value = target.casefold()
    return any(
        marker in value
        for marker in (
            "button",
            "icon",
            "label",
            "field",
            "box",
            "window title",
            "error message",
            "on screen",
        )
    )


def _contains_sensitive_value(text: str) -> bool:
    digits = re.sub(r"\D", "", text)
    return bool(
        re.search(r"\b(?:sk-|bearer\s+)[a-z0-9._-]{8,}\b", text)
        or 13 <= len(digits) <= 19
        or re.search(r"\b(?:otp|code)\s+\d{4,8}\b", text)
    )


__all__ = ["AutomationPlanner", "apply_safety_policy"]
