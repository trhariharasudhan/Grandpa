"""Facade for safe browser automation."""

from __future__ import annotations

from grandpa.browser.executor import (
    BrowserExecutor,
    ConfirmationCallback,
    HotkeyCallback,
    OpenCallback,
)
from grandpa.browser.models import BrowserOperationResult
from grandpa.browser.parser import BrowserParser
from grandpa.browser.safety import configured_trusted_domains


class BrowserAutomation:
    """Parse and execute safe browser commands."""

    def __init__(
        self,
        parser: BrowserParser | None = None,
        executor: BrowserExecutor | None = None,
    ) -> None:
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
    confirm: ConfirmationCallback | None = None,
    confirmed: bool = False,
    trusted_domains: tuple[str, ...] | None = None,
) -> BrowserOperationResult:
    """Convenience wrapper used by chat and voice command paths.

    Navigating actions need ``confirmed=True`` or a ``confirm`` callback that
    approves, unless the domain is in ``tools.browser.trusted_domains``. With
    no callback the action is refused rather than performed, as tool execution
    is in ``tools/_stubs.py``.
    """

    executor = BrowserExecutor(
        opener=opener,
        hotkey_runner=hotkey_runner,
        confirm=confirm,
        confirmed=confirmed,
        trusted_domains=(
            configured_trusted_domains() if trusted_domains is None else trusted_domains
        ),
    )
    return BrowserAutomation(executor=executor).handle(text)


__all__ = ["BrowserAutomation", "handle_browser_command"]
