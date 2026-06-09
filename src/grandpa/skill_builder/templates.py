"""Safe declarative templates for user-created Grandpa skills."""

from __future__ import annotations

import re
from typing import Any


def slugify_skill_name(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")
    return slug or "custom_skill"


def default_triggers(name: str, triggers: list[str] | None = None) -> list[str]:
    seen: set[str] = set()
    values = [name, *(triggers or [])]
    clean: list[str] = []
    for value in values:
        item = " ".join(str(value).strip().split())
        key = item.lower()
        if item and key not in seen:
            clean.append(item)
            seen.add(key)
    return clean


def template_steps_for_name(name: str) -> list[dict[str, Any]]:
    text = name.lower()
    if "coding" in text or "code" in text:
        return [
            _step("desktop.summary", "Check desktop readiness"),
            _step("automation.workflow_status", "Check workflow runtime"),
            _step("planner.diagnostics", "Check planner readiness"),
        ]
    if "browser" in text or "research" in text:
        return [
            _step("browser.agent_diagnostics", "Check browser agent"),
            _step("browser.search_plan", "Prepare browser search plan", {"query": name}),
        ]
    if "desktop" in text or "pc" in text:
        return [
            _step("desktop.summary", "Summarize desktop"),
            _step("desktop.operator_diagnostics", "Check desktop operator"),
        ]
    return [_step("planner.diagnostics", "Check Grandpa planner")]


def _step(skill: str, title: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "schema_version": "skill_graph_v2",
        "skill": skill,
        "title": title,
        "params": params or {},
        "risk_level": "LOW",
        "approval_required": False,
        "dependencies": [],
    }


__all__ = ["default_triggers", "slugify_skill_name", "template_steps_for_name"]
