"""Runtime skill contracts for Grandpa tool execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from time import time
from typing import Any, Callable, Literal

SkillRiskLevel = Literal["LOW", "MEDIUM", "HIGH", "BLOCKED"]
SkillStatus = Literal["completed", "dry_run", "approval_required", "blocked", "unsupported", "failed"]


@dataclass(frozen=True)
class SkillParameter:
    """Description of a supported skill parameter."""

    name: str
    description: str = ""
    required: bool = False
    type: str = "string"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "required": self.required,
            "type": self.type,
        }


@dataclass(frozen=True)
class SkillExecutionContext:
    """Per-execution context shared by workflows, API calls, and CLI routing."""

    workflow_id: str | None = None
    user_request: str = ""
    dry_run: bool = False
    approval_state: str = "none"
    source: str = "unknown"
    timeout: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "user_request": self.user_request,
            "dry_run": self.dry_run,
            "approval_state": self.approval_state,
            "source": self.source,
            "timeout": self.timeout,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class SkillResult:
    """Normalized result returned by every runtime skill."""

    ok: bool
    status: SkillStatus
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    risk_level: SkillRiskLevel = "LOW"
    approval_required: bool = False
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "status": self.status,
            "message": self.message,
            "data": self.data,
            "risk_level": self.risk_level,
            "approval_required": self.approval_required,
            "error": self.error,
        }


SkillExecutor = Callable[[dict[str, Any], SkillExecutionContext], SkillResult]


@dataclass(frozen=True)
class RuntimeSkill:
    """A callable Grandpa runtime capability registered by name."""

    name: str
    description: str
    category: str
    risk_level: SkillRiskLevel
    approval_required: bool
    parameters: tuple[SkillParameter, ...] = ()
    dry_run_supported: bool = True
    executor: SkillExecutor | None = None
    aliases: tuple[str, ...] = ()

    def execute(self, params: dict[str, Any] | None = None, context: SkillExecutionContext | None = None) -> SkillResult:
        if self.approval_required and context and context.approval_state not in {"approved", "preapproved"}:
            return SkillResult(
                ok=False,
                status="approval_required",
                message=f"Confirmation required before running {self.name}.",
                risk_level=self.risk_level,
                approval_required=True,
            )
        if self.executor is None:
            return SkillResult(
                ok=False,
                status="unsupported",
                message=f"{self.name} is registered but has no executor.",
                risk_level=self.risk_level,
                approval_required=self.approval_required,
            )
        started_at = time()
        try:
            result = self.executor(params or {}, context or SkillExecutionContext())
        except Exception as exc:  # pragma: no cover - defensive guard
            return SkillResult(
                ok=False,
                status="failed",
                message="Skill execution failed safely.",
                risk_level=self.risk_level,
                approval_required=self.approval_required,
                error=exc.__class__.__name__,
            )
        data = dict(result.data)
        data.setdefault("runtime_ms", round((time() - started_at) * 1000, 2))
        return SkillResult(
            ok=result.ok,
            status=result.status,
            message=result.message,
            data=data,
            risk_level=result.risk_level or self.risk_level,
            approval_required=result.approval_required,
            error=result.error,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "risk_level": self.risk_level,
            "approval_required": self.approval_required,
            "parameters": [item.to_dict() for item in self.parameters],
            "dry_run_supported": self.dry_run_supported,
            "aliases": list(self.aliases),
        }


__all__ = [
    "RuntimeSkill",
    "SkillExecutionContext",
    "SkillExecutor",
    "SkillParameter",
    "SkillResult",
    "SkillRiskLevel",
    "SkillStatus",
]
