"""OrchestratorAgent — multi-turn agent with tool-calling loop.

Supports two modes:

- **function_calling** (default): Uses OpenAI-format tool definitions and
  parses ``tool_calls`` from the engine response.
- **structured**: Uses a THOUGHT/TOOL/INPUT/FINAL_ANSWER text format
  (like ReAct) with a canonical system prompt from the orchestrator
  prompt registry.  This is the format used by the SFT/GRPO training
  pipelines, making the Orchestrator a distinctive trainable agent type.
"""

from __future__ import annotations

import concurrent.futures
import json
import os
import re
import sqlite3
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, List, Optional

from grandpa.agents._stubs import AgentContext, AgentResult, ToolUsingAgent
from grandpa.core.config import DEFAULT_CONFIG_DIR
from grandpa.core.events import EventBus
from grandpa.core.registry import AgentRegistry
from grandpa.core.types import Message, Role, ToolCall, ToolResult
from grandpa.engine._stubs import InferenceEngine
from grandpa.tools._stubs import BaseTool


@AgentRegistry.register("orchestrator")
class OrchestratorAgent(ToolUsingAgent):
    """Multi-turn agent that routes between tools and the LLM.

    Implements a tool-calling loop:
    1. Send messages with tool definitions to the engine.
    2. If the response contains tool_calls, execute them and loop.
    3. If no tool_calls, return the final answer.
    4. Stop after ``max_turns`` iterations.

    In **structured** mode the agent instead uses a
    ``THOUGHT: / TOOL: / INPUT: / FINAL_ANSWER:`` text protocol
    identical to the format used by the orchestrator SFT/GRPO
    training pipelines.
    """

    agent_id = "orchestrator"
    _default_temperature = 0.7
    _default_max_tokens = 1024
    _default_max_turns = 10

    def __init__(
        self,
        engine: InferenceEngine,
        model: str,
        *,
        tools: Optional[List[BaseTool]] = None,
        bus: Optional[EventBus] = None,
        max_turns: Optional[int] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        mode: str = "function_calling",
        system_prompt: Optional[str] = None,
        parallel_tools: bool = True,
        interactive: bool = False,
        confirm_callback=None,
    ) -> None:
        super().__init__(
            engine,
            model,
            tools=tools,
            bus=bus,
            max_turns=max_turns,
            temperature=temperature,
            max_tokens=max_tokens,
            interactive=interactive,
            confirm_callback=confirm_callback,
        )
        self._mode = mode
        self._system_prompt = system_prompt
        self._parallel_tools = parallel_tools

    def run(
        self,
        input: str,
        context: Optional[AgentContext] = None,
        **kwargs: Any,
    ) -> AgentResult:
        if self._mode == "structured":
            return self._run_structured(input, context, **kwargs)
        return self._run_function_calling(input, context, **kwargs)

    # ------------------------------------------------------------------
    # Structured mode (THOUGHT/TOOL/INPUT/FINAL_ANSWER)
    # ------------------------------------------------------------------

    def _run_structured(
        self,
        input: str,
        context: Optional[AgentContext] = None,
        **kwargs: Any,
    ) -> AgentResult:
        self._emit_turn_start(input)

        # Build system prompt
        if self._system_prompt:
            sys_prompt = self._system_prompt
        else:
            from grandpa.learning.intelligence.orchestrator.prompt_registry import (
                build_system_prompt,
            )

            sys_prompt = build_system_prompt(tools=self._tools)

        messages = self._build_messages(input, context, system_prompt=sys_prompt)

        all_tool_results: list[ToolResult] = []
        turns = 0

        for _turn in range(self._max_turns):
            turns += 1

            if self._loop_guard:
                messages = self._loop_guard.compress_context(messages)

            result = self._generate(messages)
            content = result.get("content", "")

            parsed = self._parse_structured_response(content)

            # FINAL_ANSWER -> done
            if parsed["final_answer"]:
                self._emit_turn_end(turns=turns)
                return AgentResult(
                    content=parsed["final_answer"],
                    tool_results=all_tool_results,
                    turns=turns,
                )

            # TOOL -> execute
            if parsed["tool"]:
                messages.append(Message(role=Role.ASSISTANT, content=content))

                tool_call = ToolCall(
                    id=f"orch_{turns}",
                    name=parsed["tool"],
                    arguments=parsed["input"] or "{}",
                )
                tool_result = self._executor.execute(tool_call)
                all_tool_results.append(tool_result)

                observation = f"Observation: {tool_result.content}"
                messages.append(Message(role=Role.USER, content=observation))
                continue

            # Neither -> treat content as final answer
            self._emit_turn_end(turns=turns)
            return AgentResult(
                content=content,
                tool_results=all_tool_results,
                turns=turns,
            )

        # Max turns exceeded
        return self._max_turns_result(all_tool_results, turns)

    @staticmethod
    def _parse_structured_response(text: str) -> dict:
        """Parse THOUGHT/TOOL/INPUT/FINAL_ANSWER from model output."""
        result = {
            "thought": "",
            "tool": "",
            "input": "",
            "final_answer": "",
        }

        thought_match = re.search(
            r"THOUGHT:\s*(.+?)(?=\nTOOL:|\nFINAL[_ ]?ANSWER:|\Z)",
            text,
            re.DOTALL | re.IGNORECASE,
        )
        if thought_match:
            result["thought"] = thought_match.group(1).strip()

        final_match = re.search(
            r"FINAL[_ ]?ANSWER:\s*(.+)",
            text,
            re.DOTALL | re.IGNORECASE,
        )
        if final_match:
            result["final_answer"] = final_match.group(1).strip()
            return result

        tool_match = re.search(r"TOOL:\s*(.+)", text, re.IGNORECASE)
        if tool_match:
            result["tool"] = tool_match.group(1).strip()

        input_match = re.search(
            r"INPUT:\s*(.+?)(?=\nTHOUGHT:|\nTOOL:|\nFINAL|\Z)",
            text,
            re.DOTALL | re.IGNORECASE,
        )
        if input_match:
            result["input"] = input_match.group(1).strip()

        return result

    # ------------------------------------------------------------------
    # Function-calling mode (original behaviour)
    # ------------------------------------------------------------------

    def _run_function_calling(
        self,
        input: str,
        context: Optional[AgentContext] = None,
        **kwargs: Any,
    ) -> AgentResult:
        self._emit_turn_start(input)

        # Build initial messages
        messages = self._build_messages(input, context)

        # Get OpenAI-format tool definitions
        openai_tools = self._executor.get_openai_tools() if self._tools else []

        all_tool_results: list[ToolResult] = []
        turns = 0
        total_prompt_tokens = 0
        total_completion_tokens = 0

        for _turn in range(self._max_turns):
            turns += 1

            if self._loop_guard:
                messages = self._loop_guard.compress_context(messages)

            # Build generate kwargs
            gen_kwargs: dict[str, Any] = {}
            if openai_tools:
                gen_kwargs["tools"] = openai_tools

            result = self._generate(messages, **gen_kwargs)

            # Accumulate token usage
            usage = result.get("usage", {})
            total_prompt_tokens += usage.get("prompt_tokens", 0)
            total_completion_tokens += usage.get("completion_tokens", 0)

            content = result.get("content", "")
            raw_tool_calls = result.get("tool_calls", [])

            # No tool calls -> check continuation, then final answer
            if not raw_tool_calls:
                content = self._check_continuation(result, messages)
                content = self._strip_think_tags(content)
                self._emit_turn_end(turns=turns, content_length=len(content))
                return AgentResult(
                    content=content,
                    tool_results=all_tool_results,
                    turns=turns,
                    metadata={
                        "prompt_tokens": total_prompt_tokens,
                        "completion_tokens": total_completion_tokens,
                        "total_tokens": total_prompt_tokens + total_completion_tokens,
                    },
                )

            # Build ToolCall objects from raw dicts
            tool_calls = [
                ToolCall(
                    id=tc.get("id", f"call_{i}"),
                    name=tc.get("name", ""),
                    arguments=tc.get("arguments", "{}"),
                )
                for i, tc in enumerate(raw_tool_calls)
            ]

            # Append assistant message with tool calls
            messages.append(
                Message(
                    role=Role.ASSISTANT,
                    content=content,
                    tool_calls=tool_calls,
                )
            )

            # Execute each tool (with loop guard check) and append results
            if self._parallel_tools and len(tool_calls) > 1:
                # Parallel execution
                def _exec_tool(tc: ToolCall) -> tuple:
                    if self._loop_guard:
                        verdict = self._loop_guard.check_call(
                            tc.name,
                            tc.arguments,
                        )
                        if verdict.blocked:
                            return tc, ToolResult(
                                tool_name=tc.name,
                                content=f"Loop guard: {verdict.reason}",
                                success=False,
                            )
                    return tc, self._executor.execute(tc)

                with concurrent.futures.ThreadPoolExecutor(
                    max_workers=len(tool_calls),
                ) as pool:
                    futures = {pool.submit(_exec_tool, tc): tc for tc in tool_calls}
                    results_map: dict[int, tuple] = {}
                    for future in concurrent.futures.as_completed(futures):
                        tc_orig = futures[future]
                        results_map[id(tc_orig)] = future.result()

                # Append results in original order
                for tc in tool_calls:
                    _, tool_result = results_map[id(tc)]
                    all_tool_results.append(tool_result)
                    messages.append(
                        Message(
                            role=Role.TOOL,
                            content=tool_result.content,
                            tool_call_id=tc.id,
                            name=tc.name,
                        )
                    )
            else:
                # Sequential execution
                for tc in tool_calls:
                    # Loop guard check before execution
                    if self._loop_guard:
                        verdict = self._loop_guard.check_call(
                            tc.name,
                            tc.arguments,
                        )
                        if verdict.blocked:
                            tool_result = ToolResult(
                                tool_name=tc.name,
                                content=f"Loop guard: {verdict.reason}",
                                success=False,
                            )
                            all_tool_results.append(tool_result)
                            messages.append(
                                Message(
                                    role=Role.TOOL,
                                    content=tool_result.content,
                                    tool_call_id=tc.id,
                                    name=tc.name,
                                )
                            )
                            continue

                    tool_result = self._executor.execute(tc)
                    all_tool_results.append(tool_result)

                    # Append tool response message
                    messages.append(
                        Message(
                            role=Role.TOOL,
                            content=tool_result.content,
                            tool_call_id=tc.id,
                            name=tc.name,
                        )
                    )

        # Max turns exceeded
        final_content = self._strip_think_tags(content) if content else ""
        self._emit_turn_end(turns=turns, max_turns_exceeded=True)
        return AgentResult(
            content=final_content or "Maximum turns reached without a final answer.",
            tool_results=all_tool_results,
            turns=turns,
            metadata={
                "max_turns_exceeded": True,
                "prompt_tokens": total_prompt_tokens,
                "completion_tokens": total_completion_tokens,
                "total_tokens": total_prompt_tokens + total_completion_tokens,
            },
        )


