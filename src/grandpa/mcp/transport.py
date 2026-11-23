"""MCP transport implementations."""

from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import threading
import time
from abc import ABC, abstractmethod
from collections import deque
from typing import TYPE_CHECKING, Any, List, Optional

from grandpa.mcp.protocol import MCPRequest, MCPResponse

if TYPE_CHECKING:
    from grandpa.mcp.server import MCPServer


class MCPTransport(ABC):
    """Abstract transport layer for MCP communication."""

    @abstractmethod
    def send(self, request: MCPRequest) -> MCPResponse:
        """Send a request and return the response."""

    def send_notification(self, request: MCPRequest) -> None:
        """Send a JSON-RPC notification (no response expected).

        The default implementation delegates to :meth:`send` and discards the
        response.  Transports may override this when the server returns no
        body for notifications (e.g. HTTP 202 Accepted).
        """
        self.send(request)

    @abstractmethod
    def close(self) -> None:
        """Release transport resources."""


class InProcessTransport(MCPTransport):
    """Direct in-process transport for testing.

    Routes requests directly to an ``MCPServer`` instance without
    serialization overhead.
    """

    def __init__(self, server: MCPServer) -> None:
        self._server = server

    def send(self, request: MCPRequest) -> MCPResponse:
        """Dispatch request directly to the server."""
        return self._server.handle(request)

    def close(self) -> None:
        """No resources to release."""


class MCPTimeoutError(TimeoutError):
    """An MCP server did not answer in time. Its process has been killed."""


class StdioTransport(MCPTransport):
    """JSON-RPC over stdin/stdout subprocess transport.

    Launches a subprocess and communicates via JSON lines on
    stdin/stdout.

    Two background threads read the child's stdout and stderr, so a server
    that logs a lot can never fill a pipe and freeze, and a request can wait
    with a deadline instead of blocking on ``readline``. Lines that are not
    the answer to the request just sent (server notifications, log lines,
    requests from the server, late answers) are skipped.

    ``timeout`` is per request, in seconds; ``None`` waits forever (the old
    behaviour). When it runs out the process is killed and
    :class:`MCPTimeoutError` is raised: a server that hung once is not
    trusted with the next request.
    """

    def __init__(
        self,
        command: List[str],
        *,
        timeout: Optional[float] = None,
        env: Optional[dict] = None,
        cwd: Optional[str] = None,
    ) -> None:
        self._command = list(command)
        self._timeout = timeout
        self._env = env
        self._cwd = cwd
        self._process: Optional[subprocess.Popen[str]] = None
        self._lines: "queue.Queue[Optional[str]]" = queue.Queue()
        self._stderr_tail: "deque[str]" = deque(maxlen=40)
        self._lock = threading.Lock()
        self._start()

    def _start(self) -> None:
        """Start the subprocess."""
        command = list(self._command)
        if command:
            # Popen does not try PATHEXT on Windows, so "npx" would never
            # find npx.cmd. shutil.which does.
            found = shutil.which(command[0])
            if found:
                command[0] = found
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        self._process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=self._env,
            cwd=self._cwd,
            creationflags=flags,
        )
        proc = self._process
        threading.Thread(
            target=self._pump,
            args=(proc.stdout, self._lines),
            name="mcp-stdio-out",
            daemon=True,
        ).start()
        threading.Thread(
            target=self._drain,
            args=(proc.stderr, self._stderr_tail),
            name="mcp-stdio-err",
            daemon=True,
        ).start()

    @staticmethod
    def _pump(stream: Any, lines: "queue.Queue[Optional[str]]") -> None:
        try:
            for line in stream:
                lines.put(line)
        except (OSError, ValueError):
            pass
        finally:
            lines.put(None)  # end of output: the process is gone

    @staticmethod
    def _drain(stream: Any, tail: "deque[str]") -> None:
        try:
            for line in stream:
                tail.append(line.rstrip())
        except (OSError, ValueError):
            pass

    @property
    def stderr_tail(self) -> List[str]:
        """The last lines the server wrote to stderr, for error messages."""
        return list(self._stderr_tail)

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def _write(self, request: MCPRequest) -> None:
        proc = self._process
        if proc is None or proc.stdin is None:
            raise RuntimeError("Transport process is not running")
        try:
            proc.stdin.write(request.to_json() + "\n")
            proc.stdin.flush()
        except (OSError, ValueError) as exc:
            raise RuntimeError(
                f"MCP server process is not accepting input: {exc}"
            ) from exc

    def send(self, request: MCPRequest) -> MCPResponse:
        """Write request as a JSON line, read lines until its response arrives."""
        with self._lock:
            self._write(request)
            deadline = (
                None if self._timeout is None else time.monotonic() + self._timeout
            )
            while True:
                remaining = None
                if deadline is not None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        self._kill()
                        raise MCPTimeoutError(
                            f"MCP server did not answer {request.method!r} within "
                            f"{self._timeout:g} s, so it was stopped"
                        )
                try:
                    line = self._lines.get(timeout=remaining)
                except queue.Empty:
                    continue  # the deadline check above raises
                if line is None:
                    self._lines.put(None)  # keep reporting "gone" to later calls
                    raise RuntimeError("No response from subprocess")
                text = line.strip()
                if not text:
                    continue
                try:
                    parsed = json.loads(text)
                except ValueError:
                    continue  # a log line on stdout
                if not isinstance(parsed, dict) or "method" in parsed:
                    continue  # a notification or a request from the server
                if parsed.get("id") != request.id:
                    continue  # a late answer to an earlier, abandoned request
                return MCPResponse.from_json(text)

    def send_notification(self, request: MCPRequest) -> None:
        """Send a JSON-RPC notification — write only, never read.

        Overrides the base implementation: stdio servers do not reply
        to notifications, so the default ``send()`` would wait forever.
        """
        with self._lock:
            self._write(request)

    def _kill(self) -> None:
        proc = self._process
        if proc is None:
            return
        try:
            proc.kill()
            proc.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            pass
        self._process = None

    def close(self) -> None:
        """Terminate the subprocess, and kill it if it does not stop."""
        proc = self._process
        if proc is None:
            return
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
        except OSError:
            pass
        self._process = None


