"""High-level File Automation facade for Grandpa."""

from __future__ import annotations

from pathlib import Path

from grandpa.files.executor import ConfirmationCallback, FileExecutor, OpenCallback
from grandpa.files.models import FileOperationResult
from grandpa.files.parser import FileParser
from grandpa.files.safety import FileSafetyPolicy


class FileAutomation:
    """Parse and execute safe local file commands."""

    def __init__(
        self,
        *,
        roots: tuple[Path, ...] = (),
        parser: FileParser | None = None,
        executor: FileExecutor | None = None,
        opener: OpenCallback | None = None,
    ) -> None:
        self.parser = parser or FileParser()
        self.executor = executor or FileExecutor(roots=roots, safety=FileSafetyPolicy(), opener=opener)

    def handle(self, text: str, *, confirm: ConfirmationCallback | None = None) -> FileOperationResult:
        action = self.parser.parse(text)
        if action is None:
            return FileOperationResult("no_match", "")
        return self.executor.execute(action, confirm=confirm)


def handle_file_automation(
    text: str,
    *,
    roots: tuple[Path, ...] = (),
    confirm: ConfirmationCallback | None = None,
    opener: OpenCallback | None = None,
) -> FileOperationResult:
    """Convenience entrypoint used by chat, voice, and slash commands."""

    return FileAutomation(roots=roots, opener=opener).handle(text, confirm=confirm)


__all__ = ["FileAutomation", "handle_file_automation"]
