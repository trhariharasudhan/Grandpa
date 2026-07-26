"""Safe modular Google Calendar integration for Grandpa."""

from grandpa.calendar.auth import CalendarAuthManager, CalendarAuthStatus
from grandpa.calendar.automation import CalendarAutomation, handle_calendar_command
from grandpa.calendar.client import CalendarClient
from grandpa.calendar.models import CalendarAction, CalendarEventSummary, CalendarResult
from grandpa.calendar.parser import CalendarParser
from grandpa.calendar.safety import CalendarSafetyPolicy

__all__ = [
    "CalendarAction",
    "CalendarAuthManager",
    "CalendarAuthStatus",
    "CalendarAutomation",
    "CalendarClient",
    "CalendarEventSummary",
    "CalendarParser",
    "CalendarResult",
    "CalendarSafetyPolicy",
    "handle_calendar_command",
]
