"""Central runtime skill registry for Grandpa."""

from grandpa.skills.registry.core import (
    SkillRegistryError,
    clear_skills,
    execute_skill,
    get_skill,
    list_categories,
    list_skills,
    match_skill,
    register_skill,
    registry_diagnostics,
)
from grandpa.skills.registry.defaults import ensure_default_skills_registered

__all__ = [
    "SkillRegistryError",
    "clear_skills",
    "ensure_default_skills_registered",
    "execute_skill",
    "get_skill",
    "list_categories",
    "list_skills",
    "match_skill",
    "register_skill",
    "registry_diagnostics",
]
