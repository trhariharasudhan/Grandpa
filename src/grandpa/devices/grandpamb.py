"""GrandpaMB driver: talk to Grandpa's own ESP32-S3 board over serial.

The board is Grandpa's *body*: an LED ring and OLED that show what Grandpa is
doing, WAKE / MUTE buttons, room sensors, a buzzer and one relay. The brain
(models, memory, tools) stays here on the PC.

Wire protocol (firmware: github.com/trhariharasudhan/GrandpaMB, src/protocol.cpp)
is newline-delimited JSON:

* PC -> board: ``{"id": 3, "cmd": "state", "value": "thinking"}``
* board -> PC: ``{"type": "reply", "id": 3, "ok": true, ...}`` for replies, and
  unsolicited ``hello`` / ``event`` / ``telemetry`` lines.

The transport is anything with ``read(n)``, ``write(b)`` and ``close()``. In
production it is ``serial.serial_for_url(port)``: ``COM5`` for a real board, or
``rfc2217://localhost:4000`` for the Wokwi simulator. Tests pass a fake.

Safety: switching the relay ON is two-step on purpose. ``request_relay_on``
only asks the board, which answers with a one-time token; nothing switches
until ``confirm`` sends that token back. Whoever calls this module is
responsible for asking a human in between. Switching OFF is always immediate.
"""

from __future__ import annotations

import itertools
import json
import logging
import os
import queue
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Protocol

logger = logging.getLogger(__name__)

__all__ = [
    "BOARD_STATES",
    "BoardError",
    "BoardNotConnectedError",
    "GrandpaMBClient",
    "GrandpaMBConfig",
    "RelayConfirmation",
    "Transport",
]

#: States the firmware accepts for ``state`` (assistant_state.cpp).
BOARD_STATES = frozenset({"idle", "listening", "thinking", "speaking", "muted", "error"})

#: OLED fits ~60 characters on its message line.
MAX_MESSAGE_CHARS = 60


class BoardError(RuntimeError):
    """The board answered ``ok: false`` or did not answer in time."""


class BoardNotConnectedError(BoardError):
    """The serial port / simulator could not be opened."""


class Transport(Protocol):
    def read(self, size: int = 1) -> bytes: ...
    def write(self, data: bytes) -> Optional[int]: ...
    def close(self) -> None: ...


@dataclass(frozen=True)
class GrandpaMBConfig:
    """Where the board is. Read from the environment so no code change is
    needed to move from the simulator to a real board."""

    port: str = "rfc2217://localhost:4000"
    baud: int = 115200
    reply_timeout: float = 3.0

    @classmethod
    def from_env(cls) -> "GrandpaMBConfig":
        return cls(
            port=os.environ.get("GRANDPA_MB_PORT", cls.port),
            baud=int(os.environ.get("GRANDPA_MB_BAUD", cls.baud)),
            reply_timeout=float(os.environ.get("GRANDPA_MB_TIMEOUT", cls.reply_timeout)),
        )


@dataclass(frozen=True)
class RelayConfirmation:
    """What the board sent back for ``relay on``. Show ``action`` to the user;
    pass ``token`` to :meth:`GrandpaMBClient.confirm` only after they agree."""

    action: str
    token: str
    expires_ms: int


@dataclass
class _Latest:
    telemetry: dict[str, Any] = field(default_factory=dict)
    hello: dict[str, Any] = field(default_factory=dict)


def _open_serial(config: GrandpaMBConfig) -> Transport:
    try:
        import serial  # pyserial, optional dependency
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise BoardNotConnectedError(
            "pyserial is not installed. Install it with: uv pip install pyserial"
        ) from exc
    try:
        return serial.serial_for_url(config.port, baudrate=config.baud, timeout=0.2)
    except serial.SerialException as exc:
        hint = (
            "Is the Wokwi simulator running?"
            if config.port.startswith("rfc2217://")
            else "Check the COM port and close other serial monitors."
        )
        raise BoardNotConnectedError(f"Cannot open {config.port}: {exc}. {hint}") from exc


