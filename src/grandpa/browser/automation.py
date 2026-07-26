"""Facade for safe browser automation."""

from __future__ import annotations

from grandpa.browser.executor import BrowserExecutor, HotkeyCallback, OpenCallback
from grandpa.browser.models import BrowserOperationResult
from grandpa.browser.parser import BrowserParser


class BrowserAutomation:
    """Parse and execute safe browser commands."""

    def __init__(self, parser: BrowserParser | None = None, executor: BrowserExecutor | None = None) -> None:
        self.parser = parser or BrowserParser()
        self.executor = executor or BrowserExecutor()

    def handle(self, text: str) -> BrowserOperationResult:
        action = self.parser.parse(text)
        if action is None:
            return BrowserOperationResult("no_match", "")
        return self.executor.execute(action)


def handle_browser_command(
    text: str,
    *,
    opener: OpenCallback | None = None,
    hotkey_runner: HotkeyCallback | None = None,
) -> BrowserOperationResult:
    """Convenience wrapper used by chat and voice command paths."""

    executor = BrowserExecutor(opener=opener, hotkey_runner=hotkey_runner)
    return BrowserAutomation(executor=executor).handle(text)


__all__ = ["BrowserAutomation", "handle_browser_command"]
