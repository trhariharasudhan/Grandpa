"""Safe local notes automation facade."""

from __future__ import annotations

from collections.abc import Callable

from grandpa.notes.formatter import (
    format_note_detail,
    format_note_list,
    format_search_results,
)
from grandpa.notes.models import NotesAction, NotesResult
from grandpa.notes.parser import NotesParser
from grandpa.notes.safety import NotesSafetyError, NotesSafetyPolicy
from grandpa.notes.storage import NotesStorageError, NotesStore

ConfirmationCallback = Callable[[NotesAction], bool]


class NotesAutomation:
    """Parse and execute local note commands safely."""

    def __init__(
        self,
        parser: NotesParser | None = None,
        store: NotesStore | None = None,
        safety: NotesSafetyPolicy | None = None,
    ) -> None:
        self.parser = parser or NotesParser()
        self.safety = safety or NotesSafetyPolicy()
        self.store = store or NotesStore(safety=self.safety)

    def handle(
        self,
        text: str,
        *,
        confirmed: bool = False,
        confirm: ConfirmationCallback | None = None,
    ) -> NotesResult:
        action = self.parser.parse(text)
        if action is None:
            return NotesResult("no_match", "")
        return self.execute(action, confirmed=confirmed, confirm=confirm)

    def execute(
        self,
        action: NotesAction,
        *,
        confirmed: bool = False,
        confirm: ConfirmationCallback | None = None,
    ) -> NotesResult:
        try:
            if self._needs_confirmation(action, confirmed=confirmed, confirm=confirm):
                return NotesResult(
                    "needs_confirmation",
                    _confirmation_message(action),
                    action,
                    requires_confirmation=True,
                )
            return self._execute(action)
        except NotesSafetyError as exc:
            return NotesResult("blocked", str(exc), action, error=str(exc))
        except NotesStorageError as exc:
            return NotesResult("error", str(exc), action, error=str(exc))
        except PermissionError as exc:
            return NotesResult(
                "error",
                f"Notes storage permission denied: {exc}",
                action,
                error=str(exc),
            )
        except Exception as exc:
            return NotesResult(
                "error", f"Notes action failed: {exc}", action, error=str(exc)
            )

    def _execute(self, action: NotesAction) -> NotesResult:
        if action.action == "list":
            notes = self.store.list()
            return NotesResult("handled", format_note_list(notes), action, notes)
        if action.action == "recent":
            notes = self.store.recent()
            return NotesResult(
                "handled",
                format_note_list(notes, empty_message="No recent notes found."),
                action,
                notes,
            )
        if action.action == "search":
            notes = self.store.search(action.query)
            return NotesResult(
                "handled", format_search_results(notes, action.query), action, notes
            )
        if action.action == "open":
            note = self.store.find_one(action.query or action.title)
            if note is None:
                return NotesResult("error", "Note not found.", action)
            return NotesResult("handled", format_note_detail(note), action, (note,))
        if action.action == "create":
            note = self.store.create(
                action.title or "Quick Note",
                action.content,
                tags=action.tags,
                category=action.category or "general",
            )
            return NotesResult(
                "handled", f'Note created: "{note.title}".', action, (note,)
            )
        if action.action == "append":
            note = self.store.append(action.title, action.content)
            return NotesResult(
                "handled", f'Note updated: "{note.title}".', action, (note,)
            )
        if action.action == "rename":
            note = self.store.rename(action.query or action.title, action.new_title)
            return NotesResult(
                "handled", f'Note renamed to "{note.title}".', action, (note,)
            )
        if action.action == "delete":
            note = self.store.delete(action.query or action.title)
            return NotesResult(
                "handled", f'Note deleted: "{note.title}".', action, (note,)
            )
        if action.action == "archive":
            note = self.store.archive(action.query or action.title, archived=True)
            return NotesResult(
                "handled", f'Note archived: "{note.title}".', action, (note,)
            )
        if action.action == "restore":
            note = self.store.archive(action.query or action.title, archived=False)
            return NotesResult(
                "handled", f'Note restored: "{note.title}".', action, (note,)
            )
        if action.action == "pin":
            note = self.store.pin(action.query or action.title, pinned=True)
            return NotesResult(
                "handled", f'Note pinned: "{note.title}".', action, (note,)
            )
        if action.action == "unpin":
            note = self.store.pin(action.query or action.title, pinned=False)
            return NotesResult(
                "handled", f'Note unpinned: "{note.title}".', action, (note,)
            )
        return NotesResult(
            "unsupported", "That notes action is not supported yet.", action
        )

    def _needs_confirmation(
        self,
        action: NotesAction,
        *,
        confirmed: bool,
        confirm: ConfirmationCallback | None,
    ) -> bool:
        if not self.safety.requires_confirmation(action.action):
            return False
        if confirmed:
            return False
        if confirm is not None:
            return not confirm(action)
        return True


def handle_notes_command(
    text: str,
    *,
    store: NotesStore | None = None,
    confirmed: bool = False,
    confirm: ConfirmationCallback | None = None,
) -> NotesResult:
    return NotesAutomation(store=store).handle(
        text, confirmed=confirmed, confirm=confirm
    )


def _confirmation_message(action: NotesAction) -> str:
    if action.action == "delete":
        return f'Delete note "{action.title or action.query}"? [y/N]'
    return "Confirm notes action? [y/N]"


__all__ = ["NotesAutomation", "handle_notes_command"]
