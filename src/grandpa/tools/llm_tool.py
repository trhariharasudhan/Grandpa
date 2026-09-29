"""LLM tool — delegate a sub-query to an inference engine."""

from __future__ import annotations

from typing import Any, Optional

from grandpa.core.registry import ToolRegistry
from grandpa.core.types import Message, Role, ToolResult
from grandpa.engine._stubs import InferenceEngine
from grandpa.tools._stubs import BaseTool, ToolSpec
from grandpa.tools.model_timeout import model_call_timeout


@ToolRegistry.register("llm")
class LLMTool(BaseTool):
    """Delegate a sub-query to an inference engine for generation."""

    tool_id = "llm"
    requires = ("engine", "model")

    # One HTTP request to an inference engine: no lock, no cursor, no file
    # handle, no subprocess. Dropping it mid-flight leaves nothing half-done on
    # this side, and the engine's own request simply completes unread.
    abandon_on_timeout = True

    def __init__(
        self,
        engine: Optional[InferenceEngine] = None,
        *,
        model: str = "",
    ) -> None:
        self._engine = engine
        self._model = model

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="llm",
            description=(
                "Send a prompt to a language model."
                " Useful for sub-queries or summarization."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "The prompt to send to the language model.",
                    },
                    "system": {
                        "type": "string",
                        "description": "Optional system message to set context.",
                    },
                },
                "required": ["prompt"],
            },
            category="inference",
            # Not the generic 30s every tool gets: this makes one model call, and
            # the engine that serves it is allowed 900. translate-doc's correct
            # translation took 110s and was thrown away. See tools/model_timeout.py.
            timeout_seconds=model_call_timeout(),
        )

    def execute(self, **params: Any) -> ToolResult:
        if self._engine is None:
            return ToolResult(
                tool_name="llm",
                content="No inference engine configured.",
                success=False,
            )
        if not self._model:
            return ToolResult(
                tool_name="llm",
                content="No model configured.",
                success=False,
            )
        prompt = params.get("prompt", "")
        if not prompt:
            return ToolResult(
                tool_name="llm",
                content="No prompt provided.",
                success=False,
            )
        messages = []
        system = params.get("system")
        if system:
            messages.append(Message(role=Role.SYSTEM, content=system))
        messages.append(Message(role=Role.USER, content=prompt))
        try:
            result = self._engine.generate(messages, model=self._model)
            content = result.get("content", "")
            return ToolResult(
                tool_name="llm",
                content=content,
                success=True,
                usage=result.get("usage", {}),
            )
        except Exception as exc:
            return ToolResult(
                tool_name="llm",
                content=f"LLM error: {exc}",
                success=False,
            )


__all__ = ["LLMTool"]
