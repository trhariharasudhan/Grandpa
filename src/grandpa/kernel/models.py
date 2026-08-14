"""Dependency-light contracts for Grandpa's canonical execution kernel."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Mapping


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AssistantSource(str, Enum):
    CLI = "cli"
    TUI = "tui"
    VOICE = "voice"
    API = "api"
    SDK = "sdk"
    GUI = "gui"


class PolicyOutcome(str, Enum):
    ALLOW = "allow"
    CONFIRM = "confirm"
    BLOCK = "block"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ToolStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"
    PARTIAL = "partial"


class VerificationStatus(str, Enum):
    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    FAILED = "failed"


class ResponseStatus(str, Enum):
    COMPLETED = "completed"
    CONFIRMATION_REQUIRED = "confirmation_required"
    BLOCKED = "blocked"
    FAILED = "failed"


class AuditStage(str, Enum):
    REQUEST_RECEIVED = "request_received"
    PLAN_CREATED = "plan_created"
    ACTION_ATTEMPTED = "action_attempted"
    POLICY_EVALUATED = "policy_evaluated"
    CONFIRMATION_REQUIRED = "confirmation_required"
    EXECUTION_STARTED = "execution_started"
    EXECUTION_FINISHED = "execution_finished"
    VERIFICATION_FINISHED = "verification_finished"
    MEMORY_UPDATED = "memory_updated"
    REQUEST_COMPLETED = "request_completed"
    REQUEST_FAILED = "request_failed"


@dataclass(frozen=True)
class AssistantRequest:
    request_id: str
    session_id: str
    source: AssistantSource
    text: str
    attachments: tuple[Mapping[str, Any], ...] = ()
    confirmation_token: str | None = None
    dry_run: bool = False

    @classmethod
    def create(
        cls,
        *,
        session_id: str,
        source: AssistantSource,
        text: str,
        attachments: tuple[Mapping[str, Any], ...] = (),
        confirmation_token: str | None = None,
        dry_run: bool = False,
    ) -> AssistantRequest:
        return cls(
            request_id=str(uuid.uuid4()),
            session_id=session_id,
            source=source,
            text=text,
            attachments=attachments,
            confirmation_token=confirmation_token,
            dry_run=dry_run,
        )


@dataclass(frozen=True)
class AssistantContext:
    capabilities: frozenset[str] = frozenset()
    environment: Mapping[str, Any] = field(default_factory=dict)
    conversation: tuple[Mapping[str, Any], ...] = ()
    memories: tuple[Mapping[str, Any], ...] = ()


@dataclass(frozen=True)
class Intent:
    domain: str
    name: str
    confidence: float
    entities: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VerificationSpec:
    kind: str
    parameters: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PlannedAction:
    action_id: str
    tool_name: str
    arguments: Mapping[str, Any]
    dependencies: tuple[str, ...] = ()
    verification: VerificationSpec | None = None
    idempotency_key: str = ""


@dataclass(frozen=True)
class ExecutionPlan:
    plan_id: str
    request_id: str
    actions: tuple[PlannedAction, ...]


@dataclass(frozen=True)
class PolicyDecision:
    outcome: PolicyOutcome
    risk: RiskLevel
    reason: str
    action_digest: str
    constraints: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ConfirmationRequest:
    token: str
    request_id: str
    session_id: str
    action_id: str
    action_digest: str
    expires_at: datetime


@dataclass(frozen=True)
class ExecutionAuthorization:
    """Proof passed to an executor after policy and confirmation checks."""

    decision: PolicyDecision
    confirmation_validated: bool = False

    def __post_init__(self) -> None:
        authorized = self.decision.outcome is PolicyOutcome.ALLOW or (
            self.decision.outcome is PolicyOutcome.CONFIRM
            and self.confirmation_validated
        )
        if not authorized:
            raise ValueError("Execution authorization requires an allowed action.")


@dataclass(frozen=True)
class ToolResult:
    status: ToolStatus
    data: Mapping[str, Any]
    safe_message: str
    evidence: tuple[Mapping[str, Any], ...] = ()


@dataclass(frozen=True)
class VerificationResult:
    status: VerificationStatus
    reason: str
    evidence: tuple[Mapping[str, Any], ...] = ()


@dataclass(frozen=True)
class AuditEvent:
    event_id: str
    request_id: str
    action_id: str | None
    stage: AuditStage
    outcome: str
    redacted_payload: Mapping[str, Any]
    timestamp: datetime = field(default_factory=utc_now)


@dataclass(frozen=True)
class AssistantResponse:
    status: ResponseStatus
    text: str
    plan_id: str | None = None
    confirmation: ConfirmationRequest | None = None
    actions: tuple[ToolResult, ...] = ()


def action_digest(
    request: AssistantRequest,
    action: PlannedAction,
    canonical_arguments: Mapping[str, Any],
) -> str:
    """Return a deterministic digest bound to an exact request and action."""

    payload = {
        "request_id": request.request_id,
        "session_id": request.session_id,
        "tool_name": action.tool_name,
        "arguments": _canonicalize(canonical_arguments),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def model_to_dict(value: Any) -> Any:
    """Convert kernel models to JSON-compatible primitives."""

    if is_dataclass(value):
        return model_to_dict(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): model_to_dict(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [model_to_dict(item) for item in value]
    return value


def _canonicalize(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _canonicalize(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (tuple, list)):
        return [_canonicalize(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"Unsupported action argument type: {type(value).__name__}")
