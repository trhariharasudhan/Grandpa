"""Models for Grandpa's safe Gmail integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

GmailActionType = Literal[
    "status",
    "setup",
    "disconnect",
    "list",
    "search",
    "read",
    "summarize",
    "draft",
    "send",
    "reply",
    "forward",
    "archive",
    "label",
    "trash",
    "labels",
]

GmailActionStatus = Literal[
    "handled",
    "needs_confirmation",
    "blocked",
    "unsupported",
    "not_configured",
    "no_match",
    "error",
]


@dataclass(frozen=True)
class GmailAction:
    """Parsed Gmail command."""

    action: GmailActionType
    query: str = ""
    selector: str = ""
    recipient: str = ""
    subject: str = ""
    body: str = ""
    label: str = ""
    bulk: bool = False
    args: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GmailMessageSummary:
    """Safe compact representation of one Gmail message."""

    message_id: str
    thread_id: str = ""
    subject: str = ""
    sender: str = ""
    recipients: tuple[str, ...] = ()
    date: str = ""
    snippet: str = ""
    body: str = ""
    labels: tuple[str, ...] = ()
    attachments: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class GmailResult:
    """User-facing Gmail result."""

    status: GmailActionStatus
    message: str
    action: GmailAction | None = None
    messages: tuple[GmailMessageSummary, ...] = ()
    requires_confirmation: bool = False
    account: str = ""
    error: str | None = None

    @property
    def should_fallback(self) -> bool:
        return self.status == "no_match"


__all__ = [
    "GmailAction",
    "GmailActionStatus",
    "GmailActionType",
    "GmailMessageSummary",
    "GmailResult",
]
