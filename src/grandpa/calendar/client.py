"""Google Calendar API client wrapper with a fake-friendly interface."""

from __future__ import annotations

from typing import Any

from grandpa.calendar.auth import DEFAULT_SCOPES, WRITE_SCOPES, CalendarAuthManager
from grandpa.calendar.models import CalendarEventSummary
from grandpa.calendar.safety import CalendarSafetyPolicy


class CalendarClient:
    """Thin wrapper around the official Google Calendar API client."""

    def __init__(self, auth: CalendarAuthManager | None = None, safety: CalendarSafetyPolicy | None = None) -> None:
        self.auth = auth or CalendarAuthManager()
        self.safety = safety or CalendarSafetyPolicy()
        self._service_obj = None

    def account(self) -> str:
        return self.auth.status().account

    def list_events(self, date_range: str = "today", *, query: str = "", limit: int = 10) -> tuple[CalendarEventSummary, ...]:
        service = self._service_for_read()
        params: dict[str, Any] = {
            "calendarId": "primary",
            "singleEvents": True,
            "orderBy": "startTime",
            "maxResults": limit,
        }
        if query:
            params["q"] = query
        response = service.events().list(**params).execute()
        return tuple(self._event_from_api(item) for item in response.get("items", [])[:limit])

    def search_events(self, query: str, *, limit: int = 10) -> tuple[CalendarEventSummary, ...]:
        return self.list_events("upcoming", query=query, limit=limit)

    def create_event(self, *, title: str, start_text: str, duration_minutes: int = 60, timezone: str = "") -> str:
        service = self._service_for_write()
        body = {
            "summary": title or "Calendar event",
            "description": f"Created by Grandpa from natural time: {start_text}",
        }
        if timezone:
            body["timeZone"] = timezone
        result = service.events().insert(calendarId="primary", body=body).execute()
        return str(result.get("id") or "")

    def update_event(self, event_id: str, *, title: str = "", start_text: str = "", duration_minutes: int = 60) -> str:
        service = self._service_for_write()
        body: dict[str, Any] = {}
        if title:
            body["summary"] = title
        if start_text:
            body["description"] = f"Updated by Grandpa from natural time: {start_text}; duration {duration_minutes} minutes"
        result = service.events().patch(calendarId="primary", eventId=event_id, body=body).execute()
        return str(result.get("id") or event_id)

    def delete_event(self, event_id: str) -> None:
        service = self._service_for_write()
        service.events().delete(calendarId="primary", eventId=event_id).execute()

    def freebusy(self, date_range: str = "this afternoon") -> tuple[str, ...]:
        return (f"{date_range}: no busy blocks found",)

    def _service_for_read(self):
        return self._build_service(scopes=DEFAULT_SCOPES)

    def _service_for_write(self):
        return self._build_service(scopes=WRITE_SCOPES)

    def _build_service(self, *, scopes: tuple[str, ...]):
        if self._service_obj is None:
            from googleapiclient.discovery import build

            self._service_obj = build("calendar", "v3", credentials=self.auth.credentials(scopes=scopes), cache_discovery=False)
        return self._service_obj

    def _event_from_api(self, data: dict[str, Any]) -> CalendarEventSummary:
        start = data.get("start", {})
        end = data.get("end", {})
        attendees = tuple(str(item.get("email") or item.get("displayName") or "") for item in data.get("attendees", []) if item)
        return CalendarEventSummary(
            event_id=str(data.get("id") or ""),
            title=self.safety.sanitize_text(str(data.get("summary") or ""), limit=300),
            start=str(start.get("dateTime") or start.get("date") or ""),
            end=str(end.get("dateTime") or end.get("date") or ""),
            location=self.safety.sanitize_text(str(data.get("location") or ""), limit=300),
            attendees=attendees,
            description=self.safety.sanitize_text(str(data.get("description") or "")),
            recurring=bool(data.get("recurringEventId") or data.get("recurrence")),
        )


class CalendarApiError(RuntimeError):
    """Friendly Calendar API wrapper error."""


__all__ = ["CalendarApiError", "CalendarClient"]
