"""Validation for declarative user-defined skills."""

from __future__ import annotations

import re
from typing import Any

ALLOWED_RISK_LEVELS = {"LOW", "MEDIUM", "HIGH", "BLOCKED"}
BLOCKED_SKILL_WORDS = {
    "shell",
    "powershell",
    "cmd",
    "exec",
    "eval",
    "python",
    "delete",
    "format",
    "wipe",
    "password",
    "payment",
    "purchase",
}


class SkillValidationError(ValueError):
    """Raised when a declarative user skill is malformed or unsafe."""


def validate_skill_definition(payload: dict[str, Any]) -> dict[str, Any]:
    name = _clean_name(str(payload.get("name") or ""))
    description = " ".join(str(payload.get("description") or "").strip().split())
    triggers = _validate_triggers(payload.get("trigger_phrases") or [name])
    steps = validate_workflow_steps(payload.get("workflow_steps") or [])
    approvals = payload.get("approval_requirements") or {}
    if not isinstance(approvals, dict):
        raise SkillValidationError("approval_requirements must be an object.")
    return {
        "name": name,
        "description": description or f"User-defined Grandpa skill: {name}",
        "trigger_phrases": triggers,
        "workflow_steps": steps,
        "approval_requirements": approvals,
    }


def validate_workflow_steps(raw_steps: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_steps, list):
        raise SkillValidationError("workflow_steps must be a list.")
    if len(raw_steps) > 25:
        raise SkillValidationError("workflow_steps cannot contain more than 25 steps.")
    steps: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_steps):
        if not isinstance(raw, dict):
            raise SkillValidationError(f"workflow step {index + 1} must be an object.")
        skill = str(raw.get("skill") or "").strip()
        if not skill:
            raise SkillValidationError(f"workflow step {index + 1} needs a skill name.")
        if _contains_blocked_word(skill):
            raise SkillValidationError(
                f"workflow step {index + 1} uses a blocked skill name."
            )
        params = raw.get("params") or {}
        if not isinstance(params, dict):
            raise SkillValidationError(
                f"workflow step {index + 1} params must be an object."
            )
        supplied_risk = str(raw.get("risk_level") or "LOW").upper()
        if supplied_risk not in ALLOWED_RISK_LEVELS:
            raise SkillValidationError(
                f"workflow step {index + 1} has an invalid risk level."
            )
        _reject_capability_naming_params(index, skill, params)
        risk, approval_required = _risk_from_the_registry(skill)
        if supplied_risk == "BLOCKED":
            # The one thing a request may make *stricter* about itself.
            risk, approval_required = "BLOCKED", True
        steps.append(
            {
                "schema_version": "skill_graph_v2",
                "skill": skill,
                "title": str(raw.get("title") or skill).strip()[:160],
                "params": _redact_params(params),
                "risk_level": risk,
                "approval_required": approval_required,
                "dependencies": raw.get("dependencies")
                if isinstance(raw.get("dependencies"), list)
                else [],
            }
        )
    return steps


CAPABILITY_NAMING_PARAMS = frozenset(
    {
        "action_type",
        "action",
        "skill",
        "tool",
        "implementation",
        "module",
    }
)
"""Param keys that would choose *what runs* rather than pass it a value.

``action_type`` is the one that was actually read this way: ``_pc_action``
built its payload with ``params.get("action_type", action_type)``, and a
runtime skill's params come from a stored step, so a step could rename a read
into a write. The rest are here because a step must not be able to name a
capability *at all*, and these are the names such an attempt would use.

A skill that legitimately declares one of these as a parameter is not caught:
the check asks the registry. Nothing does today -- the declared parameter names
across all registered skills are target, text, query, tag, topic, field, value,
limit, request, document_id and dry_run -- but the rule is about naming a
capability, not about these particular words.
"""


def _reject_capability_naming_params(
    index: int, skill: str, params: dict[str, Any]
) -> None:
    """A step's params may supply values, never name what to run."""
    offending = sorted(CAPABILITY_NAMING_PARAMS & set(map(str, params)))
    if not offending:
        return
    declared = _declared_parameters(skill)
    offending = [key for key in offending if key not in declared]
    if not offending:
        return
    raise SkillValidationError(
        f"workflow step {index + 1} ({skill}) passes {', '.join(offending)} in "
        "params. A step may supply parameters for the skill it names, but it "
        "cannot name a different action -- what a skill does is fixed where it "
        "is registered."
    )


def _registered(skill: str):
    from grandpa.skills.registry import ensure_default_skills_registered, get_skill

    ensure_default_skills_registered()
    try:
        return get_skill(skill)
    except KeyError:
        return None


def _declared_parameters(skill: str) -> frozenset[str]:
    registered = _registered(skill)
    if registered is None:
        return frozenset()
    return frozenset(parameter.name for parameter in registered.parameters)


def _risk_from_the_registry(skill: str) -> tuple[str, bool]:
    """What this step is worth, read from the registry rather than the request.

    A stored step declares its own ``risk_level`` and would otherwise be
    believed about it: the probe that reached the screen lock declared
    ``LOW``. A skill nothing has registered cannot be vouched for, so it counts
    as acting -- ``run_user_skill`` refuses it later by name anyway.
    """
    registered = _registered(skill)
    if registered is None:
        return "HIGH", True
    return str(registered.risk_level), bool(registered.approval_required)


def _clean_name(name: str) -> str:
    clean = " ".join(name.strip().split())
    if len(clean) < 3:
        raise SkillValidationError("Skill name must contain at least 3 characters.")
    if len(clean) > 80:
        raise SkillValidationError("Skill name is too long.")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _.-]*", clean):
        raise SkillValidationError("Skill name contains unsupported characters.")
    if _contains_blocked_word(clean):
        raise SkillValidationError("Skill name contains unsafe wording.")
    return clean


def _validate_triggers(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        raise SkillValidationError("trigger_phrases must be a list.")
    triggers: list[str] = []
    seen: set[str] = set()
    for value in raw[:20]:
        item = " ".join(str(value).strip().split())
        key = item.lower()
        if not item or key in seen:
            continue
        if _contains_blocked_word(item):
            raise SkillValidationError("Trigger phrase contains unsafe wording.")
        triggers.append(item)
        seen.add(key)
    if not triggers:
        raise SkillValidationError("At least one trigger phrase is required.")
    return triggers


def _contains_blocked_word(value: str) -> bool:
    text = value.lower()
    return any(
        re.search(rf"\b{re.escape(word)}\b", text) for word in BLOCKED_SKILL_WORDS
    )


def _redact_params(params: dict[str, Any]) -> dict[str, Any]:
    redacted: dict[str, Any] = {}
    for key, value in params.items():
        clean_key = str(key)
        if re.search(
            r"password|token|secret|api[_-]?key|credential",
            clean_key,
            flags=re.IGNORECASE,
        ):
            redacted[clean_key] = "[redacted]"
        else:
            redacted[clean_key] = value
    return redacted


__all__ = [
    "ALLOWED_RISK_LEVELS",
    "SkillValidationError",
    "validate_skill_definition",
    "validate_workflow_steps",
]
