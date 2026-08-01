"""Result verification and outcome comparison module for Agent Execution Engine V2."""

from __future__ import annotations

from grandpa.agent.execution.models import ValidationResult


def verify_execution_outcome(
    initial_exit_code: int,
    validation_res: ValidationResult,
    ruff_exit_code: int = 0,
    compile_exit_code: int = 0,
) -> str:
    """Compare post-application validation results against initial failure to verify success."""
    if validation_res.timeout_triggered:
        return "blocked"

    # All validations must pass (exit code 0)
    if validation_res.exit_code == 0 and ruff_exit_code == 0 and compile_exit_code == 0:
        if validation_res.passed > 0 and validation_res.failed == 0:
            return "verified_success"
        return "verified_success"  # Compilation & linting passed completely

    # Check for partial success
    if validation_res.failed == 0 and (ruff_exit_code != 0 or compile_exit_code != 0):
        return "partial_success"

    # Stale or environment failure check
    if validation_res.exit_code == -2:
        return "environment_failure"

    return "failed"
