"""Safe modular Gmail integration for Grandpa."""

from grandpa.gmail.auth import GmailAuthManager, GmailAuthStatus
from grandpa.gmail.automation import GmailAutomation, handle_gmail_command
from grandpa.gmail.client import GmailClient
from grandpa.gmail.models import GmailAction, GmailMessageSummary, GmailResult
from grandpa.gmail.parser import GmailParser
from grandpa.gmail.safety import GmailSafetyPolicy

__all__ = [
    "GmailAction",
    "GmailAuthManager",
    "GmailAuthStatus",
    "GmailAutomation",
    "GmailClient",
    "GmailMessageSummary",
    "GmailParser",
    "GmailResult",
    "GmailSafetyPolicy",
    "handle_gmail_command",
]
