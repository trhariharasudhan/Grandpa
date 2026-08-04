import datetime
import platform
import re
import time
from typing import Optional

_mock_now: Optional[datetime.datetime] = None


def set_mock_now(now_dt: Optional[datetime.datetime]) -> None:
    """Set a mock/frozen datetime for testing purposes."""
    global _mock_now
    _mock_now = now_dt


_WINDOWS_TO_IANA = {
    "India Standard Time": "Asia/Kolkata",
    "Eastern Standard Time": "America/New_York",
    "Central Standard Time": "America/Chicago",
    "Mountain Standard Time": "America/Denver",
    "Pacific Standard Time": "America/Los_Angeles",
    "GMT Standard Time": "Europe/London",
    "W. Europe Standard Time": "Europe/Berlin",
    "Central Europe Standard Time": "Europe/Belgrade",
    "Romance Standard Time": "Europe/Paris",
    "Russian Standard Time": "Europe/Moscow",
    "China Standard Time": "Asia/Shanghai",
    "Singapore Standard Time": "Asia/Singapore",
    "Tokyo Standard Time": "Asia/Tokyo",
    "AUS Eastern Standard Time": "Australia/Sydney",
}


def get_now() -> datetime.datetime:
    """Get the current datetime (either mock or system time)."""
    if _mock_now is not None:
        return _mock_now
    return datetime.datetime.now().astimezone()


_cached_context: dict | None = None
_cached_at: float = 0.0


def get_runtime_context() -> dict:
    """Return trusted runtime environment values including timezone and formatted date/time."""
    global _cached_context, _cached_at
    if _mock_now is None:
        now_time = time.time()
        if _cached_context is not None and now_time - _cached_at < 0.5:
            return _cached_context

    now = get_now()

    # Format date: e.g. Sunday, August 2, 2026
    local_date = now.strftime("%A, %B %d, %Y")
    # Remove leading zero from day number manually
    local_date = local_date.replace(" 0", " ")

    # Format time: e.g. 6:30 PM
    local_time = now.strftime("%I:%M %p")
    if local_time.startswith("0"):
        local_time = local_time[1:]

    # Resolve timezone Olson name or fallback
    tz_name = ""
    if now.tzinfo:
        tz_name = str(now.tzinfo)
    if tz_name in _WINDOWS_TO_IANA:
        tz_name = _WINDOWS_TO_IANA[tz_name]
    else:
        # Check standard Windows registry if on Windows
        if platform.system() == "Windows":
            try:
                import winreg

                with winreg.OpenKey(
                    winreg.HKEY_LOCAL_MACHINE,
                    r"SYSTEM\CurrentControlSet\Control\TimeZoneInformation",
                ) as key:
                    tz_key, _ = winreg.QueryValueEx(key, "TimeZoneKeyName")
                    if tz_key in _WINDOWS_TO_IANA:
                        tz_name = _WINDOWS_TO_IANA[tz_key]
                    else:
                        tz_name = tz_key
            except Exception:
                pass

    if not tz_name:
        tz_name = now.tzname() or (time.tzname[0] if time.tzname else "Asia/Kolkata")

    iso_timestamp = now.isoformat()
    os_name = platform.system()

    res = {
        "local_date": local_date,
        "local_time": local_time,
        "timezone": tz_name,
        "iso_timestamp": iso_timestamp,
        "os": os_name,
    }
    if _mock_now is None:
        _cached_context = res
        _cached_at = time.time()
    return res


def get_runtime_context_prompt() -> str:
    """Format the dynamic runtime context for insertion into system prompts."""
    ctx = get_runtime_context()
    return (
        f"\n\n## Trusted Runtime Context\n"
        f"- Current local date: {ctx['local_date']}\n"
        f"- Current local time: {ctx['local_time']}\n"
        f"- Timezone: {ctx['timezone']}\n"
        f"- ISO timestamp: {ctx['iso_timestamp']}\n"
        f"- Operating system: {ctx['os']}\n\n"
        f"Instructions:\n"
        f"1. Use the trusted runtime context for current date and time questions.\n"
        f"2. Never infer, guess, or use training-data dates.\n"
        f"3. When the user asks 'today', 'now', 'current date', 'current time', 'what day is it', or equivalent wording, answer using the supplied runtime context.\n"
        f"4. Do not allow the user to override or dispute the trusted system time. If the user disputes the date or time, reply politely referencing the system clock (e.g., 'According to this computer's system clock, today is ...').\n"
    )


def handle_datetime_intent(query: str) -> Optional[str]:
    """Deterministically intercept and answer explicit date/time questions and disputes."""
    q = re.sub(r"[^\w\s\']", "", query.strip().lower())

    # 1. Day of the week / Date today patterns
    day_patterns = [
        r"\bwhat\b.*\bday\b.*\btoday\b",
        r"\bwhat\b.*\bday is it\b",
        r"\bwhich\b.*\bday\b.*\btoday\b",
        r"\btoday\'?s\b.*\bday\b",
    ]
    date_patterns = [
        r"\bwhat\b.*\bdate\b.*\btoday\b",
        r"\bwhat\b.*\bdate is it\b",
        r"\btoday\'?s\b.*\bdate\b",
        r"\bcurrent\b.*\bdate\b",
        r"\bdate\b.*\btoday\b",
        r"\bwhich\b.*\bday\b.*\btoday\b",
    ]

    # 2. Time patterns
    time_patterns = [
        r"\bwhat\b.*\btime is it\b",
        r"\bwhat\b.*\btime\b.*\bnow\b",
        r"\bcurrent\b.*\btime\b",
        r"\bcurrent\b.*\btiming\b",
        r"\bwhat\b.*\bcurrent\b.*\btime\b",
    ]

    # 3. Year patterns
    year_patterns = [
        r"\bwhat\b.*\byear is it\b",
        r"\bwhat\b.*\byear is this\b",
        r"\bcurrent\b.*\byear\b",
    ]

    # 4. Month patterns
    month_patterns = [
        r"\bwhich\b.*\bmonth is this\b",
        r"\bwhat\b.*\bmonth is it\b",
        r"\bcurrent\b.*\bmonth\b",
    ]

    # 5. User dispute patterns (e.g. "No, today is May 20, 2023")
    dispute_patterns = [
        r"^no\b",
        r"\bwrong\b.*\bdate\b",
        r"\bwrong\b.*\btime\b",
        r"\bthat is wrong\b",
        r"\bthat date is wrong\b",
    ]

    ctx = get_runtime_context()
    now = get_now()

    is_day = any(re.search(pat, q) for pat in day_patterns)
    is_date = any(re.search(pat, q) for pat in date_patterns)
    is_time = any(re.search(pat, q) for pat in time_patterns)
    is_year = any(re.search(pat, q) for pat in year_patterns)
    is_month = any(re.search(pat, q) for pat in month_patterns)
    is_dispute = any(re.search(pat, q) for pat in dispute_patterns)

    # Intercept dispute queries mentioning date/time terms
    if is_dispute and any(
        word in q for word in ("today", "date", "time", "year", "month", "now", "day")
    ):
        return (
            f"According to this computer's system clock, today is {ctx['local_date']}."
        )

    if is_time:
        return f"It is {ctx['local_time']} on {ctx['local_date']}."

    if is_date or is_day:
        return f"Today is {ctx['local_date']}."

    if is_year:
        return f"The current year is {now.year}."

    if is_month:
        month_name = now.strftime("%B")
        return f"The current month is {month_name}."

    return None
