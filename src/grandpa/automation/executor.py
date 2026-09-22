"""Execution bridge from planned automation into existing safe services."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from grandpa.automation.keyboard import keyboard_payload
from grandpa.automation.locator import HighlightOverlay, ScreenElementLocator
from grandpa.automation.models import AutomationAction, AutomationResult, Point
from grandpa.automation.mouse import mouse_payload
from grandpa.automation.windows import window_payload
from grandpa.screen.errors import SensitiveScreenDetectedError

ActionRunner = Callable[[dict[str, Any]], Any]


class AutomationExecutor:
    def __init__(
        self,
        *,
        runner: ActionRunner | None = None,
        locator: ScreenElementLocator | None = None,
        highlighter: HighlightOverlay | None = None,
    ) -> None:
        self.runner = runner or _default_runner
        self.locator = locator or ScreenElementLocator()
        self.highlighter = highlighter or HighlightOverlay()

    def execute(
        self,
        action: AutomationAction,
        *,
        dry_run: bool = False,
        require_approval: bool = False,
    ) -> AutomationResult:
        started = time.perf_counter()
        try:
            if action.kind in {"locate", "highlight"}:
                return self._locate(action, started)
            point, element = self._resolve_point(action)
            payload = self._payload(action, point)
            payload.update({"dry_run": dry_run, "require_approval": require_approval})
            response = self.runner(payload)
            return _result_from_response(action, response, element, started)
        except SensitiveScreenDetectedError as exc:
            return AutomationResult("blocked", str(exc), action)
        except LocatorResolutionError as exc:
            return AutomationResult(exc.status, str(exc), action)  # type: ignore[arg-type]
        except Exception as exc:
            return AutomationResult(
                "error",
                f"I could not complete that automation action ({exc.__class__.__name__}).",
                action,
                data={"duration_ms": _elapsed_ms(started)},
            )

    def _locate(self, action: AutomationAction, started: float) -> AutomationResult:
        matches = self.locator.locate(action.target)
        if not matches:
            return AutomationResult(
                "not_found",
                f'I could not find "{action.target}" on the visible screen.',
                action,
                data={"duration_ms": _elapsed_ms(started)},
            )
        element = matches[0]
        if action.kind == "highlight":
            self.highlighter.show(element)
        box = element.bounds
        return AutomationResult(
            "handled",
            (
                f'Found "{_display_label(element.text)}" at ({box.center.x}, {box.center.y}) '
                f"with {element.confidence:.0%} confidence."
            ),
            action,
            element,
            data={
                "matches": [item.to_dict() for item in matches],
                "duration_ms": _elapsed_ms(started),
            },
        )

    def _resolve_point(
        self, action: AutomationAction
    ) -> tuple[Point | None, Any | None]:
        if "x" in action.args and "y" in action.args:
            return Point(int(action.args["x"]), int(action.args["y"])), None
        if (
            action.kind
            not in {
                "move",
                "click",
                "double_click",
                "right_click",
                "middle_click",
            }
            or not action.target
        ):
            return None, None
        matches = self.locator.locate(action.target, limit=2)
        if not matches:
            raise LocatorResolutionError(
                f'I could not find "{action.target}" on the visible screen.'
            )
        if (
            len(matches) > 1
            and abs(matches[0].confidence - matches[1].confidence) < 0.05
        ):
            raise LocatorResolutionError(
                f'I found multiple possible matches for "{action.target}". Please be more specific.',
                status="ambiguous",
            )
        return matches[0].bounds.center, matches[0]

    def _payload(self, action: AutomationAction, point: Point | None) -> dict[str, Any]:
        if action.kind in MOUSE_KINDS:
            return mouse_payload(action, point)
        if action.kind in KEYBOARD_KINDS:
            return keyboard_payload(action)
        if action.kind in {"focus", "maximize", "minimize", "restore"}:
            return window_payload(action)
        raise ValueError(f"Unsupported automation action: {action.kind}")


MOUSE_KINDS = frozenset(
    {"move", "click", "double_click", "right_click", "middle_click", "scroll", "drag"}
)
KEYBOARD_KINDS = frozenset({"type", "paste", "press"})
INPUT_KINDS = MOUSE_KINDS | KEYBOARD_KINDS | {"scroll_until"}
"""Every kind that sends keyboard or mouse input; the rest locate or manage windows."""


class LocatorResolutionError(RuntimeError):
    def __init__(self, message: str, *, status: str = "not_found") -> None:
        super().__init__(message)
        self.status = status


def _default_runner(payload: dict[str, Any]) -> Any:
    """Perform one input action through the action layer.

    Not pc_control: it refuses synthetic input at its own door now, because a
    code is consent from minutes ago. The service above has already asked the
    caller, in this turn, so the layer is told the consent is held -- and the
    layer still applies the catalogue's schema and the automation service's
    denylists, protected-window check and cooldown.
    """
    from grandpa.action_layer.catalogue import get
    from grandpa.action_layer.executor import execute
    from grandpa.action_layer.model import ActionRequest, Origin

    action = str(payload.get("action_type") or "")
    spec = get(action)
    if spec is None:
        from grandpa.pc_control import run_local_action

        return run_local_action(payload)
    parameters = dict(payload.get("args") or {})
    if spec.target_parameter and payload.get("target"):
        parameters.setdefault(spec.target_parameter, payload["target"])
    return execute(
        ActionRequest(
            action,
            parameters,
            origin=Origin.USER_CHAT,
            risk=spec.risk,
            requires_confirmation=spec.requires_confirmation,
        ),
        lambda *_a, **_k: True,
    )


def _result_from_response(
    action: AutomationAction,
    response: Any,
    element: Any,
    started: float,
) -> AutomationResult:
    raw_status = str(getattr(response, "status", "error"))
    status = {
        "completed": "handled",
        "dry_run": "handled",
        "approval_required": "needs_confirmation",
        "blocked": "blocked",
        "unsupported": "unsupported",
    }.get(raw_status, "error")
    message = str(getattr(response, "message", "") or _friendly_success(action))
    if status == "handled" and raw_status != "dry_run":
        message = _friendly_success(action)
    return AutomationResult(
        status,  # type: ignore[arg-type]
        message,
        action,
        element,
        getattr(response, "action_id", None),
        {
            "duration_ms": _elapsed_ms(started),
            "window": getattr(element, "window_title", "") if element else "",
        },
    )


def _friendly_success(action: AutomationAction) -> str:
    return {
        "move": "Mouse moved.",
        "click": "Clicked.",
        "double_click": "Double-clicked.",
        "right_click": "Right-clicked.",
        "middle_click": "Middle-clicked.",
        "drag": "Mouse dragged.",
        "scroll": f"Scrolled {action.target}.",
        "type": "Text typed.",
        "paste": "Pasted into the focused application.",
        "press": f"Pressed {action.target}.",
        "focus": f"Focused {action.target}.",
        "maximize": "Window maximized.",
        "minimize": "Window minimized.",
        "restore": "Window restored.",
    }.get(action.kind, "Done.")


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 2)


def _display_label(value: str) -> str:
    return str(value).strip().strip("\"'")


__all__ = ["AutomationExecutor", "LocatorResolutionError"]
