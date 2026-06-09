"""Execution and runtime registration for declarative user skills."""

from __future__ import annotations

from typing import Any

from grandpa.skill_builder.storage import UserSkillStore
from grandpa.skills.runtime import RuntimeSkill, SkillExecutionContext, SkillParameter, SkillResult


def run_user_skill(skill_id_or_name: str, *, params: dict[str, Any] | None = None, source: str = "user_skill") -> dict[str, Any]:
    store = UserSkillStore()
    skill = store.get(skill_id_or_name)
    results: list[dict[str, Any]] = []
    ok = True
    status = "completed"
    message = f"Ran user skill: {skill['name']}."
    try:
        from grandpa.skills.registry import ensure_default_skills_registered, execute_skill

        ensure_default_skills_registered()
        for index, step in enumerate(skill["workflow_steps"], start=1):
            if step.get("risk_level") == "BLOCKED":
                ok = False
                status = "blocked"
                message = f"Blocked user skill step {index}: {step.get('title') or step.get('skill')}."
                results.append({"step": step, "ok": False, "status": "blocked", "message": message})
                break
            skill_name = str(step.get("skill") or "")
            context = SkillExecutionContext(
                user_request=str((params or {}).get("user_request") or skill["name"]),
                source=source,
                dry_run=bool((params or {}).get("dry_run", False)),
                approval_state="none",
                metadata={"user_skill_id": skill["skill_id"], "step_index": index},
            )
            result = execute_skill(skill_name, dict(step.get("params") or {}), context)
            row = result.to_dict()
            row["step"] = step
            results.append(row)
            if result.status == "approval_required":
                ok = False
                status = "approval_required"
                message = f"Confirmation required before continuing user skill: {skill['name']}."
                break
            if not result.ok:
                ok = False
                status = result.status
                message = result.message
                break
    except KeyError as exc:
        ok = False
        status = "failed"
        message = f"User skill references an unknown runtime skill: {exc}."
    except Exception as exc:  # pragma: no cover - defensive guard
        ok = False
        status = "failed"
        message = "User skill execution failed safely."
        results.append({"ok": False, "status": "failed", "error": exc.__class__.__name__})
    store.record_usage(skill["skill_id"], success=ok and status == "completed")
    return {
        "ok": ok,
        "status": status,
        "message": message,
        "skill": UserSkillStore().get(skill["skill_id"]),
        "results": results,
        "local_only": True,
    }


def register_user_skills() -> dict[str, Any]:
    from grandpa.skills.registry import register_skill

    store = UserSkillStore()
    registered: list[str] = []
    for skill in store.list(limit=500):
        runtime_name = runtime_skill_name(skill)
        register_skill(
            RuntimeSkill(
                name=runtime_name,
                description=skill["description"],
                category="user",
                risk_level=_max_risk(skill["workflow_steps"]),
                approval_required=any(step.get("approval_required") for step in skill["workflow_steps"]),
                parameters=(SkillParameter("dry_run", "Plan without executing where supported", required=False, type="boolean"),),
                dry_run_supported=True,
                executor=_make_executor(skill["skill_id"]),
                aliases=tuple(skill["trigger_phrases"]),
            ),
            replace=True,
        )
        registered.append(runtime_name)
    return {"registered": registered, "count": len(registered)}


def runtime_skill_name(skill: dict[str, Any]) -> str:
    from grandpa.skill_builder.templates import slugify_skill_name

    return f"user.{slugify_skill_name(skill['name'])}"


def _make_executor(skill_id: str):
    def _execute(params: dict[str, Any], context: SkillExecutionContext) -> SkillResult:
        result = run_user_skill(skill_id, params={**params, "user_request": context.user_request}, source="runtime_skill")
        return SkillResult(
            ok=bool(result["ok"]),
            status=result["status"],
            message=result["message"],
            data=result,
            risk_level=_max_risk(result["skill"]["workflow_steps"]),
            approval_required=result["status"] == "approval_required",
        )

    return _execute


def _max_risk(steps: list[dict[str, Any]]) -> str:
    order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "BLOCKED": 3}
    level = "LOW"
    for step in steps:
        risk = str(step.get("risk_level") or "LOW").upper()
        if order.get(risk, 0) > order[level]:
            level = risk
    return level


__all__ = ["register_user_skills", "run_user_skill", "runtime_skill_name"]
