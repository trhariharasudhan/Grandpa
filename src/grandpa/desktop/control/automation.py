"""Keyboard and mouse automation service for PC control.

This is the one owner of synthetic input. There used to be two: this service,
reached by the action layer and pc_control, and ``grandpa.desktop_automation``,
reached by chat through ``local_actions``. Each blocked what the other allowed.
This one refused Win+R, Win+X, Ctrl+Shift+Esc and Ctrl+Alt+Del outright and, via
``pc_control._preflight_guard``, refused to type into a window that looks
sensitive. That one refused *text* that named a shell -- powershell, cmd, format
-- and rate-limited itself, but would press Win+R on a yes, which opens the Run
dialog: the exact command-execution surface the first list exists to deny.

All three guards live here now, so the weaker route cannot reappear by calling a
different module.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any

# Key aliases normalised before checking the hotkey denylist, so "Windows+R",
# "win + r" and "WIN+r" are all recognised as the same combination.
_HOTKEY_ALIASES = {
    "windows": "win",
    "super": "win",
    "meta": "win",
    "cmd": "win",
    "command": "win",
    "control": "ctrl",
    "escape": "esc",
    "del": "delete",
    "return": "enter",
}

# Key combinations that open a command-execution surface. These are blocked
# outright rather than gated on approval: approving "press Win+R" is in effect
# approving shell access, which BLOCKED_ACTIONS (script_run / shell_run) exists
# to prevent. Compared as unordered key sets.
_BLOCKED_HOTKEYS = (
    frozenset({"win", "r"}),  # Run dialog
    frozenset({"win", "x"}),  # Power User menu -> Terminal / PowerShell
    frozenset({"ctrl", "shift", "esc"}),  # Task Manager
    frozenset({"ctrl", "alt", "delete"}),  # Secure attention sequence
)

# Text that must not be typed. Carried over from grandpa.desktop_automation,
# which had these and no hotkey denylist. Pressing Win+R is blocked above, but a
# launcher can also be reached by other means -- an already-open terminal, a
# browser address bar -- and typing a shell name into one is the same capability
# script_run and shell_run are BLOCKED to prevent.
_BLOCKED_TEXT_PATTERNS = (
    r"\bdelete\b.*\bsystem32\b",
    r"\bformat\b",
    r"\bwipe\b",
    r"\brm\s+-",
    r"\bdel\s+",
    r"\bpowershell\b",
    r"\bcmd(?:\.exe)?\b",
)

_ACTION_COOLDOWN_SECONDS = 0.35
"""Smallest gap between two synthetic input actions.

Also carried over. It is not a security control on its own -- it is what stops a
runaway loop from driving the desktop faster than a person can interrupt it.
"""

_last_action_at = 0.0


def is_blocked_text(value: Any) -> bool:
    """True when this text names a shell or a destructive command."""
    lowered = str(value or "").casefold()
    return any(re.search(pattern, lowered) for pattern in _BLOCKED_TEXT_PATTERNS)


_SPEC_ACTIONS: dict[str, tuple[str, str]] = {
    "type": ("keyboard_type", "text"),
    "press": ("keyboard_hotkey", "keys"),
    "hotkey": ("keyboard_hotkey", "keys"),
    "click": ("mouse_click", "target"),
    "scroll": ("mouse_scroll", "direction"),
    "click_center": ("mouse_click", ""),
    "move_center": ("mouse_move", ""),
}
"""Specs that are synthetic input. ``focus`` is not here: it is a window action.

When this table replaced ``grandpa.desktop_automation`` in Phase 1.6, three of
that module's specs were mapped wrongly or not at all. ``click_center`` and
``move_center`` had no entry, so they answered "not supported" where they had
worked. ``focus`` was sent to ``desktop_navigate``, which only moves a selection
up, down, left or right and so refused every app name -- including the first
half of "type hello in notepad".
"""

_UNSUPPORTED_SPECS: dict[str, str] = {
    "click_highlighted": (
        "Clicking highlighted UI elements needs visual target detection, which is "
        "not enabled yet."
    ),
}
"""Specs that have always been refusals, kept as the same honest refusal."""


@dataclass(frozen=True)
class AutomationResult:
    """What a spec run reports back, in ``local_actions``' shape."""

    status: str
    action: str
    message: str
    tts_text: str = ""


