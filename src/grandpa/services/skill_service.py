"""Service facade for runtime skill routes."""

from __future__ import annotations

from typing import Any

from grandpa.services.base import safe_call, summarize_ready


def list_skills() -> dict[str, Any]:
    from grandpa.core.registry import SkillRegistry
    from grandpa.skills.registry import (
        ensure_default_skills_registered,
        registry_diagnostics,
    )
    from grandpa.skills.registry import (
        list_skills as list_runtime_skills,
    )

    ensure_default_skills_registered()
    diagnostics = registry_diagnostics()
    manifest_skills = [{"name": key, "source": "manifest"} for key in sorted(SkillRegistry.keys())]
    runtime_skills = [item.to_dict() for item in list_runtime_skills()]
    return {"skills": runtime_skills + manifest_skills, "runtime": diagnostics}


def categories() -> dict[str, Any]:
    from grandpa.skills.registry import (
        ensure_default_skills_registered,
        list_categories,
    )

    ensure_default_skills_registered()
    return {"categories": list_categories()}


def get_skill(name: str) -> dict[str, Any]:
    from grandpa.skills.registry import (
        ensure_default_skills_registered,
    )
    from grandpa.skills.registry import (
        get_skill as registry_get_skill,
    )

    ensure_default_skills_registered()
    return registry_get_skill(name).to_dict()


def execute_skill_from_body(body: dict[str, Any]) -> dict[str, Any]:
    from grandpa.skills.registry import ensure_default_skills_registered, execute_skill
    from grandpa.skills.runtime import SkillExecutionContext

    ensure_default_skills_registered()
    name = str(body.get("name") or body.get("skill") or "").strip()
    if not name:
        raise ValueError("'name' field is required")
    params = body.get("params") or {}
    if not isinstance(params, dict):
        raise TypeError("'params' must be an object")
    context = SkillExecutionContext(
        workflow_id=body.get("workflow_id"),
        user_request=str(body.get("user_request") or ""),
        dry_run=bool(body.get("dry_run", False)),
        approval_state=str(body.get("approval_state") or "none"),
        source=str(body.get("source") or "api"),
        timeout=float(body["timeout"]) if body.get("timeout") is not None else None,
        metadata=body.get("metadata") if isinstance(body.get("metadata"), dict) else {},
    )
    return execute_skill(name, params, context).to_dict()


def diagnostics() -> dict[str, Any]:
    return safe_call("skills", list_skills)


def health() -> dict[str, Any]:
    payload = diagnostics()
    runtime = payload.get("runtime", {}) if isinstance(payload.get("runtime"), dict) else payload
    return {
        "name": "skills",
        "ready": summarize_ready(runtime),
        "status": runtime.get("status", payload.get("status", "ready")),
        "dependencies": {"registry": "ready" if summarize_ready(runtime) else "unavailable"},
    }


def readiness() -> dict[str, Any]:
    payload = diagnostics()
    return {
        "ready": health()["ready"],
        "skill_count": len(payload.get("skills", [])) if isinstance(payload.get("skills"), list) else 0,
        "runtime": payload.get("runtime", {}),
    }
