"""Strict, serializable contracts for Grandpa Executive Planner V1."""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class PlanStatus(str, Enum):
    CREATED = "created"
    VALIDATING = "validating"
    READY = "ready"
    RUNNING = "running"
    WAITING_FOR_CONFIRMATION = "waiting_for_confirmation"
    WAITING_FOR_CLARIFICATION = "waiting_for_clarification"
    PAUSED = "paused"
    RECOVERING = "recovering"
    COMPLETED = "completed"
    PARTIALLY_COMPLETED = "partially_completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class StepStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    VERIFYING = "verifying"
    RETRYING = "retrying"
    WAITING_FOR_CONFIRMATION = "waiting_for_confirmation"
    WAITING_FOR_CLARIFICATION = "waiting_for_clarification"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    PROHIBITED = "prohibited"


@dataclass(frozen=True)
class Goal:
    text: str
    normalized: str
    session_id: str


@dataclass(frozen=True)
class StepDependency:
    step_id: str
    required_status: str = StepStatus.COMPLETED.value


@dataclass(frozen=True)
class StepCondition:
    kind: str
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StepVerification:
    strategy: str
    parameters: dict[str, Any] = field(default_factory=dict)
    mandatory: bool = True


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 1
    delay_seconds: float = 0.25
    retryable_statuses: tuple[str, ...] = ("failed", "target_lost")


@dataclass(frozen=True)
class RecoveryPolicy:
    strategies: tuple[str, ...] = ()
    max_recoveries: int = 0


@dataclass(frozen=True)
class PlannerLimits:
    max_steps: int = 20
    max_retries_per_step: int = 2
    max_recoveries: int = 4
    max_replans: int = 1
    max_scroll_attempts: int = 6
    max_duration_seconds: float = 120.0


@dataclass
class StepAttempt:
    attempt: int
    started_at: datetime = field(default_factory=utc_now)
    ended_at: datetime | None = None
    status: str = "running"
    message: str = ""
    verification: dict[str, Any] = field(default_factory=dict)
    recovery: str = ""


@dataclass
class PlanStep:
    step_id: str
    order: int
    description: str
    action: str
    parameters: dict[str, Any] = field(default_factory=dict)
    dependencies: tuple[StepDependency, ...] = ()
    preconditions: tuple[StepCondition, ...] = ()
    expected_postconditions: tuple[StepCondition, ...] = ()
    verification: StepVerification = field(
        default_factory=lambda: StepVerification("execution_success")
    )
    timeout_seconds: float = 15.0
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    recovery_policy: RecoveryPolicy = field(default_factory=RecoveryPolicy)
    risk: RiskLevel = RiskLevel.LOW
    requires_confirmation: bool = False
    status: StepStatus = StepStatus.PENDING
    attempts: list[StepAttempt] = field(default_factory=list)
    result_metadata: dict[str, Any] = field(default_factory=dict)

    def transition(self, status: StepStatus) -> None:
        allowed = _STEP_TRANSITIONS.get(self.status, frozenset())
        if status not in allowed:
            raise ValueError(
                f"Invalid step transition: {self.status.value} -> {status.value}"
            )
        self.status = status


@dataclass
class ExecutionPlan:
    plan_id: str
    session_id: str
    original_goal: str
    normalized_goal: str
    created_at: datetime
    status: PlanStatus
    steps: list[PlanStep]
    current_step_id: str | None = None
    limits: PlannerLimits = field(default_factory=PlannerLimits)
    metadata: dict[str, Any] = field(default_factory=dict)
    planner_source: str = "deterministic"
    model_name: str | None = None
    safety_classification: RiskLevel = RiskLevel.LOW
    updated_at: datetime = field(default_factory=utc_now)
    confirmation: "ConfirmationRequest | None" = None
    clarification: "ClarificationRequest | None" = None

    def transition(self, status: PlanStatus) -> None:
        allowed = _PLAN_TRANSITIONS.get(self.status, frozenset())
        if status not in allowed:
            raise ValueError(
                f"Invalid plan transition: {self.status.value} -> {status.value}"
            )
        self.status = status
        self.updated_at = utc_now()

    @classmethod
    def create(
        cls,
        goal: Goal,
        steps: list[PlanStep],
        *,
        limits: PlannerLimits | None = None,
        planner_source: str = "deterministic",
        model_name: str | None = None,
    ) -> "ExecutionPlan":
        return cls(
            plan_id=f"plan_{uuid.uuid4().hex[:16]}",
            session_id=goal.session_id,
            original_goal=goal.text,
            normalized_goal=goal.normalized,
            created_at=utc_now(),
            status=PlanStatus.CREATED,
            steps=steps,
            limits=limits or PlannerLimits(),
            planner_source=planner_source,
            model_name=model_name,
        )


@dataclass(frozen=True)
class FailureReason:
    code: str
    message: str
    step_id: str | None = None
    recoverable: bool = False


@dataclass(frozen=True)
class ConfirmationRequest:
    plan_id: str
    step_id: str
    session_id: str
    message: str
    token: str | None = None


