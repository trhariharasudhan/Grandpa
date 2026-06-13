"""Deterministic natural-language parsing for local reminders."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from grandpa.core.config import load_config


class ReminderParseError(ValueError):
    """Raised when a reminder phrase cannot be parsed safely."""


@dataclass(frozen=True)
class ParsedReminder:
    message: str
    due_at: datetime
    matched_expression: str


_MONTHS = {
    "january": 1,
    "jan": 1,
    "february": 2,
    "feb": 2,
    "march": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "may": 5,
    "june": 6,
    "jun": 6,
    "july": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sep": 9,
    "sept": 9,
    "october": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
}


def default_reminder_timezone() -> tzinfo:
    """Return Grandpa's configured reminder timezone, falling back locally."""

    try:
        config = load_config()
        timezone_name = (
            getattr(getattr(config, "proactive", None), "timezone", "")
            or getattr(getattr(config, "digest", None), "timezone", "")
        )
        if timezone_name:
            return ZoneInfo(timezone_name)
    except (OSError, ZoneInfoNotFoundError, ValueError):
        pass
    local = datetime.now().astimezone().tzinfo
    return local or UTC


def parse_reminder_phrase(
    phrase: str,
    *,
    now: datetime | None = None,
    timezone: tzinfo | None = None,
) -> ParsedReminder:
    """Parse a safe reminder phrase into message and timezone-aware due time."""

    clean = _normalize_phrase(phrase)
    tz = timezone or default_reminder_timezone()
    current = _coerce_now(now, tz)

    parsed = (
        _parse_relative(clean, current)
        or _parse_relative_message_first(clean, current)
        or _parse_today_tomorrow(clean, current)
        or _parse_month_date(clean, current)
        or _parse_iso(clean, current)
    )
    if parsed is None:
        raise ReminderParseError(
            "Unsupported reminder time. Try: 'in 30 minutes', "
            "'tomorrow at 7 PM', or an ISO 8601 datetime."
        )
    _ensure_future(parsed.due_at, current)
    return parsed


def _normalize_phrase(phrase: str) -> str:
    clean = " ".join(phrase.strip().split())
    if not clean:
        raise ReminderParseError("Reminder text is required.")
    return clean


def _coerce_now(now: datetime | None, timezone: tzinfo) -> datetime:
    if now is None:
        return datetime.now(timezone)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ReminderParseError("Current time must include timezone information.")
    return now.astimezone(timezone)


def _parse_relative(clean: str, now: datetime) -> ParsedReminder | None:
    match = re.fullmatch(
        r"(?i)(?:please\s+)?remind\s+me\s+in\s+(\d+)\s+"
        r"(minutes?|mins?|hours?|hrs?)\s+to\s+(.+)",
        clean,
    )
    if not match:
        return None
    amount = int(match.group(1))
    unit = match.group(2).lower()
    message = _require_message(match.group(3))
    if amount <= 0:
        raise ReminderParseError("Reminder delay must be greater than zero.")
    delta = timedelta(hours=amount) if unit.startswith(("hour", "hr")) else timedelta(minutes=amount)
    return ParsedReminder(message=message, due_at=now + delta, matched_expression=match.group(0))


def _parse_relative_message_first(clean: str, now: datetime) -> ParsedReminder | None:
    match = re.fullmatch(
        r"(?i)(?:please\s+)?remind\s+me\s+to\s+(.+?)\s+in\s+(\d+)\s+"
        r"(minutes?|mins?|hours?|hrs?)",
        clean,
    )
    if not match:
        return None
    message = _require_message(match.group(1))
    amount = int(match.group(2))
    unit = match.group(3).lower()
    if amount <= 0:
        raise ReminderParseError("Reminder delay must be greater than zero.")
    delta = timedelta(hours=amount) if unit.startswith(("hour", "hr")) else timedelta(minutes=amount)
    return ParsedReminder(message=message, due_at=now + delta, matched_expression=match.group(0))


