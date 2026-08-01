"""Central Orchestration Engine for Grandpa Agent Runtime V1."""

from __future__ import annotations

import uuid
from typing import Any

from grandpa.agent.context import build_context
from grandpa.agent.executor import AgentExecutor
from grandpa.agent.models import (
    AgentContext,
    AgentExecutionState,
    AgentGoal,
    AgentIntent,
    AgentPlan,
    AgentResult,
    AgentStep,
    StepStatus,
)
from grandpa.agent.verifier import StepVerifier
from grandpa.memory.service import MemoryService


class AgentRuntime:
    """The central brain orchestrating context loading, intent analysis, planning, tools, and validation."""

    def __init__(
        self,
        session_id: str | None = None,
        confirm_callback: bool | None | Any = None,
        progress_callback: bool | None | Any = None,
    ) -> None:
        self.session_id = session_id or str(uuid.uuid4())
        self.executor = AgentExecutor(
            confirm_callback=confirm_callback,
            progress_callback=progress_callback,
        )
        self.verifier = StepVerifier()

    def plan_steps(self, context: AgentContext) -> list[AgentStep]:
        """Generate plan steps based on intent and goal context."""
        intent = context.intent

        if intent == AgentIntent.PROJECT_CONTINUE:
            return [
                AgentStep(
                    id="step_1",
                    description="Load and check stored Grandpa project memory.",
                    tool="memory",
                ),
                AgentStep(
                    id="step_2",
                    description="Verify Git repository branch and commit status.",
                    tool="automation",
                ),
                AgentStep(
                    id="step_3",
                    description="Generate project continuation roadmap.",
                    tool="planner",
                ),
            ]

        elif intent == AgentIntent.PROJECT_STATUS:
            return [
                AgentStep(
                    id="step_1",
                    description="Fetch current project status summary.",
                    tool="memory",
                ),
                AgentStep(
                    id="step_2",
                    description="Verify latest completed commits.",
                    tool="automation",
                ),
            ]

        elif intent == AgentIntent.RESEARCH:
            return [
                AgentStep(
                    id="step_1",
                    description="Query Browser Intelligence for FastAPI deployment.",
                    tool="research",
                ),
                AgentStep(
                    id="step_2",
                    description="Summarize and store research outcomes.",
                    tool="memory",
                ),
            ]

        elif intent == AgentIntent.BROWSER_TASK:
            return [
                AgentStep(
                    id="step_1",
                    description="Read current browser page DOM or Accessibility Tree.",
                    tool="research",
                ),
                AgentStep(
                    id="step_2",
                    description="Perform click on browser element.",
                    tool="automation",
                ),
            ]

        elif intent == AgentIntent.AUTOMATION_TASK:
            return [
                AgentStep(
                    id="step_1",
                    description="Inspect active UI controls on the desktop screen.",
                    tool="vision",
                ),
                AgentStep(
                    id="step_2",
                    description="Execute mouse click or text typing.",
                    tool="automation",
                ),
            ]

        elif intent == AgentIntent.MEMORY_TASK:
            return [
                AgentStep(
                    id="step_1",
                    description="Retrieve or store preferred setting.",
                    tool="memory",
                ),
            ]

        elif intent == AgentIntent.PLANNING_TASK:
            return [
                AgentStep(
                    id="step_1",
                    description="Decompose goal text into structured actions.",
                    tool="planner",
                ),
            ]

        # Fallback
        return [
            AgentStep(
                id="step_1",
                description=f"Process general goal: {context.goal.raw_text}",
                tool="planner",
            )
        ]

    def run(self, goal_text: str, dry_run: bool = False) -> AgentResult:
        """Run the Agent Runtime loop to execute or preview the goal."""
        goal = AgentGoal(raw_text=goal_text, session_id=self.session_id)
        context = build_context(goal)

        # 1. Plan creation
        steps = self.plan_steps(context)
        plan = AgentPlan(plan_id=str(uuid.uuid4()), goal=goal, steps=steps)

        # Populate context selected tools
        for step in steps:
            tool_sel = self.executor.route_tool(step)
            context.selected_tools.append(tool_sel)

        if dry_run:
            return AgentResult(
                state=AgentExecutionState.IDLE,
                goal=goal,
                context=context,
                plan=plan,
                message="Preview generation completed successfully.",
            )

        # 2. Execution loop
        self.executor.report_progress("🚀 Starting Agent V1 runtime loop...")

        has_failed = False

        for step in steps:
            # Check for cancellation
            # If session is cancelled (simulated via global context/cancellation)
            try:
                result = self.executor.execute_step(step, context)
                context.execution_history.append(step)

                # Verify
                v_res = self.verifier.verify_step(step, result)
                context.verification_results.append(v_res)

                if not v_res.action_completed:
                    has_failed = True
                    break
            except Exception as exc:
                has_failed = True
                step.status = StepStatus.FAILED
                step.error = str(exc)
                context.execution_history.append(step)
                break

        # Generate message
        state = AgentExecutionState.COMPLETED
        msg = "Goal achieved successfully."

        if has_failed:
            state = AgentExecutionState.FAILED
            msg = "Execution failed during step processing."

        # Auto-remember project updates if successful continue command
        if state == AgentExecutionState.COMPLETED and context.intent == AgentIntent.PROJECT_CONTINUE:
            try:
                MemoryService.get_instance().remember_project_result(
                    project_name="Grandpa",
                    goal=goal_text,
                    status="completed",
                    latest_feature=context.project_memory.get("latest_feature") or "Memory Integration V1",
                    latest_commit=context.project_memory.get("latest_commit"),
                    next_task=context.project_memory.get("next_task") or "Grandpa Agent Runtime V1",
                    project_path=context.project_memory.get("project_path") or "D:\\Grandpa",
                )
            except Exception:
                pass

        return AgentResult(
            state=state,
            goal=goal,
            context=context,
            plan=plan,
            message=msg,
        )

    def format_output(self, result: AgentResult) -> str:
        """Format AgentResult to standard visual layout output."""
        lines = []

        # Goal
        lines.append("Goal:")
        lines.append(result.goal.raw_text)
        lines.append("")

        # Memory Used
        lines.append("Memory Used:")
        mem = result.context.project_memory
        if mem:
            for k, v in mem.items():
                if v:
                    # Format keys nicely
                    label = k.replace("_", " ").title()
                    lines.append(f"- {label}: {v}")
        else:
            lines.append("- No project memory found.")

        # User preferences if accessed
        prefs = result.context.preferences
        if prefs:
            lines.append(f"- Preferences: Browser={prefs.get('default_browser') or 'Chrome'}, Shell={prefs.get('preferred_shell') or 'PowerShell'}")
        lines.append("")

        # Plan
        lines.append("Plan:")
        if result.plan:
            for idx, step in enumerate(result.plan.steps, 1):
                lines.append(f"{idx}. {step.description} [Tool: {step.tool}]")
        lines.append("")

        # Execution
        lines.append("Execution:")
        if result.state == AgentExecutionState.IDLE:
            lines.append("- (Dry run preview mode, no steps executed)")
        else:
            for step in result.context.execution_history:
                status_label = step.status.value.upper()
                lines.append(f"- {step.description} : {status_label}")
                if step.error:
                    lines.append(f"  Error: {step.error}")
        lines.append("")

        # Verification
        lines.append("Verification:")
        if not result.context.verification_results:
            lines.append("- Pending verification")
        else:
            for idx, v_res in enumerate(result.context.verification_results, 1):
                status_str = "SUCCESS" if v_res.action_completed else "FAILED"
                lines.append(f"- Step {idx} verification: {status_str}")
                if v_res.failures:
                    lines.append(f"  Failures: {', '.join(v_res.failures)}")
        lines.append("")

        # Next Actions
        lines.append("Next Actions:")
        if result.state == AgentExecutionState.COMPLETED:
            if result.context.intent == AgentIntent.PROJECT_CONTINUE:
                ntask = result.context.project_memory.get("next_task") or "Memory Integration V1"
                lines.append(f"- Recommended next action: proceed with task '{ntask}'")
            else:
                lines.append("- Goal completed. No next actions recommended.")
        elif result.state == AgentExecutionState.FAILED:
            lines.append("- Bounded recovery failed. Check logs and retry with manual steps.")
        else:
            lines.append("- Proceed with plan execution.")

        return "\n".join(lines)
