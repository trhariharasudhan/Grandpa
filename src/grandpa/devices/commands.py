"""Commands and voice from a paired phone (D2).

A phone sends text (or a short recording, which is transcribed first) and it
goes through the same action-layer tool loop as ``grandpa chat``. The one
difference is who can say yes:

* Low-risk actions the model picks run as they would in chat.
* Anything that needs confirmation is **refused**, not asked about: the loop
  runs with no confirm callback, which makes the executor answer
  ``confirmation_required`` and do nothing. The reply lists those actions so
  the phone can say "that needs a yes on the PC". Since D4 each one is also
  kept as a pending request (``grandpa.devices.approvals``) that someone at
  the PC can approve with ``grandpa devices approve <id>``. The phone itself
  can never say yes.

Every command is written to the device log (``grandpa devices log``) with
the device that sent it, and each device is limited to
``MAX_COMMANDS_PER_MINUTE`` commands a minute.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any

MAX_COMMAND_CHARS = 500
MAX_COMMANDS_PER_MINUTE = 20
MAX_AUDIO_BYTES = 10 * 1024 * 1024
"""About five minutes of 16 kHz mono WAV: far more than one command needs."""


class CommandRefused(Exception):
    """A command was not run. ``status`` is the HTTP status to answer with."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


class RateLimiter:
    """At most ``limit`` calls per ``window`` seconds for each key."""

    def __init__(
        self, limit: int = MAX_COMMANDS_PER_MINUTE, window: float = 60.0
    ) -> None:
        self.limit = limit
        self.window = window
        self._calls: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, *, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        with self._lock:
            calls = self._calls[key]
            while calls and calls[0] <= now - self.window:
                calls.popleft()
            if len(calls) >= self.limit:
                return False
            calls.append(now)
            return True


@dataclass
class PhoneCommandResult:
    reply: str
    actions: list[dict[str, Any]] = field(default_factory=list)
    needs_pc_confirmation: list[str] = field(default_factory=list)
    pending: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "reply": self.reply,
            "actions": self.actions,
            "needs_pc_confirmation": self.needs_pc_confirmation,
            "pending": self.pending,
        }


def clean_command(text: str) -> str:
    cleaned = " ".join((text or "").split())
    if not cleaned:
        raise CommandRefused("Say or type something for Grandpa to do.")
    if len(cleaned) > MAX_COMMAND_CHARS:
        raise CommandRefused(
            f"That is too long for one command (over {MAX_COMMAND_CHARS} characters)."
        )
    return cleaned


def run_phone_command(
    text: str, *, engine: Any, model: str, device_id: str, store: Any
) -> PhoneCommandResult:
    """Run one phone command through the action layer, refusing confirmations."""
    from grandpa.action_layer.executor import CONFIRMATION_REQUIRED
    from grandpa.action_layer.loop import ToolsUnsupportedError, run
    from grandpa.action_layer.model import Origin

    command = clean_command(text)
    if engine is None or not model:
        raise CommandRefused("Grandpa has no model running on the PC.", status=503)

    store.log_event("command", device_id=device_id, detail=command)
    try:
        # confirm_callback=None: nobody at the PC is being asked, so every
        # action that needs a yes is refused by the executor, never run.
        result = run(
            command,
            engine=engine,
            model=model,
            confirm_callback=None,
            origin=Origin.MODEL,
        )
    except ToolsUnsupportedError as exc:
        store.log_event("command_failed", device_id=device_id, detail=str(exc))
        raise CommandRefused(str(exc), status=503) from exc

    actions = [
        {
            "action": entry.action,
            "success": entry.success,
            "error": entry.error,
            "message": entry.message,
        }
        for entry in result.trace
    ]
    waiting = [e for e in result.trace if e.error == CONFIRMATION_REQUIRED]
    pending = _queue_for_pc(waiting, device_id=device_id, command=command, store=store)
    reply = result.text.strip() or "Done."
    if waiting:
        reply += (
            "\n\nThese need a yes on the PC, so I did not do them yet: "
            + ", ".join(f"#{p['id']} {p['action']}" for p in pending)
            + ". They wait 10 minutes for someone at the PC to run "
            "`grandpa devices approve <number>`."
        )
    done = ", ".join(
        f"{a['action']}={'ok' if a['success'] else a['error']}" for a in actions
    )
    store.log_event("command_done", device_id=device_id, detail=done or "no actions")
    return PhoneCommandResult(
        reply, actions, list(dict.fromkeys(e.action for e in waiting)), pending
    )


def _queue_for_pc(
    waiting: list[Any], *, device_id: str, command: str, store: Any
) -> list[dict[str, Any]]:
    """Keep each refused action as a request someone at the PC can approve (D4).

    The same action with the same arguments twice in one command is kept once.
    """
    from grandpa.devices.approvals import queue

    pending: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in waiting:
        parameters = dict(entry.parameters or {})
        key = entry.action + repr(sorted(parameters.items()))
        if key in seen:
            continue
        seen.add(key)
        new_id = queue(
            store,
            device_id=device_id,
            action=entry.action,
            parameters=parameters,
            command=command,
        )
        pending.append({"id": new_id, "action": entry.action, "parameters": parameters})
    return pending
