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
            raise SkillValidationError(f"workflow step {index + 1} uses a blocked skill name.")
        params = raw.get("params") or {}
        if not isinstance(params, dict):
            raise SkillValidationError(f"workflow step {index + 1} params must be an object.")
        risk = str(raw.get("risk_level") or "LOW").upper()
        if risk not in ALLOWED_RISK_LEVELS:
            raise SkillValidationError(f"workflow step {index + 1} has an invalid risk level.")
        approval_required = bool(raw.get("approval_required")) or risk in {"MEDIUM", "HIGH"}
        if risk == "BLOCKED":
            approval_required = True
        steps.append(
            {
                "schema_version": "skill_graph_v2",
                "skill": skill,
                "title": str(raw.get("title") or skill).strip()[:160],
                "params": _redact_params(params),
                "risk_level": risk,
                "approval_required": approval_required,
                "dependencies": raw.get("dependencies") if isinstance(raw.get("dependencies"), list) else [],
            }
        )
    return steps


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
    return any(re.search(rf"\b{re.escape(word)}\b", text) for word in BLOCKED_SKILL_WORDS)


def _redact_params(params: dict[str, Any]) -> dict[str, Any]:
    redacted: dict[str, Any] = {}
    for key, value in params.items():
        clean_key = str(key)
        if re.search(r"password|token|secret|api[_-]?key|credential", clean_key, flags=re.IGNORECASE):
            redacted[clean_key] = "[redacted]"
        else:
            redacted[clean_key] = value
    return redacted


__all__ = ["ALLOWED_RISK_LEVELS", "SkillValidationError", "validate_skill_definition", "validate_workflow_steps"]
