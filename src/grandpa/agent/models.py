"""Structured models for Grandpa Agent Runtime V1."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AgentIntent(str, Enum):
    PROJECT_CONTINUE = "project_continue"
    PROJECT_STATUS = "project_status"
    RESEARCH = "research"
    BROWSER_TASK = "browser_task"
    AUTOMATION_TASK = "automation_task"
    MEMORY_TASK = "memory_task"
    PLANNING_TASK = "planning_task"
    UNKNOWN = "unknown"


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class AgentGoal:
    raw_text: str
    session_id: str
    created_at: float = field(default_factory=time.time)


@dataclass
class AgentStep:
    id: str
    description: str
    tool: str
    status: StepStatus = StepStatus.PENDING
    args: dict[str, Any] = field(default_factory=dict)
    logs: list[str] = field(default_factory=list)
    started_at: float | None = None
    ended_at: float | None = None
    error: str | None = None


@dataclass
class AgentPlan:
    plan_id: str
    goal: AgentGoal
    steps: list[AgentStep]
    created_at: float = field(default_factory=time.time)


@dataclass
class ToolSelection:
    tool_name: str
    reason: str
    requires_confirmation: bool = False


@dataclass
class VerificationResult:
    action_completed: bool
    expected_result_obtained: bool
    failures: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class RecoveryAttempt:
    step_id: str
    attempt_number: int
    error_message: str
    action_taken: str
    success: bool = False


@dataclass
class AgentContext:
    goal: AgentGoal
    intent: AgentIntent
    project_memory: dict[str, Any] = field(default_factory=dict)
    preferences: dict[str, Any] = field(default_factory=dict)
    session_memory: list[dict[str, Any]] = field(default_factory=list)
    planner_output: str | None = None
    selected_tools: list[ToolSelection] = field(default_factory=list)
    execution_history: list[AgentStep] = field(default_factory=list)
    verification_results: list[VerificationResult] = field(default_factory=list)
    recovery_attempts: list[RecoveryAttempt] = field(default_factory=list)


class AgentExecutionState(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class AgentResult:
    state: AgentExecutionState
    goal: AgentGoal
    context: AgentContext
    plan: AgentPlan | None = None
    message: str = ""
    error: str | None = None
    ended_at: float = field(default_factory=time.time)