@dataclass(frozen=True)
class _SpecRequest:
    """The request shape the service reads: ``.target`` and ``.args``."""

    target: str = ""
    args: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "args", dict(self.args or {}))


def execute_spec(
    spec: str,
    *,
    confirm_callback: Any = None,
    confirmed: bool = False,
    platform: str | None = None,
) -> AutomationResult:
    """Run one ``"type|hello"`` style spec through this service.

    Translation and nothing else. The blocked hotkeys, the blocked text, the
    protected-window check and the cooldown all belong to ``execute`` -- which is
    the point of there being one owner, rather than a second module that asked
    politely about text and pressed Win+R on a yes.
    """
    import sys

    if "||" in spec:
        # A chain, in order, stopping at the first step that does not complete.
        # Each step is checked and confirmed on its own: approving the focus in
        # "type hello in notepad" is not approving the typing.
        messages: list[str] = []
        for part in (piece.strip() for piece in spec.split("||")):
            if not part:
                continue
            step = execute_spec(
                part,
                confirm_callback=confirm_callback,
                confirmed=confirmed,
                platform=platform,
            )
            if step.status != "handled":
                return step
            messages.append(step.message)
        message = " ".join(messages)
        return AutomationResult("handled", spec, message, message)

    action_name, _, argument = spec.partition("|")
    action_name = action_name.strip().casefold()
    argument = argument.strip()

    if action_name in _UNSUPPORTED_SPECS:
        message = _UNSUPPORTED_SPECS[action_name]
        return AutomationResult("unsupported", spec, message, message)

    if action_name == "focus":
        return _focus_window(spec, argument)

    mapped = _SPEC_ACTIONS.get(action_name)
    if mapped is None:
        message = "That desktop action is not supported."
        return AutomationResult("unsupported", spec, message, message)

    name, key = mapped
    # Ask exactly when pc_control would: its approval set is the one rule for
    # synthetic input. Scrolling and focusing a window are deliberately outside
    # it -- neither activates anything -- so they no longer prompt here either.
    # Asking for everything looked stricter, but it taught a user to say yes
    # without reading, which is the opposite of what a prompt is for.
    from grandpa.pc_control import APPROVAL_REQUIRED_ACTIONS

    if not confirmed and name in APPROVAL_REQUIRED_ACTIONS:
        if confirm_callback is None:
            message = "Confirmation required before controlling the active app."
            return AutomationResult("blocked", spec, message, message)
        if not confirm_callback(spec, "requires_confirmation"):
            return AutomationResult("cancelled", spec, "Cancelled.", "Cancelled.")

    args: dict[str, Any] = {key: argument} if key else {}
    if action_name in {"click_center", "move_center"}:
        args.update(_screen_center())
    response = AutomationControlService().execute(
        _SpecRequest(target=argument, args=args),
        name,
        platform=platform or sys.platform,
    )
    message = str(getattr(response, "message", "") or "")
    if getattr(response, "ok", False):
        return AutomationResult("handled", spec, message, message)
    status = str(getattr(response, "status", "") or "blocked")
    return AutomationResult(
        status if status in {"unsupported", "blocked", "failed"} else "blocked",
        spec,
        message,
        message,
    )


