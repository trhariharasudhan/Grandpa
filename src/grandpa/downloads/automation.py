"""Safe Downloads Manager automation facade."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from grandpa.downloads.formatter import (
    format_download_info,
    format_download_list,
    format_duplicate_groups,
    format_operation_plan,
)
from grandpa.downloads.models import DownloadAction, DownloadItem, DownloadResult
from grandpa.downloads.organizer import DownloadsOrganizer, destination_for_name
from grandpa.downloads.parser import DownloadsParser
from grandpa.downloads.safety import (
    DownloadsSafetyError,
    DownloadsSafetyPolicy,
    default_download_roots,
)
from grandpa.downloads.scanner import DownloadsScanner

ConfirmationCallback = Callable[[DownloadAction, tuple[DownloadItem, ...]], bool]
OpenCallback = Callable[[Path], None]


class DownloadsAutomation:
    """Parse and execute safe Downloads Manager commands."""

    def __init__(
        self,
        parser: DownloadsParser | None = None,
        scanner: DownloadsScanner | None = None,
        safety: DownloadsSafetyPolicy | None = None,
        organizer: DownloadsOrganizer | None = None,
        opener: OpenCallback | None = None,
    ) -> None:
        self.parser = parser or DownloadsParser()
        self.scanner = scanner or DownloadsScanner()
        self.safety = safety or self.scanner.safety
        self.organizer = organizer or DownloadsOrganizer(self.safety)
        self.opener = opener or _open_path

    def handle(
        self,
        text: str,
        *,
        confirmed: bool = False,
        confirm: ConfirmationCallback | None = None,
    ) -> DownloadResult:
        action = self.parser.parse(text)
        if action is None:
            return DownloadResult("no_match", "")
        return self.execute(action, confirmed=confirmed, confirm=confirm)

    def execute(
        self,
        action: DownloadAction,
        *,
        confirmed: bool = False,
        confirm: ConfirmationCallback | None = None,
    ) -> DownloadResult:
        try:
            items = self._items_for_action(action)
            if self._needs_confirmation(action, items, confirmed=confirmed, confirm=confirm):
                return DownloadResult(
                    "needs_confirmation",
                    format_operation_plan(action.action, items),
                    action,
                    items,
                    requires_confirmation=True,
                )
            return self._execute(action, items)
        except DownloadsSafetyError as exc:
            return DownloadResult("blocked", str(exc), action, error=str(exc))
        except PermissionError as exc:
            return DownloadResult("error", f"Downloads permission denied: {exc}", action, error=str(exc))
        except Exception as exc:
            return DownloadResult("error", f"Downloads action failed: {exc}", action, error=str(exc))

    def _execute(self, action: DownloadAction, items: tuple[DownloadItem, ...]) -> DownloadResult:
        if action.action in {"recent", "today", "large", "incomplete", "search"}:
            return DownloadResult("handled", format_download_list(items), action, items)
        if action.action == "duplicates":
            return DownloadResult("handled", format_duplicate_groups(items), action, items)
        if action.action == "info":
            if not items:
                return DownloadResult("error", "No matching download found.", action)
            return DownloadResult("handled", format_download_info(items[0]), action, (items[0],))
        if action.action == "open":
            if not items:
                return DownloadResult("error", "No matching download found.", action)
            item = items[0]
            if not item.safe_to_open:
                return DownloadResult("blocked", f"I will not open potentially unsafe download: {item.name}", action, (item,))
            self.opener(item.path)
            return DownloadResult("handled", f"Opened download: {item.name}", action, (item,))
        if action.action == "open_folder":
            if not items:
                return DownloadResult("error", "No matching download found.", action)
            self.opener(items[0].path.parent)
            return DownloadResult("handled", f"Opened containing folder for: {items[0].name}", action, (items[0],))
        if action.action == "move":
            moved = self.organizer.move_items(items, destination_for_name(action.destination))
            return DownloadResult("handled", f"Moved {len(moved)} download{'s' if len(moved) != 1 else ''}.", action, items)
        if action.action == "organize":
            root = self._primary_root()
            moved = self.organizer.organize_items(root, items)
            return DownloadResult("handled", f"Organized {len(moved)} download{'s' if len(moved) != 1 else ''}.", action, items)
        if action.action == "archive":
            moved = self.organizer.archive_items(self._primary_root(), items)
            return DownloadResult("handled", f"Archived {len(moved)} download{'s' if len(moved) != 1 else ''}.", action, items)
        if action.action == "delete":
            for item in items:
                self.safety.ensure_allowed_root(item.path).unlink(missing_ok=True)
            return DownloadResult("handled", f"Deleted {len(items)} download{'s' if len(items) != 1 else ''}.", action, items)
        return DownloadResult("unsupported", "That Downloads action is not supported yet.", action, items)

    def _items_for_action(self, action: DownloadAction) -> tuple[DownloadItem, ...]:
        if action.action == "recent":
            return self.scanner.recent()
        if action.action == "today":
            return self.scanner.today()
        if action.action in {"latest", "open", "open_folder"}:
            latest = self.scanner.latest()
            return (latest,) if latest else ()
        if action.action == "large":
            return self.scanner.large()
        if action.action == "incomplete":
            return self.scanner.incomplete()
        if action.action == "duplicates":
            return self.scanner.duplicates()
        if action.action == "search":
            return self.scanner.search(action.query)
        if action.action == "info":
            return self._select(action.selector)
        if action.action in {"move", "archive", "delete"}:
            return self._select(action.selector, days=action.days)
        if action.action == "organize":
            return tuple(item for item in self.scanner.scan() if not item.incomplete)
        return ()

    def _select(self, selector: str, *, days: int = 30) -> tuple[DownloadItem, ...]:
        selector = selector.casefold().strip()
        if selector in {"latest", ""}:
            latest = self.scanner.latest()
            return (latest,) if latest else ()
        if selector in {"old", "older"}:
            return self.scanner.older_than(days)
        if selector in {"temporary", "temp", "incomplete"}:
            return self.scanner.incomplete()
        return self.scanner.search(selector)

    def _needs_confirmation(
        self,
        action: DownloadAction,
        items: tuple[DownloadItem, ...],
        *,
        confirmed: bool,
        confirm: ConfirmationCallback | None,
    ) -> bool:
        if not self.safety.requires_confirmation(action.action, count=len(items)):
            return False
        if confirmed:
            return False
        if confirm is not None:
            return not confirm(action, items)
        return True

    def _primary_root(self) -> Path:
        roots = self.scanner.roots or default_download_roots()
        return Path(roots[0]).expanduser()


def handle_downloads_command(
    text: str,
    *,
    scanner: DownloadsScanner | None = None,
    confirmed: bool = False,
    confirm: ConfirmationCallback | None = None,
    opener: OpenCallback | None = None,
) -> DownloadResult:
    return DownloadsAutomation(scanner=scanner, opener=opener).handle(text, confirmed=confirmed, confirm=confirm)


def _open_path(path: Path) -> None:
    if os.name == "nt":
        os.startfile(path)  # type: ignore[attr-defined]
        return
    raise DownloadsSafetyError("Opening downloads is only supported on Windows in this build.")


__all__ = ["DownloadsAutomation", "handle_downloads_command"]
