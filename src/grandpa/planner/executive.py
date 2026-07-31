"""Verified, bounded, session-scoped Executive Planner state machine."""

from __future__ import annotations

import secrets
import time

from grandpa.planner.decomposer import (
    DeterministicDecomposer,
    GoalDecompositionError,
    LocalModelDecomposer,
    normalize_goal,
)
from grandpa.planner.executor import PlannerStepExecutor
from grandpa.planner.models import (
    ClarificationRequest,
    ConfirmationRequest,
    ExecutionPlan,
    FailureReason,
    Goal,
    PlannerLimits,
    PlanResult,
    PlanStatus,
    StepAttempt,
    StepResult,
    StepStatus,
    utc_now,
)
from grandpa.planner.recovery import NON_IDEMPOTENT_ACTIONS, RecoveryManager
from grandpa.planner.scheduler import PlanScheduler
from grandpa.planner.state_store import PlanStateStore
from grandpa.planner.validator import PlanValidator
from grandpa.planner.verifier import StepVerifier


class ExecutivePlanner:
    """Create, validate, execute, pause, resume, and inspect one session plan."""

    def __init__(
        self,
        *,
        session_id: str = "default",
        limits: PlannerLimits | None = None,
        deterministic: DeterministicDecomposer | None = None,
        local_model: LocalModelDecomposer | None = None,
        validator: PlanValidator | None = None,
        executor: PlannerStepExecutor | None = None,
        verifier: StepVerifier | None = None,
        recovery: RecoveryManager | None = None,
        scheduler: PlanScheduler | None = None,
        store: PlanStateStore | None = None,
    ) -> None:
        self.session_id = session_id
        self.limits = limits or PlannerLimits()
        self.deterministic = deterministic or DeterministicDecomposer()
        self.local_model = local_model or LocalModelDecomposer()
        self.validator = validator or PlanValidator()
        self.executor = executor or PlannerStepExecutor(session_id=session_id)
        self.verifier = verifier or StepVerifier(self.executor)
        self.recovery = recovery or RecoveryManager()
        self.scheduler = scheduler or PlanScheduler()
        self.store = store or PlanStateStore()

    def create(self, goal_text: str, *, allow_local_model: bool = False) -> ExecutionPlan:
        goal = Goal(goal_text.strip(), normalize_goal(goal_text), self.session_id)
        steps = self.deterministic.decompose(goal, self.limits)
        source = "deterministic"
        model_name = None
        if steps is None and allow_local_model:
            steps = self.local_model.decompose(goal, self.limits)
            source = "local_model"
            model_name = self.local_model.model_name
        if steps is None:
            raise GoalDecompositionError(
                "I could not create a safe, verified plan for that goal. Please be more specific."
            )
        plan = ExecutionPlan.create(
            goal,
            steps,
            limits=self.limits,
            planner_source=source,
            model_name=model_name,
        )
        validation = self.validator.validate(plan)
        if not validation.valid:
            plan.metadata["validation_issues"] = [
                {"code": item.code, "message": item.message, "step_id": item.step_id}
                for item in validation.issues
            ]
        plan.updated_at = utc_now()
        self.store.save(plan)
        return plan

    def preview(self, goal_text: str, *, allow_local_model: bool = False) -> PlanResult:
        try:
            plan = self.create(goal_text, allow_local_model=allow_local_model)
        except GoalDecompositionError as exc:
            empty = ExecutionPlan.create(
                Goal(goal_text, normalize_goal(goal_text), self.session_id), []
            )
            empty.status = PlanStatus.WAITING_FOR_CLARIFICATION
            empty.clarification = ClarificationRequest(
                empty.plan_id, None, self.session_id, str(exc)
            )
            self.store.save(empty)
            return PlanResult("clarification_required", str(exc), empty)
        if plan.status == PlanStatus.FAILED:
            message = _validation_message(plan)
            return PlanResult("blocked", message, plan, FailureReason("validation_failed", message))
        return PlanResult("ready", f"I created a {len(plan.steps)}-step plan.", plan)

    def execute(
        self,
        goal_or_plan: str | ExecutionPlan,
        *,
        dry_run: bool = False,
        allow_local_model: bool = False,
    ) -> PlanResult:
        if isinstance(goal_or_plan, str):
            preview = self.preview(goal_or_plan, allow_local_model=allow_local_model)
            if preview.status != "ready":
                return preview
            plan = preview.plan
        else:
            plan = goal_or_plan
        if plan.session_id != self.session_id:
            return PlanResult("blocked", "That plan belongs to another session.", plan, FailureReason("session_mismatch", "Plan session mismatch."))
        if plan.status not in {PlanStatus.READY, PlanStatus.PAUSED, PlanStatus.RUNNING}:
            return PlanResult("blocked", f"Plan cannot execute from {plan.status.value}.", plan)
        return self._run(plan, dry_run=dry_run)

    def resume(self, *, confirmed: bool = False) -> PlanResult:
        plan = self.current()
        if plan is None:
            return _missing_result(self.session_id)
        if plan.session_id != self.session_id:
            return PlanResult("blocked", "That plan belongs to another session.", plan)
        if plan.status == PlanStatus.WAITING_FOR_CONFIRMATION:
            if not confirmed:
                return PlanResult("confirmation_required", plan.confirmation.message if plan.confirmation else "Confirmation is required.", plan)
            step = _current_step(plan)
            if step is None:
                return PlanResult("failed", "The pending plan step is unavailable.", plan)
            plan.confirmation = None
            step.status = StepStatus.READY
            return self._run(plan, confirmed_step_id=step.step_id)
        if plan.status == PlanStatus.WAITING_FOR_CLARIFICATION:
            return PlanResult("clarification_required", plan.clarification.message if plan.clarification else "Clarification is required.", plan)
        if plan.status != PlanStatus.PAUSED:
            return PlanResult("blocked", f"Plan cannot resume from {plan.status.value}.", plan)
        return self._run(plan)

    def clarify(self, response: str) -> PlanResult:
        """Resolve a pending ambiguity through the same session-owned service."""

        plan = self.current()
        if plan is None:
            return _missing_result(self.session_id)
        if plan.session_id != self.session_id:
            return PlanResult("blocked", "That plan belongs to another session.", plan)
        if plan.status != PlanStatus.WAITING_FOR_CLARIFICATION:
            return PlanResult("blocked", "This plan is not waiting for clarification.", plan)
        step = _current_step(plan)
        if step is None:
            return PlanResult("failed", "The pending plan step is unavailable.", plan)
        result = self.executor.resolve_clarification(step, response)
        if result.status == "clarification_required":
            plan.clarification = ClarificationRequest(
                plan.plan_id,
                step.step_id,
                plan.session_id,
                result.message,
                tuple(result.data.get("choices", ())),
            )
            self.store.save(plan)
            return PlanResult("clarification_required", result.message, plan)
        if result.status != "success":
            return self._fail(
                plan,
                "clarification_failed",
                result.message,
                step_id=step.step_id,
                partial=True,
            )
        plan.clarification = None
        step.status = StepStatus.READY
        plan.status = PlanStatus.RUNNING
        return self._run(
            plan,
            resolved_step_id=step.step_id,
            resolved_result=result,
        )

    def pause(self) -> PlanResult:
        plan = self.current()
        if plan is None:
            return _missing_result(self.session_id)
        if plan.status not in {PlanStatus.RUNNING, PlanStatus.READY}:
            return PlanResult("blocked", f"Plan cannot pause from {plan.status.value}.", plan)
        plan.status = PlanStatus.PAUSED
        plan.updated_at = utc_now()
        self.store.save(plan)
        return PlanResult("paused", "The task is paused.", plan)

    def cancel(self) -> PlanResult:
        plan = self.current()
        if plan is None:
            return _missing_result(self.session_id)
        if plan.status in {PlanStatus.COMPLETED, PlanStatus.CANCELLED, PlanStatus.FAILED}:
            return PlanResult("blocked", f"Plan is already {plan.status.value}.", plan)
        plan.status = PlanStatus.CANCELLED
        plan.confirmation = None
        plan.clarification = None
        for step in plan.steps:
            if step.status in {StepStatus.PENDING, StepStatus.READY, StepStatus.RETRYING}:
                step.status = StepStatus.CANCELLED
        plan.updated_at = utc_now()
        self.store.save(plan)
        return PlanResult("cancelled", "The task was cancelled safely.", plan)

    def retry(self) -> PlanResult:
        plan = self.current()
        if plan is None:
            return _missing_result(self.session_id)
        step = _current_step(plan) or next((item for item in reversed(plan.steps) if item.status == StepStatus.FAILED), None)
        if step is None or step.action in NON_IDEMPOTENT_ACTIONS:
            return PlanResult("blocked", "The failed step cannot be retried automatically.", plan)
        step.status = StepStatus.RETRYING
        plan.status = PlanStatus.RUNNING
        return self._run(plan)

    def current(self) -> ExecutionPlan | None:
        return self.store.get(self.session_id)

    def _run(
        self,
        plan: ExecutionPlan,
        *,
        dry_run: bool = False,
        confirmed_step_id: str | None = None,
        resolved_step_id: str | None = None,
        resolved_result: StepResult | None = None,
    ) -> PlanResult:
        started = time.monotonic()
        plan.status = PlanStatus.RUNNING
        while True:
            if time.monotonic() - started > plan.limits.max_duration_seconds:
                return self._fail(plan, "plan_timeout", "The task stopped because its time limit was reached.")
            step = self.scheduler.next_step(plan)
            if step is None:
                blocked = self.scheduler.blocked_by_dependency(plan)
                if blocked:
                    for item in blocked:
                        item.status = StepStatus.BLOCKED
                    return self._fail(plan, "dependency_failed", "The task stopped because a required earlier step failed.", partial=True)
                if all(item.status in {StepStatus.COMPLETED, StepStatus.SKIPPED} for item in plan.steps):
                    partial = bool(plan.metadata.get("partial_steps"))
                    plan.status = (
                        PlanStatus.PARTIALLY_COMPLETED
                        if partial
                        else PlanStatus.COMPLETED
                    )
                    plan.current_step_id = None
                    plan.updated_at = utc_now()
                    self._sync_diagnostics(plan)
                    self.store.save(plan)
                    return PlanResult(
                        plan.status.value,
                        "Task completed with partial verification evidence."
                        if partial
                        else "Task completed.",
                        plan,
                    )
                return self._fail(plan, "no_runnable_step", "The task stopped because no verified step could run.", partial=True)
            plan.current_step_id = step.step_id
            step.status = StepStatus.RUNNING
            attempt = StepAttempt(len(step.attempts) + 1)
            step.attempts.append(attempt)
            self.store.save(plan)
            if step.step_id == resolved_step_id and resolved_result is not None:
                result = resolved_result
                resolved_step_id = None
                resolved_result = None
            else:
                result = self.executor.execute(
                    step,
                    dry_run=dry_run,
                    confirmed=step.step_id == confirmed_step_id,
                )
            if result.status == "confirmation_required":
                step.status = StepStatus.WAITING_FOR_CONFIRMATION
                attempt.status = result.status
                attempt.message = result.message
                attempt.ended_at = utc_now()
                plan.status = PlanStatus.WAITING_FOR_CONFIRMATION
                plan.confirmation = ConfirmationRequest(
                    plan.plan_id,
                    step.step_id,
                    plan.session_id,
                    result.message,
                    result.confirmation_token or secrets.token_urlsafe(12),
                )
                plan.updated_at = utc_now()
                self.store.save(plan)
                return PlanResult("confirmation_required", result.message, plan)
            if result.status == "clarification_required":
                step.status = StepStatus.WAITING_FOR_CLARIFICATION
                attempt.status = result.status
                attempt.message = result.message
                attempt.ended_at = utc_now()
                plan.status = PlanStatus.WAITING_FOR_CLARIFICATION
                plan.clarification = ClarificationRequest(
                    plan.plan_id,
                    step.step_id,
                    plan.session_id,
                    result.message,
                    tuple(result.data.get("choices", ())),
                )
                self.store.save(plan)
                return PlanResult("clarification_required", result.message, plan)
            if result.status == "success":
                step.status = StepStatus.VERIFYING
                result = self.verifier.verify(step, result)
            if result.status in {"success", "partial_success"} and (
                result.data.get("verified") or dry_run
            ):
                step.status = StepStatus.COMPLETED
                step.result_metadata = _safe_evidence(result.data)
                attempt.status = result.status
                attempt.message = result.message
                attempt.verification = _safe_evidence(result.data)
                attempt.ended_at = utc_now()
                if result.status == "partial_success":
                    plan.metadata.setdefault("partial_steps", []).append(step.step_id)
                plan.updated_at = utc_now()
                self._sync_diagnostics(plan)
                self.store.save(plan)
                continue
            attempt.status = result.status
            attempt.message = result.message
            attempt.ended_at = utc_now()
            recovery = self.recovery.recover(plan, step, result, self.executor)
            if recovery and len(step.attempts) < step.retry_policy.max_attempts:
                attempt.recovery = recovery
                step.status = StepStatus.RETRYING
                plan.status = PlanStatus.RECOVERING
                self._sync_diagnostics(plan)
                self.store.save(plan)
                continue
            step.status = StepStatus.BLOCKED if result.status in {"blocked", "target_lost"} else StepStatus.FAILED
            return self._fail(plan, "step_failed", result.message, step_id=step.step_id, partial=True)

    def _fail(
        self,
        plan: ExecutionPlan,
        code: str,
        message: str,
        *,
        step_id: str | None = None,
        partial: bool = False,
    ) -> PlanResult:
        completed = any(step.status == StepStatus.COMPLETED for step in plan.steps)
        plan.status = PlanStatus.PARTIALLY_COMPLETED if partial and completed else PlanStatus.FAILED
        plan.metadata["failure_point"] = {
            "code": code,
            "step_id": step_id,
            "message": message,
        }
        plan.updated_at = utc_now()
        self._sync_diagnostics(plan)
        self.store.save(plan)
        return PlanResult(plan.status.value, message, plan, FailureReason(code, message, step_id))

    def _sync_diagnostics(self, plan: ExecutionPlan) -> None:
        diagnostics = getattr(self.executor, "diagnostics", None)
        if diagnostics:
            plan.metadata["diagnostics"] = list(diagnostics)


def _validation_message(plan: ExecutionPlan) -> str:
    issues = plan.metadata.get("validation_issues", [])
    return "Plan validation failed: " + "; ".join(str(item.get("message")) for item in issues[:5])


def _current_step(plan: ExecutionPlan):
    return next((step for step in plan.steps if step.step_id == plan.current_step_id), None)


def _safe_evidence(data: dict) -> dict:
    blocked = {"window_handle", "process_id", "runtime_id", "password", "token", "secret"}
    return {key: value for key, value in data.items() if key.casefold() not in blocked}


def _missing_result(session_id: str) -> PlanResult:
    plan = ExecutionPlan.create(Goal("", "", session_id), [])
    plan.status = PlanStatus.FAILED
    return PlanResult("not_found", "No plan exists for this session.", plan)


__all__ = ["ExecutivePlanner"]
