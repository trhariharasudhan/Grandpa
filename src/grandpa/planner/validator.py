"""Structural, safety, dependency, and bounds validation for execution plans."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from grandpa.planner.action_catalog import (
    PROHIBITED_ACTION_NAMES,
    action_definition,
)
from grandpa.planner.models import ExecutionPlan, PlanStatus, RiskLevel


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    step_id: str | None = None


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    issues: tuple[ValidationIssue, ...] = ()


class PlanValidator:
    def validate(self, plan: ExecutionPlan) -> ValidationResult:
        plan.status = PlanStatus.VALIDATING
        issues: list[ValidationIssue] = []
        if not plan.session_id.strip():
            issues.append(
                ValidationIssue("missing_session", "A plan must belong to a session.")
            )
        if not plan.steps:
            issues.append(
                ValidationIssue("empty_plan", "The plan has no executable steps.")
            )
        if len(plan.steps) > plan.limits.max_steps:
            issues.append(
                ValidationIssue(
                    "step_limit",
                    f"The plan exceeds the {plan.limits.max_steps}-step limit.",
                )
            )

        ids = [step.step_id for step in plan.steps]
        if len(set(ids)) != len(ids):
            issues.append(
                ValidationIssue("duplicate_step", "Plan step IDs must be unique.")
            )
        known = set(ids)
        for step in plan.steps:
            definition = action_definition(step.action)
            if step.action in PROHIBITED_ACTION_NAMES or definition is None:
                issues.append(
                    ValidationIssue(
                        "unknown_action",
                        f"Unsupported planner action: {step.action}",
                        step.step_id,
                    )
                )
                continue
            keys = set(step.parameters)
            missing = definition.required - keys
            unexpected = keys - definition.parameters
            if missing:
                issues.append(
                    ValidationIssue(
                        "missing_parameter",
                        f"Missing parameters: {', '.join(sorted(missing))}",
                        step.step_id,
                    )
                )
            if unexpected:
                issues.append(
                    ValidationIssue(
                        "unexpected_parameter",
                        f"Unexpected parameters: {', '.join(sorted(unexpected))}",
                        step.step_id,
                    )
                )
            if {"x", "y", "coordinates"} & keys:
                issues.append(
                    ValidationIssue(
                        "raw_coordinates",
                        "Raw coordinates are not allowed in executive plans.",
                        step.step_id,
                    )
                )
            if definition.verification_required:
                if not step.verification.mandatory:
                    issues.append(
                        ValidationIssue(
                            "verification_optional",
                            "This action requires mandatory verification.",
                            step.step_id,
                        )
                    )
                if step.verification.strategy not in definition.verification_strategies:
                    issues.append(
                        ValidationIssue(
                            "invalid_verification",
                            f"Verification {step.verification.strategy!r} is not valid for {step.action}.",
                            step.step_id,
                        )
                    )
            if (
                step.retry_policy.max_attempts < 1
                or step.retry_policy.max_attempts > plan.limits.max_retries_per_step + 1
            ):
                issues.append(
                    ValidationIssue(
                        "retry_limit",
                        "Step retry policy exceeds planner limits.",
                        step.step_id,
                    )
                )
            if _risk_rank(definition.risk) > _risk_rank(step.risk):
                step.risk = definition.risk
            if step.action == "save_document" or (
                step.action == "invoke_verified_dialog_action"
                and str(step.parameters.get("choice") or "").casefold() != "cancel"
            ):
                step.requires_confirmation = True
            if step.risk == RiskLevel.PROHIBITED:
                issues.append(
                    ValidationIssue(
                        "prohibited",
                        "The plan contains a prohibited action.",
                        step.step_id,
                    )
                )
            for dependency in step.dependencies:
                if dependency.step_id not in known:
                    issues.append(
                        ValidationIssue(
                            "missing_dependency",
                            f"Unknown dependency: {dependency.step_id}",
                            step.step_id,
                        )
                    )

        if _has_cycle(plan):
            issues.append(
                ValidationIssue(
                    "dependency_cycle", "The plan contains a dependency cycle."
                )
            )
        if plan.limits.max_duration_seconds <= 0:
            issues.append(
                ValidationIssue("duration_limit", "Plan duration must be bounded.")
            )

        plan.safety_classification = max(
            (step.risk for step in plan.steps),
            default=RiskLevel.LOW,
            key=lambda item: list(RiskLevel).index(item),
        )
        plan.status = PlanStatus.READY if not issues else PlanStatus.FAILED
        return ValidationResult(not issues, tuple(issues))


def validate_model_plan_payload(payload: Any) -> bool:
    return isinstance(payload, dict) and isinstance(payload.get("steps"), list)


def _has_cycle(plan: ExecutionPlan) -> bool:
    graph = {
        step.step_id: [item.step_id for item in step.dependencies]
        for step in plan.steps
    }
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        if any(visit(child) for child in graph.get(node, ())):
            return True
        visiting.remove(node)
        visited.add(node)
        return False

    return any(visit(node) for node in graph)


def _risk_rank(value: RiskLevel) -> int:
    return {
        RiskLevel.LOW: 0,
        RiskLevel.MEDIUM: 1,
        RiskLevel.HIGH: 2,
        RiskLevel.PROHIBITED: 3,
    }[value]


__all__ = [
    "PlanValidator",
    "ValidationIssue",
    "ValidationResult",
    "validate_model_plan_payload",
]
