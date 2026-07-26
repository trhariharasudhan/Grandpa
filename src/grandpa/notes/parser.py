"""Parser for local notes commands."""

from __future__ import annotations

import re

from grandpa.notes.models import NotesAction


class NotesParser:
    """Parse confident local notes commands."""

    def parse(self, text: str) -> NotesAction | None:
        raw = _clean(text)
        command = raw.casefold()
        if not command:
            return None
        return (
            self._parse_list(command)
            or self._parse_search(command, raw)
            or self._parse_create_append(command, raw)
            or self._parse_mutation(command, raw)
        )

    def _parse_list(self, command: str) -> NotesAction | None:
        if command in {"show my notes", "list my notes", "show notes", "notes", "notes list"}:
            return NotesAction("list")
        if command in {"list recent notes", "recent notes", "notes recent"}:
            return NotesAction("recent")
        return None

    def _parse_search(self, command: str, raw: str) -> NotesAction | None:
        patterns = (
            r"search notes for (.+)",
            r"find note about (.+)",
            r"find notes about (.+)",
            r"notes search (.+)",
        )
        for pattern in patterns:
            match = re.fullmatch(pattern, command)
            if match:
                query = raw[match.start(1) : match.end(1)]
                return NotesAction("search", query=query)
        match = re.fullmatch(r"(?:open|show|read) (?:my )?note(?: called)? (.+)", command)
        if match:
            title = raw[match.start(1) : match.end(1)]
            return NotesAction("open", title=title, query=title)
        return None

    def _parse_create_append(self, command: str, raw: str) -> NotesAction | None:
        match = re.fullmatch(r"create a note called (.+)", command)
        if match:
            title = raw[match.start(1) : match.end(1)]
            return NotesAction("create", title=title)
        if command == "create a project note":
            return NotesAction("create", title="Project Note", category="project")
        match = re.fullmatch(r"(?:take a note|remember this note|add this to my notes)(?: (.+))?", command)
        if match:
            content = raw[match.start(1) : match.end(1)] if match.group(1) else ""
            return NotesAction("create", title="Quick Note", content=content)
        match = re.fullmatch(r"append this to my (.+?) note(?: (.+))?", command)
        if match:
            title = raw[match.start(1) : match.end(1)]
            if title.casefold() == "project":
                title = "Project Note"
            content = raw[match.start(2) : match.end(2)] if match.group(2) else ""
            return NotesAction("append", title=title, content=content)
        match = re.fullmatch(r"notes create (.+)", command)
        if match:
            title = raw[match.start(1) : match.end(1)]
            return NotesAction("create", title=title)
        match = re.fullmatch(r"notes append (.+?) (?:with |: )?(.+)", command)
        if match:
            title = raw[match.start(1) : match.end(1)]
            content = raw[match.start(2) : match.end(2)]
            return NotesAction("append", title=title, content=content)
        return None

    def _parse_mutation(self, command: str, raw: str) -> NotesAction | None:
        match = re.fullmatch(r"(?:rename note|notes rename) (.+?) to (.+)", command)
        if match:
            title = raw[match.start(1) : match.end(1)]
            new_title = raw[match.start(2) : match.end(2)]
            return NotesAction("rename", title=title, query=title, new_title=new_title)
        for action, pattern in (
            ("delete", r"(?:delete note|notes delete) (.+)"),
            ("archive", r"(?:archive note|notes archive) (.+)"),
            ("restore", r"(?:restore archived note|restore note|notes restore) (.+)"),
            ("pin", r"(?:pin note|notes pin) (.+)"),
            ("unpin", r"(?:unpin note|notes unpin) (.+)"),
        ):
            match = re.fullmatch(pattern, command)
            if match:
                title = raw[match.start(1) : match.end(1)]
                return NotesAction(action, title=title, query=title)
        return None


def _clean(text: str) -> str:
    value = re.sub(r"[?!,;]+", " ", str(text))
    return re.sub(r"\s+", " ", value).strip()


__all__ = ["NotesParser"]
