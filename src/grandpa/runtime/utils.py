"""Runtime message serialization and token estimation utilities."""

from __future__ import annotations

import select
import socket
from collections.abc import Sequence
from typing import Any, Dict, List
from urllib.parse import urlparse

from grandpa.core.types import Message

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


def messages_to_dicts(messages: Sequence[Message]) -> List[Dict[str, Any]]:
    """Convert ``Message`` objects to OpenAI-format dicts."""
    out: List[Dict[str, Any]] = []
    for m in messages:
        d: Dict[str, Any] = {"role": m.role.value, "content": m.content}
        if m.name:
            d["name"] = m.name
        if m.tool_calls:
            d["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": tc.arguments,
                    },
                }
                for tc in m.tool_calls
            ]
        if m.tool_call_id:
            d["tool_call_id"] = m.tool_call_id
        out.append(d)
    return out


def estimate_prompt_tokens(messages: Sequence[Message]) -> int:
    """Estimate full prompt token count from message content."""
    total_chars = sum(len(m.content) for m in messages)
    overhead = len(messages) * 4
    return max(1, total_chars // 4 + overhead)


def local_port_is_open(base_url: str, timeout: float = 0.25) -> bool:
    """Return whether a local HTTP base URL has a listening TCP port."""
    parsed = urlparse(base_url)
    host = parsed.hostname
    if not host or host not in _LOCAL_HOSTS:
        return True

    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError:
        return False

    for family, socktype, proto, _, sockaddr in addresses:
        sock = socket.socket(family, socktype, proto)
        try:
            sock.setblocking(False)
            err = sock.connect_ex(sockaddr)
            if err == 0:
                return True
            _, writable, _ = select.select([], [sock], [], timeout)
            if writable:
                err = sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
                if err == 0:
                    return True
        except OSError:
            continue
        finally:
            sock.close()
    return False


__all__ = ["estimate_prompt_tokens", "local_port_is_open", "messages_to_dicts"]
