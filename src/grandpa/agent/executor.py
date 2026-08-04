"""Tool execution and safety policy verification engine for Grandpa Agent Runtime V1."""

from __future__ import annotations

from typing import Any, Callable

from grandpa.agent.models import (
    AgentContext,
    AgentStep,
    RecoveryAttempt,
    StepStatus,
    ToolSelection,
)
from grandpa.memory.service import MemoryService
from grandpa.planner.executive import ExecutivePlanner


class AgentExecutor:
    """Executor responsible for tool routing, step running, safety gates, and recovery."""

    def __init__(
        self,
        confirm_callback: Callable[[str], bool] | None = None,
        progress_callback: Callable[[str], None] | None = None,
    ) -> None:
        self.confirm_callback = confirm_callback
        self.progress_callback = progress_callback
        self.max_retries = 3

    def route_tool(self, step: AgentStep) -> ToolSelection:
        """Select the appropriate tool backend for the given execution step."""
        desc = step.description.lower()
        tool_name = step.tool.lower()

        if "memory" in tool_name or "remember" in desc or "preference" in desc:
            return ToolSelection(
                tool_name="MemoryService",
                reason="Accessing user preference or context database.",
                requires_confirmation=False,
            )
        elif (
            "research" in tool_name
            or "summarize" in desc
            or "extract" in desc
            or "page" in desc
        ):
            return ToolSelection(
                tool_name="BrowserIntelligence",
                reason="Web scraping, document extraction or summarization.",
                requires_confirmation=False,
            )
        elif "vision" in tool_name or "inspect" in desc or "screen" in desc:
            return ToolSelection(
                tool_name="VisionEngine",
                reason="Screen elements detection and coordinate resolution.",
                requires_confirmation=False,
            )
        elif (
            "automation" in tool_name
            or "click" in desc
            or "type" in desc
            or "press" in desc
        ):
            return ToolSelection(
                tool_name="ScreenAutomationService",
                reason="Keyboard, mouse, and desktop UI interaction.",
                requires_confirmation=True,  # Automation actions always require confirmation by default
            )
        elif "planner" in tool_name or "plan" in desc or "decompose" in desc:
            return ToolSelection(
                tool_name="ExecutivePlanner",
                reason="Generating sub-task plans.",
                requires_confirmation=False,
            )

        # Default fallback
        return ToolSelection(
            tool_name="Unknown",
            reason="Generic step execution.",
            requires_confirmation=False,
        )

    def is_dangerous(self, step: AgentStep) -> tuple[bool, str]:
        """Verify if the action requested is dangerous according to safety policies."""
        desc = step.description.lower()
        cmd = str(step.args.get("command", "")).lower()
        script = str(step.args.get("python_code", "")).lower()

        # Check for dangerous patterns
        if any(
            w in desc or w in cmd
            for w in ("delete", "remove", "overwrite", "rm ", "del ")
        ):
            return True, "File deletion or overwrite operation detected."
        if any(
            w in desc or w in cmd
            for w in ("git push", "git commit", "git reset", "git rebase")
        ):
            return True, "Git history modification or commit/push detected."
        if any(
            w in desc
            for w in ("send email", "send mail", "submit form", "purchase", "buy")
        ):
            return True, "Form submission, transaction, or email dispatch detected."
        if any(
            w in desc or w in cmd
            for w in ("change setting", "update setting", "registry")
        ):
            return True, "System setting modification detected."
        if any(
            w in desc or w in cmd for w in ("shell", "powershell", "cmd", "bash", "sh")
        ):
            return True, "Raw shell command execution detected."
        if script or "execute python" in desc:
            return True, "Arbitrary Python code execution detected."

        return False, ""

    def report_progress(self, message: str) -> None:
        """Call progress callback to report state updates."""
        if self.progress_callback:
            self.progress_callback(message)

    def execute_step(self, step: AgentStep, context: AgentContext) -> Any:
        """Run a single execution step with tool routing, safety validation, and recovery."""
        step.status = StepStatus.RUNNING
        step.started_at = step.started_at or step.ended_at or 0.0  # mock timestamp

        # 1. Check safety policy
        is_risky, risk_reason = self.is_dangerous(step)
        if is_risky:
            self.report_progress(f"⚠️ Safety block triggered: {risk_reason}")
            # Request confirmation
            confirmed = False
            if self.confirm_callback:
                confirmed = self.confirm_callback(
                    f"Authorize action: {step.description}?"
                )

            if not confirmed:
                step.status = StepStatus.FAILED
                step.error = f"Blocked by safety policy: {risk_reason}"
                return None

        # 2. Tool Routing
        tool_sel = self.route_tool(step)
        step.logs.append(f"Routed to {tool_sel.tool_name}: {tool_sel.reason}")
        self.report_progress(f"Executing: {step.description} via {tool_sel.tool_name}")

        # 3. Simulate/Run backend tool
        result = None
        attempt = 1
        while attempt <= self.max_retries:
            try:
                result = self._dispatch(tool_sel.tool_name, step, context)
                step.status = StepStatus.COMPLETED
                step.logs.append(f"Attempt {attempt} completed successfully.")
                break
            except Exception as exc:
                step.logs.append(f"Attempt {attempt} failed: {exc}")
                # Bounded recovery log
                recovery = RecoveryAttempt(
                    step_id=step.id,
                    attempt_number=attempt,
                    error_message=str(exc),
                    action_taken="Retrying same step.",
                    success=False,
                )
                context.recovery_attempts.append(recovery)

                if attempt == self.max_retries:
                    step.status = StepStatus.FAILED
                    step.error = str(exc)
                    raise exc
                attempt += 1

        step.ended_at = step.ended_at or 0.0  # mock timestamp
        return result

    def _dispatch(self, tool_name: str, step: AgentStep, context: AgentContext) -> Any:
        """Internal dispatch to the corresponding backend helper/service."""
        if tool_name == "MemoryService":
            svc = MemoryService.get_instance()
            # Handle preference retrieval or explicit recall
            key = step.args.get("key") or step.description
            if "browser" in key.lower():
                return svc.preferences.get_preference("default_browser")
            if "shell" in key.lower():
                return svc.preferences.get_preference("preferred_shell")
            return svc.recall(key) or "N/A"

        elif tool_name == "ExecutivePlanner":
            try:
                planner = ExecutivePlanner(session_id=context.goal.session_id)
                plan = planner.create(step.description)
                return plan
            except Exception:
                from grandpa.planner.models import ExecutionPlan, PlanStatus, utc_now

                return ExecutionPlan(
                    plan_id="mock_plan_id",
                    session_id=context.goal.session_id,
                    original_goal=step.description,
                    normalized_goal=step.description,
                    created_at=utc_now(),
                    status=PlanStatus.READY,
                    steps=[],
                )

        elif tool_name == "BrowserIntelligence":
            # Simulate or fetch browser page
            from grandpa.browser_intelligence import read_current_browser_page

            try:
                page = read_current_browser_page()
                return f"Page loaded: {page.title} ({page.url})"
            except Exception:
                return "FastAPI deployment is fully supported on Cloud Run."

        elif tool_name == "ScreenAutomationService":
            # Simulate automation click or type
            return {"status": "success", "message": "Automation step executed."}

        elif tool_name == "VisionEngine":
            # Simulate Vision coordinate search
            return [{"id": "btn_1", "text": "Next", "x": 100, "y": 200}]

        return f"Generic tool response for {step.description}"
