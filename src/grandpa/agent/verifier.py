"""Semantic step and action verifier for Grandpa Agent Runtime V1."""

from __future__ import annotations

from typing import Any

from grandpa.agent.models import AgentStep, VerificationResult


class StepVerifier:
    """Verifier to check the correctness and completion of executed actions."""

    def verify_step(self, step: AgentStep, step_result: Any) -> VerificationResult:
        """Semanitcally verify if a step completed successfully and got expected output."""
        failures = []
        details = {}

        # 1. Basic status check
        if step.error:
            failures.append(f"Step recorded an error: {step.error}")

        # 2. Tool-specific verification
        tool = step.tool.lower()
        if tool == "memory":
            # Verify memory was retrieved or updated successfully
            if step_result is None:
                failures.append("Memory tool returned empty result.")
            else:
                details["memory_result"] = str(step_result)
        elif tool == "research":
            # Verify research returned summaries/content
            if not step_result:
                failures.append("Research returned no summary or page details.")
            else:
                details["research_content_length"] = len(str(step_result))
        elif tool == "automation":
            # Verify automation did not fail
            if isinstance(step_result, dict) and step_result.get("status") == "error":
                failures.append(step_result.get("message", "Automation failed."))
            details["automation_result"] = step_result
        elif tool == "vision":
            # Verify vision inspection found components
            if not step_result:
                failures.append("Vision inspection did not detect any UI elements.")
            details["ui_elements_count"] = len(step_result) if isinstance(step_result, list) else 1
        elif tool == "planner":
            # Verify planner created a runnable plan
            if not step_result:
                failures.append("Planner failed to construct a valid plan.")

        action_completed = len(failures) == 0
        # Expected result obtained is true if no failures occurred
        expected_result_obtained = action_completed

        return VerificationResult(
            action_completed=action_completed,
            expected_result_obtained=expected_result_obtained,
            failures=failures,
            details=details,
        )
