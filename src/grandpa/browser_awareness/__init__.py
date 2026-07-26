"""Read-only browser awareness for Grandpa."""

from grandpa.browser_awareness.analyzer import BrowserPageAnalyzer
from grandpa.browser_awareness.automation import (
    BrowserAwareness,
    handle_browser_awareness_command,
)
from grandpa.browser_awareness.capture import BrowserPageCapture
from grandpa.browser_awareness.models import (
    BrowserAwarenessAction,
    BrowserAwarenessResult,
    BrowserPageSnapshot,
)
from grandpa.browser_awareness.parser import BrowserAwarenessParser

__all__ = [
    "BrowserAwareness",
    "BrowserAwarenessAction",
    "BrowserAwarenessParser",
    "BrowserAwarenessResult",
    "BrowserPageAnalyzer",
    "BrowserPageCapture",
    "BrowserPageSnapshot",
    "handle_browser_awareness_command",
]
