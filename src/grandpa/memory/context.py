"""Deterministic short-term conversation context building."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from grandpa.memory.conversation import ConversationSession


@dataclass(frozen=True)
class ConversationContextBuilder:
    """Build a bounded recent-message context from short-term memory."""

    session: ConversationSession
    max_messages: int = 6
    max_chars: int = 2000

    def build(self) -> dict[str, Any]:
        max_messages = max(0, int(self.max_messages))
        max_chars = max(0, int(self.max_chars))
        source_messages = [
            message
            for message in self.session.messages
            if message.content and message.content.strip()
        ]
        if max_messages:
            source_messages = source_messages[-max_messages:]
        else:
            source_messages = []

        selected: list[dict[str, str]] = []
        total_chars = 0
        for message in reversed(source_messages):
            content = message.content.strip()
            line = f"{message.role}: {content}"
            projected = total_chars + len(line) + (1 if selected else 0)
            if max_chars and projected > max_chars:
                remaining = max_chars - total_chars - (1 if selected else 0)
                if remaining <= len(f"{message.role}: "):
                    break
                content_limit = max(0, remaining - len(f"{message.role}: "))
                content = content[:content_limit].rstrip()
                if not content:
                    break
                line = f"{message.role}: {content}"
            selected.insert(
                0,
                {
                    "role": message.role,
                    "content": content,
                    "timestamp": message.timestamp,
                },
            )
            total_chars += len(line) + (1 if selected[:-1] else 0)
            if max_chars and total_chars >= max_chars:
                break

        context_text = "\n".join(
            f"{message['role']}: {message['content']}" for message in selected
        )
        return {
            "messages": selected,
            "context_text": context_text,
            "message_count": len(selected),
        }


__all__ = ["ConversationContextBuilder"]
