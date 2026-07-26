"""Safe Gmail automation facade."""

from __future__ import annotations

from collections.abc import Callable

from grandpa.gmail.auth import (
    GmailAuthManager,
    GmailDependencyError,
    GmailNotConfiguredError,
)
from grandpa.gmail.client import GmailApiError, GmailClient
from grandpa.gmail.formatter import (
    format_draft_preview,
    format_full_message,
    format_message_cards,
    format_summary,
)
from grandpa.gmail.models import GmailAction, GmailResult
from grandpa.gmail.parser import GmailParser
from grandpa.gmail.safety import GmailSafetyPolicy

ConfirmationCallback = Callable[[GmailAction], bool]


class GmailAutomation:
    """Parse and execute Gmail commands through a safe client facade."""

    def __init__(
        self,
        parser: GmailParser | None = None,
        client: object | None = None,
        safety: GmailSafetyPolicy | None = None,
        auth: GmailAuthManager | None = None,
    ) -> None:
        self.parser = parser or GmailParser()
        self.safety = safety or GmailSafetyPolicy()
        self.auth = auth or GmailAuthManager()
        self.client = client or GmailClient(auth=self.auth, safety=self.safety)

    def handle(
        self,
        text: str,
        *,
        confirmed: bool = False,
        confirm: ConfirmationCallback | None = None,
    ) -> GmailResult:
        action = self.parser.parse(text)
        if action is None:
            return GmailResult("no_match", "")
        return self.execute(action, confirmed=confirmed, confirm=confirm)

    def execute(
        self,
        action: GmailAction,
        *,
        confirmed: bool = False,
        confirm: ConfirmationCallback | None = None,
    ) -> GmailResult:
        try:
            if action.action == "status":
                status = self.auth.status()
                result_status = "handled" if status.ready else "not_configured"
                return GmailResult(result_status, status.message, action, account=status.account)
            if action.action == "setup":
                status = self.auth.setup()
                result_status = "handled" if status.ready else "not_configured"
                return GmailResult(result_status, status.message, action, account=status.account)
            if action.action == "disconnect":
                removed = self.auth.disconnect()
                message = "Gmail disconnected." if removed else "Gmail was not connected."
                return GmailResult("handled", message, action)
            if action.args.get("permanent_delete_blocked"):
                return GmailResult(
                    "blocked",
                    "Permanent Gmail deletion is blocked. You can move an email to Trash instead.",
                    action,
                )
            if self._needs_confirmation(action, confirmed=confirmed, confirm=confirm):
                return GmailResult(
                    "needs_confirmation",
                    _confirmation_message(action),
                    action,
                    requires_confirmation=True,
                    account=_client_account(self.client),
                )
            return self._execute_connected(action)
        except (GmailDependencyError, GmailNotConfiguredError) as exc:
            return GmailResult("not_configured", str(exc), action, error=str(exc))
        except GmailApiError as exc:
            return GmailResult("error", str(exc), action, error=str(exc))
        except Exception as exc:
            return GmailResult("error", f"Gmail action failed: {exc}", action, error=str(exc))

    def _execute_connected(self, action: GmailAction) -> GmailResult:
        account = _client_account(self.client)
        if action.action in {"list", "search"}:
            messages = tuple(self.client.list_messages(action.query, limit=10))  # type: ignore[attr-defined]
            if action.args.get("count_only"):
                return GmailResult("handled", f"Unread emails: {len(messages)}", action, messages, account=account)
            return GmailResult("handled", format_message_cards(messages), action, messages, account=account)
        if action.action == "read":
            message = self._selected_message(action)
            return GmailResult("handled", format_full_message(message, safety=self.safety), action, (message,), account=account)
        if action.action == "summarize":
            messages = self._messages_for_summary(action)
            return GmailResult("handled", format_summary(messages, safety=self.safety), action, messages, account=account)
        if action.action == "labels":
            labels = tuple(self.client.labels())  # type: ignore[attr-defined]
            text = "Gmail labels:\n" + "\n".join(f"- {label}" for label in labels) if labels else "No Gmail labels found."
            return GmailResult("handled", text, action, account=account)
        if action.action == "draft":
            draft_id = self.client.create_draft(to=action.recipient, subject=action.subject, body=action.body)  # type: ignore[attr-defined]
            preview = format_draft_preview(recipient=action.recipient, subject=action.subject, body=action.body)
            return GmailResult("handled", f"{preview}\n\nDraft saved.", action, account=account, error=draft_id)
        if action.action == "send":
            sent_id = self.client.send_draft(action.selector if action.selector != "draft" else "")  # type: ignore[attr-defined]
            return GmailResult("handled", "Email sent.", action, account=account, error=sent_id)
        if action.action in {"reply", "forward"}:
            method = getattr(self.client, action.action, None)
            if callable(method):
                method(action.selector or "latest", action.body)
            message = "Reply sent." if action.action == "reply" else "Email forwarded."
            return GmailResult("handled", message, action, account=account)
        if action.action == "archive":
            messages = self._messages_for_write(action)
            count = self.client.archive(tuple(message.message_id for message in messages))  # type: ignore[attr-defined]
            return GmailResult("handled", f"Archived {count} email{'s' if count != 1 else ''}.", action, messages, account=account)
        if action.action == "label":
            if action.args.get("create"):
                return GmailResult("handled", f'Label "{action.label}" is ready.', action, account=account)
            messages = self._messages_for_write(action)
            count = self.client.add_label(tuple(message.message_id for message in messages), action.label)  # type: ignore[attr-defined]
            return GmailResult("handled", f'Labeled {count} email{"s" if count != 1 else ""} as {action.label}.', action, messages, account=account)
        if action.action == "trash":
            messages = self._messages_for_write(action)
            count = self.client.trash(tuple(message.message_id for message in messages))  # type: ignore[attr-defined]
            return GmailResult("handled", f"Moved {count} email{'s' if count != 1 else ''} to Trash.", action, messages, account=account)
        return GmailResult("unsupported", "That Gmail action is not supported yet.", action, account=account)

    def _needs_confirmation(self, action: GmailAction, *, confirmed: bool, confirm: ConfirmationCallback | None) -> bool:
        if not self.safety.requires_confirmation(action.action, bulk=action.bulk):
            return False
        if confirmed:
            return False
        if confirm is not None:
            return not confirm(action)
        return True

    def _selected_message(self, action: GmailAction):
        if action.query:
            messages = tuple(self.client.list_messages(action.query, limit=1))  # type: ignore[attr-defined]
            if not messages:
                raise GmailApiError("No Gmail messages matched.")
            return messages[0]
        return self.client.get_message(action.selector or "latest")  # type: ignore[attr-defined]

    def _messages_for_summary(self, action: GmailAction):
        if action.selector and not action.query:
            return (self._selected_message(action),)
        return tuple(self.client.list_messages(action.query, limit=5))  # type: ignore[attr-defined]

    def _messages_for_write(self, action: GmailAction):
        if action.query:
            return tuple(self.client.list_messages(action.query, limit=10))  # type: ignore[attr-defined]
        return (self.client.get_message(action.selector or "latest"),)  # type: ignore[attr-defined]


def handle_gmail_command(
    text: str,
    *,
    client: object | None = None,
    confirmed: bool = False,
    confirm: ConfirmationCallback | None = None,
    auth: GmailAuthManager | None = None,
) -> GmailResult:
    return GmailAutomation(client=client, auth=auth).handle(text, confirmed=confirmed, confirm=confirm)


def _client_account(client: object) -> str:
    account_method = getattr(client, "account", None)
    if callable(account_method):
        return str(account_method() or "")
    return ""


def _confirmation_message(action: GmailAction) -> str:
    if action.action == "send":
        return "Send this email? [y/N]"
    if action.action == "trash":
        return "Move this email to Trash? [y/N]"
    if action.action == "archive":
        return "Archive these emails? [y/N]" if action.bulk else "Archive this email? [y/N]"
    if action.action == "label":
        return f'Apply label "{action.label}" to these emails? [y/N]' if action.bulk else f'Apply label "{action.label}"? [y/N]'
    if action.action == "reply":
        return "Reply to this email? [y/N]"
    if action.action == "forward":
        return "Forward this email? [y/N]"
    return "Confirm Gmail action? [y/N]"


__all__ = ["GmailAutomation", "handle_gmail_command"]