def _screen_center() -> dict[str, int]:
    """The primary screen's centre, from the system rather than a guess."""
    try:
        import ctypes

        metrics = ctypes.windll.user32.GetSystemMetrics  # type: ignore[attr-defined]
        return {"x": int(metrics(0)) // 2, "y": int(metrics(1)) // 2}
    except Exception:
        return {"x": 0, "y": 0}


def _focus_window(spec: str, target: str) -> AutomationResult:
    """Bring a named application's window to the front.

    A window action, so it goes to the window domain. The deleted module handled
    only ``focus|chrome``, by pressing Alt+Tab and hoping; every other name was
    "not supported". Focusing does not activate anything in the window it
    brings forward, so it does not ask.
    """
    from grandpa.desktop.control.windows import WindowControlService

    if not target:
        message = "Tell me which window to bring to the front."
        return AutomationResult("unsupported", spec, message, message)

    response = WindowControlService().execute(
        _SpecRequest(target=target), "focus_window"
    )
    message = str(getattr(response, "message", "") or "")
    status = "handled" if getattr(response, "ok", False) else "failed"
    return AutomationResult(status, spec, message, message)


def _cooldown_remaining() -> float:
    return max(0.0, _ACTION_COOLDOWN_SECONDS - (time.monotonic() - _last_action_at))


def _mark_action() -> None:
    global _last_action_at
    _last_action_at = time.monotonic()


def _normalise_hotkey(keys: Any) -> list[str]:
    """Split and canonicalise a hotkey spec into a list of lowercase key names."""
    if isinstance(keys, str):
        parts = [part for part in keys.split("+")]
    elif isinstance(keys, (list, tuple)):
        parts = [str(part) for part in keys]
    else:
        parts = [str(keys)]
    normalised: list[str] = []
    for part in parts:
        token = str(part).strip().lower()
        if not token:
            continue
        normalised.append(_HOTKEY_ALIASES.get(token, token))
    return normalised


def is_blocked_hotkey(keys: Any) -> bool:
    """Return ``True`` when *keys* names a denied command-execution shortcut."""
    pressed = frozenset(_normalise_hotkey(keys))
    return any(combo <= pressed for combo in _BLOCKED_HOTKEYS)


@dataclass(frozen=True)
class AutomationControlService:
    """Visible-screen keyboard and mouse actions."""

    name: str = "automation"

    def execute(self, request: Any, action: str, *, platform: str):
        """Check, then actuate, then start the cooldown.

        The order matters. A refusal must not start the cooldown, or one blocked
        hotkey would make the next honest request fail too and the reason a user
        was given would be the wrong one.
        """
        from grandpa.pc_control import LocalActionResponse

        if platform != "win32":
            return LocalActionResponse(
                False,
                None,
                "unsupported",
                "Keyboard and mouse control is only supported on Windows desktop.",
                False,
                "MEDIUM",
                error="unsupported",
            )
        # The window check runs for every input action, not just the ones
        # pc_control's preflight covered: a caller reaching this service
        # directly used to get no check at all.
        from grandpa.desktop_context import active_window_is_protected

        try:
            if active_window_is_protected():
                return LocalActionResponse(
                    False,
                    None,
                    "blocked",
                    "I blocked this because the active window appears sensitive.",
                    False,
                    "HIGH",
                    {"protected_window": True},
                    error="protected_window",
                )
        except Exception:  # pragma: no cover - platform specific
            pass

        remaining = _cooldown_remaining()
        if remaining > 0:
            return LocalActionResponse(
                False,
                None,
                "blocked",
                "That was too fast after the last desktop action; try again.",
                False,
                "MEDIUM",
                {"retry_after_seconds": round(remaining, 2)},
                error="cooldown",
            )

        response = self._actuate(request, action)
        if getattr(response, "ok", False):
            _mark_action()
        return response

    def _actuate(self, request: Any, action: str):
        import pyautogui  # type: ignore

        from grandpa.pc_control import LocalActionResponse

        pyautogui.FAILSAFE = True
        if action == "keyboard_type":
            text = str(request.args.get("text", request.target))
            if is_blocked_text(text):
                return LocalActionResponse(
                    False,
                    None,
                    "blocked",
                    "I blocked this text because it names a shell or a "
                    "destructive command.",
                    False,
                    "BLOCKED",
                    {"characters": len(text)},
                    error="blocked_by_policy",
                )
            pyautogui.write(text, interval=0.01)
            return LocalActionResponse(
                True,
                None,
                "completed",
                "Typed text.",
                False,
                "MEDIUM",
                {"characters": len(text)},
            )
        if action == "keyboard_hotkey":
            raw_keys = request.args.get("keys", request.target)
            keys = _normalise_hotkey(raw_keys)
            if not keys:
                return LocalActionResponse(
                    False,
                    None,
                    "blocked",
                    "I blocked this hotkey because no keys were supplied.",
                    False,
                    "BLOCKED",
                    error="blocked_by_policy",
                )
            if is_blocked_hotkey(keys):
                return LocalActionResponse(
                    False,
                    None,
                    "blocked",
                    "I blocked this hotkey because it opens a command-execution surface.",
                    False,
                    "BLOCKED",
                    {"keys": keys},
                    error="blocked_by_policy",
                )
            pyautogui.hotkey(*keys)
            return LocalActionResponse(
                True,
                None,
                "completed",
                "Pressed hotkey.",
                False,
                "MEDIUM",
                {"keys": keys},
            )
        if action == "mouse_move":
            if "relative_x" in request.args or "relative_y" in request.args:
                pyautogui.moveRel(
                    int(request.args.get("relative_x", 0)),
                    int(request.args.get("relative_y", 0)),
                    duration=max(
                        0.0, min(1.0, float(request.args.get("duration", 0.15)))
                    ),
                )
            else:
                pyautogui.moveTo(
                    int(request.args.get("x", 0)),
                    int(request.args.get("y", 0)),
                    duration=max(
                        0.0, min(1.0, float(request.args.get("duration", 0.15)))
                    ),
                )
            return LocalActionResponse(
                True,
                None,
                "completed",
                "Moved mouse.",
                False,
                "MEDIUM",
                {"x": request.args.get("x"), "y": request.args.get("y")},
            )
        if action == "mouse_click":
            pyautogui.click(
                int(request.args.get("x", 0)),
                int(request.args.get("y", 0)),
                clicks=max(1, min(2, int(request.args.get("clicks", 1)))),
                interval=max(0.0, min(0.5, float(request.args.get("interval", 0.12)))),
                button=str(request.args.get("button", "left")),
            )
            return LocalActionResponse(
                True,
                None,
                "completed",
                "Clicked mouse.",
                False,
                "MEDIUM",
                {"x": request.args.get("x"), "y": request.args.get("y")},
            )
        if action == "mouse_scroll":
            pyautogui.scroll(int(request.args.get("amount", request.target or 0)))
            return LocalActionResponse(
                True,
                None,
                "completed",
                "Scrolled mouse.",
                False,
                "MEDIUM",
                {"amount": request.args.get("amount", request.target)},
            )
        if action == "mouse_drag":
            start_x = int(request.args.get("start_x", request.args.get("x", 0)))
            start_y = int(request.args.get("start_y", request.args.get("y", 0)))
            end_x = int(request.args.get("end_x", request.args.get("to_x", 0)))
            end_y = int(request.args.get("end_y", request.args.get("to_y", 0)))
            duration = max(0.1, min(2.0, float(request.args.get("duration", 0.25))))
            pyautogui.moveTo(start_x, start_y)
            pyautogui.dragTo(
                end_x,
                end_y,
                duration=duration,
                button=str(request.args.get("button", "left")),
            )
            return LocalActionResponse(
                True,
                None,
                "completed",
                "Dragged the mouse.",
                False,
                "MEDIUM",
                {
                    "start": [start_x, start_y],
                    "end": [end_x, end_y],
                    "duration": duration,
                },
            )
        if action == "desktop_navigate":
            direction = str(request.args.get("direction", request.target)).lower()
            if direction not in {"up", "down", "left", "right"}:
                return LocalActionResponse(
                    False,
                    None,
                    "blocked",
                    "I blocked this navigation action for safety.",
                    False,
                    "BLOCKED",
                    error="blocked_by_policy",
                )
            pyautogui.press(direction)
            return LocalActionResponse(
                True,
                None,
                "completed",
                f"Moved selection {direction}.",
                False,
                "MEDIUM",
                {"direction": direction},
            )
        return LocalActionResponse(
            False,
            None,
            "blocked",
            "I blocked this automation action for safety.",
            False,
            "BLOCKED",
            error="blocked_by_policy",
        )

    def diagnostics(self, *, platform: str) -> dict[str, Any]:
        try:
            import pyautogui  # noqa: F401

            pyautogui_available = True
        except Exception:
            pyautogui_available = False
        return {
            "service": self.name,
            "ready": platform == "win32" and pyautogui_available,
            "risk_levels": {
                "keyboard_type": "MEDIUM",
                "keyboard_hotkey": "MEDIUM",
                "mouse_move": "MEDIUM",
                "mouse_click": "MEDIUM",
                "mouse_scroll": "MEDIUM",
                "mouse_drag": "MEDIUM",
                "desktop_navigate": "MEDIUM",
            },
            "dependencies": {"pyautogui": pyautogui_available, "platform": platform},
            "safety": {"failsafe": True, "protected_window_preflight": True},
        }


__all__ = [
    "AutomationResult",
    "execute_spec",
    "is_blocked_text",
    "AutomationControlService",
    "is_blocked_hotkey",
]
