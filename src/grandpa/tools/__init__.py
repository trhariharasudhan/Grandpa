"""Tool primitives with on-demand built-in registration."""

from __future__ import annotations

import importlib
import logging

from grandpa.tools._stubs import BaseTool, ToolExecutor, ToolSpec

logger = logging.getLogger(__name__)
_BUILTINS = (
    "calculator", "think", "retrieval", "llm_tool", "file_read", "web_search",
    "code_interpreter", "code_interpreter_docker", "repl", "storage_tools",
    "mcp_adapter", "channel_tools", "http_request", "docker_shell_exec", "shell_exec",
    "memory_manage", "user_profile_manage", "skill_manage", "file_write", "apply_patch",
    "git_tool", "db_query", "pdf_tool", "image_tool", "audio_tool", "knowledge_tools",
    "text_to_speech", "digest_collect",
)
_builtins_loaded = False


def load_builtin_tools() -> None:
    """Import tool implementations once to populate the tool registry."""
    global _builtins_loaded
    if _builtins_loaded:
        return
    for module in _BUILTINS:
        try:
            importlib.import_module(f"grandpa.tools.{module}")
        except ImportError as exc:
            logger.debug("Optional tool %s unavailable: %s", module, exc)
    _builtins_loaded = True


__all__ = ["BaseTool", "ToolExecutor", "ToolSpec", "load_builtin_tools"]
