"""High-level user skill builder API."""

from __future__ import annotations

import re
from typing import Any

from grandpa.skill_builder.execution import register_user_skills, run_user_skill
from grandpa.skill_builder.storage import UserSkillStore
from grandpa.skill_builder.templates import default_triggers, template_steps_for_name
from grandpa.skill_builder.validator import (
    SkillValidationError,
    validate_skill_definition,
)


def create_user_skill(payload: dict[str, Any]) -> dict[str, Any]:
    data = dict(payload)
    name = _extract_skill_name(str(data.get("name") or data.get("request") or ""))
    data["name"] = name
    data["trigger_phrases"] = default_triggers(name, data.get("trigger_phrases") or [])
    if not data.get("workflow_steps"):
        data["workflow_steps"] = template_steps_for_name(name)
    validated = validate_skill_definition(data)
    skill = UserSkillStore().create(validated)
    register_user_skills()
    _remember_skill(skill)
    return {"status": "created", "skill": skill}


def list_user_skills(*, limit: int = 100) -> dict[str, Any]:
    store = UserSkillStore()
    skills = store.list(limit=limit)
    return {"skills": skills, "count": len(skills), "diagnostics": store.diagnostics()}


def search_user_skills(query: str, *, limit: int = 50) -> dict[str, Any]:
    store = UserSkillStore()
    skills = store.list(limit=limit, query=query)
    return {"skills": skills, "count": len(skills), "query": query}


def get_user_skill(skill_id_or_name: str) -> dict[str, Any]:
    return UserSkillStore().get(skill_id_or_name)


def delete_user_skill(skill_id_or_name: str) -> dict[str, Any]:
    deleted = UserSkillStore().delete(skill_id_or_name)
    try:
        from grandpa.skill_builder.execution import runtime_skill_name
        from grandpa.skills.registry import unregister_skill

        unregister_skill(runtime_skill_name(deleted))
    except Exception:
        pass
    register_user_skills()
    return {"status": "deleted", "skill": deleted}


def diagnostics() -> dict[str, Any]:
    store = UserSkillStore()
    registered = register_user_skills()
    return {
        "status": "ready",
        "storage": store.diagnostics(),
        "runtime_registration": registered,
        "declarative_only": True,
        "code_generation_allowed": False,
        "local_only": True,
    }


def _extract_skill_name(value: str) -> str:
    text = " ".join(value.strip().split())
    match = re.search(
        r"(?:create a skill called|skill called|called)\s+(.+)$",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        return match.group(1).strip()
    return text


def _remember_skill(skill: dict[str, Any]) -> None:
    try:
        from grandpa.memory_context import remember_fact

        remember_fact(
            category="skills",
            key=skill["name"],
            value=f"User-defined skill with triggers: {', '.join(skill.get('trigger_phrases', []))}",
            source="skill_builder",
        )
    except Exception:
        # Memory writeback is helpful, but skill creation must not depend on it.
        pass


__all__ = [
    "SkillValidationError",
    "create_user_skill",
    "delete_user_skill",
    "diagnostics",
    "get_user_skill",
    "list_user_skills",
    "run_user_skill",
    "search_user_skills",
]
