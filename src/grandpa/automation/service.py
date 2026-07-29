"""Public Screen Automation V2 facade shared by CLI, chat, and voice."""

from __future__ import annotations

import logging
import re
from dataclasses import replace
from pathlib import Path

from grandpa.automation.confirmation import ConfirmationManager
from grandpa.automation.executor import AutomationExecutor
from grandpa.automation.models import AutomationAction, AutomationResult
from grandpa.automation.planner import AutomationPlanner
from grandpa.automation.windows import (
    DialogIdentity,
    WindowIdentity,
    WindowTargetController,
)

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
        self._window_choices: tuple[WindowIdentity, ...] = ()
        self._choice_action: AutomationAction | None = None
        self._pending_dialog: tuple[WindowIdentity, DialogIdentity] | None = None

    @property
    def has_pending_confirmation(self) -> bool:
        return self._last_confirmation_token is not None

    @property
    def has_pending_window_choice(self) -> bool:
        return bool(self._window_choices)

    @property
    def has_pending_dialog(self) -> bool:
        return self._pending_dialog is not None

    @property
    def target_window(self) -> WindowIdentity | None:
        return self._target_window

    def clear_target(self) -> None:
        self._target_window = None

    def pin_target(self, window: WindowIdentity) -> None:
        """Pin a target identity produced by another verified local service."""

        self._target_window = window

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
        dialog_result = self._handle_dialog_response(decision)
        if dialog_result is not None:
            return dialog_result
        choice = self._handle_window_choice(text, dry_run=dry_run)
        if choice is not None:
            return choice
        action = self.planner.parse(text)
        if action is None:
            return AutomationResult("no_match", "")
        verification = None
        used_pinned_target = False
        if target_window:
            action = replace(action, args={**action.args, "window": target_window})
        if action.kind == "focus":
            return self._focus_target(action, dry_run=dry_run)
        if action.kind == "close":
            return self._prepare_close(action, dry_run=dry_run)
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
        if action.kind == "overwrite_dialog":
            window = action.args.get("window_identity")
            dialog = action.args.get("dialog_identity")
            path = str(action.args.get("path") or "")
            if not isinstance(window, WindowIdentity) or not isinstance(
                dialog, DialogIdentity
            ):
                return AutomationResult(
                    "target_lost",
                    "The verified overwrite dialog is no longer available.",
                    action,
                )
            result = self.window_targets.respond_to_dialog(
                window, dialog, "overwrite"
            )
            return self._save_as_result(window, dialog, path, result)
        if action.kind == "save_as_overwrite":
            window = action.args.get("window_identity")
            dialog = action.args.get("dialog_identity")
            path = str(action.args.get("path") or "")
            if not isinstance(window, WindowIdentity) or not isinstance(
                dialog, DialogIdentity
            ):
                return AutomationResult(
                    "target_lost",
                    "The verified Save As dialog is no longer available.",
                    action,
                )
            result = self.window_targets.save_as_and_verify(
                window,
                dialog,
                path,
                allow_overwrite=True,
            )
            return self._save_as_result(window, dialog, path, result)
        if action.kind == "close":
            window = action.args.get("window_identity")
            if not isinstance(window, WindowIdentity):
                return AutomationResult(
                    "target_lost",
                    "The selected window is no longer available. Nothing was closed.",
                    action,
                )
            verification = self.window_targets.close_and_verify(window)
            close_status = str(getattr(verification, "status", ""))
            dialog = getattr(verification, "dialog", None)
            if close_status == "dialog_pending" and isinstance(
                dialog, DialogIdentity
            ):
                self._pending_dialog = (window, dialog)
                return AutomationResult(
                    "dialog_pending",
                    "Notepad has unsaved changes. Save, don't save, or cancel?",
                    action,
                    data=_dialog_data(window, dialog),
                )
            if verification.ok:
                if self._target_window and self._target_window.handle == window.handle:
                    self.clear_target()
                return AutomationResult(
                    "handled",
                    verification.message,
                    action,
                    data={
                        "verified": True,
                        "window_handle": window.handle,
                        "process_id": window.process_id,
                    },
                )
            if close_status == "target_lost":
                self.clear_target()
                return AutomationResult(
                    "target_lost",
                    verification.message,
                    action,
                    data={**_window_data(window), "verified": False},
                )
            return AutomationResult(
                "failed",
                verification.message,
                action,
                data={
                    "verified": False,
                    "window_handle": window.handle,
                    "process_id": window.process_id,
                },
            )
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
            if verification.candidates:
                return self._ambiguity_result(action, verification.candidates)
            return AutomationResult("blocked", verification.message, action)
        self._clear_window_choices()
        self._target_window = verification.expected
        message = verification.message if dry_run else f"Focused and pinned target: {action.target}."
        return AutomationResult("handled", message, action, data={"window": action.target})

    def _prepare_close(
        self,
        action: AutomationAction,
        *,
        dry_run: bool = False,
        selected: WindowIdentity | None = None,
    ) -> AutomationResult:
        window = selected
        if window is None and self._target_matches(action.target):
            window = self._target_window
        if window is None:
            verification = self.window_targets.focus_and_verify(
                action.target, dry_run=True
            )
            if not verification.ok:
                if verification.candidates:
                    return self._ambiguity_result(action, verification.candidates)
                return AutomationResult("blocked", verification.message, action)
            window = verification.expected
        if window is None:
            return AutomationResult(
                "not_found",
                f"I could not find an open {action.target.title()} window.",
                action,
            )
        self._target_window = window
        self._clear_window_choices()
        prepared = replace(
            action,
            args={**action.args, "window_identity": window},
            requires_confirmation=True,
            confirmation_reason="Closing a window may discard unsaved work.",
        )
        if dry_run:
            verification = self.window_targets.close_and_verify(window, dry_run=True)
            return AutomationResult(
                "needs_confirmation",
                verification.message,
                prepared,
                data=_window_data(window),
            )
        pending = self.confirmations.create(prepared)
        self._last_confirmation_token = pending.token
        return AutomationResult(
            "needs_confirmation",
            f"Close {window.title}? Unsaved work may be lost. Yes / No",
            prepared,
            confirmation_token=pending.token,
            data=_window_data(window),
        )

    def _handle_dialog_response(
        self, decision: str
    ) -> AutomationResult | None:
        if self._pending_dialog is None:
            return None
        window, dialog = self._pending_dialog
        if dialog.kind == "save_as" and decision not in {"cancel"}:
            return self._handle_save_as_path(window, dialog, decision)
        aliases = {
            "save": "save",
            "save changes": "save",
            "don't save": "discard",
            "dont save": "discard",
            "discard": "discard",
            "discard changes": "discard",
            "close without saving": "discard",
            "cancel": "cancel",
        }
        choice = aliases.get(decision)
        if choice is None:
            return None
        result = self.window_targets.respond_to_dialog(window, dialog, choice)
        status = str(getattr(result, "status", "failed"))
        next_dialog = getattr(result, "dialog", None)
        if status == "save_as_pending" and isinstance(
            next_dialog, DialogIdentity
        ):
            self._pending_dialog = (window, next_dialog)
            return AutomationResult(
                "dialog_pending",
                "A Save As dialog is open. What filename or path should I use?",
                AutomationAction("close", window.target),
                data=_dialog_data(window, next_dialog),
            )
        if status == "closed":
            self._pending_dialog = None
            self.clear_target()
            return AutomationResult(
                "handled",
                result.message,
                AutomationAction("close", window.target),
                data={
                    **_window_data(window),
                    "verified": True,
                    "dialog_action": choice,
                },
            )
        if status == "cancelled":
            self._pending_dialog = None
            self._target_window = window
            return AutomationResult(
                "cancelled",
                result.message,
                AutomationAction("close", window.target),
                data={
                    **_window_data(window),
                    "verified": True,
                    "dialog_action": choice,
                },
            )
        self._pending_dialog = None
        return AutomationResult(
            "failed",
            result.message,
            AutomationAction("close", window.target),
            data={
                **_dialog_data(window, dialog),
                "verified": False,
                "dialog_action": choice,
            },
        )

    def _handle_save_as_path(
        self,
        window: WindowIdentity,
        dialog: DialogIdentity,
        value: str,
    ) -> AutomationResult:
        path = _resolve_save_path(value)
        if path is None:
            return AutomationResult(
                "dialog_pending",
                "Please provide a filename or path, or say cancel.",
                data=_dialog_data(window, dialog),
            )
        try:
            from grandpa.pc_control import _is_protected_path

            protected = _is_protected_path(path)
        except Exception:
            protected = False
        if protected or not path.parent.exists() or not path.parent.is_dir():
            return AutomationResult(
                "blocked",
                "That save location is unavailable or protected. Choose another path.",
                data=_dialog_data(window, dialog),
            )
        if path.exists():
            action = AutomationAction(
                "save_as_overwrite",
                str(path),
                {
                    "window_identity": window,
                    "dialog_identity": dialog,
                    "path": str(path),
                },
                True,
                "The selected file already exists.",
            )
            pending = self.confirmations.create(action)
            self._last_confirmation_token = pending.token
            return AutomationResult(
                "needs_confirmation",
                f"{path} already exists. Overwrite it? Yes / No",
                action,
                confirmation_token=pending.token,
                data=_dialog_data(window, dialog),
            )
        result = self.window_targets.save_as_and_verify(
            window,
            dialog,
            str(path),
        )
        return self._save_as_result(window, dialog, str(path), result)

    def _save_as_result(
        self,
        window: WindowIdentity,
        dialog: DialogIdentity,
        path: str,
        result: object,
    ) -> AutomationResult:
        status = str(getattr(result, "status", "failed"))
        next_dialog = getattr(result, "dialog", None)
        if status == "closed":
            self._pending_dialog = None
            self.clear_target()
            return AutomationResult(
                "handled",
                str(getattr(result, "message", "Saved and closed Notepad.")),
                AutomationAction("close", window.target),
                data={
                    **_window_data(window),
                    "verified": True,
                    "saved_path": path,
                },
            )
        if status == "overwrite_pending" and isinstance(
            next_dialog, DialogIdentity
        ):
            self._pending_dialog = (window, next_dialog)
            action = AutomationAction(
                "overwrite_dialog",
                path,
                {
                    "window_identity": window,
                    "dialog_identity": next_dialog,
                    "path": path,
                },
                True,
                "The selected file already exists.",
            )
            pending = self.confirmations.create(action)
            self._last_confirmation_token = pending.token
            return AutomationResult(
                "needs_confirmation",
                str(getattr(result, "message", "Overwrite the existing file? Yes / No")),
                action,
                confirmation_token=pending.token,
                data=_dialog_data(window, next_dialog),
            )
        self._pending_dialog = None
        return AutomationResult(
            "failed",
            str(getattr(result, "message", "The Save As action could not be verified.")),
            AutomationAction("close", window.target),
            data={
                **_dialog_data(window, dialog),
                "verified": False,
                "saved_path": path,
            },
        )

    def _ambiguity_result(
        self,
        action: AutomationAction,
        candidates: tuple[WindowIdentity, ...],
    ) -> AutomationResult:
        self._window_choices = candidates
        self._choice_action = action
        lines = [
            f"{index}. {window.title}"
            for index, window in enumerate(candidates, start=1)
        ]
        return AutomationResult(
            "ambiguous",
            "I found multiple matching windows. Which one?\n" + "\n".join(lines),
            action,
            data={"window_choices": [_window_data(item) for item in candidates]},
        )

    def _handle_window_choice(
        self, text: str, *, dry_run: bool
    ) -> AutomationResult | None:
        if not self._window_choices or self._choice_action is None:
            return None
        command = " ".join(str(text).casefold().split())
        index = _choice_index(command)
        selected = None
        if index is not None:
            if index < 0 or index >= len(self._window_choices):
                return self._ambiguity_result(
                    self._choice_action, self._window_choices
                )
            selected = self._window_choices[index]
        else:
            candidate_text = re.sub(
                r"^(?:choose|select|focus)(?: option)?\s+", "", command
            )
            exact = [
                item
                for item in self._window_choices
                if _normalize_window_title(item.title)
                == _normalize_window_title(candidate_text)
            ]
            if len(exact) == 1:
                selected = exact[0]
        if selected is None:
            return None
        action = self._choice_action
        self._clear_window_choices()
        if action.kind == "close":
            return self._prepare_close(action, dry_run=dry_run, selected=selected)
        verification = self.window_targets.focus_and_verify(
            selected, dry_run=dry_run
        )
        if not verification.ok:
            return AutomationResult("target_lost", verification.message, action)
        self._target_window = verification.expected or selected
        return AutomationResult(
            "handled",
            f"Focused option {index + 1 if index is not None else ''}: {selected.title}.".replace(
                "option : ", ""
            ),
            action,
            data=_window_data(selected),
        )

    def _target_matches(self, target: str) -> bool:
        if self._target_window is None:
            return False
        wanted = " ".join(target.casefold().split())
        values = {
            " ".join(self._target_window.target.casefold().split()),
            " ".join(self._target_window.title.casefold().split()),
        }
        return wanted in values or any(wanted and wanted in value for value in values)

    def _clear_window_choices(self) -> None:
        self._window_choices = ()
        self._choice_action = None

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


