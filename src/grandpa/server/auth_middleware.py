"""API key authentication middleware for the Grandpa server."""

from __future__ import annotations

import logging
import os
import secrets

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)


class AuthMiddleware:
    """Validate bearer credentials on protected HTTP and WebSocket routes.

    Webhook routes and health checks are exempt — they use
    per-channel signature verification instead.
    """

    def __init__(self, app: ASGIApp, api_key: str = "") -> None:
        self.app = app
        self._api_key = api_key or os.environ.get("Grandpa_API_KEY", "")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        scope_type = scope.get("type")
        if (
            not self._api_key
            or scope_type not in {"http", "websocket"}
            or not self._requires_auth(scope.get("path", ""))
        ):
            await self.app(scope, receive, send)
            return

        auth = self._authorization_header(scope)
        scheme, separator, token = auth.partition(" ")
        valid = (
            bool(separator)
            and scheme.lower() == "bearer"
            and secrets.compare_digest(token, self._api_key)
        )
        if valid:
            await self.app(scope, receive, send)
            return

        if scope_type == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return

        detail = "Missing Authorization header" if not auth else "Invalid API key"
        response = JSONResponse({"detail": detail}, status_code=401)
        await response(scope, receive, send)

    @staticmethod
    def _authorization_header(scope: Scope) -> str:
        for name, value in scope.get("headers", []):
            if name.lower() == b"authorization":
                return value.decode("latin-1")
        return ""

    @staticmethod
    def _requires_auth(path: str) -> bool:
        """Only protect API routes, not the frontend UI or static assets."""
        return path.startswith("/v1/") or path.startswith("/api/")



def generate_api_key() -> str:
    """Generate a new API key with ``oj_sk_`` prefix."""
    return f"oj_sk_{secrets.token_urlsafe(32)}"


def check_bind_safety(
    host: str,
    *,
    api_key: str,
    allow_insecure_bind: bool = False,
) -> None:
    """Refuse to bind non-loopback without an API key.

    Raises ``SystemExit`` if *host* is not a loopback address and
    *api_key* is empty.
    """
    import ipaddress
    import sys

    try:
        is_loop = ipaddress.ip_address(host).is_loopback
    except ValueError:
        is_loop = host in ("localhost", "")

    if not is_loop and not api_key and not allow_insecure_bind:
        logger.error(
            "Binding to %s requires Grandpa_API_KEY to be set. "
            "Run: Grandpa auth generate-key",
            host,
        )
        sys.exit(1)
