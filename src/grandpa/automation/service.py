"""Public Screen Automation V2 facade shared by CLI, chat, and voice."""

from __future__ import annotations

import logging
from dataclasses import replace

from grandpa.automation.confirmation import ConfirmationManager
from grandpa.automation.executor import AutomationExecutor
from grandpa.automation.models import AutomationAction, AutomationResult
from grandpa.automation.planner import AutomationPlanner
from grandpa.automation.windows import WindowIdentity, WindowTargetController

logger = logging.getLogger(__name__)


class ScreenAutomationService:
    def __init__(
        self,
        *,
        planner: AutomationPlanner | None = None,
        executor: AutomationExecutor | None = None,
        confirmations: ConfirmationManager | None = None,
        window_targets: WindowTargetController | None = None,
    ) -> None:
        self.planner = planner or AutomationPlanner()
        self.executor = executor or AutomationExecutor()
        self.confirmations = confirmations or ConfirmationManager()
        self.window_targets = window_targets or WindowTargetController()
        self._last_confirmation_token: str | None = None
        self._target_window: WindowIdentity | None = None

    @property
    def has_pending_confirmation(self) -> bool:
        return self._last_confirmation_token is not None

    @property
    def target_window(self) -> WindowIdentity | None:
        return self._target_window

    def clear_target(self) -> None:
        self._target_window = None

    def handle(
        self,
        text: str,
        *,
        dry_run: bool = False,
        target_window: str | None = None,
    ) -> AutomationResult:
        decision = str(text).strip().casefold()
        if self._last_confirmation_token and decision in {"yes", "confirm", "continue"}:
            return self.confirm(self._last_confirmation_token)
        if self._last_confirmation_token and decision in {"no", "cancel", "stop"}:
            return self.reject(self._last_confirmation_token)
        action = self.planner.parse(text)
        if action is None:
            return AutomationResult("no_match", "")
        verification = None
        used_pinned_target = False
        if target_window:
            action = replace(action, args={**action.args, "window": target_window})
        if action.kind == "focus":
            return self._focus_target(action, dry_run=dry_run)
        if _needs_verified_target(action):
            explicit_target = str(action.args.get("window") or "").strip()
            target: str | WindowIdentity | None = explicit_target or None
            if target is None and self._target_window is not None:
                target = self._target_window
                used_pinned_target = True
            if target is None:
                if dry_run:
                    return self._execute(action, dry_run=True)
                return AutomationResult(
                    "blocked",
                    "This input action needs a target window. Use --window or focus a target in the current session.\n"
                    "No input was sent.",
                    action,
                )
            target_label = target.label if isinstance(target, WindowIdentity) else target
            action = replace(action, args={**action.args, "window": target_label})
            verification = self.window_targets.focus_and_verify(target, dry_run=dry_run)
            if not verification.ok:
                status = "target_lost" if used_pinned_target else "blocked"
                if used_pinned_target:
                    self.clear_target()
                return AutomationResult(status, verification.message, action)
            self._target_window = verification.expected
        if action.requires_confirmation and not dry_run:
            preview = self._preview(action)
            if preview is not None:
                if verification_message := _verification_message(verification):
                    return replace(preview, message=f"{verification_message}\n{preview.message}")
                return preview
            pending = self.confirmations.create(action)
            self._last_confirmation_token = pending.token
            reason = action.confirmation_reason or "This action can change the desktop."
            prefix = _verification_message(verification)
            message = f"{reason} Do you want me to continue? Yes / No"
            if prefix:
                message = f"{prefix}\n{message}"
            return AutomationResult(
                "needs_confirmation",
                message,
                action,
                confirmation_token=pending.token,
            )
        result = self._execute(action, dry_run=dry_run)
        result = self._verify_after_input(action, result, dry_run=dry_run)
        if verification_message := _verification_message(verification):
            return replace(result, message=f"{verification_message}\n{result.message}")
        return result

    def confirm(self, token: str) -> AutomationResult:
        action = self.confirmations.consume(token)
        if self._last_confirmation_token == token:
            self._last_confirmation_token = None
        if action is None:
            return AutomationResult(
                "error", "That automation confirmation expired or was already used."
            )
        action = replace(action, requires_confirmation=False)
        if _needs_verified_target(action):
            target = str(action.args.get("window") or "").strip()
            verification = self.window_targets.focus_and_verify(target)
            if not verification.ok:
                return AutomationResult("blocked", verification.message, action)
            self._target_window = verification.expected
            result = self._execute(action)
            return replace(result, message=f"{verification.message}\n{result.message}")
        return self._execute(action)

    def reject(self, token: str) -> AutomationResult:
        rejected = self.confirmations.reject(token)
        if self._last_confirmation_token == token:
            self._last_confirmation_token = None
        if not rejected:
            return AutomationResult(
                "error", "That automation confirmation expired or was already used."
            )
        return AutomationResult("handled", "Automation action cancelled.")

    def _preview(self, action: AutomationAction) -> AutomationResult | None:
        if action.kind not in {
            "click",
            "double_click",
            "right_click",
            "middle_click",
        } or not action.target:
            return None
        located = self.executor.execute(AutomationAction("highlight", action.target))
        if located.status != "handled":
            return AutomationResult(
                located.status,
                located.message,
                action,
                located.element,
                data=located.data,
            )
        matches = list(located.data.get("matches", []))
        if len(matches) > 1 and abs(
            float(matches[0].get("confidence", 0))
            - float(matches[1].get("confidence", 0))
        ) < 0.05:
            return AutomationResult(
                "ambiguous",
                f'I found multiple possible matches for "{action.target}". Please be more specific.',
                action,
                data=located.data,
            )
        pending = self.confirmations.create(action)
        self._last_confirmation_token = pending.token
        element = located.element
        label = _quoted_label(element.text if element is not None else action.target)
        return AutomationResult(
            "needs_confirmation",
            f'I found "{label}". Do you want me to click it? Yes / No',
            action,
            element,
            pending.token,
            located.data,
        )

    def _focus_target(
        self, action: AutomationAction, *, dry_run: bool = False
    ) -> AutomationResult:
        verification = self.window_targets.focus_and_verify(action.target, dry_run=dry_run)
        if not verification.ok:
            return AutomationResult("blocked", verification.message, action)
        self._target_window = verification.expected
        message = verification.message if dry_run else f"Focused and pinned target: {action.target}."
        return AutomationResult("handled", message, action, data={"window": action.target})

    def _execute(self, action: AutomationAction, *, dry_run: bool = False) -> AutomationResult:
        result = self.executor.execute(action, dry_run=dry_run)
        point = result.element.bounds.center if result.element is not None else None
        x = point.x if point is not None else action.args.get("x")
        y = point.y if point is not None else action.args.get("y")
        logger.info(
            "screen_automation action=%s target=%s coordinates=%s,%s window=%s status=%s duration_ms=%s",
            action.kind,
            "[redacted]" if action.kind == "type" or action.sensitive else action.target,
            x,
            y,
            result.data.get("window", ""),
            result.status,
            result.data.get("duration_ms", 0),
        )
        return result

    def _verify_after_input(
        self,
        action: AutomationAction,
        result: AutomationResult,
        *,
        dry_run: bool,
    ) -> AutomationResult:
        if (
            dry_run
            or result.status != "handled"
            or not _needs_verified_target(action)
            or self._target_window is None
        ):
            return result
        verify = getattr(self.window_targets, "verify_foreground", None)
        if not callable(verify):
            return result
        verification = verify(self._target_window)
        if verification.ok:
            return replace(
                result,
                data={
                    **result.data,
                    "verified": True,
                    "window_handle": self._target_window.handle,
                    "process_id": self._target_window.process_id,
                },
            )
        self.clear_target()
        return replace(
            result,
            status="target_lost",
            message=(
                f"{verification.message} The action may have partially completed, "
                "so I stopped the automation session before sending more input."
            ),
            data={**result.data, "verified": False},
        )


_SERVICE: ScreenAutomationService | None = None


def get_automation_service() -> ScreenAutomationService:
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = ScreenAutomationService()
    return _SERVICE


def handle_automation_command(
    text: str,
    *,
    dry_run: bool = False,
    service: ScreenAutomationService | None = None,
    target_window: str | None = None,
) -> AutomationResult:
    return (service or get_automation_service()).handle(
        text, dry_run=dry_run, target_window=target_window
    )


def _needs_verified_target(action: AutomationAction) -> bool:
    return action.kind in {
        "type",
        "paste",
        "press",
        "click",
        "double_click",
        "right_click",
        "middle_click",
        "drag",
        "scroll",
    }


def _verification_message(verification: object) -> str:
    return str(getattr(verification, "message", ""))


def _quoted_label(value: str) -> str:
    return str(value).strip().strip('"\'')


__all__ = [
    "ScreenAutomationService",
    "get_automation_service",
    "handle_automation_command",
]
