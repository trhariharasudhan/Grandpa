"""Bounded recovery policies for idempotent planner steps."""

from __future__ import annotations

from grandpa.planner.models import ExecutionPlan, PlanStep, StepResult

NON_IDEMPOTENT_ACTIONS = frozenset(
    {
        "click_element",
        "close_window",
        "type_text",
        "press_key",
        "press_hotkey",
        "save_document",
        "invoke_verified_dialog_action",
        "navigate_url",
        "browser_search",
    }
)


class RecoveryManager:
    def recover(
        self,
        plan: ExecutionPlan,
        step: PlanStep,
        result: StepResult,
        executor,
    ) -> str | None:
        if step.action in NON_IDEMPOTENT_ACTIONS:
            return None
        used = int(plan.metadata.get("recoveries", 0))
        if used >= plan.limits.max_recoveries:
            return None
        attempts = sum(bool(item.recovery) for item in step.attempts)
        if attempts >= min(step.recovery_policy.max_recoveries, plan.limits.max_recoveries):
            return None
        for strategy in step.recovery_policy.strategies:
            if strategy == "refocus":
                target = executor.automation_service.target_window
                if target is not None:
                    check = executor.automation_service.window_targets.focus_and_verify(target)
                    if check.ok:
                        plan.metadata["recoveries"] = used + 1
                        return "refocus"
            if strategy == "refresh_vision":
                try:
                    executor.vision_engine.inspect()
                    plan.metadata["recoveries"] = used + 1
                    return "refresh_vision"
                except Exception:
                    continue
            if strategy == "wait" and result.status in {"failed", "target_lost"}:
                plan.metadata["recoveries"] = used + 1
                return "wait"
        return None


__all__ = ["NON_IDEMPOTENT_ACTIONS", "RecoveryManager"]
