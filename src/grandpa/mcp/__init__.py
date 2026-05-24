"""MCP (Model Context Protocol) layer for grandpa."""

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
    "InProcessTransport",
    "SSETransport",
    "StdioTransport",
    "StreamableHTTPTransport",
]
