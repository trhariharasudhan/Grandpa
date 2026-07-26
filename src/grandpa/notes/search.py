"""Search helpers for local notes."""

from __future__ import annotations

from grandpa.notes.models import Note
from grandpa.notes.storage import NotesStore


class NotesSearch:
    """Fast local case-insensitive note search."""

    def __init__(self, store: NotesStore | None = None) -> None:
        self.store = store or NotesStore()

    def search(self, query: str, *, include_archived: bool = False) -> tuple[Note, ...]:
        return self.store.search(query, include_archived=include_archived)


__all__ = ["NotesSearch"]
