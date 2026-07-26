"""Parser for Downloads Manager commands."""

from __future__ import annotations

import re

from grandpa.downloads.models import DownloadAction


class DownloadsParser:
    """Parse confident Downloads commands without invoking an LLM."""

    def parse(self, text: str) -> DownloadAction | None:
        raw = _clean(text)
        command = raw.casefold()
        if not command:
            return None
        return (
            self._parse_read(command, raw)
            or self._parse_move(command, raw)
            or self._parse_organize(command)
            or self._parse_archive_delete(command, raw)
        )

    def _parse_read(self, command: str, raw: str) -> DownloadAction | None:
        if command in {"show my recent downloads", "show recent downloads", "downloads recent"}:
            return DownloadAction("recent")
        if command in {"show downloads from today", "downloads today"}:
            return DownloadAction("today")
        if command in {"open latest download", "downloads latest"}:
            return DownloadAction("open", selector="latest")
        if command in {"open the folder containing the latest download", "open latest download folder"}:
            return DownloadAction("open_folder", selector="latest")
        if command in {"show large downloads", "downloads large"}:
            return DownloadAction("large")
        if command in {"show incomplete downloads", "downloads incomplete"}:
            return DownloadAction("incomplete")
        if command in {"show duplicate downloads", "downloads duplicates"}:
            return DownloadAction("duplicates")
        match = re.fullmatch(r"(?:find downloaded|downloads search|find download(?:ed)? file) (.+)", command)
        if match:
            query = raw[match.start(1) : match.end(1)]
            return DownloadAction("search", query=query)
        match = re.fullmatch(r"(?:downloads info|show download info for) (.+)", command)
        if match:
            selector = raw[match.start(1) : match.end(1)]
            return DownloadAction("info", selector=selector)
        return None

    def _parse_move(self, command: str, raw: str) -> DownloadAction | None:
        patterns = (
            (r"move downloaded pdfs to documents", "pdf", "Documents"),
            (r"move images to pictures", "image", "Pictures"),
            (r"downloads move (.+?) (documents|pictures|videos|music)", "", ""),
        )
        for pattern, selector, destination in patterns:
            match = re.fullmatch(pattern, command)
            if not match:
                continue
            if selector:
                return DownloadAction("move", selector=selector, destination=destination)
            raw_selector = raw[match.start(1) : match.end(1)]
            raw_destination = raw[match.start(2) : match.end(2)]
            return DownloadAction("move", selector=raw_selector, destination=raw_destination)
        return None

    def _parse_organize(self, command: str) -> DownloadAction | None:
        if command in {"organize my downloads folder", "organize downloads", "downloads organize"}:
            return DownloadAction("organize")
        return None

    def _parse_archive_delete(self, command: str, raw: str) -> DownloadAction | None:
        if command in {"archive old downloads", "downloads archive old"}:
            return DownloadAction("archive", selector="old", days=30)
        match = re.fullmatch(r"(?:delete downloads older than|downloads delete older than) (\d+) days", command)
        if match:
            return DownloadAction("delete", selector="old", days=int(match.group(1)))
        if command in {"clear temporary download files", "downloads delete temporary", "downloads delete temp"}:
            return DownloadAction("delete", selector="temporary")
        match = re.fullmatch(r"downloads archive (.+)", command)
        if match:
            selector = raw[match.start(1) : match.end(1)]
            return DownloadAction("archive", selector=selector)
        match = re.fullmatch(r"downloads delete (.+)", command)
        if match:
            selector = raw[match.start(1) : match.end(1)]
            return DownloadAction("delete", selector=selector)
        return None


def _clean(text: str) -> str:
    value = re.sub(r"[?!,;]+", " ", str(text))
    return re.sub(r"\s+", " ", value).strip()


__all__ = ["DownloadsParser"]
