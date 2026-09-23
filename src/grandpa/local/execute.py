"""Performing an action the parsers described and the tiers allowed."""

from __future__ import annotations

import logging
import os
import urllib.parse
import webbrowser
from pathlib import Path
from typing import Any

from grandpa.local.types import ConfirmationCallback
from grandpa.local_action_result import ActionStatus, LocalActionResult

logger = logging.getLogger(__name__)


def execute_automation_spec(spec, *, confirm_callback=None, confirmed=False):
    """Synthetic input, run by the service that owns it."""
    from grandpa.desktop.control.automation import execute_spec

    return execute_spec(spec, confirm_callback=confirm_callback, confirmed=confirmed)


def execute_parsed_action(
    result: LocalActionResult,
    *,
    confirm: ConfirmationCallback | None = None,
    consented: bool = False,
) -> LocalActionResult:
    """Perform a parsed action.

    ``consented`` means the user already said yes to exactly this action --
    inline, or by approving it when it was staged -- so it is not asked again.
    """
    from grandpa.natural_actions import request_for, run_parsed

    performed = (
        # A migrated shape staged before approval runs through the layer, like
        # every other migrated shape.
        run_parsed(result.kind, result.target, confirm=confirm, confirmed=consented)
        if request_for(result.kind, result.target) is not None
        else None
    )
    if performed is not None:
        return LocalActionResult(
            status=performed.status,
            kind=performed.kind,
            target=performed.target,
            message=performed.message,
            tts_text=performed.tts_text,
            permission=performed.permission,
        )

    if result.kind == "time" or result.kind == "system_info":
        return result

    registry_result = execute_runtime_skill(result)
    if registry_result is not None:
        return registry_result

    if result.kind == "app_lookup":
        from grandpa.windows_app_resolver import describe_app, list_installed_apps

        if result.target == "installed_apps":
            apps = list_installed_apps()
            if apps and all(app["status"] == "unsupported" for app in apps):
                return LocalActionResult(
                    status="unsupported",
                    kind="app_lookup",
                    target=result.target,
                    message="Windows app discovery is only supported on Windows desktop.",
                    tts_text="Windows app discovery is only supported on Windows desktop.",
                )
            lines = ["Installed app resolver:"]
            for app in apps:
                status = app["status"]
                target = app["launch_target"] or app["message"]
                lines.append(f"- {app['display_name']}: {status} ({target})")
            return LocalActionResult(
                status="handled",
                kind="app_lookup",
                target=result.target,
                message="\n".join(lines),
                tts_text="Here are the installed app results.",
            )

        message = describe_app(result.target)
        status = "unsupported" if "only supported on Windows" in message else "handled"
        return LocalActionResult(
            status=status,
            kind="app_lookup",
            target=result.target,
            message=message,
            tts_text=message,
        )

    if result.kind == "screen":
        from grandpa.screen_awareness import (
            describe_screen,
            get_active_window_info,
            screen_diagnostics,
        )

        if result.target == "active_window":
            info = get_active_window_info()
            if info.supported:
                title = info.window_title or "Unknown window"
                app = f" ({info.app_name})" if info.app_name else ""
                message = f"The active window is: {title}{app}."
                return LocalActionResult(
                    status="handled",
                    kind="screen",
                    target=result.target,
                    message=message,
                    tts_text=message,
                )
            return LocalActionResult(
                status="unsupported",
                kind="screen",
                target=result.target,
                message=info.message,
                tts_text=info.message,
            )

        if result.target == "screen_diagnostics":
            diagnostics = screen_diagnostics()
            screenshot = diagnostics.get("screenshot", {})
            ocr = diagnostics.get("ocr", {})
            active = diagnostics.get("active_window", {})
            message = (
                "Screen awareness diagnostics:\n"
                f"- Platform: {diagnostics.get('platform')}\n"
                f"- Active window: {'ready' if active.get('supported') else 'unavailable'}\n"
                f"- Screenshot backends: {', '.join(screenshot.get('backends') or []) or 'none'}\n"
                f"- OCR backend: {ocr.get('backend') or 'unavailable'}\n"
                f"- Visible windows: {diagnostics.get('visible_window_count', 0)}\n"
                "- Local only: yes"
            )
            return LocalActionResult(
                status="handled" if diagnostics.get("supported") else "unsupported",
                kind="screen",
                target=result.target,
                message=message,
                tts_text="Screen diagnostics are ready.",
            )

        info = describe_screen(include_ocr=True)
        return LocalActionResult(
            status="handled" if info.supported else "unsupported",
            kind="screen",
            target=result.target,
            message=info.message,
            tts_text="Here is what I can see on the screen.",
        )

    if result.kind == "screenshot":
        from grandpa.screen_awareness import capture_screenshot

        info = capture_screenshot()
        return LocalActionResult(
            status="handled" if info.supported else "unsupported",
            kind="screenshot",
            target=info.screenshot_path or result.target,
            message=info.message,
            tts_text="Screenshot captured." if info.supported else info.message,
        )

    if result.kind == "automation":
        # Not ``confirmed=consented``: synthetic input keeps its own gate, which
        # asks at the moment it acts even after a staged approval (the
        # enforcement probe's P5b). It moves onto the layer in a later tranche.
        automation = execute_automation_spec(result.target, confirm_callback=confirm)
        return LocalActionResult(
            status=automation.status,
            kind="automation",
            target=result.target,
            message=automation.message,
            tts_text=automation.tts_text or automation.message,
        )

    if result.kind == "window":
        from grandpa.windows_window_control import control_window, list_open_windows

        action, _, target = result.target.partition("|")
        if action == "list":
            window_result = list_open_windows()
        else:
            window_result = control_window(action, target or "active")
        status = {
            "handled": "handled",
            "blocked": "blocked",
            "unsupported": "unsupported",
            "not_found": "handled",
            "multiple_matches": "handled",
            "error": "error",
        }.get(window_result.status, "error")
        return LocalActionResult(
            status=status,
            kind="window",
            target=result.target,
            message=window_result.message,
            tts_text=window_result.message,
            permission=result.permission,
        )

    if result.kind == "pc_control":
        from grandpa.pc_control import run_local_action

        action_type, _, target = result.target.partition("|")
        response = run_local_action({"action_type": action_type, "target": target})
        return LocalActionResult(
            status="handled"
            if response.ok
            else response.status
            if response.status in {"blocked", "unsupported"}
            else "error",
            kind="pc_control",
            target=result.target,
            message=response.message,
            tts_text=response.message,
            permission=result.permission,
        )

    if result.kind == "agent_plan":
        from grandpa.agents.goal_mode import create_goal

        goal = create_goal(result.target, execute=True)
        analysis = goal.plan
        lines = [
            f"Agent plan goal {goal.status}: {analysis.get('intent', 'local goal')}.",
            f"- Phase: {goal.current_phase}",
            f"- Confidence: {float(analysis.get('confidence', 0.0)):.0%}",
            f"- Risk: {analysis.get('estimated_risk', 'LOW')}",
            f"- Skills: {', '.join(analysis.get('required_skills', [])) or 'none'}",
            f"- Actions taken: {len(goal.actions_taken)}",
        ]
        if goal.approvals_needed:
            lines.append(
                f"- Approval needed: {', '.join(item.get('step_id', '') for item in goal.approvals_needed)}"
            )
        if goal.result_summary:
            lines.append(goal.result_summary)
        else:
            lines.append(
                str(
                    analysis.get(
                        "reasoning_summary", "Grandpa prepared a safe local goal plan."
                    )
                )
            )
        return LocalActionResult(
            status="handled"
            if goal.status not in {"failed", "cancelled"}
            else "unsupported",
            kind="agent_plan",
            target=goal.goal_id,
            message="\n".join(lines),
            tts_text="I processed the autonomous goal safely.",
            permission=result.permission,
        )

    if result.kind == "app":
        from grandpa.windows_app_resolver import launch_app

        launched = launch_app(result.target)
        if launched.status == "found":
            return LocalActionResult(
                status="handled",
                kind="app",
                target=launched.launch_target,
                message=f"{launched.display_name} opened.",
                tts_text=f"{launched.display_name} opened.",
            )
        status = "unsupported" if launched.status == "unsupported" else "error"
        return LocalActionResult(
            status=status,
            kind="app",
            target=result.target,
            message=launched.message,
            tts_text=launched.message,
        )

    if result.kind == "folder":
        path = Path(result.target)
        if not path.exists():
            return LocalActionResult(
                status="error",
                kind="folder",
                target=result.target,
                message=f"I could not find {result.target}.",
                tts_text="I could not find that folder.",
            )
        os.startfile(path)  # type: ignore[attr-defined]  # noqa: S606
        return result

    if result.kind == "url":
        webbrowser.open(result.target)
        return result

    if result.kind == "browser":
        from grandpa.browser_control import execute_browser_action

        if "|" in result.target:
            action, _, target = result.target.partition("|")
            browser_result = execute_browser_action(action, target)
        elif result.target == "about:blank":
            browser_result = execute_browser_action("new_tab", result.target)
        elif "youtube.com/results" in result.target:
            parsed = urllib.parse.urlparse(result.target)
            query = urllib.parse.parse_qs(parsed.query).get("search_query", [""])[0]
            browser_result = execute_browser_action("youtube_search", query)
        elif "google.com/search" in result.target:
            parsed = urllib.parse.urlparse(result.target)
            query = urllib.parse.parse_qs(parsed.query).get("q", [""])[0]
            browser_result = execute_browser_action("search", query)
        else:
            browser_result = execute_browser_action("open", result.target)
        return LocalActionResult(
            status=browser_result.status,
            kind="browser",
            target=result.target,
            message=browser_result.message,
            tts_text=browser_result.message,
            permission=result.permission,
        )

    return result


