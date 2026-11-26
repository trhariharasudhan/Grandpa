"""The states the avatar window shows, and the messages that carry them.

Phase A's presence is a web page (pywebview + Three.js) driven from Python over
a local WebSocket. This module is the contract between the two: the state names
the page animates, and the JSON shape of every message, so the page and the
server cannot drift apart without a test noticing.

Eight states, from the Stage 2 spec. Each is *shown*, never guessed:

* ``idle``      -- nothing in flight.
* ``listening`` -- a microphone is recording (voice arrives in Phase B).
* ``thinking``  -- a request is being routed or the model is answering.
* ``speaking``  -- a reply is being read aloud (visemes ride along, Phase A4).
* ``working``   -- a catalogued action is running right now, from the action
  layer's own TOOL_CALL_START/END announcements.
* ``done``      -- an operation finished (the bubble's "success" rule).
* ``error``     -- the reply was a failure or refusal.
* ``confirm``   -- Grandpa asked a yes/no question before acting.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

PROTOCOL_VERSION = 1


class AvatarState(StrEnum):
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    WORKING = "working"
    DONE = "done"
    ERROR = "error"
    CONFIRM = "confirm"


STATE_LABELS: dict[AvatarState, str] = {
    AvatarState.IDLE: "Standby",
    AvatarState.LISTENING: "Listening",
    AvatarState.THINKING: "Thinking...",
    AvatarState.SPEAKING: "Speaking...",
    AvatarState.WORKING: "Working...",
    AvatarState.DONE: "Done",
    AvatarState.ERROR: "Error",
    AvatarState.CONFIRM: "Waiting for your yes or no",
}


def _colours() -> dict[AvatarState, str]:
    """The bubble's palette, so the orb means the same colour in both UIs."""
    from grandpa.ui import palette

    return {
        AvatarState.IDLE: palette.NEUTRAL_WHITE,
        AvatarState.LISTENING: palette.BLUE_LISTENING,
        AvatarState.THINKING: palette.YELLOW_PROCESSING,
        AvatarState.SPEAKING: palette.ORANGE_SPEAKING,
        AvatarState.WORKING: palette.PURPLE_EXECUTING,
        AvatarState.DONE: palette.GREEN_SUCCESS,
        AvatarState.ERROR: palette.RED_ERROR,
        AvatarState.CONFIRM: palette.AMBER_UNREAD,
    }


STATE_COLOURS: dict[AvatarState, str] = _colours()


@dataclass(frozen=True, slots=True)
class StateMessage:
    """``{"type": "state", ...}`` -- what the orb should look like now."""

    state: AvatarState
    label: str = ""
    action: str = ""
    """The catalogued action running, for ``working``."""
    question: str = ""
    """What Grandpa asked, for ``confirm``."""
    visemes: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    """Mouth shapes for ``speaking``: ``{"t": ms, "v": viseme, "w": 0..1}`` from
    :func:`grandpa.ui.lipsync.build_track`, ``t`` counted from playback start."""
    speech_start_ms: float = 0.0
    """When playback starts, in ms since the epoch (this PC's clock), for
    ``speaking``. The page plays the track against ``Date.now()`` minus this."""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["state"] = str(self.state)
        data["label"] = self.label or STATE_LABELS[self.state]
        data["visemes"] = list(self.visemes)
        data["colour"] = STATE_COLOURS[self.state]
        return {"type": "state", "v": PROTOCOL_VERSION, **data}


@dataclass(frozen=True, slots=True)
class ChatMessage:
    """``{"type": "chat", "role": "user"|"grandpa", "text": ...}``."""

    role: str
    text: str
    failed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"type": "chat", "v": PROTOCOL_VERSION, **asdict(self)}


@dataclass(frozen=True, slots=True)
class ModeMessage:
    """``{"type": "mode", "character": bool, "reason": ...}`` (A7).

    ``character`` false: show the ring only, never the 3D character, for the
    rest of this run. Sent when the avatar goes over its GPU or memory budget
    (or ``--orb-only``), so the PC stays fast while Ollama works.
    """

    character: bool = True
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"type": "mode", "v": PROTOCOL_VERSION, **asdict(self)}


def encode(
    message: StateMessage | ChatMessage | ModeMessage | dict[str, Any],
) -> str:
    payload = message if isinstance(message, dict) else message.to_dict()
    return json.dumps(payload, ensure_ascii=False)


MAX_INBOUND_TEXT = 2000
"""Longest line the page may send. A typed request, not a document."""


def parse_inbound(raw: str | bytes) -> tuple[str, str] | None:
    """``(kind, text)`` for a message the page sent, or ``None`` if invalid.

    The page may send exactly two things:

    * ``{"type": "send", "text": "..."}`` -- a typed line, or Yes/No;
    * ``{"type": "talk"}`` -- click-to-talk (A6): listen for one spoken line,
      which then goes the same way as a typed one. It carries nothing else.

    Anything else -- unknown types, missing or non-string text, oversize lines
    -- is dropped, so the socket cannot become a second, looser way in.
    """
    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError:
            return None
    if len(raw) > MAX_INBOUND_TEXT * 2:
        return None
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if isinstance(data, dict) and data.get("type") == "talk" and len(data) == 1:
        return ("talk", "")
    # The desktop app's Stop button: cancels the reply being written. Like
    # "talk" it carries nothing, and it can only stop work, never start any.
    if isinstance(data, dict) and data.get("type") == "cancel" and len(data) == 1:
        return ("cancel", "")
    if not isinstance(data, dict) or data.get("type") != "send":
        return None
    text = data.get("text")
    if not isinstance(text, str):
        return None
    text = text.strip()
    if not text or len(text) > MAX_INBOUND_TEXT:
        return None
    return ("send", text)


__all__ = [
    "AvatarState",
    "ChatMessage",
    "MAX_INBOUND_TEXT",
    "ModeMessage",
    "PROTOCOL_VERSION",
    "STATE_COLOURS",
    "STATE_LABELS",
    "StateMessage",
    "encode",
    "parse_inbound",
]
