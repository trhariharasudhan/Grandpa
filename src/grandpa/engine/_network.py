"""Network helpers for local engine probes."""

from __future__ import annotations

import select
import socket
from urllib.parse import urlparse


_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


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
