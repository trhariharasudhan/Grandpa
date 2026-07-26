"""Local Markdown storage for Grandpa notes."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from grandpa.core.config import DEFAULT_CONFIG_DIR
from grandpa.notes.models import Note
from grandpa.notes.safety import NotesSafetyError, NotesSafetyPolicy

DEFAULT_NOTES_DIR = DEFAULT_CONFIG_DIR / "notes"


class NotesStore:
    """Store one UTF-8 Markdown file per note with JSON front matter."""

    def __init__(self, root: Path | str = DEFAULT_NOTES_DIR, safety: NotesSafetyPolicy | None = None) -> None:
        self.root = Path(root)
        self.safety = safety or NotesSafetyPolicy()

    def status(self) -> tuple[str, str]:
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            self.safety.ensure_inside_root(self.root, self.root)
            probe = self.root / ".write-test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return "ready", f"Notes storage ready at {self.root}."
        except PermissionError as exc:
            return "permission_denied", f"Notes storage permission denied: {exc}"
        except Exception as exc:
            return "error", f"Notes storage unavailable: {exc}"

    def create(self, title: str, content: str = "", *, tags: tuple[str, ...] = (), category: str = "general") -> Note:
        title = self.safety.sanitize_title(title)
        if self.safety.contains_secret(content):
            raise NotesSafetyError("I blocked saving that note because it looks like it contains a secret.")
        slug = self._unique_slug(self.safety.slugify(title))
        note = Note(note_id=uuid4().hex, title=title, slug=slug, content=content.strip(), tags=tags, category=category or "general")
        self._write(note)
        return note

    def append(self, title_or_query: str, content: str) -> Note:
        if self.safety.contains_secret(content):
            raise NotesSafetyError("I blocked appending that text because it looks like it contains a secret.")
        note = self.find_one(title_or_query)
        if note is None:
            note = self.create(title_or_query, "")
        separator = "\n\n" if note.content else ""
        updated = _replace(note, content=f"{note.content}{separator}{content.strip()}", updated_at=_now())
        self._write(updated)
        return updated

    def rename(self, title_or_query: str, new_title: str) -> Note:
        note = self._require_note(title_or_query)
        new_title = self.safety.sanitize_title(new_title)
        new_slug = self._unique_slug(self.safety.slugify(new_title), exclude=note.slug)
        old_path = self._path_for_slug(note.slug)
        updated = _replace(note, title=new_title, slug=new_slug, updated_at=_now())
        self._write(updated)
        if old_path != self._path_for_slug(new_slug):
            old_path.unlink(missing_ok=True)
        return updated

    def delete(self, title_or_query: str) -> Note:
        note = self._require_note(title_or_query)
        self._path_for_slug(note.slug).unlink(missing_ok=True)
        return note

    def archive(self, title_or_query: str, *, archived: bool = True) -> Note:
        note = self._require_note(title_or_query)
        updated = _replace(note, archived=archived, updated_at=_now())
        self._write(updated)
        return updated

    def pin(self, title_or_query: str, *, pinned: bool = True) -> Note:
        note = self._require_note(title_or_query)
        updated = _replace(note, pinned=pinned, updated_at=_now())
        self._write(updated)
        return updated

    def list(self, *, include_archived: bool = False) -> tuple[Note, ...]:
        notes = tuple(sorted(self._read_all(), key=lambda note: (not note.pinned, note.updated_at), reverse=False))
        if include_archived:
            return notes
        return tuple(note for note in notes if not note.archived)

    def recent(self, *, limit: int = 10) -> tuple[Note, ...]:
        notes = sorted((note for note in self._read_all() if not note.archived), key=lambda note: note.updated_at, reverse=True)
        return tuple(notes[:limit])

    def search(self, query: str, *, include_archived: bool = False) -> tuple[Note, ...]:
        needle = query.casefold().strip()
        if not needle:
            return ()
        results = []
        for note in self._read_all():
            if note.archived and not include_archived:
                continue
            haystack = " ".join((note.title, note.content, note.category, " ".join(note.tags))).casefold()
            if needle in haystack:
                results.append(note)
        return tuple(sorted(results, key=lambda note: note.updated_at, reverse=True))

    def find_one(self, query: str) -> Note | None:
        query = self.safety.sanitize_title(query)
        slug = self.safety.slugify(query)
        path = self._path_for_slug(slug)
        if path.exists():
            return self._read(path)
        matches = self.search(query, include_archived=True)
        return matches[0] if matches else None

    def _require_note(self, query: str) -> Note:
        note = self.find_one(query)
        if note is None:
            raise NotesStorageError("Note not found.")
        return note

    def _read_all(self) -> list[Note]:
        self.root.mkdir(parents=True, exist_ok=True)
        return [note for path in self.root.glob("*.md") if (note := self._read(path)) is not None]

    def _read(self, path: Path) -> Note | None:
        self.safety.ensure_inside_root(self.root, path)
        text = path.read_text(encoding="utf-8")
        metadata: dict = {}
        content = text
        if text.startswith("---\n"):
            try:
                _, raw_meta, content = text.split("---\n", 2)
                metadata = json.loads(raw_meta.strip() or "{}")
            except ValueError:
                metadata = {}
        return Note(
            note_id=str(metadata.get("note_id") or path.stem),
            title=str(metadata.get("title") or path.stem),
            slug=str(metadata.get("slug") or path.stem),
            content=content.strip(),
            tags=tuple(str(tag) for tag in metadata.get("tags") or ()),
            category=str(metadata.get("category") or "general"),
            pinned=bool(metadata.get("pinned")),
            archived=bool(metadata.get("archived")),
            created_at=str(metadata.get("created_at") or _now()),
            updated_at=str(metadata.get("updated_at") or _now()),
        )

    def _write(self, note: Note) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self._path_for_slug(note.slug)
        metadata = asdict(note)
        content = metadata.pop("content", "")
        path.write_text("---\n" + json.dumps(metadata, indent=2, sort_keys=True) + "\n---\n\n" + content.strip() + "\n", encoding="utf-8")

    def _path_for_slug(self, slug: str) -> Path:
        safe_slug = self.safety.slugify(slug)
        return self.safety.ensure_inside_root(self.root, self.root / f"{safe_slug}.md")

    def _unique_slug(self, base_slug: str, *, exclude: str = "") -> str:
        slug = base_slug
        counter = 2
        while self._path_for_slug(slug).exists() and slug != exclude:
            slug = f"{base_slug}-{counter}"
            counter += 1
        return slug


class NotesStorageError(RuntimeError):
    """Raised when a note cannot be found or stored."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _replace(note: Note, **changes) -> Note:
    data = asdict(note)
    data.update(changes)
    return Note(**data)


__all__ = ["DEFAULT_NOTES_DIR", "NotesStorageError", "NotesStore"]
