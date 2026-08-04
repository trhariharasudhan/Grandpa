"""User-facing Gmail response formatting."""

from __future__ import annotations

from grandpa.gmail.models import GmailMessageSummary
from grandpa.gmail.safety import GmailSafetyPolicy


def format_message_cards(messages: tuple[GmailMessageSummary, ...]) -> str:
    if not messages:
        return "No Gmail messages matched."
    cards = []
    for message in messages:
        cards.append(
            "\n".join(
                [
                    f"Subject: {message.subject or '(no subject)'}",
                    f"From: {message.sender or 'Unknown'}",
                    f"Date: {message.date or 'Unknown'}",
                    f"Snippet: {message.snippet or '(no snippet)'}",
                    f"Attachments: {len(message.attachments)}",
                ]
            )
        )
    return "\n\n".join(cards)


def format_full_message(
    message: GmailMessageSummary, *, safety: GmailSafetyPolicy | None = None
) -> str:
    safety = safety or GmailSafetyPolicy()
    attachments = _format_attachments(message)
    return "\n".join(
        [
            f"Subject: {message.subject or '(no subject)'}",
            f"From: {message.sender or 'Unknown'}",
            f"To: {', '.join(message.recipients) if message.recipients else 'Unknown'}",
            f"Date: {message.date or 'Unknown'}",
            "",
            safety.sanitize_text(
                message.body or message.snippet or "(No readable body.)"
            ),
            "",
            attachments,
        ]
    ).strip()


def format_summary(
    messages: tuple[GmailMessageSummary, ...],
    *,
    safety: GmailSafetyPolicy | None = None,
) -> str:
    if not messages:
        return "No Gmail messages matched."
    safety = safety or GmailSafetyPolicy()
    lines = ["Summary:"]
    for message in messages[:5]:
        body = safety.summarize_body(message.body or message.snippet)
        lines.append(
            f"- {message.subject or '(no subject)'} from {message.sender or 'Unknown'}: {body[:350]}"
        )
    return "\n".join(lines)


def format_draft_preview(*, recipient: str, subject: str, body: str) -> str:
    return "\n".join(
        [
            "Draft created for review:",
            f"To: {recipient or '(recipient needed)'}",
            f"Subject: {subject or '(no subject)'}",
            "",
            body or "(empty body)",
        ]
    )


def _format_attachments(message: GmailMessageSummary) -> str:
    if not message.attachments:
        return "Attachments: none"
    lines = ["Attachments:"]
    for attachment in message.attachments:
        suffix = (
            " (blocked executable/script type)" if attachment.get("blocked") else ""
        )
        lines.append(
            f"- {attachment.get('filename', 'attachment')} "
            f"{attachment.get('mime_type', '')} "
            f"{attachment.get('size', 0)} bytes{suffix}".strip()
        )
    return "\n".join(lines)


__all__ = [
    "format_draft_preview",
    "format_full_message",
    "format_message_cards",
    "format_summary",
]