DEFAULT_MULTI_AGENT_DB = DEFAULT_CONFIG_DIR / "agents" / "multi_agent.db"


@dataclass(frozen=True)
class MultiAgentTask:
    """Persisted multi-agent collaboration task."""

    task_id: str
    user_request: str
    participating_agents: tuple[str, ...]
    status: str
    observations: dict[str, Any]
    outputs: list[dict[str, Any]]
    summary: str
    created_at: float
    updated_at: float
    completed_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["participating_agents"] = list(self.participating_agents)
        return payload


class MultiAgentTaskStore:
    """SQLite persistence for deterministic multi-agent tasks."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path or os.environ.get("GRANDPA_MULTI_AGENT_DB") or DEFAULT_MULTI_AGENT_DB)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS multi_agent_tasks (
                    task_id TEXT PRIMARY KEY,
                    user_request TEXT NOT NULL,
                    participating_agents TEXT NOT NULL,
                    status TEXT NOT NULL,
                    observations TEXT NOT NULL,
                    outputs TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    completed_at REAL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS multi_agent_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    agent_id TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    status TEXT NOT NULL,
                    message TEXT NOT NULL,
                    data TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_multi_agent_tasks_updated "
                "ON multi_agent_tasks(updated_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_multi_agent_events_task "
                "ON multi_agent_events(task_id, timestamp)"
            )

    def save(self, task: MultiAgentTask) -> MultiAgentTask:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO multi_agent_tasks(
                    task_id, user_request, participating_agents, status,
                    observations, outputs, summary, created_at, updated_at, completed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    participating_agents=excluded.participating_agents,
                    status=excluded.status,
                    observations=excluded.observations,
                    outputs=excluded.outputs,
                    summary=excluded.summary,
                    updated_at=excluded.updated_at,
                    completed_at=excluded.completed_at
                """,
                (
                    task.task_id,
                    task.user_request,
                    json.dumps(list(task.participating_agents), ensure_ascii=True),
                    task.status,
                    json.dumps(task.observations, ensure_ascii=True),
                    json.dumps(task.outputs, ensure_ascii=True),
                    task.summary,
                    task.created_at,
                    task.updated_at,
                    task.completed_at,
                ),
            )
        return task

    def add_event(
        self,
        task_id: str,
        agent_id: str,
        phase: str,
        status: str,
        message: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO multi_agent_events(task_id, timestamp, agent_id, phase, status, message, data)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (task_id, time.time(), agent_id, phase, status, message, json.dumps(data or {}, ensure_ascii=True)),
            )

    def list(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM multi_agent_tasks
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [_task_from_row(row).to_dict() for row in rows]

    def get(self, task_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM multi_agent_tasks WHERE task_id = ?", (task_id,)).fetchone()
        return _task_from_row(row).to_dict() if row else None

    def events(self, task_id: str, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM multi_agent_events
                WHERE task_id = ?
                ORDER BY timestamp ASC
                LIMIT ?
                """,
                (task_id, limit),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "task_id": row["task_id"],
                "timestamp": row["timestamp"],
                "agent_id": row["agent_id"],
                "phase": row["phase"],
                "status": row["status"],
                "message": row["message"],
                "data": _loads_dict(row["data"]),
            }
            for row in rows
        ]

    def count(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM multi_agent_tasks").fetchone()
        return int(row["count"] if row else 0)


def orchestrate_goal(user_request: str, *, store: MultiAgentTaskStore | None = None) -> MultiAgentTask:
    """Run a deterministic multi-agent collaboration and persist the result."""

    from grandpa.agents.context import build_shared_context
    from grandpa.agents.registry import select_agents_for_goal

    task_store = store or MultiAgentTaskStore()
    context = build_shared_context(user_request)
    selected_agents = select_agents_for_goal(user_request)
    now = time.time()
    task = MultiAgentTask(
        task_id=context.task_id,
        user_request=user_request.strip(),
        participating_agents=tuple(agent.agent_id for agent in selected_agents),
        status="running",
        observations=context.to_dict(),
        outputs=[],
        summary="Multi-agent task started.",
        created_at=now,
        updated_at=now,
    )
    task_store.save(task)
    outputs: list[dict[str, Any]] = []
    for agent in selected_agents:
        task_store.add_event(task.task_id, agent.agent_id, "execute", "running", "Agent started.")
        try:
            result = agent.executor(context)
            output = {
                "agent_id": agent.agent_id,
                "name": agent.name,
                "status": result.get("status", "completed"),
                "ok": bool(result.get("ok", True)),
                "message": str(result.get("message", "")),
                "data": result.get("data", {}),
            }
        except Exception as exc:
            output = {
                "agent_id": agent.agent_id,
                "name": agent.name,
                "status": "failed",
                "ok": False,
                "message": f"{agent.name} could not complete its local check.",
                "data": {"error": exc.__class__.__name__},
            }
        task_store.add_event(task.task_id, agent.agent_id, "execute", output["status"], output["message"], output)
        outputs.append(output)

    final_status = "completed" if all(item.get("ok") for item in outputs) else "completed_with_warnings"
    summary = _summarize_outputs(user_request, outputs)
    completed = time.time()
    final_task = MultiAgentTask(
        task_id=task.task_id,
        user_request=task.user_request,
        participating_agents=task.participating_agents,
        status=final_status,
        observations=task.observations,
        outputs=outputs,
        summary=summary,
        created_at=task.created_at,
        updated_at=completed,
        completed_at=completed,
    )
    task_store.save(final_task)
    task_store.add_event(task.task_id, "orchestrator", "summary", final_status, summary)
    _safe_memory_writeback(final_task)
    return final_task


def list_multi_agent_tasks(limit: int = 50, *, store: MultiAgentTaskStore | None = None) -> list[dict[str, Any]]:
    return (store or MultiAgentTaskStore()).list(limit=limit)


def get_multi_agent_task(task_id: str, *, store: MultiAgentTaskStore | None = None) -> dict[str, Any] | None:
    task_store = store or MultiAgentTaskStore()
    task = task_store.get(task_id)
    if task:
        task["events"] = task_store.events(task_id)
    return task


def multi_agent_diagnostics(*, store: MultiAgentTaskStore | None = None) -> dict[str, Any]:
    from grandpa.agents.registry import agent_registry_diagnostics

    task_store = store or MultiAgentTaskStore()
    registry = agent_registry_diagnostics()
    return {
        "status": "ready",
        "ready": True,
        "db_path": str(task_store.db_path),
        "task_count": task_store.count(),
        "registry": registry,
        "collaboration_flows": [
            "research Python tutorials",
            "analyze Grandpa health",
            "summarize current webpage",
            "prepare coding environment",
            "collect diagnostics report",
        ],
        "local_only": True,
        "approval_safe": True,
    }


def _task_from_row(row: sqlite3.Row) -> MultiAgentTask:
    return MultiAgentTask(
        task_id=row["task_id"],
        user_request=row["user_request"],
        participating_agents=tuple(_loads_list(row["participating_agents"])),
        status=row["status"],
        observations=_loads_dict(row["observations"]),
        outputs=_loads_list(row["outputs"]),
        summary=row["summary"],
        created_at=float(row["created_at"]),
        updated_at=float(row["updated_at"]),
        completed_at=float(row["completed_at"]) if row["completed_at"] is not None else None,
    )


def _loads_dict(value: str) -> dict[str, Any]:
    try:
        loaded = json.loads(value or "{}")
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}


def _loads_list(value: str) -> list[Any]:
    try:
        loaded = json.loads(value or "[]")
        return loaded if isinstance(loaded, list) else []
    except Exception:
        return []


def _summarize_outputs(user_request: str, outputs: list[dict[str, Any]]) -> str:
    completed = [item for item in outputs if item.get("ok")]
    warnings = [item for item in outputs if not item.get("ok")]
    agent_names = ", ".join(item["name"] for item in completed) or "No agents"
    suffix = f" {len(warnings)} agent check needs attention." if warnings else ""
    return f"Grandpa coordinated {agent_names} for: {user_request.strip()}.{suffix}"


def _safe_memory_writeback(task: MultiAgentTask) -> None:
    if not task.summary or _looks_sensitive(task.user_request):
        return
    try:
        from grandpa.memory_context import MemoryStore

        MemoryStore().remember(
            "work_context",
            f"multi_agent_{task.task_id}",
            f"{task.user_request}: {task.summary}",
            source="multi_agent",
        )
    except Exception:
        return


def _looks_sensitive(text: str) -> bool:
    return bool(re.search(r"\b(password|token|api\s*key|secret|otp|credential|credit\s*card|cvv)\b", text, re.I))


__all__ = [
    "MultiAgentTask",
    "MultiAgentTaskStore",
    "OrchestratorAgent",
    "get_multi_agent_task",
    "list_multi_agent_tasks",
    "multi_agent_diagnostics",
    "orchestrate_goal",
]