@dataclass(frozen=True)
class ClarificationRequest:
    plan_id: str
    step_id: str | None
    session_id: str
    message: str
    choices: tuple[str, ...] = ()


@dataclass(frozen=True)
class StepResult:
    status: str
    message: str
    step_id: str
    data: dict[str, Any] = field(default_factory=dict)
    confirmation_token: str | None = None


@dataclass(frozen=True)
class PlanProgress:
    plan_id: str
    completed_steps: int
    total_steps: int
    current_step_id: str | None
    status: str


@dataclass(frozen=True)
class PlanResult:
    status: str
    message: str
    plan: ExecutionPlan
    failure: FailureReason | None = None


@dataclass(frozen=True)
class StepExecutionState:
    step_id: str
    status: str
    attempts: int


@dataclass(frozen=True)
class PlanExecutionState:
    plan_id: str
    session_id: str
    status: str
    current_step_id: str | None
    steps: tuple[StepExecutionState, ...]


def model_to_dict(value: Any) -> Any:
    """Convert planner contracts into JSON-safe primitives."""

    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "__dataclass_fields__"):
        return {key: model_to_dict(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): model_to_dict(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [model_to_dict(item) for item in value]
    return value


_PLAN_TRANSITIONS = {
    PlanStatus.CREATED: frozenset({PlanStatus.VALIDATING, PlanStatus.CANCELLED}),
    PlanStatus.VALIDATING: frozenset({PlanStatus.READY, PlanStatus.FAILED}),
    PlanStatus.READY: frozenset({PlanStatus.RUNNING, PlanStatus.PAUSED, PlanStatus.CANCELLED}),
    PlanStatus.RUNNING: frozenset(
        {
            PlanStatus.WAITING_FOR_CONFIRMATION,
            PlanStatus.WAITING_FOR_CLARIFICATION,
            PlanStatus.PAUSED,
            PlanStatus.RECOVERING,
            PlanStatus.COMPLETED,
            PlanStatus.PARTIALLY_COMPLETED,
            PlanStatus.FAILED,
            PlanStatus.CANCELLED,
            PlanStatus.EXPIRED,
        }
    ),
    PlanStatus.RECOVERING: frozenset(
        {PlanStatus.RUNNING, PlanStatus.FAILED, PlanStatus.PARTIALLY_COMPLETED}
    ),
    PlanStatus.WAITING_FOR_CONFIRMATION: frozenset(
        {PlanStatus.RUNNING, PlanStatus.CANCELLED, PlanStatus.EXPIRED}
    ),
    PlanStatus.WAITING_FOR_CLARIFICATION: frozenset(
        {PlanStatus.RUNNING, PlanStatus.CANCELLED, PlanStatus.EXPIRED}
    ),
    PlanStatus.PAUSED: frozenset({PlanStatus.RUNNING, PlanStatus.CANCELLED}),
}

_STEP_TRANSITIONS = {
    StepStatus.PENDING: frozenset(
        {StepStatus.READY, StepStatus.SKIPPED, StepStatus.BLOCKED, StepStatus.CANCELLED}
    ),
    StepStatus.READY: frozenset(
        {StepStatus.RUNNING, StepStatus.SKIPPED, StepStatus.CANCELLED}
    ),
    StepStatus.RUNNING: frozenset(
        {
            StepStatus.VERIFYING,
            StepStatus.WAITING_FOR_CONFIRMATION,
            StepStatus.WAITING_FOR_CLARIFICATION,
            StepStatus.RETRYING,
            StepStatus.FAILED,
            StepStatus.BLOCKED,
            StepStatus.CANCELLED,
        }
    ),
    StepStatus.VERIFYING: frozenset(
        {StepStatus.COMPLETED, StepStatus.RETRYING, StepStatus.FAILED, StepStatus.BLOCKED}
    ),
    StepStatus.RETRYING: frozenset({StepStatus.READY, StepStatus.RUNNING, StepStatus.FAILED}),
    StepStatus.WAITING_FOR_CONFIRMATION: frozenset(
        {StepStatus.READY, StepStatus.RUNNING, StepStatus.CANCELLED}
    ),
    StepStatus.WAITING_FOR_CLARIFICATION: frozenset(
        {StepStatus.READY, StepStatus.RUNNING, StepStatus.CANCELLED}
    ),
}


__all__ = [
    "ClarificationRequest",
    "ConfirmationRequest",
    "ExecutionPlan",
    "FailureReason",
    "Goal",
    "PlanExecutionState",
    "PlanProgress",
    "PlanResult",
    "PlanStatus",
    "PlanStep",
    "PlannerLimits",
    "RecoveryPolicy",
    "RetryPolicy",
    "RiskLevel",
    "StepAttempt",
    "StepCondition",
    "StepDependency",
    "StepExecutionState",
    "StepResult",
    "StepStatus",
    "StepVerification",
    "model_to_dict",
    "utc_now",
]
