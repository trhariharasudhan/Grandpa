"""Conversation state for Grandpa voice sessions."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

VoiceState = Literal["idle", "listening", "thinking", "speaking", "error"]


@dataclass(frozen=True)
class VoiceMessage:
    role: str
    content: str
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }


@dataclass
class VoiceConversation:
    session_id: str = field(default_factory=lambda: f"voice_{uuid.uuid4().hex[:12]}")
    active: bool = False
    state: VoiceState = "idle"
    context_window: int = 12
    current_task: str = ""
    current_goal: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    messages: list[VoiceMessage] = field(default_factory=list)

    def start(self) -> None:
        self.active = True
        self.state = "idle"
        self.touch()

    def stop(self) -> None:
        self.active = False
        self.state = "idle"
        self.current_task = ""
        self.touch()

    def set_state(self, state: VoiceState) -> None:
        self.state = state
        self.touch()

    def add_message(self, role: str, content: str, metadata: dict[str, Any] | None = None) -> None:
        if content:
            self.messages.append(VoiceMessage(role=role, content=content, metadata=metadata or {}))
            if len(self.messages) > self.context_window:
                self.messages = self.messages[-self.context_window :]
        self.touch()

    def touch(self) -> None:
        self.updated_at = time.time()

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "active": self.active,
            "state": self.state,
            "context_window": self.context_window,
            "current_task": self.current_task,
            "current_goal": self.current_goal,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_messages": [message.to_dict() for message in self.messages[-self.context_window :]],
        }


__all__ = ["VoiceConversation", "VoiceMessage", "VoiceState"]
