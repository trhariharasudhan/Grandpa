"""Visible-screen-only desktop automation for Grandpa.

This module is intentionally small and allowlisted. It does not expose
arbitrary scripting, background automation, loops, or hidden window control.
"""

from __future__ import annotations

import logging
import re
import sys
import time
from dataclasses import dataclass
from typing import Literal

logger = logging.getLogger(__name__)

AutomationStatus = Literal["handled", "blocked", "unsupported", "error"]

COOLDOWN_SECONDS = 0.75
_last_action_at = 0.0

_DANGEROUS_TEXT_PATTERNS = (
    r"\bpassword\b",
    r"\bpasscode\b",
    r"\botp\b",
    r"\bpin\b",
    r"\bcredit\s*card\b",
    r"\bcard\s*number\b",
    r"\bssn\b",
    r"\bsecret\b",
    r"\btoken\b",
)


@dataclass(frozen=True)
class AutomationResult:
    status: AutomationStatus
    action: str
    message: str
    tts_text: str = ""


def execute_automation(spec: str) -> AutomationResult:
    """Execute a tiny allowlisted automation spec."""
    if sys.platform != "win32":
        return AutomationResult(
            status="unsupported",
            action=spec,
            message="Desktop automation is not supported in this environment.",
            tts_text="Desktop automation is not supported here.",
        )

    cooldown = _check_cooldown()
    if cooldown is not None:
        return cooldown

    try:
        import pyautogui  # type: ignore
    except Exception:
        return AutomationResult(
            status="unsupported",
            action=spec,
            message="Desktop automation needs pyautogui installed on this Windows machine.",
            tts_text="Desktop automation needs pyautogui installed.",
        )

    try:
        pyautogui.FAILSAFE = True
        result = _execute_with_pyautogui(pyautogui, spec)
    except Exception as exc:  # pragma: no cover - device/permission edge
        result = AutomationResult(
            status="error",
            action=spec,
            message=f"I could not complete that desktop action: {exc}",
            tts_text="I could not complete that desktop action.",
        )

    _mark_action_time()
    _log_automation(spec, result)
    return result


def requires_confirmation(spec: str) -> bool:
    """Return True for action specs that should require future confirmation."""
    if "||" in spec:
        messages = []
        final_result = None
        for part in spec.split("||"):
            result = _execute_with_pyautogui(pyautogui, part)
            final_result = result
            messages.append(result.message)
        return AutomationResult(
            status=final_result.status if final_result else "error",
            message=" ".join(messages),
            tts_text=final_result.tts_text if final_result else "",
        )

    action, value = _split_spec(spec)
    if action in {"paste", "click_highlighted"}:
        return True
    if action == "type" and _contains_sensitive_text(value):
        return True
    return False


def emergency_stop_placeholder() -> str:
    return (
        "Emergency stop design: move the mouse to a screen corner to trigger "
        "pyautogui failsafe; future UI can expose a persistent stop button."
    )


def _execute_with_pyautogui(pyautogui, spec: str) -> AutomationResult:
    action, value = _split_spec(spec)

    if action == "type":
        if _contains_sensitive_text(value):
            return AutomationResult(
                status="blocked",
                action=spec,
                message="I blocked this action for safety.",
                tts_text="I blocked this action for safety.",
            )
        pyautogui.write(value, interval=0.01)
        return AutomationResult(
            status="handled",
            action=spec,
            message=f'Typed "{value}".',
            tts_text="Typed that.",
        )

    if action == "press" and value in {"enter", "tab", "escape"}:
        pyautogui.press(value)
        return AutomationResult(
            status="handled",
            action=spec,
            message=f"Pressed {value}.",
            tts_text=f"Pressed {value}.",
        )

    if action == "scroll":
        amount = -5 if value == "down" else 5
        pyautogui.scroll(amount)
        return AutomationResult(
            status="handled",
            action=spec,
            message=f"Scrolled {value}.",
            tts_text=f"Scrolled {value}.",
        )

    if action == "hotkey":
        keys = value.split("+")
        if keys in (["ctrl", "c"], ["ctrl", "v"], ["alt", "tab"]):
            pyautogui.hotkey(*keys)
            label = "+".join(keys)
            return AutomationResult(
                status="handled",
                action=spec,
                message=f"Pressed {label}.",
                tts_text=f"Pressed {label}.",
            )

    if action == "click_center":
        width, height = pyautogui.size()
        pyautogui.click(width // 2, height // 2)
        return AutomationResult(
            status="handled",
            action=spec,
            message="Clicked the center of the screen.",
            tts_text="Clicked the center of the screen.",
        )

    if action == "move_center":
        width, height = pyautogui.size()
        pyautogui.moveTo(width // 2, height // 2)
        return AutomationResult(
            status="handled",
            action=spec,
            message="Moved the mouse to the center of the screen.",
            tts_text="Moved the mouse to the center.",
        )

    if action == "focus" and value == "chrome":
        pyautogui.hotkey("alt", "tab")
        return AutomationResult(
            status="handled",
            action=spec,
            message="Tried to switch focus toward Chrome.",
            tts_text="Tried to focus Chrome.",
        )

    if action == "click_highlighted":
        return AutomationResult(
            status="unsupported",
            action=spec,
            message=(
                "Clicking highlighted UI elements needs visual target detection, "
                "which is not enabled in Phase 3."
            ),
            tts_text="Highlighted button clicking is not enabled yet.",
        )

    return AutomationResult(
        status="unsupported",
        action=spec,
        message="That desktop automation action is not supported.",
        tts_text="That desktop automation action is not supported.",
    )


def _split_spec(spec: str) -> tuple[str, str]:
    if "|" not in spec:
        return spec, ""
    action, value = spec.split("|", 1)
    return action, value


def _contains_sensitive_text(text: str) -> bool:
    lowered = text.lower()
    return any(re.search(pattern, lowered) for pattern in _DANGEROUS_TEXT_PATTERNS)


def _check_cooldown() -> AutomationResult | None:
    remaining = COOLDOWN_SECONDS - (time.monotonic() - _last_action_at)
    if remaining <= 0:
        return None
    return AutomationResult(
        status="blocked",
        action="cooldown",
        message="Please wait a moment before sending another desktop action.",
        tts_text="Please wait a moment before another desktop action.",
    )


def _mark_action_time() -> None:
    global _last_action_at
    _last_action_at = time.monotonic()


def _log_automation(spec: str, result: AutomationResult) -> None:
    logger.info(
        "desktop_automation_attempt spec=%r status=%s message=%r",
        spec,
        result.status,
        result.message,
    )


__all__ = [
    "AutomationResult",
    "emergency_stop_placeholder",
    "execute_automation",
    "requires_confirmation",
]
