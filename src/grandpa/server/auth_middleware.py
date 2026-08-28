"""API key authentication middleware for the Grandpa server."""

from __future__ import annotations

import logging
import os
import secrets

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)

#: Canonical environment variable for the local API key.
API_KEY_ENV = "GRANDPA_API_KEY"
#: Pre-rename spelling, still honoured so existing setups keep working.
LEGACY_API_KEY_ENV = "Grandpa_API_KEY"


def api_key_from_env() -> str:
    """Return the API key from the environment, preferring the canonical name.

    ``Grandpa_API_KEY`` predates the project rename and is case-inconsistent
    with every other ``GRANDPA_*`` variable. It is still read, with a warning,
    so existing setups do not break.
    """
    key = os.environ.get(API_KEY_ENV, "").strip()
    if key:
        return key
    legacy = os.environ.get(LEGACY_API_KEY_ENV, "").strip()
    if legacy:
        logger.warning(
            "%s is deprecated; rename it to %s.",
            LEGACY_API_KEY_ENV,
            API_KEY_ENV,
        )
    return legacy


class AuthMiddleware:
    """Validate bearer credentials on protected HTTP and WebSocket routes.

    Health and other non-API routes are exempt. All API routes are protected
    when an API key is configured.
    """

    def __init__(self, app: ASGIApp, api_key: str = "") -> None:
        self.app = app
        self._api_key = api_key or api_key_from_env()

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
        """Protect API routes while leaving non-API health paths available."""
        return path.startswith("/v1/") or path.startswith("/api/")


def generate_api_key() -> str:
    """Generate a new API key with a ``gp_sk_`` prefix.

    The prefix was ``oj_sk_`` from the project's OpenJarvis era. It is purely
    informational — nothing validates it, and comparison is against the whole
    key. Renaming it is free right now because auth only just became enabled by
    default, so no keys have been issued yet; once they exist in configs and
    scripts, it would no longer be.
    """
    return f"gp_sk_{secrets.token_urlsafe(32)}"


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
            "Binding to %s requires an API key. Set %s, or drop --no-auth so "
            "grandpa serve generates one for you.",
            host,
            API_KEY_ENV,
        )
        sys.exit(1)