def _window_data(window: WindowIdentity) -> dict[str, object]:
    data: dict[str, object] = {
        "title": window.title,
        "hwnd": window.handle,
        "pid": window.process_id,
    }
    if window.document_id:
        data["document_id"] = window.document_id
        data["document_title"] = window.document_title
    return data


def _dialog_data(
    window: WindowIdentity, dialog: DialogIdentity
) -> dict[str, object]:
    return {
        **_window_data(window),
        "dialog": {
            "title": dialog.title,
            "kind": dialog.kind,
            "hwnd": dialog.handle,
            "pid": dialog.process_id,
            "owner_hwnd": dialog.owner_handle,
        },
    }


def _choice_index(command: str) -> int | None:
    match = re.fullmatch(
        r"(?:choose|select)(?: the)? (first|second|third|fourth|\d+)(?: one)?"
        r"|focus option (one|two|three|four|\d+)",
        command,
    )
    if not match:
        return None
    value = next(part for part in match.groups() if part is not None)
    words = {
        "first": 1,
        "one": 1,
        "second": 2,
        "two": 2,
        "third": 3,
        "three": 3,
        "fourth": 4,
        "four": 4,
    }
    number = words.get(value, int(value) if value.isdigit() else 0)
    return number - 1


def _normalize_window_title(value: str) -> str:
    return " ".join(re.sub(r"[^\w]+", " ", value.casefold()).split())


def _resolve_save_path(value: str) -> Path | None:
    cleaned = re.sub(r"^(?:save as|save to)\s+", "", value.strip(), flags=re.I)
    cleaned = cleaned.strip().strip('"')
    if not cleaned:
        return None
    candidate = Path(cleaned).expanduser()
    if not candidate.is_absolute():
        candidate = Path.home() / "Documents" / candidate
    try:
        return candidate.resolve(strict=False)
    except (OSError, RuntimeError):
        return None


__all__ = [
    "ScreenAutomationService",
    "get_automation_service",
    "handle_automation_command",
]
