"""Safe recovery manager for Agent Execution Engine V2."""

from __future__ import annotations

from typing import Any, Callable

from grandpa.agent.execution.models import RecoveryAttempt


def execute_with_recovery(
    func: Callable[..., Any],
    *args: Any,
    max_retries: int = 3,
    recovery_action: Callable[[], None] | None = None,
    **kwargs: Any,
) -> tuple[Any, list[RecoveryAttempt]]:
    """Execute an action with bounded retries, logging recovery attempts."""
    attempts = []
    result = None

    for i in range(1, max_retries + 1):
        try:
            result = func(*args, **kwargs)
            return result, attempts
        except Exception as exc:
            # Recovery action callback (e.g. refreshing git or cleanup)
            if recovery_action:
                try:
                    recovery_action()
                except Exception:
                    pass
            attempts.append(
                RecoveryAttempt(
                    attempt_number=i,
                    error_message=str(exc),
                    action_taken="Ran recovery callback and retried.",
                    success=False,
                )
            )
            if i == max_retries:
                raise exc

    return result, attempts
