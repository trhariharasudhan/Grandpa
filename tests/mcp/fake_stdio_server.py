"""A tiny stdio MCP server for tests. It only echoes; it touches nothing.

Tools: ``echo`` (returns its text), ``slow`` (sleeps ``seconds`` first),
``fail`` (answers with isError) and ``secret`` (never on a test allow list).
Before every response it also writes the noise a real server may write: a log
line, a notification and a server-to-client request, which the client must
skip. It logs to stderr on every request.
"""

from __future__ import annotations

import json
import sys
import time

TOOLS = [
    {
        "name": "echo",
        "description": "Echo the text back.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "note": {"type": ["string", "null"]},
            },
            "required": ["text"],
        },
    },
    {
        "name": "slow",
        "description": "Sleep, then answer.",
        "inputSchema": {
            "type": "object",
            "properties": {"seconds": {"type": "number"}},
        },
    },
    {"name": "fail", "description": "Always fails.", "inputSchema": {"type": "object"}},
    {"name": "secret", "description": "Not allowed in tests.", "inputSchema": {}},
]


def write(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        request = json.loads(line)
        sys.stderr.write(f"fake server got {request.get('method')}\n")
        sys.stderr.flush()
        if "id" not in request:
            continue  # a notification
        sys.stdout.write("this is a log line, not JSON\n")
        write({"jsonrpc": "2.0", "method": "notifications/message", "params": {}})
        write({"jsonrpc": "2.0", "id": "srv-1", "method": "ping"})
        method = request.get("method")
        rid = request["id"]
        if method == "initialize":
            result = {
                "protocolVersion": "2025-03-26",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "fake", "version": "0"},
            }
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            name = request["params"]["name"]
            args = request["params"].get("arguments", {})
            if name == "slow":
                time.sleep(float(args.get("seconds", 5)))
                result = {"content": [{"type": "text", "text": "slept"}]}
            elif name == "fail":
                result = {
                    "content": [{"type": "text", "text": "nope"}],
                    "isError": True,
                }
            else:
                result = {
                    "content": [
                        {"type": "text", "text": f"{name}:{args.get('text', '')}"}
                    ]
                }
        else:
            write(
                {
                    "jsonrpc": "2.0",
                    "id": rid,
                    "error": {"code": -32601, "message": "no"},
                }
            )
            continue
        write({"jsonrpc": "2.0", "id": rid, "result": result})


if __name__ == "__main__":
    main()
