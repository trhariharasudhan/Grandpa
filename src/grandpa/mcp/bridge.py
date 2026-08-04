"""Local MCP-style bridge over Grandpa runtime skills.

This is an internal compatibility layer only. It does not open sockets or
connect to external MCP servers.
"""

from __future__ import annotations

from typing import Any

from grandpa.skills.registry import ensure_default_skills_registered, execute_skill
from grandpa.skills.registry import list_skills as list_runtime_skills
from grandpa.skills.runtime import SkillExecutionContext


def list_tools() -> list[dict[str, Any]]:
    """Return MCP-style tool schemas for registered runtime skills."""
    ensure_default_skills_registered()
    tools = []
    for skill in list_runtime_skills():
        tools.append(
            {
                "name": skill.name,
                "description": skill.description,
                "category": skill.category,
                "risk_level": skill.risk_level,
                "approval_required": skill.approval_required,
                "input_schema": {
                    "type": "object",
                    "properties": {
                        parameter.name: {
                            "type": parameter.type,
                            "description": parameter.description,
                        }
                        for parameter in skill.parameters
                    },
                    "required": [
                        parameter.name
                        for parameter in skill.parameters
                        if parameter.required
                    ],
                },
                "local_only": True,
            }
        )
    return tools


def execute_tool(
    name: str, arguments: dict[str, Any] | None = None, *, source: str = "mcp-local"
) -> dict[str, Any]:
    """Execute a runtime skill through an MCP-style tool call."""
    ensure_default_skills_registered()
    result = execute_skill(
        name,
        arguments or {},
        SkillExecutionContext(source=source, user_request=name),
    )
    return result.to_dict()


def tool_diagnostics() -> dict[str, Any]:
    tools = list_tools()
    return {
        "status": "ready",
        "tool_count": len(tools),
        "local_only": True,
        "networking_enabled": False,
        "tools": tools,
    }


__all__ = ["execute_tool", "list_tools", "tool_diagnostics"]
