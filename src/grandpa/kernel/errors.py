"""Explicit fail-closed errors raised by the canonical kernel."""

from __future__ import annotations


class KernelError(RuntimeError):
    """Base error with a message safe to return to an interface."""

    def __init__(self, message: str, *, safe_message: str | None = None) -> None:
        super().__init__(message)
        self.safe_message = (
            safe_message or "Grandpa could not complete that request safely."
        )


class RequestNormalizationError(KernelError):
    pass


class IntentClassificationError(KernelError):
    pass


class PlanningError(KernelError):
    pass


class ToolNotFoundError(KernelError):
    pass


class ToolArgumentValidationError(KernelError):
    pass


class PolicyEvaluationError(KernelError):
    pass


class ConfirmationValidationError(KernelError):
    pass


class SecurityInvariantError(KernelError):
    pass


class AuditWriteError(KernelError):
    pass


class ToolExecutionError(KernelError):
    pass


class ResultVerificationError(KernelError):
    pass


class MemoryUpdateError(KernelError):
    pass


class ResponseRenderingError(KernelError):
    pass
