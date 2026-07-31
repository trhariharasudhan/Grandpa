"""Dependency-aware step scheduling without background threads."""

from __future__ import annotations

from grandpa.planner.models import ExecutionPlan, PlanStep, StepStatus


class PlanScheduler:
    def next_step(self, plan: ExecutionPlan) -> PlanStep | None:
        by_id = {step.step_id: step for step in plan.steps}
        for step in sorted(plan.steps, key=lambda item: item.order):
            if step.status not in {StepStatus.PENDING, StepStatus.READY, StepStatus.RETRYING}:
                continue
            if all(
                dependency.step_id in by_id
                and by_id[dependency.step_id].status.value == dependency.required_status
                for dependency in step.dependencies
            ):
                step.status = StepStatus.READY
                return step
        return None

    def blocked_by_dependency(self, plan: ExecutionPlan) -> tuple[PlanStep, ...]:
        failed = {StepStatus.FAILED, StepStatus.BLOCKED, StepStatus.CANCELLED}
        by_id = {step.step_id: step for step in plan.steps}
        return tuple(
            step
            for step in plan.steps
            if step.status == StepStatus.PENDING
            and any(
                by_id.get(item.step_id) is not None
                and by_id[item.step_id].status in failed
                for item in step.dependencies
            )
        )


__all__ = ["PlanScheduler"]
