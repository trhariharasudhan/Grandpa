"""High-level user skill builder API."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from grandpa.skill_builder.execution import register_user_skills, run_user_skill
from grandpa.skill_builder.storage import UserSkillStore
from grandpa.skill_builder.templates import default_triggers, template_steps_for_name
from grandpa.skill_builder.validator import (
    SkillValidationError,
    validate_skill_definition,
)


def create_user_skill(
    payload: dict[str, Any],
    *,
    confirm: Callable[[str, str], bool] | None = None,
) -> dict[str, Any]:
    """Save a declarative user skill, asking first if it can do anything.

    Saving is deferred execution: the skill runs later, on a trigger phrase,
    with nobody reading its steps. So a skill containing a step that acts is
    approved when it is *saved*, and the prompt lists those steps -- the point
    at which a person can still see what they are agreeing to.

    The risk each step carries is read from the registered skill, not from the
    step: a stored step declares its own ``risk_level`` and would otherwise be
    trusted about it. That reconciliation lives in ``validate_skill_definition``
    so the HTTP route gets it too, and a step naming an action in its params is
    rejected there before anything is stored.
    """
    data = dict(payload)
    name = _extract_skill_name(str(data.get("name") or data.get("request") or ""))
    data["name"] = name
    data["trigger_phrases"] = default_triggers(name, data.get("trigger_phrases") or [])
    if not data.get("workflow_steps"):
        data["workflow_steps"] = template_steps_for_name(name)
    validated = validate_skill_definition(data)
    _approve_saving(validated, confirm)
    skill = UserSkillStore().create(validated)
    register_user_skills()
    _remember_skill(skill)
    return {"status": "created", "skill": skill}


def _approve_saving(
    validated: dict[str, Any], confirm: Callable[[str, str], bool] | None
) -> None:
    acting = [
        step
        for step in validated["workflow_steps"]
        if step["risk_level"] != "LOW" or step["approval_required"]
    ]
    if not acting:
        return
    listed = "\n".join(
        f"- {step['title']} ({step['skill']}, {step['risk_level']})" for step in acting
    )
    name = validated["name"]
    prompt = (
        f'Saving "{name}" stores steps that change this PC, and it will '
        f"run them later whenever its trigger phrase is said:\n{listed}\n"
        "Save it?"
    )
    if confirm is None:
        raise SkillValidationError(
            f"{prompt}\n\nThere is no way to ask for that here, so it was not saved."
        )
    if not confirm(prompt, "requires_confirmation"):
        raise SkillValidationError("The skill was not saved.")


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
