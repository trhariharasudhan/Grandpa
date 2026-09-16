"""Facade for read-only browser awareness."""

from __future__ import annotations

from grandpa.browser_awareness.analyzer import BrowserPageAnalyzer
from grandpa.browser_awareness.capture import BrowserPageCapture, CaptureProvider
from grandpa.browser_awareness.models import BrowserAwarenessResult
from grandpa.browser_awareness.parser import BrowserAwarenessParser


class BrowserAwareness:
    """Parse, capture, and answer safe browser awareness requests."""

    def __init__(
        self,
        parser: BrowserAwarenessParser | None = None,
        capture: BrowserPageCapture | CaptureProvider | None = None,
        analyzer: BrowserPageAnalyzer | None = None,
    ) -> None:
        self.parser = parser or BrowserAwarenessParser()
        self.capture = capture or BrowserPageCapture()
        self.analyzer = analyzer or BrowserPageAnalyzer()

    def handle(self, text: str) -> BrowserAwarenessResult:
        action = self.parser.parse(text)
        if action is None:
            return BrowserAwarenessResult("no_match", "")
        snapshot = self.capture() if callable(self.capture) else self.capture.capture()
        return self.analyzer.analyze(action, snapshot)


def execute_awareness(
    action: str,
    query: str = "",
    *,
    capture: BrowserPageCapture | CaptureProvider | None = None,
) -> BrowserAwarenessResult:
    """Answer one already-chosen awareness action.

    The structured seam: ``handle`` parses and answers, which is what a chat
    phrase needs; the action layer has already been told which action to take
    and only needs the second half. Both go through the same capture and the
    same analyzer, so the answer does not depend on which called.
    """
    from grandpa.browser_awareness.models import BrowserAwarenessAction

    awareness = BrowserAwareness(capture=capture)
    snapshot = (
        awareness.capture()
        if callable(awareness.capture)
        else awareness.capture.capture()
    )
    return awareness.analyzer.analyze(BrowserAwarenessAction(action, query), snapshot)


def handle_browser_awareness_command(
    text: str,
    *,
    capture: BrowserPageCapture | CaptureProvider | None = None,
) -> BrowserAwarenessResult:
    """Convenience wrapper used by chat and voice command paths."""

    return BrowserAwareness(capture=capture).handle(text)


__all__ = [
    "BrowserAwareness",
    "execute_awareness",
    "handle_browser_awareness_command",
]