class StreamableHTTPTransport(MCPTransport):
    """MCP Streamable HTTP transport (JSON-RPC over HTTP).

    Uses a persistent ``httpx.Client`` session, tracks the
    ``Mcp-Session-Id`` header, and sends the ``Accept`` header
    required by the MCP Streamable HTTP specification.
    """

    def __init__(
        self,
        url: str,
        *,
        connect_timeout: float = 10.0,
        request_timeout: float = 60.0,
    ) -> None:
        import httpx

        self._url = url
        self._session_id: Optional[str] = None
        self._client = httpx.Client(
            timeout=httpx.Timeout(
                connect=connect_timeout,
                read=request_timeout,
                write=request_timeout,
                pool=connect_timeout,
            ),
        )

    def _safe_url(self) -> str:
        """Return scheme://host:port without path or query (avoids leaking tokens)."""
        from urllib.parse import urlparse

        parsed = urlparse(self._url)
        return f"{parsed.scheme}://{parsed.netloc}"

    def _build_headers(self) -> dict:
        """Build common request headers."""
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._session_id is not None:
            headers["Mcp-Session-Id"] = self._session_id
        return headers

    def _post(self, request: MCPRequest) -> Any:
        """Post a request and return the raw httpx response."""
        import httpx

        headers = self._build_headers()
        try:
            response = self._client.post(
                self._url,
                json=request.to_dict(),
                headers=headers,
            )
            response.raise_for_status()
        except httpx.ConnectError as exc:
            raise RuntimeError(
                f"Failed to connect to MCP server at {self._safe_url()}: {exc}"
            ) from exc
        except httpx.TimeoutException as exc:
            raise RuntimeError(
                f"Timeout communicating with MCP server at {self._safe_url()}: {exc}"
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"MCP server at {self._safe_url()} returned HTTP "
                f"{exc.response.status_code}"
            ) from exc

        # Track session id from the first response
        new_session_id = response.headers.get("mcp-session-id")
        if new_session_id is not None:
            self._session_id = new_session_id
        return response

    @staticmethod
    def _extract_json_from_sse(text: str) -> str:
        """Extract JSON payload from an SSE response body.

        MCP Streamable HTTP servers may respond with ``text/event-stream``
        instead of ``application/json``.  In that case the body looks like::

            event: message
            data: {"jsonrpc":"2.0", ...}

        This helper finds the last ``data:`` line and returns its content,
        which is the actual JSON-RPC response.
        """
        last_data = ""
        for line in text.splitlines():
            if line.startswith("data:"):
                last_data = line[len("data:") :].strip()
        if not last_data:
            raise RuntimeError(
                "SSE response contained no 'data:' lines"
                " — cannot extract JSON-RPC payload"
            )
        return last_data

    def send(self, request: MCPRequest) -> MCPResponse:
        """Send request via HTTP POST following the MCP Streamable HTTP spec.

        Handles both ``application/json`` and ``text/event-stream`` responses
        as allowed by the MCP Streamable HTTP specification.
        """
        response = self._post(request)
        content_type = response.headers.get("content-type", "")
        body = response.text
        if "text/event-stream" in content_type or body.lstrip().startswith("event:"):
            body = self._extract_json_from_sse(body)
        return MCPResponse.from_json(body)

    def send_notification(self, request: MCPRequest) -> None:
        """Send a notification — accept any 2xx, don't parse the body."""
        # Track session id but don't try to parse a JSON-RPC response.
        # Servers may return 202 Accepted with an empty body.
        self._post(request)

    def close(self) -> None:
        """Close the underlying httpx client."""
        self._client.close()


# Backward-compatible alias
SSETransport = StreamableHTTPTransport


__all__ = [
    "InProcessTransport",
    "MCPTimeoutError",
    "MCPTransport",
    "SSETransport",
    "StdioTransport",
    "StreamableHTTPTransport",
]
