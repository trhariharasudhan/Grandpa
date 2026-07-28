"""Authoritative safe command path for local Windows control."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Literal

from grandpa.automation.service import ScreenAutomationService

logger = logging.getLogger(__name__)

ExecutionStatus = Literal[
    "success",
    "partial_success",
    "failed",
    "blocked",
    "confirmation_required",
    "target_lost",
    "unsupported",
]


@dataclass(frozen=True)
class CommandExecutionResult:
    status: ExecutionStatus
    message: str
    kind: str = ""
    action: str = ""
    target: str = ""
    confirmation_token: str | None = None
    data: dict[str, Any] = field(default_factory=dict)

    @property
    def should_fallback(self) -> bool:
        return self.status == "unsupported" and bool(self.data.get("no_match"))

    @property
    def legacy_status(self) -> str:
        return {
            "success": "handled",
            "confirmation_required": "needs_confirmation",
            "failed": "error",
            "partial_success": "handled",
        }.get(self.status, self.status)


class WindowsCommandPipeline:
    """Route deterministic Windows commands through existing safe facades."""

    def __init__(
        self,
        *,
        automation_service: ScreenAutomationService | None = None,
        source: str = "local",
        session_id: str = "",
    ) -> None:
        self.automation_service = automation_service or ScreenAutomationService()
        self.source = source
        self.session_id = session_id

    def handle(
        self,
        text: str,
        *,
        dry_run: bool = False,
        spoken: bool = False,
    ) -> CommandExecutionResult:
        try:
            return self._handle(text, dry_run=dry_run, spoken=spoken)
        except Exception:
            logger.exception(
                "Windows command pipeline failed source=%s session_id=%s",
                self.source,
                self.session_id,
            )
            return CommandExecutionResult(
                "failed",
                "I could not complete that Windows action safely. Please try again.",
                data=self._metadata(),
            )

    def _handle(
        self,
        text: str,
        *,
        dry_run: bool,
        spoken: bool,
    ) -> CommandExecutionResult:
        automation = self.automation_service.handle(text, dry_run=dry_run)
        if not automation.should_fallback:
            action = automation.action
            return CommandExecutionResult(
                _canonical_status(automation.status),
                automation.message,
                "screen_automation",
                action.kind if action else "",
                action.target if action else "",
                automation.confirmation_token,
                self._metadata(automation.data),
            )

        from grandpa.screen import handle_screen_command

        screen = handle_screen_command(text)
        if not screen.should_fallback:
            message = screen.spoken_text if spoken and screen.spoken_text else screen.message
            return CommandExecutionResult(
                _canonical_status(screen.status),
                message,
                "screen",
                screen.action,
                data=self._metadata(screen.data),
            )

        from grandpa.desktop.automation import handle_desktop_command

        desktop = handle_desktop_command(text, dry_run=dry_run)
        if not desktop.should_fallback:
            action = desktop.action
            return CommandExecutionResult(
                _canonical_status(desktop.status),
                desktop.message,
                "desktop",
                action.action_type if action else "",
                action.target if action else "",
                data=self._metadata(),
            )

        return CommandExecutionResult(
            "unsupported",
            "",
            data=self._metadata({"no_match": True}),
        )

    def _metadata(self, values: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "source": self.source,
            "session_id": self.session_id,
            **(values or {}),
        }


def _canonical_status(status: str) -> ExecutionStatus:
    return {
        "handled": "success",
        "needs_confirmation": "confirmation_required",
        "requires_confirmation": "confirmation_required",
        "not_found": "failed",
        "ambiguous": "failed",
        "error": "failed",
        "no_match": "unsupported",
    }.get(status, status)  # type: ignore[return-value]


__all__ = [
    "CommandExecutionResult",
    "ExecutionStatus",
    "WindowsCommandPipeline",
]
