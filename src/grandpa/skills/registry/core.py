"""In-process registry for runtime skills."""

from __future__ import annotations

from threading import RLock
from typing import Any

from grandpa.skills.runtime import RuntimeSkill, SkillExecutionContext, SkillResult


class SkillRegistryError(ValueError):
    """Raised when a runtime skill registration is invalid."""


_LOCK = RLock()
_SKILLS: dict[str, RuntimeSkill] = {}
_ALIASES: dict[str, str] = {}
_HISTORY: list[dict[str, Any]] = []


def _key(name: str) -> str:
    return " ".join(name.strip().lower().split())


def register_skill(skill: RuntimeSkill, *, replace: bool = False) -> RuntimeSkill:
    """Register a runtime skill by canonical name and aliases."""
    name = _key(skill.name)
    if not name:
        raise SkillRegistryError("Skill name is required.")
    with _LOCK:
        if not replace and name in _SKILLS:
            raise SkillRegistryError(f"Skill already registered: {skill.name}")
        _SKILLS[name] = skill
        for alias in skill.aliases:
            alias_key = _key(alias)
            if not alias_key:
                continue
            if not replace and alias_key in _ALIASES and _ALIASES[alias_key] != name:
                raise SkillRegistryError(f"Skill alias already registered: {alias}")
            _ALIASES[alias_key] = name
    return skill


def unregister_skill(name: str) -> None:
    """Remove a skill by name or alias if it is currently registered."""
    key = _key(name)
    with _LOCK:
        canonical = _ALIASES.get(key, key)
        skill = _SKILLS.pop(canonical, None)
        if skill is None:
            return
        aliases = {_key(alias) for alias in skill.aliases}
        aliases.add(canonical)
        for alias in list(_ALIASES):
            if alias in aliases or _ALIASES.get(alias) == canonical:
                _ALIASES.pop(alias, None)


def get_skill(name: str) -> RuntimeSkill:
    """Return a skill by name or alias."""
    key = _key(name)
    with _LOCK:
        canonical = _ALIASES.get(key, key)
        try:
            return _SKILLS[canonical]
        except KeyError as exc:
            raise KeyError(f"Unknown skill: {name}") from exc


def list_skills(*, category: str | None = None) -> list[RuntimeSkill]:
    """List registered skills, optionally filtered by category."""
    with _LOCK:
        skills = sorted(_SKILLS.values(), key=lambda item: item.name)
    if category:
        clean = _key(category)
        skills = [item for item in skills if _key(item.category) == clean]
    return skills


def list_categories() -> list[dict[str, Any]]:
    """Return skill categories with counts."""
    counts: dict[str, int] = {}
    with _LOCK:
        for skill in _SKILLS.values():
            counts[skill.category] = counts.get(skill.category, 0) + 1
    return [{"name": name, "count": counts[name]} for name in sorted(counts)]


def match_skill(user_request: str) -> RuntimeSkill | None:
    """Match a natural-language request to an exact skill name or alias."""
    request = _key(user_request)
    if not request:
        return None
    with _LOCK:
        canonical = _ALIASES.get(request, request)
        return _SKILLS.get(canonical)


def execute_skill(
    name: str,
    params: dict[str, Any] | None = None,
    context: SkillExecutionContext | None = None,
) -> SkillResult:
    """Execute a registered skill and record a small redacted history entry."""
    skill = get_skill(name)
    ctx = context or SkillExecutionContext()
    result = skill.execute(params or {}, ctx)
    with _LOCK:
        _HISTORY.insert(
            0,
            {
                "skill": skill.name,
                "category": skill.category,
                "status": result.status,
                "ok": result.ok,
                "risk_level": result.risk_level,
                "approval_required": result.approval_required,
                "source": ctx.source,
            },
        )
        del _HISTORY[50:]
    return result


def registry_diagnostics() -> dict[str, Any]:
    """Return fast read-only runtime registry diagnostics."""
    with _LOCK:
        skills = list(_SKILLS.values())
        history = list(_HISTORY)
    return {
        "status": "ready",
        "skill_count": len(skills),
        "categories": list_categories(),
        "approval_required_count": sum(1 for item in skills if item.approval_required),
        "loaded_skills": [
            item.to_dict() for item in sorted(skills, key=lambda item: item.name)
        ],
        "history": history,
        "runtime_ready": True,
    }


def clear_skills() -> None:
    """Clear registry state for tests."""
    with _LOCK:
        _SKILLS.clear()
        _ALIASES.clear()
        _HISTORY.clear()


__all__ = [
    "SkillRegistryError",
    "clear_skills",
    "execute_skill",
    "get_skill",
    "list_categories",
    "list_skills",
    "match_skill",
    "register_skill",
    "registry_diagnostics",
    "unregister_skill",
]
