"""Gmail API client wrapper with a small fake-friendly interface."""

from __future__ import annotations

import base64
from email.message import EmailMessage
from typing import Any

from grandpa.gmail.auth import DEFAULT_SCOPES, WRITE_SCOPES, GmailAuthManager
from grandpa.gmail.models import GmailMessageSummary
from grandpa.gmail.safety import GmailSafetyPolicy


class GmailClient:
    """Thin wrapper around the official Gmail API client."""

    def __init__(self, auth: GmailAuthManager | None = None, safety: GmailSafetyPolicy | None = None) -> None:
        self.auth = auth or GmailAuthManager()
        self.safety = safety or GmailSafetyPolicy()
        self._service_obj = None

    def account(self) -> str:
        return self.auth.status().account

    def list_messages(self, query: str = "", *, limit: int = 10) -> tuple[GmailMessageSummary, ...]:
        service = self._service_for_read()
        response = service.users().messages().list(userId="me", q=query, maxResults=limit).execute()
        messages = []
        for item in response.get("messages", [])[:limit]:
            messages.append(self.get_message(str(item["id"])))
        return tuple(messages)

    def get_message(self, selector: str = "latest") -> GmailMessageSummary:
        if selector == "latest":
            found = self.list_messages("", limit=1)
            if not found:
                raise GmailApiError("No Gmail messages matched.")
            return found[0]
        service = self._service_for_read()
        data = service.users().messages().get(userId="me", id=selector, format="full").execute()
        return self._message_from_api(data)

    def labels(self) -> tuple[str, ...]:
        service = self._service_for_read()
        response = service.users().labels().list(userId="me").execute()
        return tuple(str(item.get("name") or "") for item in response.get("labels", []) if item.get("name"))

    def create_draft(self, *, to: str, subject: str, body: str) -> str:
        service = self._service_for_write()
        message = EmailMessage()
        message["To"] = to
        message["Subject"] = subject or "(no subject)"
        message.set_content(body or "")
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
        result = service.users().drafts().create(userId="me", body={"message": {"raw": raw}}).execute()
        return str(result.get("id") or "")

    def send_draft(self, draft_id: str = "") -> str:
        service = self._service_for_write()
        result = service.users().drafts().send(userId="me", body={"id": draft_id}).execute()
        return str(result.get("id") or "")

    def archive(self, message_ids: tuple[str, ...]) -> int:
        return self._modify(message_ids, remove_labels=("INBOX",))

    def trash(self, message_ids: tuple[str, ...]) -> int:
        service = self._service_for_write()
        for message_id in message_ids:
            service.users().messages().trash(userId="me", id=message_id).execute()
        return len(message_ids)

    def add_label(self, message_ids: tuple[str, ...], label: str) -> int:
        return self._modify(message_ids, add_labels=(label,))

    def _modify(self, message_ids: tuple[str, ...], *, add_labels: tuple[str, ...] = (), remove_labels: tuple[str, ...] = ()) -> int:
        service = self._service_for_write()
        for message_id in message_ids:
            service.users().messages().modify(
                userId="me",
                id=message_id,
                body={"addLabelIds": list(add_labels), "removeLabelIds": list(remove_labels)},
            ).execute()
        return len(message_ids)

    def _service_for_read(self):
        return self._build_service(scopes=DEFAULT_SCOPES)

    def _service_for_write(self):
        return self._build_service(scopes=WRITE_SCOPES)

    def _build_service(self, *, scopes: tuple[str, ...]):
        if self._service_obj is None:
            from googleapiclient.discovery import build

            self._service_obj = build("gmail", "v1", credentials=self.auth.credentials(scopes=scopes), cache_discovery=False)
        return self._service_obj

    def _message_from_api(self, data: dict[str, Any]) -> GmailMessageSummary:
        headers = {item.get("name", "").casefold(): item.get("value", "") for item in data.get("payload", {}).get("headers", [])}
        body = _extract_body(data.get("payload", {}))
        attachments = []
        for part in _walk_parts(data.get("payload", {})):
            filename = str(part.get("filename") or "")
            if filename:
                attachments.append(
                    {
                        "filename": filename,
                        "mime_type": str(part.get("mimeType") or ""),
                        "size": int(part.get("body", {}).get("size") or 0),
                        "blocked": self.safety.attachment_is_blocked(filename),
                    }
                )
        return GmailMessageSummary(
            message_id=str(data.get("id") or ""),
            thread_id=str(data.get("threadId") or ""),
            subject=self.safety.sanitize_text(headers.get("subject", ""), limit=300),
            sender=self.safety.sanitize_text(headers.get("from", ""), limit=300),
            recipients=(self.safety.sanitize_text(headers.get("to", ""), limit=500),) if headers.get("to") else (),
            date=str(headers.get("date") or ""),
            snippet=self.safety.sanitize_text(str(data.get("snippet") or ""), limit=500),
            body=self.safety.sanitize_text(body),
            labels=tuple(str(item) for item in data.get("labelIds") or ()),
            attachments=tuple(attachments),
        )


def _walk_parts(payload: dict[str, Any]):
    yield payload
    for part in payload.get("parts") or ():
        yield from _walk_parts(part)


def _extract_body(payload: dict[str, Any]) -> str:
    chunks = []
    for part in _walk_parts(payload):
        data = part.get("body", {}).get("data")
        if data:
            try:
                chunks.append(base64.urlsafe_b64decode(data.encode("ascii")).decode("utf-8", errors="replace"))
            except Exception:
                continue
    return "\n".join(chunks)


class GmailApiError(RuntimeError):
    """Friendly Gmail API wrapper error."""


__all__ = ["GmailApiError", "GmailClient"]
