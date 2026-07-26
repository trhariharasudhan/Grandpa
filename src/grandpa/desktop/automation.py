"""Production-facing Windows desktop automation facade.

This module parses friendly desktop commands and executes only through the
existing PC-control safety layer. It does not run arbitrary shell commands.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from grandpa.desktop.applications import resolve_application
from grandpa.desktop.folders import folder_path, resolve_folder
from grandpa.desktop.power import resolve_power_action
from grandpa.desktop.volume import clamp_volume

DesktopActionType = Literal[
    "open_app",
    "close_app",
    "focus_window",
    "window_control",
    "app_inventory",
    "open_folder",
    "power",
    "volume",
    "empty_recycle_bin",
]
DesktopActionStatus = Literal[
    "handled",
    "needs_confirmation",
    "blocked",
    "unsupported",
    "no_match",
    "error",
]


@dataclass(frozen=True)
class DesktopAction:
    """Parsed desktop automation action."""

    action_type: DesktopActionType
    pc_action_type: str
    target: str = ""
    label: str = ""
    args: dict[str, Any] = field(default_factory=dict)
    requires_confirmation: bool = False


@dataclass(frozen=True)
class DesktopAutomationResult:
    """User-facing result from the desktop automation facade."""

    status: DesktopActionStatus
    message: str
    action: DesktopAction | None = None
    pc_response: Any | None = None

    @property
    def should_fallback(self) -> bool:
        return self.status == "no_match"


ConfirmationCallback = Callable[[DesktopAction], bool]
ActionRunner = Callable[[dict[str, Any]], Any]


class DesktopParser:
    """Parse natural desktop commands without executing anything."""

    def parse(self, text: str) -> DesktopAction | None:
        command = _normalize(text)
        if not command:
            return None
        return (
            self._parse_open(command)
            or self._parse_close(command)
            or self._parse_focus(command)
            or self._parse_window_control(command)
            or self._parse_volume(command)
            or self._parse_power(command)
            or self._parse_recycle_bin(command)
            or self._parse_app_inventory(command)
        )

    def _parse_open(self, command: str) -> DesktopAction | None:
        target = _strip_prefix(command, ("open ", "launch ", "start ", "go to "))
        if target is None:
            return None
        if _looks_like_path_target(target):
            return None
        folder = resolve_folder(target)
        if folder is not None:
            folder_id, label = folder
            path = str(folder_path(folder_id))
            return DesktopAction("open_folder", "open_folder", path, label)
        app = resolve_application(target)
        app_id, label = app if app is not None else (target, _label_from_target(target))
        return DesktopAction("open_app", "open_app", app_id, label)

    def _parse_close(self, command: str) -> DesktopAction | None:
        target = _strip_prefix(command, ("close ", "quit "))
        if target is None:
            return None
        if target in {"this window", "current window", "active window", "the window"}:
            return None
        app = resolve_application(target)
        app_id, label = app if app is not None else (target, _label_from_target(target))
        return DesktopAction("close_app", "close_app", app_id, label)

    def _parse_focus(self, command: str) -> DesktopAction | None:
        target = _strip_prefix(command, ("switch to ", "focus "))
        if target is None:
            return None
        target = target.removesuffix(" to front").strip()
        app = resolve_application(target)
        app_id, label = app if app is not None else (target, _label_from_target(target))
        return DesktopAction("focus_window", "focus_window", app_id, label)

    def _parse_window_control(self, command: str) -> DesktopAction | None:
        for prefix, pc_action in (
            ("minimize ", "minimize_window"),
            ("maximize ", "maximize_window"),
            ("restore ", "restore_window"),
            ("bring ", "focus_window"),
        ):
            target = _strip_prefix(command, (prefix,))
            if target is None:
                continue
            target = target.removesuffix(" to front").strip()
            if target in {"this window", "current window", "active window", "the window"}:
                target = "active"
            app = resolve_application(target)
            app_id, label = app if app is not None else (target, _label_from_target(target))
            return DesktopAction("window_control", pc_action, app_id, label)
        return None

    def _parse_app_inventory(self, command: str) -> DesktopAction | None:
        if command in {"list installed applications", "list installed apps", "show installed applications", "show installed apps"}:
            return DesktopAction("app_inventory", "apps_list", label="Applications")
        if command in {"refresh application database", "refresh apps", "scan my apps", "scan installed applications"}:
            return DesktopAction("app_inventory", "apps_scan", label="Applications")
        target = _strip_prefix(command, ("search applications for ", "search apps for ", "find application ", "find app "))
        if target:
            return DesktopAction("app_inventory", "apps_search", target, _label_from_target(target))
        if command in {"what apps are running", "list running apps", "what applications are running"}:
            return DesktopAction("app_inventory", "apps_running", label="Applications")
        target = _strip_prefix(command, ("is ",))
        if target and target.endswith(" open"):
            app = target.removesuffix(" open").strip()
            return DesktopAction("app_inventory", "apps_is_running", app, _label_from_target(app))
        restart_target = _strip_prefix(command, ("restart ", "reopen "))
        if restart_target:
            return DesktopAction(
                "app_inventory",
                "apps_restart",
                restart_target,
                _label_from_target(restart_target),
                requires_confirmation=True,
            )
        return None

    def _parse_volume(self, command: str) -> DesktopAction | None:
        if command in {"mute", "mute sound", "mute volume"}:
            return DesktopAction("volume", "volume_mute", label="Volume")
        if command in {"unmute", "unmute sound", "unmute volume"}:
            return DesktopAction("volume", "volume_unmute", label="Volume")
        match = re.fullmatch(r"(?:set )?volume(?: to)? (\d{1,3})%?", command)
        if not match:
            return None
        level = clamp_volume(int(match.group(1)))
        return DesktopAction("volume", "volume_set", str(level), "Volume", {"level": level})

    def _parse_power(self, command: str) -> DesktopAction | None:
        normalized = command.replace(" computer", " pc").replace(" the pc", " pc")
        mapping = {
            "lock pc": "lock",
            "lock my pc": "lock",
            "lock computer": "lock",
            "sleep pc": "sleep",
            "sleep computer": "sleep",
            "restart pc": "restart",
            "restart computer": "restart",
            "shutdown pc": "shutdown",
            "shut down pc": "shutdown",
            "shutdown computer": "shutdown",
            "shut down computer": "shutdown",
        }
        key = mapping.get(normalized) or mapping.get(command)
        if key is None:
            return None
        resolved = resolve_power_action(key)
        if resolved is None:
            return None
        pc_action, label, needs_confirmation = resolved
        return DesktopAction("power", pc_action, key, label, requires_confirmation=needs_confirmation)

    def _parse_recycle_bin(self, command: str) -> DesktopAction | None:
        if command in {"empty recycle bin", "empty the recycle bin"}:
            return DesktopAction(
                "empty_recycle_bin",
                "empty_recycle_bin",
                "recycle_bin",
                "Recycle Bin",
                requires_confirmation=True,
            )
        return None


class DesktopExecutor:
    """Execute parsed actions through PC-control."""

    def __init__(self, runner: ActionRunner | None = None) -> None:
        self.runner = runner

    def execute(self, action: DesktopAction, *, dry_run: bool = False) -> DesktopAutomationResult:
        runner = self.runner or _default_runner
        payload = {
            "action_type": action.pc_action_type,
            "target": action.target,
            "args": action.args,
            "dry_run": dry_run,
            "require_approval": action.requires_confirmation,
        }
        if action.action_type == "app_inventory":
            return _execute_app_inventory_action(action)
        response = runner(payload)
        status = _coerce_status(response)
        message = _friendly_message(action, response)
        return DesktopAutomationResult(status, message, action, response)


class DesktopAutomation:
    """Parse and execute safe local desktop commands."""

    def __init__(self, parser: DesktopParser | None = None, executor: DesktopExecutor | None = None) -> None:
        self.parser = parser or DesktopParser()
        self.executor = executor or DesktopExecutor()

    def handle(
        self,
        text: str,
        *,
        dry_run: bool = False,
        confirm: ConfirmationCallback | None = None,
    ) -> DesktopAutomationResult:
        action = self.parser.parse(text)
        if action is None:
            return DesktopAutomationResult("no_match", "")
        if action.requires_confirmation and confirm is not None and not confirm(action):
            return DesktopAutomationResult("needs_confirmation", "Cancelled.", action)
        return self.executor.execute(action, dry_run=dry_run)


def handle_desktop_command(
    text: str,
    *,
    dry_run: bool = False,
    confirm: ConfirmationCallback | None = None,
    runner: ActionRunner | None = None,
) -> DesktopAutomationResult:
    """Convenience wrapper used by chat and voice command paths."""

    return DesktopAutomation(executor=DesktopExecutor(runner)).handle(text, dry_run=dry_run, confirm=confirm)


def _normalize(text: str) -> str:
    value = re.sub(r"[?!.,;:]+", " ", str(text).casefold())
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _strip_prefix(value: str, prefixes: tuple[str, ...]) -> str | None:
    for prefix in prefixes:
        if value.startswith(prefix):
            return value[len(prefix) :].strip()
    return None


def _looks_like_path_target(value: str) -> bool:
    return "\\" in value or "/" in value or re.search(r"\.[a-z0-9]{1,8}\b", value) is not None


def _default_runner(payload: dict[str, Any]) -> Any:
    from grandpa.pc_control import run_local_action

    return run_local_action(payload)


def _coerce_status(response: Any) -> DesktopActionStatus:
    if getattr(response, "ok", False):
        return "handled"
    status = str(getattr(response, "status", "error"))
    if status == "approval_required":
        return "needs_confirmation"
    if status in {"blocked", "unsupported"}:
        return status  # type: ignore[return-value]
    return "error"


def _friendly_message(action: DesktopAction, response: Any) -> str:
    if not getattr(response, "ok", False):
        return str(getattr(response, "message", "") or f"{action.label or action.target} could not be handled.")
    if action.action_type == "open_app":
        return f"{action.label} opened."
    if action.action_type == "close_app":
        return f"{action.label} closed."
    if action.action_type == "focus_window":
        return f"{action.label} focused."
    if action.action_type == "window_control":
        return str(getattr(response, "message", "") or f"{action.label} handled.")
    if action.action_type == "open_folder":
        return f"{action.label} folder opened."
    if action.pc_action_type == "volume_set":
        return f"Volume set to {action.args.get('level', action.target)}%."
    if action.pc_action_type == "volume_mute":
        return "Muted."
    if action.pc_action_type == "volume_unmute":
        return "Unmuted."
    if action.pc_action_type == "system_lock":
        return "PC locked."
    if action.pc_action_type == "empty_recycle_bin":
        return "Recycle Bin emptied."
    return str(getattr(response, "message", "") or "Done.")


def _execute_app_inventory_action(action: DesktopAction) -> DesktopAutomationResult:
    from grandpa.apps.automation import ApplicationManager
    from grandpa.apps.process_manager import list_running_apps

    manager = ApplicationManager()
    if action.pc_action_type == "apps_scan":
        apps = manager.scan()
        return DesktopAutomationResult("handled", f"Found {len(apps)} applications. Database saved.", action)
    if action.pc_action_type == "apps_list":
        apps = manager.list()
        if not apps:
            return DesktopAutomationResult("handled", "No app inventory found. Run `grandpa apps scan` first.", action)
        names = ", ".join(app.display_name for app in apps[:10])
        suffix = f" and {len(apps) - 10} more" if len(apps) > 10 else ""
        return DesktopAutomationResult(
            "handled",
            f"Installed applications ({len(apps)} total): {names}{suffix}. Use `grandpa apps list` to browse them.",
            action,
        )
    if action.pc_action_type == "apps_search":
        result = manager.search(action.target)
        return DesktopAutomationResult("handled" if result.status != "missing" else "unsupported", result.message, action)
    if action.pc_action_type == "apps_running":
        apps = list_running_apps()
        if not apps:
            return DesktopAutomationResult("handled", "No running applications detected, or process inspection is unavailable.", action)
        names = ", ".join(app.display_name or app.name for app in apps[:10])
        return DesktopAutomationResult("handled", f"Running applications: {names}.", action)
    if action.pc_action_type == "apps_is_running":
        from grandpa.apps.process_manager import find_running_app

        process = find_running_app(action.target)
        if process is None:
            return DesktopAutomationResult("handled", f"{action.label} is not running.", action)
        return DesktopAutomationResult("handled", f"{action.label} is running as PID {process.pid}.", action)
    if action.pc_action_type == "apps_restart":
        return DesktopAutomationResult(
            "needs_confirmation",
            f"Restarting {action.label} requires confirmation and is not run automatically.",
            action,
        )
    return DesktopAutomationResult("unsupported", "Unknown application inventory command.", action)


def _label_from_target(target: str) -> str:
    return " ".join(word.capitalize() for word in target.split()) or "Application"


__all__ = [
    "DesktopAction",
    "DesktopAutomation",
    "DesktopAutomationResult",
    "DesktopExecutor",
    "DesktopParser",
    "handle_desktop_command",
]
