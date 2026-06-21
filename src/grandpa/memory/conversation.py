"""Short-term conversation session memory.

This module intentionally keeps only in-process session context. It does not
write to long-term memory, build embeddings, or call an LLM.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

MAX_CONVERSATION_MESSAGES = 20


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class ConversationMessage:
    role: str
    content: str
    timestamp: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, str]:
        return {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp,
        }


@dataclass
class ConversationSession:
    """Short-term conversation context capped to recent messages."""

    session_id: str = field(default_factory=lambda: str(uuid4()))
    created_at: str = field(default_factory=_now_iso)
    last_updated_at: str = field(default_factory=_now_iso)
    messages: list[ConversationMessage] = field(default_factory=list)

    def add_user_message(self, content: str) -> dict[str, Any]:
        return self._add_message("user", content)

    def add_assistant_message(self, content: str) -> dict[str, Any]:
        return self._add_message("assistant", content)

    def history(self) -> dict[str, Any]:
        return {
            **self.status(),
            "messages": [message.to_dict() for message in self.messages],
        }

    def clear(self) -> dict[str, Any]:
        cleared = len(self.messages)
        self.messages.clear()
        self.last_updated_at = _now_iso()
        return {
            **self.status(),
            "status": "cleared",
            "cleared": cleared,
        }

    def summary(self) -> dict[str, Any]:
        if not self.messages:
            text = "No recent conversation yet."
        else:
            pairs = [
                f"{message.role}: {message.content}"
                for message in self.messages[-6:]
                if message.content.strip()
            ]
            text = "Recent conversation: " + " | ".join(pairs)
        return {
            **self.status(),
            "summary": text,
        }

    def status(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "message_count": len(self.messages),
            "created_at": self.created_at,
            "last_updated_at": self.last_updated_at,
        }

    def _add_message(self, role: str, content: str) -> dict[str, Any]:
        text = content.strip()
        if not text:
            return self.status()
        message = ConversationMessage(role=role, content=text)
        self.messages.append(message)
        if len(self.messages) > MAX_CONVERSATION_MESSAGES:
            self.messages = self.messages[-MAX_CONVERSATION_MESSAGES:]
        self.last_updated_at = message.timestamp
        return message.to_dict()


__all__ = [
    "MAX_CONVERSATION_MESSAGES",
    "ConversationMessage",
    "ConversationSession",
]
