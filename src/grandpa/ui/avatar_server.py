"""The local WebSocket the avatar page talks to.

Python publishes states and chat lines; the page sends typed lines back. It is
a WebSocket rather than pywebview's in-page JS bridge so that the same page can
later be opened from a browser, the Pironman or a phone without changing.

Who may connect:

* **Loopback only.** It binds ``127.0.0.1``; nothing off the machine reaches it.
* **A per-run token.** A random token is minted on every start and must be in
  the connection URL (``?token=...``). Another program on this PC cannot drive
  Grandpa through it by guessing the port. A page without it is refused at the
  handshake, before a single message.
* **Two kinds of inbound message.** ``{"type": "send", "text": ...}``, at most
  :data:`grandpa.ui.avatar_states.MAX_INBOUND_TEXT` characters, one at a time.
  It goes to :meth:`AvatarController.submit`, i.e. through the same bridge and
  gates as the tkinter bubble. ``{"type": "talk"}`` (A6, click-to-talk) asks
  :meth:`AvatarController.talk` to listen for one line, which is then routed
  exactly like a typed one. There is no message that performs an action.

Outbound it also carries, once per connection, Captain's checked character
model (A3) as one binary frame, announced by ``{"type": "character", "bytes": n}``.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import secrets
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from http import HTTPStatus
from typing import Any
from urllib.parse import parse_qs, urlparse

from grandpa.ui.avatar_states import (
    PROTOCOL_VERSION,
    ChatMessage,
    StateMessage,
    encode,
    parse_inbound,
)

logger = logging.getLogger(__name__)

HOST = "127.0.0.1"
MAX_FRAME = 16 * 1024


def _missing_websockets() -> RuntimeError:
    return RuntimeError(
        "The avatar needs the 'websockets' package. Install the avatar extra: "
        'uv sync --extra avatar   (or: pip install -e ".[avatar]")'
    )


@dataclass
class AvatarServer:
    """Runs on its own thread with its own event loop; safe to call from any."""

    on_send: Callable[[str], Any]
    """Called (on a worker thread) with each valid line the page sends."""
    on_talk: Callable[[], Any] | None = None
    """Called (on a worker thread) when the page asks to talk (A6). ``None``
    ignores the request."""
    on_cancel: Callable[[], Any] | None = None
    """Called when the page asks to stop the current reply; ``None`` ignores it."""
    snapshot: Callable[[], list[StateMessage | ChatMessage]] = list
    """Messages a newly connected page is sent first."""
    character: bytes | None = None
    """Captain's checked ``grandpa.glb`` (A3), sent to each page as one binary
    frame after the snapshot; ``None`` keeps the placeholder head."""
    api: Callable[[str, list], Any] | None = None
    """Browser mode of the desktop app: runs one whitelisted method (name,
    args) and returns a JSON-able value. ``None`` (the orb) refuses every
    ``{"type": "api"}`` message."""
    api_methods: tuple[str, ...] = ()
    """The names :attr:`api` accepts; told to each page when it connects."""
    max_frame: int = MAX_FRAME
    """Largest inbound frame. The app's browser mode raises it for uploads."""
    port: int = 0
    token: str = field(default_factory=lambda: secrets.token_urlsafe(24))

    _loop: asyncio.AbstractEventLoop | None = field(default=None, init=False)
    _thread: threading.Thread | None = field(default=None, init=False)
    _server: Any = field(default=None, init=False)
    _clients: set = field(default_factory=set, init=False)
    _ready: threading.Event = field(default_factory=threading.Event, init=False)
    _error: BaseException | None = field(default=None, init=False)
    _worker: Any = field(default=None, init=False)
    _api_worker: Any = field(default=None, init=False)

    # --- lifecycle ------------------------------------------------------------

    def start(self, timeout: float = 5.0) -> int:
        """Start serving; returns the bound port."""
        try:
            import websockets  # noqa: F401
        except ImportError as exc:
            raise _missing_websockets() from exc
        from concurrent.futures import ThreadPoolExecutor

        self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="avatar")
        # Separate, so opening Skills never waits behind a long reply.
        self._api_worker = ThreadPoolExecutor(max_workers=2, thread_name_prefix="app-api")
        self._thread = threading.Thread(
            target=self._run, name="grandpa-avatar-ws", daemon=True
        )
        self._thread.start()
        if not self._ready.wait(timeout):
            raise RuntimeError("The avatar server did not start in time.")
        if self._error is not None:
            raise RuntimeError(f"The avatar server failed: {self._error}")
        return self.port

    def stop(self) -> None:
        loop = self._loop
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=5)
        for worker in (self._worker, self._api_worker):
            if worker is not None:
                worker.shutdown(wait=False, cancel_futures=True)

    @property
    def url(self) -> str:
        return f"ws://{HOST}:{self.port}/avatar?token={self.token}"

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._open())
        except BaseException as exc:  # noqa: BLE001 - reported through start()
            self._error = exc
            self._ready.set()
            return
        self._ready.set()
        try:
            loop.run_forever()
        finally:
            if self._server is not None:
                self._server.close()
                try:
                    loop.run_until_complete(self._server.wait_closed())
                except Exception:  # noqa: BLE001
                    pass
            loop.close()

    async def _open(self) -> None:
        from websockets.asyncio.server import serve

        self._server = await serve(
            self._handle,
            HOST,
            self.port,
            process_request=self._check_token,
            max_size=self.max_frame,
        )
        self.port = self._server.sockets[0].getsockname()[1]

    # --- connections ----------------------------------------------------------

    def token_ok(self, path: str) -> bool:
        query = parse_qs(urlparse(path).query)
        offered = (query.get("token") or [""])[0]
        return bool(offered) and hmac.compare_digest(offered, self.token)

    def _check_token(self, connection: Any, request: Any) -> Any:
        if self.token_ok(getattr(request, "path", "") or ""):
            return None
        return connection.respond(HTTPStatus.FORBIDDEN, "Forbidden\n")

    async def _handle(self, websocket: Any) -> None:
        self._clients.add(websocket)
        try:
            for message in self.snapshot():
                await websocket.send(encode(message))
            if self.character:
                announce = {
                    "type": "character",
                    "v": PROTOCOL_VERSION,
                    "bytes": len(self.character),
                }
                await websocket.send(encode(announce))
                await websocket.send(self.character)
            if self.api is not None:
                await websocket.send(
                    encode({"type": "api_methods", "methods": list(self.api_methods)})
                )
            async for raw in websocket:
                call = parse_api(raw, self.api_methods) if self.api is not None else None
                if call is not None:
                    asyncio.ensure_future(self._answer(websocket, *call))
                    continue
                parsed = parse_inbound(raw)
                if parsed is None:
                    continue
                kind, text = parsed
                loop = asyncio.get_running_loop()
                if kind == "cancel":
                    if self.on_cancel is not None:
                        # Not queued behind the reply it is meant to stop.
                        threading.Thread(target=self.on_cancel, daemon=True).start()
                    continue
                if kind == "talk":
                    if self.on_talk is not None:
                        loop.run_in_executor(self._worker, self._call_talk)
                    continue
                loop.run_in_executor(self._worker, self._call_send, text)
        except Exception:  # noqa: BLE001 - a dropped page is ordinary
            logger.debug("avatar connection ended", exc_info=True)
        finally:
            self._clients.discard(websocket)

    async def _answer(self, websocket: Any, call_id: int, method: str, args: list) -> None:
        """Run one API call off the loop and reply to the page that asked."""
        loop = asyncio.get_running_loop()
        try:
            value = await loop.run_in_executor(self._api_worker, self.api, method, args)
            reply = {"type": "api_result", "id": call_id, "ok": True, "value": value}
        except Exception as exc:  # noqa: BLE001 - reported to the page
            logger.exception("app api %s failed", method)
            reply = {"type": "api_result", "id": call_id, "ok": False, "error": str(exc)}
        try:
            payload = json.dumps(reply, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            payload = json.dumps(
                {"type": "api_result", "id": call_id, "ok": False, "error": "bad result"}
            )
        await self._safe_send(websocket, payload)

    def _call_send(self, text: str) -> None:
        try:
            self.on_send(text)
        except Exception:  # noqa: BLE001
            logger.exception("avatar request failed")

    def _call_talk(self) -> None:
        try:
            self.on_talk()
        except Exception:  # noqa: BLE001
            logger.exception("avatar talk failed")

    # --- outbound -------------------------------------------------------------

    def broadcast(self, message: StateMessage | ChatMessage) -> None:
        """Send to every connected page. Callable from any thread; never blocks."""
        loop = self._loop
        if loop is None or not loop.is_running():
            return
        payload = encode(message)

        def _send_all() -> None:
            for client in list(self._clients):
                asyncio.ensure_future(self._safe_send(client, payload))

        loop.call_soon_threadsafe(_send_all)

    async def _safe_send(self, client: Any, payload: str) -> None:
        try:
            await client.send(payload)
        except Exception:  # noqa: BLE001
            self._clients.discard(client)


MAX_API_ARGS = 8


def parse_api(raw: str | bytes, allowed: tuple[str, ...]) -> tuple[int, str, list] | None:
    """``(id, method, args)`` for a valid API call, else ``None``.

    Only names in ``allowed`` pass, and only plain JSON arguments; anything
    else falls through to :func:`parse_inbound`, which drops it.
    """
    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError:
            return None
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("type") != "api":
        return None
    call_id, method, args = data.get("id"), data.get("method"), data.get("args", [])
    if not isinstance(call_id, int) or isinstance(call_id, bool):
        return None
    if not isinstance(method, str) or method not in allowed or method.startswith("_"):
        return None
    if not isinstance(args, list) or len(args) > MAX_API_ARGS:
        return None
    return call_id, method, args


__all__ = ["AvatarServer", "HOST", "parse_api"]
