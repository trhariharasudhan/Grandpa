"""User-facing formatting for Calendar results."""

from __future__ import annotations

from grandpa.calendar.models import CalendarEventSummary
from grandpa.calendar.safety import CalendarSafetyPolicy


def format_event_list(events: tuple[CalendarEventSummary, ...], *, empty_message: str = "No calendar events found.") -> str:
    if not events:
        return empty_message
    lines = []
    for event in events:
        when = _format_when(event)
        location = f"\nLocation: {event.location}" if event.location else ""
        lines.append(f"{when}\n{event.title or '(untitled event)'}{location}")
    return "\n\n".join(lines)


def format_event_detail(event: CalendarEventSummary, *, safety: CalendarSafetyPolicy | None = None) -> str:
    policy = safety or CalendarSafetyPolicy()
    lines = [
        f"Title: {policy.sanitize_text(event.title, limit=300) or '(untitled event)'}",
        f"Start: {event.start or 'Unknown'}",
        f"End: {event.end or 'Unknown'}",
    ]
    if event.location:
        lines.append(f"Location: {policy.sanitize_text(event.location, limit=300)}")
    if event.attendees:
        lines.append("Attendees: " + ", ".join(policy.sanitize_text(attendee, limit=120) for attendee in event.attendees))
    if event.description:
        lines.append("\nDescription:\n" + policy.sanitize_text(event.description))
    return "\n".join(lines)


def format_freebusy(slots: tuple[str, ...]) -> str:
    if not slots:
        return "No free time found for that window."
    return "Free time:\n" + "\n".join(f"- {slot}" for slot in slots)


def format_event_preview(*, title: str, start_text: str, duration_minutes: int) -> str:
    return f"Calendar event preview:\nTitle: {title or 'Calendar event'}\nWhen: {start_text or 'Not specified'}\nDuration: {duration_minutes} minutes"


def _format_when(event: CalendarEventSummary) -> str:
    if event.start and event.end:
        return f"{event.start} - {event.end}"
    return event.start or event.end or "Time unknown"


__all__ = ["format_event_detail", "format_event_list", "format_event_preview", "format_freebusy"]
