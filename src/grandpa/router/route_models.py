"""Intent routing models for local action compatibility."""

from __future__ import annotations

from dataclasses import dataclass, field
from time import time
from typing import Any, Literal

RouteRiskLevel = Literal["LOW", "MEDIUM", "HIGH", "BLOCKED"]
RouteSource = Literal["skill", "planner", "legacy", "fallback"]

_SENSITIVE_KEYS = ("password", "secret", "token", "key", "clipboard", "content")


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): "[redacted]"
            if any(part in str(key).lower() for part in _SENSITIVE_KEYS)
            else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


@dataclass(frozen=True)
class IntentRoute:
    """A safe, inspectable route decision for a user request."""

    request_text: str
    intent: str
    category: str
    confidence: float
    skill_name: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    risk_level: RouteRiskLevel = "LOW"
    approval_required: bool = False
    fallback_reason: str = ""
    execution_source: RouteSource = "fallback"
    planner_suitable: bool = False
    created_at: float = field(default_factory=time)

    @property
    def can_execute_as_skill(self) -> bool:
        return (
            self.execution_source == "skill"
            and bool(self.skill_name)
            and self.confidence >= 0.7
        )

    @property
    def can_execute_as_planner(self) -> bool:
        return self.execution_source == "planner" and self.confidence >= 0.7

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_text": self.request_text,
            "intent": self.intent,
            "category": self.category,
            "confidence": round(self.confidence, 3),
            "skill_name": self.skill_name,
            "params": _redact(self.params),
            "risk_level": self.risk_level,
            "approval_required": self.approval_required,
            "fallback_reason": self.fallback_reason,
            "execution_source": self.execution_source,
            "planner_suitable": self.planner_suitable,
            "created_at": self.created_at,
        }


__all__ = ["IntentRoute", "RouteRiskLevel", "RouteSource"]
