"""Parser for safe Google Calendar commands."""

from __future__ import annotations

import re

from grandpa.calendar.models import CalendarAction


class CalendarParser:
    """Parse confident Calendar commands without invoking an LLM."""

    def parse(self, text: str) -> CalendarAction | None:
        raw = _clean(text)
        command = raw.casefold()
        if not command:
            return None
        return (
            self._parse_setup(command)
            or self._parse_read(command, raw)
            or self._parse_write(command, raw)
            or self._parse_freebusy(command, raw)
        )

    def _parse_setup(self, command: str) -> CalendarAction | None:
        if command in {"calendar setup", "google calendar setup", "connect calendar"}:
            return CalendarAction("setup")
        if command in {
            "calendar disconnect",
            "google calendar disconnect",
            "disconnect calendar",
        }:
            return CalendarAction("disconnect")
        if command in {"calendar status", "google calendar status"}:
            return CalendarAction("status")
        return None

    def _parse_read(self, command: str, raw: str) -> CalendarAction | None:
        if command in {
            "what is on my calendar today",
            "show today's schedule",
            "show todays schedule",
            "calendar today",
            "show calendar today",
        }:
            return CalendarAction("list", date_range="today")
        if command in {
            "what meetings do i have tomorrow",
            "calendar tomorrow",
            "show tomorrow's schedule",
            "show tomorrows schedule",
        }:
            return CalendarAction("list", date_range="tomorrow")
        if command in {
            "calendar week",
            "show this week calendar",
            "show calendar this week",
        }:
            return CalendarAction("list", date_range="week")
        if command in {
            "calendar upcoming",
            "upcoming calendar events",
            "show upcoming events",
        }:
            return CalendarAction("upcoming", date_range="upcoming")
        match = re.fullmatch(
            r"(?:search calendar for|find calendar events about|find meetings about) (.+)",
            command,
        )
        if match:
            query = raw[match.start(1) : match.end(1)]
            return CalendarAction("search", query=query)
        return None

    def _parse_write(self, command: str, raw: str) -> CalendarAction | None:
        match = re.fullmatch(
            r"(?:create|schedule|add) (?:a )?(?:meeting|event|reminder)(?: (.+))?",
            command,
        )
        if match:
            detail = raw[match.start(1) : match.end(1)] if match.group(1) else ""
            return CalendarAction(
                "create",
                title=_title_from_detail(detail),
                start_text=detail,
                args={"raw_detail": detail},
            )
        match = re.fullmatch(
            r"(?:move|reschedule|update) (?:my |the )?(?:meeting|event)(?: to )?(.+)",
            command,
        )
        if match:
            detail = raw[match.start(1) : match.end(1)]
            return CalendarAction(
                "update",
                query="meeting",
                start_text=detail,
                args={"raw_detail": detail},
            )
        match = re.fullmatch(
            r"(?:cancel|delete) (?:my |the )?(?:tomorrow's |tomorrows )?(?:meeting|event)(?: (.+))?",
            command,
        )
        if match:
            detail = raw[match.start(1) : match.end(1)] if match.group(1) else ""
            return CalendarAction(
                "delete",
                query=detail or "meeting",
                date_range="tomorrow" if "tomorrow" in command else "",
            )
        if "accept invitation" in command or "accept calendar invite" in command:
            return CalendarAction("update", args={"auto_accept_blocked": True})
        return None

    def _parse_freebusy(self, command: str, raw: str) -> CalendarAction | None:
        if command in {
            "show free time this afternoon",
            "calendar free",
            "show free time",
            "when am i free",
        }:
            return CalendarAction("freebusy", date_range="this afternoon")
        match = re.fullmatch(r"(?:show free time|when am i free) (.+)", command)
        if match:
            query = raw[match.start(1) : match.end(1)]
            return CalendarAction("freebusy", date_range=query)
        return None


def _title_from_detail(detail: str) -> str:
    cleaned = re.sub(
        r"\b(?:tomorrow|today|at|on|for|friday|monday|tuesday|wednesday|thursday|saturday|sunday|\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\b",
        " ",
        detail,
        flags=re.I,
    )
    title = re.sub(r"\s+", " ", cleaned).strip(" -")
    return title or "Calendar event"


def _clean(text: str) -> str:
    value = re.sub(r"[?!,;]+", " ", str(text))
    return re.sub(r"\s+", " ", value).strip()


__all__ = ["CalendarParser"]