def execute_runtime_skill(result: LocalActionResult) -> LocalActionResult | None:
    """Delegate migrated read-only actions to the runtime skill registry."""
    skill_name = ""
    params: dict[str, Any] = {}
    if result.kind == "pc_control":
        action_type, _, target = result.target.partition("|")
        skill_name = {
            "desktop_summary": "desktop.summary",
            "list_monitors": "desktop.monitors",
            "pc_diagnostics": "desktop.diagnostics",
            "workflow_status": "automation.workflow_status",
            "runtime_skill": target,
        }.get(action_type, "")
        params = {"target": target}
    elif result.kind == "browser" and result.target == "diagnostics|browser":
        skill_name = "browser.diagnostics"
    elif result.kind == "screen" and result.target in {
        "screen_diagnostics",
        "visual_diagnostics",
    }:
        skill_name = (
            "vision.visual_diagnostics"
            if result.target == "visual_diagnostics"
            else "vision.screen_diagnostics"
        )

    if not skill_name:
        return None

    try:
        from grandpa.skills.registry import (
            ensure_default_skills_registered,
            execute_skill,
        )
        from grandpa.skills.runtime import SkillExecutionContext

        ensure_default_skills_registered()
        skill_result = execute_skill(
            skill_name,
            params,
            SkillExecutionContext(
                user_request=result.message,
                source="local_actions",
                dry_run=False,
            ),
        )
    except Exception:
        logger.debug(
            "Runtime skill delegation failed for %s", skill_name, exc_info=True
        )
        return None

    status: ActionStatus = (
        "handled"
        if skill_result.ok
        else (
            "unsupported"
            if skill_result.status == "unsupported"
            else "blocked"
            if skill_result.status == "blocked"
            else "error"
        )
    )
    return LocalActionResult(
        status=status,
        kind=result.kind,
        target=result.target,
        message=skill_result.message,
        tts_text=skill_result.message,
        permission=result.permission,
    )
