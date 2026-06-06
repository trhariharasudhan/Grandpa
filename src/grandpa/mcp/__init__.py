"""MCP (Model Context Protocol) layer for Grandpa."""

from grandpa.mcp.bridge import execute_tool, list_tools, tool_diagnostics
from grandpa.mcp.client import MCPClient
from grandpa.mcp.protocol import MCPError, MCPNotification, MCPRequest, MCPResponse
from grandpa.mcp.server import MCPServer
from grandpa.mcp.transport import (
    InProcessTransport,
    MCPTransport,
    SSETransport,
    StdioTransport,
    StreamableHTTPTransport,
)

__all__ = [
    "MCPClient",
    "MCPError",
    "MCPNotification",
    "MCPRequest",
    "MCPResponse",
    "MCPServer",
    "MCPTransport",
    "execute_tool",
    "InProcessTransport",
    "list_tools",
    "SSETransport",
    "StdioTransport",
    "StreamableHTTPTransport",
    "tool_diagnostics",
]