class GrandpaMBClient:
    """Thread-safe client. One reader thread routes replies to callers and
    everything else (events, telemetry) to subscribers."""

    def __init__(
        self,
        config: Optional[GrandpaMBConfig] = None,
        transport: Optional[Transport] = None,
    ) -> None:
        self.config = config or GrandpaMBConfig.from_env()
        self._transport = transport if transport is not None else _open_serial(self.config)
        self._ids = itertools.count(1)
        self._pending: dict[int, "queue.Queue[dict[str, Any]]"] = {}
        self._pending_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._subscribers: list[Callable[[dict[str, Any]], None]] = []
        self._latest = _Latest()
        self._running = True
        self._reader = threading.Thread(target=self._read_loop, name="grandpamb-reader", daemon=True)
        self._reader.start()

    # -- lifecycle --------------------------------------------------------
    def close(self) -> None:
        self._running = False
        try:
            self._transport.close()
        except Exception:  # pragma: no cover - best effort
            logger.debug("transport close failed", exc_info=True)

    def __enter__(self) -> "GrandpaMBClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @property
    def connected(self) -> bool:
        return self._running and self._reader.is_alive()

    # -- events -----------------------------------------------------------
    def subscribe(self, callback: Callable[[dict[str, Any]], None]) -> None:
        """Called (on the reader thread) for every non-reply message, e.g.
        ``{"type": "event", "name": "wake"}``. Keep callbacks quick."""
        self._subscribers.append(callback)

    @property
    def latest_telemetry(self) -> dict[str, Any]:
        return dict(self._latest.telemetry)

    # -- low level --------------------------------------------------------
    def call(self, cmd: str, **params: Any) -> dict[str, Any]:
        """Send one command, wait for its reply. Raises :class:`BoardError`
        on timeout or ``ok: false``."""
        if not self.connected:
            raise BoardNotConnectedError("GrandpaMB connection is closed")
        rid = next(self._ids)
        box: "queue.Queue[dict[str, Any]]" = queue.Queue(maxsize=1)
        with self._pending_lock:
            self._pending[rid] = box
        line = json.dumps({"id": rid, "cmd": cmd, **params}, separators=(",", ":")) + "\n"
        try:
            with self._write_lock:
                self._transport.write(line.encode("utf-8"))
            try:
                reply = box.get(timeout=self.config.reply_timeout)
            except queue.Empty:
                raise BoardError(
                    f"GrandpaMB did not answer '{cmd}' within {self.config.reply_timeout}s"
                ) from None
        finally:
            with self._pending_lock:
                self._pending.pop(rid, None)
        if not reply.get("ok", False):
            raise BoardError(f"GrandpaMB refused '{cmd}': {reply.get('error', 'unknown error')}")
        return reply

    def _read_loop(self) -> None:
        buf = b""
        while self._running:
            try:
                chunk = self._transport.read(256)
            except Exception as exc:
                if self._running:
                    logger.warning("GrandpaMB read failed, link closed: %s", exc)
                self._running = False
                return
            if not chunk:
                continue
            buf += chunk
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                self._dispatch(raw.decode("utf-8", errors="replace").strip())

    def _dispatch(self, line: str) -> None:
        if not line.startswith("{"):
            return  # ESP32 ROM boot text, not ours
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            logger.debug("GrandpaMB sent non-JSON line: %r", line)
            return
        kind = msg.get("type")
        if kind == "reply":
            with self._pending_lock:
                box = self._pending.get(msg.get("id"))
            if box is not None:
                box.put(msg)
            return
        if kind == "telemetry":
            self._latest.telemetry = msg
        elif kind == "hello":
            self._latest.hello = msg
        for callback in list(self._subscribers):
            try:
                callback(msg)
            except Exception:
                logger.exception("GrandpaMB subscriber failed")

    # -- high level -------------------------------------------------------
    def info(self) -> dict[str, Any]:
        return self.call("info")

    def ping(self) -> bool:
        return self.call("ping").get("msg") == "pong"

    def set_state(self, state: str) -> None:
        state = state.strip().lower()
        if state not in BOARD_STATES:
            raise ValueError(f"unknown board state {state!r}; expected one of {sorted(BOARD_STATES)}")
        self.call("state", value=state)

    def say(self, text: str) -> None:
        """Show a short message on the OLED (not audio)."""
        self.call("say", text=" ".join(text.split())[:MAX_MESSAGE_CHARS])

    def beep(self, ms: int = 120, freq: int = 2000) -> None:
        self.call("beep", ms=max(10, min(int(ms), 2000)), freq=max(100, min(int(freq), 8000)))

    def relay_off(self) -> None:
        self.call("relay", value="off")

    def request_relay_on(self) -> RelayConfirmation:
        reply = self.call("relay", value="on")
        if not reply.get("confirm_required") or not reply.get("token"):
            # Firmware must never switch on without a token round-trip.
            raise BoardError("GrandpaMB did not ask for confirmation; refusing to continue")
        return RelayConfirmation(
            action=str(reply.get("action", "relay_on")),
            token=str(reply["token"]),
            expires_ms=int(reply.get("expires_ms", 0)),
        )

    def confirm(self, token: str) -> None:
        self.call("confirm", token=token)

    def cancel(self) -> None:
        self.call("cancel")
