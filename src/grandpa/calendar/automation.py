"""Safe Google Calendar automation facade."""

from __future__ import annotations

from collections.abc import Callable

from grandpa.calendar.auth import (
    CalendarAuthManager,
    CalendarDependencyError,
    CalendarNotConfiguredError,
)
from grandpa.calendar.client import CalendarApiError, CalendarClient
from grandpa.calendar.formatter import (
    format_event_list,
    format_event_preview,
    format_freebusy,
)
from grandpa.calendar.models import CalendarAction, CalendarResult
from grandpa.calendar.parser import CalendarParser
from grandpa.calendar.safety import CalendarSafetyPolicy

ConfirmationCallback = Callable[[CalendarAction], bool]


class CalendarAutomation:
    """Parse and execute Calendar commands through a safe client facade."""

    def __init__(
        self,
        parser: CalendarParser | None = None,
        client: object | None = None,
        safety: CalendarSafetyPolicy | None = None,
        auth: CalendarAuthManager | None = None,
    ) -> None:
        self.parser = parser or CalendarParser()
        self.safety = safety or CalendarSafetyPolicy()
        self.auth = auth or CalendarAuthManager()
        self.client = client or CalendarClient(auth=self.auth, safety=self.safety)

    def handle(
        self,
        text: str,
        *,
        confirmed: bool = False,
        confirm: ConfirmationCallback | None = None,
    ) -> CalendarResult:
        action = self.parser.parse(text)
        if action is None:
            return CalendarResult("no_match", "")
        return self.execute(action, confirmed=confirmed, confirm=confirm)

    def execute(
        self,
        action: CalendarAction,
        *,
        confirmed: bool = False,
        confirm: ConfirmationCallback | None = None,
    ) -> CalendarResult:
        try:
            if action.action == "status":
                status = self.auth.status()
                result_status = "handled" if status.ready else "not_configured"
                return CalendarResult(
                    result_status, status.message, action, account=status.account
                )
            if action.action == "setup":
                status = self.auth.setup()
                result_status = "handled" if status.ready else "not_configured"
                return CalendarResult(
                    result_status, status.message, action, account=status.account
                )
            if action.action == "disconnect":
                removed = self.auth.disconnect()
                message = (
                    "Google Calendar disconnected."
                    if removed
                    else "Google Calendar was not connected."
                )
                return CalendarResult("handled", message, action)
            if action.args.get("auto_accept_blocked"):
                return CalendarResult(
                    "blocked",
                    "Grandpa will not auto-accept calendar invitations.",
                    action,
                )
            if self._needs_confirmation(action, confirmed=confirmed, confirm=confirm):
                return CalendarResult(
                    "needs_confirmation",
                    _confirmation_message(action),
                    action,
                    requires_confirmation=True,
                    account=_client_account(self.client),
                )
            return self._execute_connected(action)
        except (CalendarDependencyError, CalendarNotConfiguredError) as exc:
            return CalendarResult("not_configured", str(exc), action, error=str(exc))
        except CalendarApiError as exc:
            return CalendarResult("error", str(exc), action, error=str(exc))
        except Exception as exc:
            return CalendarResult(
                "error", f"Calendar action failed: {exc}", action, error=str(exc)
            )

    def _execute_connected(self, action: CalendarAction) -> CalendarResult:
        account = _client_account(self.client)
        if action.action in {"list", "upcoming"}:
            events = tuple(
                self.client.list_events(
                    action.date_range or action.action, query=action.query, limit=10
                )
            )  # type: ignore[attr-defined]
            return CalendarResult(
                "handled", format_event_list(events), action, events, account=account
            )
        if action.action == "search":
            events = tuple(self.client.search_events(action.query, limit=10))  # type: ignore[attr-defined]
            return CalendarResult(
                "handled",
                format_event_list(
                    events, empty_message="No matching calendar events found."
                ),
                action,
                events,
                account=account,
            )
        if action.action == "freebusy":
            slots = tuple(self.client.freebusy(action.date_range or "this afternoon"))  # type: ignore[attr-defined]
            return CalendarResult(
                "handled", format_freebusy(slots), action, account=account
            )
        if action.action == "create":
            event_id = self.client.create_event(  # type: ignore[attr-defined]
                title=action.title,
                start_text=action.start_text,
                duration_minutes=action.duration_minutes,
                timezone=action.timezone,
            )
            preview = format_event_preview(
                title=action.title,
                start_text=action.start_text,
                duration_minutes=action.duration_minutes,
            )
            return CalendarResult(
                "handled",
                f"{preview}\n\nCalendar event created.",
                action,
                account=account,
                error=event_id,
            )
        if action.action == "update":
            event = self._event_for_write(action)
            event_id = self.client.update_event(  # type: ignore[attr-defined]
                event.event_id,
                title=action.title,
                start_text=action.start_text,
                duration_minutes=action.duration_minutes,
            )
            return CalendarResult(
                "handled",
                "Calendar event updated.",
                action,
                (event,),
                account=account,
                error=event_id,
            )
        if action.action == "delete":
            event = self._event_for_write(action)
            self.client.delete_event(event.event_id)  # type: ignore[attr-defined]
            return CalendarResult(
                "handled", "Calendar event deleted.", action, (event,), account=account
            )
        return CalendarResult(
            "unsupported",
            "That Calendar action is not supported yet.",
            action,
            account=account,
        )

    def _needs_confirmation(
        self,
        action: CalendarAction,
        *,
        confirmed: bool,
        confirm: ConfirmationCallback | None,
    ) -> bool:
        if not self.safety.requires_confirmation(
            action.action, recurring=bool(action.args.get("recurring"))
        ):
            return False
        if confirmed:
            return False
        if confirm is not None:
            return not confirm(action)
        return True

    def _event_for_write(self, action: CalendarAction):
        events = tuple(
            self.client.search_events(
                action.query or action.title or "meeting", limit=1
            )
        )  # type: ignore[attr-defined]
        if not events:
            raise CalendarApiError("No matching calendar event found.")
        event = events[0]
        if event.recurring and not action.args.get("recurring_confirmed"):
            raise CalendarApiError(
                "This appears to be a recurring event. Please confirm the exact event before modifying it."
            )
        return event


def handle_calendar_command(
    text: str,
    *,
    client: object | None = None,
    confirmed: bool = False,
    confirm: ConfirmationCallback | None = None,
    auth: CalendarAuthManager | None = None,
) -> CalendarResult:
    return CalendarAutomation(client=client, auth=auth).handle(
        text, confirmed=confirmed, confirm=confirm
    )


def _client_account(client: object) -> str:
    account_method = getattr(client, "account", None)
    if callable(account_method):
        return str(account_method() or "")
    return ""


def _confirmation_message(action: CalendarAction) -> str:
    if action.action == "create":
        return "Create this Calendar event? [y/N]"
    if action.action == "update":
        return "Update this Calendar event? [y/N]"
    if action.action == "delete":
        return "Delete this Calendar event? [y/N]"
    return "Confirm Calendar action? [y/N]"


__all__ = ["CalendarAutomation", "handle_calendar_command"]
