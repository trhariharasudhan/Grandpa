"""Skill-backed routing for high-confidence local read-only intents."""

from __future__ import annotations

from typing import Any

from grandpa.router.route_models import IntentRoute

_ROUTE_TABLE: dict[str, tuple[str, str, str]] = {
    "desktop summary": ("desktop.summary", "desktop_summary", "desktop"),
    "summarize desktop": ("desktop.summary", "desktop_summary", "desktop"),
    "summarize current desktop state": ("desktop.operator_plan", "desktop_operator_plan", "desktop"),
    "detect active app and suggest actions": ("desktop.active_app_actions", "active_app_actions", "desktop"),
    "desktop operator diagnostics": ("desktop.operator_diagnostics", "desktop_operator_diagnostics", "desktop"),
    "operator diagnostics": ("desktop.operator_diagnostics", "desktop_operator_diagnostics", "desktop"),
    "list monitors": ("desktop.monitors", "list_monitors", "desktop"),
    "show monitors": ("desktop.monitors", "list_monitors", "desktop"),
    "detect monitors": ("desktop.monitors", "list_monitors", "desktop"),
    "what monitors are connected": ("desktop.monitors", "list_monitors", "desktop"),
    "clipboard history": ("desktop.clipboard_history", "clipboard_history", "desktop"),
    "show clipboard history": ("desktop.clipboard_history", "clipboard_history", "desktop"),
    "browser diagnostics": ("browser.diagnostics", "browser_diagnostics", "browser"),
    "show browser diagnostics": ("browser.diagnostics", "browser_diagnostics", "browser"),
    "browser status": ("browser.diagnostics", "browser_diagnostics", "browser"),
    "visual targeting diagnostics": ("vision.visual_diagnostics", "visual_diagnostics", "vision"),
    "show visual diagnostics": ("vision.visual_diagnostics", "visual_diagnostics", "vision"),
    "visual automation diagnostics": ("vision.visual_diagnostics", "visual_diagnostics", "vision"),
    "screen diagnostics": ("vision.screen_diagnostics", "screen_diagnostics", "vision"),
    "screen awareness diagnostics": ("vision.screen_diagnostics", "screen_diagnostics", "vision"),
    "show screen diagnostics": ("vision.screen_diagnostics", "screen_diagnostics", "vision"),
    "workflow status": ("automation.workflow_status", "workflow_status", "automation"),
    "workflow diagnostics": ("automation.workflow_status", "workflow_status", "automation"),
    "show workflow status": ("automation.workflow_status", "workflow_status", "automation"),
    "planner diagnostics": ("planner.diagnostics", "planner_diagnostics", "planner"),
    "show planner diagnostics": ("planner.diagnostics", "planner_diagnostics", "planner"),
    "skills diagnostics": ("skills.diagnostics", "skills_diagnostics", "skills"),
    "coding diagnostics": ("coding.diagnostics", "coding_diagnostics", "coding"),
    "project diagnostics": ("coding.diagnostics", "coding_diagnostics", "coding"),
    "scan projects": ("coding.project_scan", "coding_project_scan", "coding"),
    "summarize repository": ("coding.project_summary", "coding_project_summary", "coding"),
    "coding project summary": ("coding.project_summary", "coding_project_summary", "coding"),
    "analyze dependencies": ("coding.dependencies", "coding_dependencies", "coding"),
    "analyze architecture": ("coding.architecture", "coding_architecture", "coding"),
    "skill diagnostics": ("skills.diagnostics", "skills_diagnostics", "skills"),
    "plugin diagnostics": ("plugins.diagnostics", "plugin_diagnostics", "plugins"),
    "plugins diagnostics": ("plugins.diagnostics", "plugin_diagnostics", "plugins"),
}


def match_skill_route(request_text: str) -> IntentRoute | None:
    """Return a skill route for exact read-only commands."""
    clean = _clean(request_text)
    item = _ROUTE_TABLE.get(clean)
    if item is None:
        return None
    skill_name, intent, category = item
    return IntentRoute(
        request_text=request_text,
        intent=intent,
        category=category,
        confidence=0.96,
        skill_name=skill_name,
        params={},
        risk_level="LOW",
        approval_required=False,
        execution_source="skill",
    )


def execute_skill_route(route: IntentRoute):
    """Execute a routed skill and return a legacy local action result."""
    from grandpa.router.legacy_adapter import skill_result_to_local_action
    from grandpa.skills.registry import ensure_default_skills_registered, execute_skill
    from grandpa.skills.runtime import SkillExecutionContext

    ensure_default_skills_registered()
    result = execute_skill(
        route.skill_name,
        route.params,
        SkillExecutionContext(
            user_request=route.request_text,
            source="intent_router",
            dry_run=False,
            metadata={"intent": route.intent, "category": route.category},
        ),
    )
    return skill_result_to_local_action(route, result)


def route_table() -> dict[str, dict[str, Any]]:
    return {
        request: {"skill_name": skill, "intent": intent, "category": category}
        for request, (skill, intent, category) in sorted(_ROUTE_TABLE.items())
    }


def _clean(text: str) -> str:
    return " ".join(text.lower().strip().rstrip("?!.").split())


__all__ = ["execute_skill_route", "match_skill_route", "route_table"]
