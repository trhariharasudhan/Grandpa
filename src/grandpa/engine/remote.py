"""Use the Windows PC's model from another machine (P2, Pironman home server).

The home server has no model of its own. Every ``generate`` goes over the LAN
to ``POST /v1/devices/llm`` on the PC, signed with the device token the home
server got when it paired (D1). The PC answers with model text only: it runs
no tools and no actions for this route, and refuses it unless
``server.device_llm`` is turned on at the PC.

The token is read from ``GRANDPA_PC_TOKEN`` or the secret store
(``headless.pc_token``); it is never logged.
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator, Sequence
from typing import Any, Dict, List

import httpx

from grandpa.core.types import Message
from grandpa.engine._stubs import InferenceEngine
from grandpa.runtime.exceptions import RuntimeConnectionError

logger = logging.getLogger(__name__)

PC_URL_ENV = "GRANDPA_PC_URL"
PC_TOKEN_ENV = "GRANDPA_PC_TOKEN"
#: Name of the device token in the secret store (``grandpa vault get``).
PC_TOKEN_SECRET = "headless.pc_token"
#: The PC's model may be slow on a laptop GPU; match the Ollama timeout order.
DEFAULT_TIMEOUT = 300.0
LLM_PATH = "/v1/devices/llm"
ME_PATH = "/v1/devices/me"


def pc_url_from_env() -> str:
    return os.environ.get(PC_URL_ENV, "").strip().rstrip("/")


def pc_token(store=None) -> str:
    """The device token: environment first, then the secret store."""
    token = os.environ.get(PC_TOKEN_ENV, "").strip()
    if token:
        return token
    try:
        if store is None:
            from grandpa.security.secret_store import SecretStore

            store = SecretStore()
        return (store.get(PC_TOKEN_SECRET) or "").strip()
    except Exception as exc:  # noqa: BLE001 - a missing store means no token
        logger.debug("Secret store unavailable: %s", type(exc).__name__)
        return ""


class RemotePCEngine(InferenceEngine):
    """An engine whose model runs on the paired Windows PC."""

    engine_id = "pc"
    supports_streaming = False

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        model: str = "",
        timeout: float = DEFAULT_TIMEOUT,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not base_url:
            raise ValueError("The PC address is empty (set GRANDPA_PC_URL).")
        if not token:
            raise ValueError("No device token (pair first: grandpa server pair).")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            headers={"Authorization": f"Bearer {token}"},
            transport=transport,
        )

    def __repr__(self) -> str:  # never show the token
        return f"RemotePCEngine({self.base_url!r})"

    def supports_tools(self, model: str) -> bool:
        return False

    def generate(
        self,
        messages: Sequence[Message],
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        # Tools are dropped on purpose: the PC route runs none.
        body = {
            "messages": [
                {"role": getattr(m.role, "value", str(m.role)), "content": m.content}
                for m in messages
                if getattr(m.role, "value", str(m.role)) != "tool"
            ],
            "model": model or self.model,
            "temperature": max(0.0, min(float(temperature), 2.0)),
            "max_tokens": max(1, min(int(max_tokens), 8192)),
        }
        try:
            resp = self._client.post(LLM_PATH, json=body)
        except httpx.HTTPError as exc:
            raise RuntimeConnectionError(
                f"Could not reach the PC at {self.base_url} ({type(exc).__name__})."
            ) from exc
        if resp.status_code != 200:
            try:
                detail = resp.json().get("detail", "")
            except ValueError:
                detail = ""
            raise RuntimeConnectionError(
                f"The PC refused the request ({resp.status_code}): {detail}".rstrip(
                    ": "
                )
            )
        data = resp.json()
        return {
            "content": data.get("content", "") or "",
            "usage": data.get("usage", {}) or {},
            "finish_reason": data.get("finish_reason", "stop") or "stop",
            "model": data.get("model", body["model"]),
        }

    async def stream(
        self,
        messages: Sequence[Message],
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        # One piece: the PC route answers whole. Run in a thread so the
        # event loop is not blocked while the PC thinks.
        import asyncio

        result = await asyncio.to_thread(
            self.generate,
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        yield result["content"]

    def list_models(self) -> List[str]:
        return [self.model] if self.model else ["pc"]

    def health(self) -> bool:
        try:
            return self._client.get(ME_PATH, timeout=5.0).status_code == 200
        except httpx.HTTPError:
            return False

    def close(self) -> None:
        self._client.close()


__all__ = [
    "PC_TOKEN_ENV",
    "PC_TOKEN_SECRET",
    "PC_URL_ENV",
    "RemotePCEngine",
    "pc_token",
    "pc_url_from_env",
]
