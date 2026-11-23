"""WorkflowEngine — executes a WorkflowGraph against a GrandpaSystem."""

# CLI surface: `grandpa workflow list/validate/run` (grandpa.cli.workflow_cmd)
# runs YAML workflows whose steps are catalogued actions (NodeType.ACTION).
# Agent/tool/condition/loop nodes are the older TOML pipelines.

from __future__ import annotations

import concurrent.futures
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from grandpa.core.events import EventBus, EventType
from grandpa.workflow.graph import WorkflowGraph
from grandpa.workflow.types import (
    NodeType,
    WorkflowNode,
    WorkflowResult,
    WorkflowStepResult,
)

_DRY_RUN = "__workflow_dry_run__"
_CONFIRM = "__workflow_confirm__"

# A failure with one of these codes would fail the same way again (or would
# ask the person a second time), so it is never retried.
_NOT_RETRIED = frozenset(
    {
        "unknown_action",
        "invalid_parameters",
        "confirmation_required",
        "confirmation_declined",
        "blocked",
        "implementation_unavailable",
        "timeout",
    }
)


class WorkflowEngine:
    """Execute DAG-based workflows.

    Sequential nodes run in topological order. Parallel-eligible nodes
    (same execution stage, no inter-dependencies) run via ThreadPoolExecutor.
    Condition nodes evaluate expressions against prior step outputs.
    Loop nodes use LoopGuard from Phase 14.3.
    """

    def __init__(
        self,
        *,
        bus: Optional[EventBus] = None,
        max_parallel: int = 4,
        default_node_timeout: int = 300,
    ) -> None:
        self._bus = bus
        self._max_parallel = max_parallel
        self._default_node_timeout = default_node_timeout

    def run(
        self,
        graph: WorkflowGraph,
        system: Any = None,  # GrandpaSystem
        *,
        initial_input: str = "",
        context: Optional[Dict[str, Any]] = None,
        variables: Optional[Dict[str, Any]] = None,
        dry_run: bool = False,
        confirm_callback: Optional[Callable[..., bool]] = None,
    ) -> WorkflowResult:
        """Execute a workflow graph end-to-end.

        For action steps: ``variables`` override the file's ``vars``;
        ``dry_run`` describes each step without performing anything; and
        ``confirm_callback`` is handed to the action executor, which asks it
        before any step whose catalogue entry needs confirmation. Without one,
        such a step is refused -- a workflow never confirms on a person's behalf.
        """
        valid, msg = graph.validate()
        if not valid:
            return WorkflowResult(
                workflow_name=graph.name,
                success=False,
                final_output=f"Invalid workflow: {msg}",
            )

        t0 = time.time()
        if self._bus:
            self._bus.publish(
                EventType.WORKFLOW_START,
                {"workflow": graph.name},
            )

        # State: outputs keyed by node_id
        outputs: Dict[str, str] = {"_input": initial_input}
        ctx = dict(context or {})
        ctx["vars"] = {**graph.variables, **(variables or {})}
        ctx["steps"] = {}
        ctx[_DRY_RUN] = dry_run
        ctx[_CONFIRM] = confirm_callback
        all_steps: List[WorkflowStepResult] = []
        success = True

        stages = graph.execution_stages()
        for stage in stages:
            if len(stage) == 1:
                # Sequential execution
                step = self._execute_node(
                    graph.get_node(stage[0]),  # type: ignore[arg-type]
                    outputs,
                    ctx,
                    system,
                    graph,
                )
                all_steps.append(step)
                outputs[stage[0]] = step.output
                if not step.success:
                    node = graph.get_node(stage[0])
                    if node is not None and node.continue_on_error:
                        continue
                    success = False
                    break
            else:
                # Parallel execution
                with concurrent.futures.ThreadPoolExecutor(
                    max_workers=min(len(stage), self._max_parallel),
                ) as pool:
                    futures = {
                        pool.submit(
                            self._execute_node,
                            graph.get_node(nid),
                            dict(outputs),
                            dict(ctx),
                            system,
                            graph,
                        ): nid
                        for nid in stage
                    }
                    for future in concurrent.futures.as_completed(futures):
                        nid = futures[future]
                        try:
                            step = future.result(
                                timeout=self._default_node_timeout,
                            )
                        except Exception as exc:
                            step = WorkflowStepResult(
                                node_id=nid,
                                success=False,
                                output=f"Node execution error: {exc}",
                            )
                        all_steps.append(step)
                        outputs[nid] = step.output
                        if not step.success:
                            success = False

            if not success:
                break

        total = time.time() - t0
        # Final output is the output of the last executed node
        final_output = all_steps[-1].output if all_steps else ""

        if self._bus:
            self._bus.publish(
                EventType.WORKFLOW_END,
                {"workflow": graph.name, "success": success, "duration": total},
            )

        return WorkflowResult(
            workflow_name=graph.name,
            success=success,
            steps=all_steps,
            final_output=final_output,
            total_duration_seconds=total,
        )

    def _execute_node(
        self,
        node: WorkflowNode,
        outputs: Dict[str, str],
        ctx: Dict[str, Any],
        system: Any,
        graph: WorkflowGraph,
    ) -> WorkflowStepResult:
        """Execute a single workflow node."""
        if self._bus:
            self._bus.publish(
                EventType.WORKFLOW_NODE_START,
                {"node": node.id, "type": node.node_type.value},
            )

        t0 = time.time()
        try:
            if node.node_type == NodeType.AGENT:
                result = self._run_agent_node(node, outputs, system, graph)
            elif node.node_type == NodeType.ACTION:
                result = self._run_action_node(node, ctx)
            elif node.node_type == NodeType.TOOL:
                result = self._run_tool_node(node, outputs, system)
            elif node.node_type == NodeType.CONDITION:
                result = self._run_condition_node(node, outputs)
            elif node.node_type == NodeType.TRANSFORM:
                result = self._run_transform_node(node, outputs)
            elif node.node_type == NodeType.LOOP:
                result = self._run_loop_node(node, outputs, system, graph)
            else:
                result = WorkflowStepResult(
                    node_id=node.id,
                    success=False,
                    output=f"Unknown node type: {node.node_type}",
                )
        except Exception as exc:
            result = WorkflowStepResult(
                node_id=node.id,
                success=False,
                output=f"Node error: {exc}",
            )

        result.duration_seconds = time.time() - t0

        if self._bus:
            self._bus.publish(
                EventType.WORKFLOW_NODE_END,
                {
                    "node": node.id,
                    "success": result.success,
                    "duration": result.duration_seconds,
                },
            )

        return result

    def _get_node_input(
        self,
        node: WorkflowNode,
        outputs: Dict[str, str],
        graph: WorkflowGraph,
    ) -> str:
        """Get input for a node from predecessor outputs."""
        preds = graph.predecessors(node.id)
        if preds:
            parts = [outputs.get(p, "") for p in preds if outputs.get(p)]
            return "\n\n".join(parts) if parts else outputs.get("_input", "")
        return outputs.get("_input", "")

    def _run_agent_node(
        self,
        node: WorkflowNode,
        outputs: Dict[str, str],
        system: Any,
        graph: WorkflowGraph,
    ) -> WorkflowStepResult:
        """Execute an agent node."""
        input_text = self._get_node_input(node, outputs, graph)
        if system is None:
            return WorkflowStepResult(
                node_id=node.id,
                success=False,
                output="No system available for agent execution.",
            )
        try:
            result = system.ask(
                input_text,
                agent=node.agent or None,
                tools=node.tools or None,
            )
            return WorkflowStepResult(
                node_id=node.id,
                success=True,
                output=result.get("content", ""),
            )
        except Exception as exc:
            return WorkflowStepResult(
                node_id=node.id,
                success=False,
                output=f"Agent error: {exc}",
            )

    def _run_action_node(
        self,
        node: WorkflowNode,
        ctx: Dict[str, Any],
    ) -> WorkflowStepResult:
        """Run one catalogued action through the action layer's executor.

        The executor is the only place an action runs: it validates, asks for
        confirmation when the catalogue says so, and audits. This method adds
        only what a routine needs around it -- ``when``, templates, retries and
        a timeout -- and never touches the confirmation decision.
        """
        from grandpa.action_layer.catalogue import get as catalogue_get
        from grandpa.workflow.expressions import (
            ExpressionError,
            evaluate_condition,
            render,
        )

        steps: Dict[str, Any] = ctx.setdefault("steps", {})
        dry_run = bool(ctx.get(_DRY_RUN))
        view = {"vars": ctx.get("vars", {}), "steps": steps}
        meta: Dict[str, Any] = {"action": node.action}

        if node.when:
            if dry_run and "steps." in node.when:
                meta["when"] = f"decided at run time: {node.when}"
            else:
                try:
                    should_run = evaluate_condition(node.when, view)
                except ExpressionError as exc:
                    return self._record(
                        node, steps, False, f"Cannot read 'when': {exc}", meta
                    )
                if not should_run:
                    meta["skipped"] = True
                    return self._record(
                        node, steps, True, f"Skipped: {node.when} is false.", meta
                    )

        params = render(node.params, view)
        meta["params"] = params

        try:
            spec = catalogue_get(node.action)
        except KeyError:
            return self._record(
                node, steps, False, f"No catalogued action {node.action!r}.", meta
            )
        meta["risk"] = spec.risk.value
        meta["needs_confirmation"] = spec.requires_confirmation

        if dry_run:
            meta["dry_run"] = True
            shown = f" {params}" if params else ""
            ask = " (will ask you first)" if spec.requires_confirmation else ""
            return self._record(
                node, steps, True, f"Would run {node.action}{shown}{ask}", meta
            )

        attempts = node.retries + 1
        result: Any = None
        for attempt in range(1, attempts + 1):
            result = self._execute_with_timeout(node, spec, params, ctx.get(_CONFIRM))
            meta["attempts"] = attempt
            if result.success or (result.error or "") in _NOT_RETRIED:
                break
            if attempt < attempts and node.retry_delay_seconds:
                time.sleep(node.retry_delay_seconds)

        meta["error"] = result.error
        meta["data"] = dict(result.data)
        return self._record(
            node,
            steps,
            bool(result.success),
            result.message or (result.error or ""),
            meta,
        )

    @staticmethod
    def _execute_with_timeout(
        node: WorkflowNode,
        spec: Any,
        params: Dict[str, Any],
        confirm_callback: Optional[Callable[..., bool]],
    ) -> Any:
        """Call the executor, giving up after ``node.timeout_seconds``.

        Time a person spends answering a confirmation prompt does not count:
        the clock only runs while the action itself is working. A step that
        times out is reported as failed and is not retried, because the
        abandoned call may still finish on its own thread.
        """
        from grandpa.action_layer import executor
        from grandpa.action_layer.model import ActionRequest, ActionResult, Origin

        asking = threading.Event()
        asked_for = [0.0]

        def confirm(*args: Any) -> bool:
            asking.set()
            started = time.monotonic()
            try:
                return bool(confirm_callback(*args))  # type: ignore[misc]
            finally:
                asked_for[0] += time.monotonic() - started
                asking.clear()

        request = ActionRequest(
            action=node.action,
            parameters=params,
            origin=Origin.SKILL,
            risk=spec.risk,
            requires_confirmation=spec.requires_confirmation,
        )
        box: Dict[str, Any] = {}

        def work() -> None:
            try:
                box["result"] = executor.execute(
                    request, confirm if confirm_callback is not None else None
                )
            except Exception as exc:  # pragma: no cover - execute never raises
                box["result"] = ActionResult.failed(
                    "execution_failed", message=str(exc)
                )

        worker = threading.Thread(
            target=work, name=f"grandpa-workflow-{node.id}", daemon=True
        )
        started = time.monotonic()
        worker.start()
        while worker.is_alive():
            worker.join(0.05)
            if asking.is_set():
                continue
            if time.monotonic() - started - asked_for[0] > node.timeout_seconds:
                return ActionResult.failed(
                    "timeout",
                    message=(
                        f"{node.action} did not finish within "
                        f"{node.timeout_seconds:g} seconds."
                    ),
                )
        return box["result"]

    @staticmethod
    def _record(
        node: WorkflowNode,
        steps: Dict[str, Any],
        ok: bool,
        message: str,
        meta: Dict[str, Any],
    ) -> WorkflowStepResult:
        steps[node.id] = {
            "ok": ok,
            "message": message,
            "data": meta.get("data", {}),
            "skipped": bool(meta.get("skipped")),
        }
        return WorkflowStepResult(
            node_id=node.id, success=ok, output=message, metadata=meta
        )

    def _run_tool_node(
        self,
        node: WorkflowNode,
        outputs: Dict[str, str],
        system: Any,
    ) -> WorkflowStepResult:
        """Execute a tool node."""
        tool_name = node.config.get("tool_name", "")
        tool_args = node.config.get("tool_args", "{}")
        if system and system.tool_executor:
            from grandpa.core.types import ToolCall

            tc = ToolCall(id=f"wf_{node.id}", name=tool_name, arguments=tool_args)
            tr = system.tool_executor.execute(tc)
            return WorkflowStepResult(
                node_id=node.id,
                success=tr.success,
                output=tr.content,
            )
        return WorkflowStepResult(
            node_id=node.id,
            success=False,
            output="No tool executor available.",
        )

    def _run_condition_node(
        self,
        node: WorkflowNode,
        outputs: Dict[str, str],
    ) -> WorkflowStepResult:
        """Evaluate a condition expression against outputs."""
        expr = node.condition_expr
        if not expr:
            return WorkflowStepResult(
                node_id=node.id,
                success=True,
                output="true",
            )
        # Simple expression evaluation — check if key exists and is truthy
        # Supports: "node_id.success", "node_id.output contains 'text'"
        try:
            result = str(eval(expr, {"__builtins__": {}}, {"outputs": outputs}))  # noqa: S307
        except Exception:
            result = "false"
        return WorkflowStepResult(
            node_id=node.id,
            success=True,
            output=result,
        )

    def _run_transform_node(
        self,
        node: WorkflowNode,
        outputs: Dict[str, str],
    ) -> WorkflowStepResult:
        """Apply a text transformation."""
        expr = node.transform_expr
        preds = [outputs.get(p, "") for p in outputs if p != "_input"]
        combined = "\n\n".join(preds) if preds else ""
        if expr == "concatenate":
            return WorkflowStepResult(node_id=node.id, output=combined)
        if expr == "first_line":
            return WorkflowStepResult(
                node_id=node.id,
                output=combined.split("\n")[0] if combined else "",
            )
        return WorkflowStepResult(node_id=node.id, output=combined)

    def _run_loop_node(
        self,
        node: WorkflowNode,
        outputs: Dict[str, str],
        system: Any,
        graph: WorkflowGraph,
    ) -> WorkflowStepResult:
        """Execute a loop node (re-runs agent until condition or max iterations)."""
        input_text = self._get_node_input(node, outputs, graph)
        max_iter = node.max_iterations
        last_output = input_text
        for i in range(max_iter):
            if system:
                result = system.ask(last_output, agent=node.agent or None)
                last_output = result.get("content", "")
                # Check if loop should terminate
                if (
                    node.condition_expr
                    and node.condition_expr.lower() in last_output.lower()
                ):
                    break
            else:
                break
        return WorkflowStepResult(
            node_id=node.id,
            success=True,
            output=last_output,
            metadata={"iterations": i + 1},
        )


__all__ = ["WorkflowEngine"]
