"""User-facing formatting for notes."""

from __future__ import annotations

from grandpa.notes.models import Note


def format_note_list(notes: tuple[Note, ...], *, empty_message: str = "No notes found.") -> str:
    if not notes:
        return empty_message
    lines = ["Notes:"]
    for note in notes:
        pin = " [pinned]" if note.pinned else ""
        archived = " [archived]" if note.archived else ""
        lines.append(f"- {note.title}{pin}{archived} — {note.updated_at}")
    return "\n".join(lines)


def format_note_detail(note: Note) -> str:
    tags = f"\nTags: {', '.join(note.tags)}" if note.tags else ""
    status = []
    if note.pinned:
        status.append("pinned")
    if note.archived:
        status.append("archived")
    state = f"\nStatus: {', '.join(status)}" if status else ""
    body = note.content or "(empty note)"
    return f"# {note.title}\nCategory: {note.category}{tags}{state}\nUpdated: {note.updated_at}\n\n{body}"


def format_search_results(notes: tuple[Note, ...], query: str) -> str:
    if not notes:
        return f'No notes matched "{query}".'
    return f'Search results for "{query}":\n' + "\n".join(f"- {note.title}" for note in notes)


__all__ = ["format_note_detail", "format_note_list", "format_search_results"]