def _parse_today_tomorrow(clean: str, now: datetime) -> ParsedReminder | None:
    match = re.fullmatch(
        r"(?i)(?:please\s+)?remind\s+me\s+(today|tomorrow)\s+at\s+(.+?)\s+to\s+(.+)",
        clean,
    )
    if not match:
        return None
    day_word = match.group(1).lower()
    parsed_time = _parse_clock_time(match.group(2))
    message = _require_message(match.group(3))
    base_day = now.date() + (timedelta(days=1) if day_word == "tomorrow" else timedelta())
    due = datetime.combine(base_day, parsed_time, tzinfo=now.tzinfo)
    return ParsedReminder(message=message, due_at=due, matched_expression=match.group(0))


def _parse_month_date(clean: str, now: datetime) -> ParsedReminder | None:
    match = re.fullmatch(
        r"(?i)(?:please\s+)?remind\s+me\s+(?:on\s+)?"
        r"([a-z]+)\s+(\d{1,2})(?:,?\s+(\d{4}))?\s+at\s+(.+?)\s+to\s+(.+)",
        clean,
    )
    if not match:
        return None
    month_name = match.group(1).lower()
    if month_name not in _MONTHS:
        return None
    year = int(match.group(3) or now.year)
    month = _MONTHS[month_name]
    day = int(match.group(2))
    parsed_time = _parse_clock_time(match.group(4))
    message = _require_message(match.group(5))
    try:
        due = datetime(year, month, day, parsed_time.hour, parsed_time.minute, tzinfo=now.tzinfo)
    except ValueError as exc:
        raise ReminderParseError(f"Invalid reminder date: {exc}") from exc
    return ParsedReminder(message=message, due_at=due, matched_expression=match.group(0))


def _parse_iso(clean: str, now: datetime) -> ParsedReminder | None:
    match = re.fullmatch(
        r"(?i)(?:please\s+)?remind\s+me\s+(?:at\s+)?(\S+)\s+to\s+(.+)",
        clean,
    )
    if not match:
        return None
    raw = match.group(1)
    try:
        due = _parse_iso_datetime(raw).astimezone(now.tzinfo)
    except ReminderParseError:
        raise
    except ValueError:
        return None
    message = _require_message(match.group(2))
    return ParsedReminder(message=message, due_at=due, matched_expression=match.group(0))


def _parse_iso_datetime(raw: str) -> datetime:
    value = raw.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    due = datetime.fromisoformat(value)
    if due.tzinfo is None or due.utcoffset() is None:
        raise ReminderParseError("ISO reminder datetime must include a timezone.")
    return due


def _parse_clock_time(raw: str):
    text = raw.strip().lower().replace(".", "")
    match = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", text)
    if not match:
        raise ReminderParseError(f"Invalid reminder time: {raw!r}.")
    hour = int(match.group(1))
    minute = int(match.group(2) or "0")
    meridiem = match.group(3)
    if minute > 59:
        raise ReminderParseError("Reminder minutes must be between 00 and 59.")
    if meridiem:
        if hour < 1 or hour > 12:
            raise ReminderParseError("12-hour reminder times must use hours 1 through 12.")
        if meridiem == "am":
            hour = 0 if hour == 12 else hour
        else:
            hour = 12 if hour == 12 else hour + 12
    elif hour > 23:
        raise ReminderParseError("24-hour reminder times must use hours 0 through 23.")
    elif 1 <= hour <= 12:
        raise ReminderParseError(
            "Ambiguous reminder time. Use AM/PM or 24-hour time, such as 19:00."
        )
    from datetime import time as dt_time

    return dt_time(hour=hour, minute=minute)


def _require_message(raw: str) -> str:
    message = " ".join(raw.strip().split())
    if not message:
        raise ReminderParseError("Reminder message is required.")
    return message


def _ensure_future(due_at: datetime, now: datetime) -> None:
    if due_at <= now:
        raise ReminderParseError("Reminder time must be in the future.")


__all__ = [
    "ParsedReminder",
    "ReminderParseError",
    "default_reminder_timezone",
    "parse_reminder_phrase",
]
