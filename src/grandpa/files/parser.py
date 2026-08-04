"""Natural language parser for Grandpa file automation."""

from __future__ import annotations

import re

from grandpa.files.models import FileAction


class FileParser:
    """Parse common file commands without executing them."""

    def parse(self, text: str) -> FileAction | None:
        command = _normalize(text)
        if not command:
            return None
        return (
            self._parse_create(command)
            or self._parse_rename(command)
            or self._parse_copy(command)
            or self._parse_move(command)
            or self._parse_delete(command)
            or self._parse_search(command)
            or self._parse_open(command)
            or self._parse_archive(command)
            or self._parse_properties(command)
        )

    def _parse_create(self, command: str) -> FileAction | None:
        match = re.fullmatch(r"(?:create|make)(?: a)? folder(?: called)? (.+)", command)
        if match:
            return FileAction("create_folder", source=match.group(1).strip())
        match = re.fullmatch(
            r"(?:create|make)(?: an empty)?(?: text)? file (.+)", command
        )
        if match:
            return FileAction("create_file", source=match.group(1).strip())
        return None

    def _parse_rename(self, command: str) -> FileAction | None:
        match = re.fullmatch(r"rename(?: folder| file)? (.+?) to (.+)", command)
        if match:
            return FileAction(
                "rename",
                source=match.group(1).strip(),
                destination=match.group(2).strip(),
            )
        return None

    def _parse_copy(self, command: str) -> FileAction | None:
        match = re.fullmatch(
            r"(?:copy|duplicate)(?: folder| file)? (.+?)(?: to (.+))?", command
        )
        if match:
            source = match.group(1).strip()
            destination = (match.group(2) or "").strip()
            return FileAction("copy", source=source, destination=destination)
        return None

    def _parse_move(self, command: str) -> FileAction | None:
        match = re.fullmatch(r"move(?: folder| file)? (.+?) to (.+)", command)
        if match:
            return FileAction(
                "move",
                source=match.group(1).strip(),
                destination=match.group(2).strip(),
            )
        return None

    def _parse_delete(self, command: str) -> FileAction | None:
        match = re.fullmatch(r"(?:delete|remove) (.+)", command)
        if match:
            return FileAction("delete", source=match.group(1).strip())
        return None

    def _parse_search(self, command: str) -> FileAction | None:
        match = re.fullmatch(r"(?:find|search for) (.+)", command)
        if match:
            query = match.group(1).strip()
            if query in {"pdf files", "pdfs", "pdf"}:
                return FileAction("search", query="pdf", args={"suffixes": [".pdf"]})
            return FileAction("search", query=query)
        match = re.fullmatch(r"find files containing (.+)", command)
        if match:
            return FileAction(
                "search", query=match.group(1).strip(), args={"contains": True}
            )
        if command in {"show recent pdfs", "find recent pdfs"}:
            return FileAction(
                "search", query="pdf", args={"recent": True, "suffixes": [".pdf"]}
            )
        if command in {"find latest screenshot", "open latest screenshot"}:
            return FileAction(
                "search",
                query="screenshot",
                args={"latest": True, "suffixes": [".png", ".jpg", ".jpeg"]},
            )
        return None

    def _parse_open(self, command: str) -> FileAction | None:
        match = re.fullmatch(r"open (?:the )?folder containing (.+)", command)
        if match:
            return FileAction("open_containing_folder", source=match.group(1).strip())
        match = re.fullmatch(r"open (.+)", command)
        if match:
            return FileAction("open", source=match.group(1).strip())
        return None

    def _parse_archive(self, command: str) -> FileAction | None:
        match = re.fullmatch(r"(?:zip|compress) (.+)", command)
        if match:
            return FileAction("zip", source=match.group(1).strip())
        match = re.fullmatch(r"extract (.+?)(?: to (.+))?", command)
        if match:
            return FileAction(
                "extract",
                source=match.group(1).strip(),
                destination=(match.group(2) or "").strip(),
            )
        return None

    def _parse_properties(self, command: str) -> FileAction | None:
        match = re.fullmatch(
            r"(?:show properties of|what is the size of|when was|show file type and location) (.+?)(?: modified)?",
            command,
        )
        if match:
            return FileAction("properties", source=match.group(1).strip())
        return None


def _normalize(text: str) -> str:
    value = re.sub(r"[?!;]+", " ", str(text).casefold())
    value = re.sub(r"\s+", " ", value)
    return value.strip()


__all__ = ["FileParser"]
