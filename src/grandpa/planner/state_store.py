"""Session-scoped planner state with sanitized local snapshots."""

from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from grandpa.core.config import DEFAULT_CONFIG_DIR
from grandpa.planner.models import (
    ClarificationRequest,
    ConfirmationRequest,
    ExecutionPlan,
    PlannerLimits,
    PlanStatus,
    PlanStep,
    RecoveryPolicy,
    RetryPolicy,
    RiskLevel,
    StepAttempt,
    StepCondition,
    StepDependency,
    StepStatus,
    StepVerification,
    model_to_dict,
)

DEFAULT_PLAN_STATE_DIR = DEFAULT_CONFIG_DIR / "plans"
_SENSITIVE_KEYS = {"password", "passcode", "otp", "token", "secret", "card", "cvv"}


class PlanStateStore:
    """Keep live state isolated by session and write only sanitized snapshots."""

    def __init__(self, root: Path = DEFAULT_PLAN_STATE_DIR) -> None:
        self.root = root
        self._plans: dict[str, ExecutionPlan] = {}
        self._lock = threading.RLock()

    def save(self, plan: ExecutionPlan) -> None:
        with self._lock:
            self._plans[plan.session_id] = plan
            self._write_snapshot(plan)

    def get(self, session_id: str) -> ExecutionPlan | None:
        with self._lock:
            live = self._plans.get(session_id)
            if live is not None:
                return live
        return self._read_snapshot(session_id)

    def list(self) -> tuple[ExecutionPlan, ...]:
        plans = dict(self._plans)
        if self.root.exists():
            for path in self.root.glob("*.json"):
                plan = self._read_path(path)
                if plan is not None:
                    plans.setdefault(plan.session_id, plan)
        return tuple(
            sorted(plans.values(), key=lambda item: item.updated_at, reverse=True)
        )

    def delete(self, session_id: str) -> None:
        with self._lock:
            self._plans.pop(session_id, None)
        self._path(session_id).unlink(missing_ok=True)

    def _write_snapshot(self, plan: ExecutionPlan) -> None:
        from grandpa.security.file_utils import secure_mkdir

        secure_mkdir(self.root)
        payload = sanitize_plan_data(model_to_dict(plan))
        path = self._path(plan.session_id)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8"
        )
        temporary.replace(path)

    def _read_snapshot(self, session_id: str) -> ExecutionPlan | None:
        return self._read_path(self._path(session_id))

    def _read_path(self, path: Path) -> ExecutionPlan | None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return _plan_from_dict(payload)
        except (OSError, ValueError, TypeError, KeyError):
            return None

    def _path(self, session_id: str) -> Path:
        safe = "".join(
            character
            for character in session_id
            if character.isalnum() or character in "_-"
        )[:80]
        return self.root / f"{safe or 'default'}.json"


def sanitize_plan_data(value: Any, key: str = "") -> Any:
    """Return a JSON-safe planner value with sensitive content redacted."""

    normalized = key.casefold()
    if any(marker in normalized for marker in _SENSITIVE_KEYS):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {
            str(name): sanitize_plan_data(item, str(name))
            for name, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize_plan_data(item, key) for item in value]
    if isinstance(value, str) and _looks_sensitive(value):
        return "[REDACTED]"
    return value


def _looks_sensitive(value: str) -> bool:
    lowered = value.casefold()
    return any(
        marker in lowered
        for marker in ("password=", "bearer ", "api_key", "api key", "cvv")
    )


def _plan_from_dict(data: dict[str, Any]) -> ExecutionPlan:
    steps: list[PlanStep] = []
    for item in data.get("steps", []):
        steps.append(
            PlanStep(
                step_id=str(item["step_id"]),
                order=int(item["order"]),
                description=str(item["description"]),
                action=str(item["action"]),
                parameters=dict(item.get("parameters") or {}),
                dependencies=tuple(
                    StepDependency(**value) for value in item.get("dependencies", [])
                ),
                preconditions=tuple(
                    StepCondition(**value) for value in item.get("preconditions", [])
                ),
                expected_postconditions=tuple(
                    StepCondition(**value)
                    for value in item.get("expected_postconditions", [])
                ),
                verification=StepVerification(
                    **item.get("verification", {"strategy": "execution_success"})
                ),
                timeout_seconds=float(item.get("timeout_seconds", 15)),
                retry_policy=RetryPolicy(**item.get("retry_policy", {})),
                recovery_policy=RecoveryPolicy(**item.get("recovery_policy", {})),
                risk=RiskLevel(item.get("risk", "low")),
                requires_confirmation=bool(item.get("requires_confirmation", False)),
                status=StepStatus(item.get("status", "pending")),
                attempts=[
                    _attempt_from_dict(value) for value in item.get("attempts", [])
                ],
                result_metadata=dict(item.get("result_metadata") or {}),
            )
        )
    limits = PlannerLimits(**data.get("limits", {}))
    return ExecutionPlan(
        plan_id=str(data["plan_id"]),
        session_id=str(data["session_id"]),
        original_goal=str(data.get("original_goal") or ""),
        normalized_goal=str(data.get("normalized_goal") or ""),
        created_at=datetime.fromisoformat(data["created_at"]),
        updated_at=datetime.fromisoformat(data.get("updated_at") or data["created_at"]),
        status=PlanStatus(data.get("status", "created")),
        steps=steps,
        current_step_id=data.get("current_step_id"),
        limits=limits,
        metadata=dict(data.get("metadata") or {}),
        planner_source=str(data.get("planner_source") or "deterministic"),
        model_name=data.get("model_name"),
        safety_classification=RiskLevel(data.get("safety_classification", "low")),
        confirmation=_confirmation_from_dict(data.get("confirmation")),
        clarification=_clarification_from_dict(data.get("clarification")),
    )


def _attempt_from_dict(data: dict[str, Any]) -> StepAttempt:
    return StepAttempt(
        attempt=int(data.get("attempt", 1)),
        started_at=datetime.fromisoformat(data["started_at"]),
        ended_at=(
            datetime.fromisoformat(data["ended_at"]) if data.get("ended_at") else None
        ),
        status=str(data.get("status") or "running"),
        message=str(data.get("message") or ""),
        verification=dict(data.get("verification") or {}),
        recovery=str(data.get("recovery") or ""),
    )


def _confirmation_from_dict(data: Any) -> ConfirmationRequest | None:
    if not isinstance(data, dict):
        return None
    return ConfirmationRequest(
        plan_id=str(data["plan_id"]),
        step_id=str(data["step_id"]),
        session_id=str(data["session_id"]),
        message=str(data.get("message") or "Confirmation is required."),
        token=str(data["token"]) if data.get("token") else None,
    )


def _clarification_from_dict(data: Any) -> ClarificationRequest | None:
    if not isinstance(data, dict):
        return None
    return ClarificationRequest(
        plan_id=str(data["plan_id"]),
        step_id=str(data["step_id"]) if data.get("step_id") else None,
        session_id=str(data["session_id"]),
        message=str(data.get("message") or "Clarification is required."),
        choices=tuple(str(item) for item in data.get("choices", [])),
    )


__all__ = ["DEFAULT_PLAN_STATE_DIR", "PlanStateStore", "sanitize_plan_data"]
