"""Safe movement and organization helpers for Downloads."""

from __future__ import annotations

import shutil
from pathlib import Path

from grandpa.downloads.models import DownloadItem
from grandpa.downloads.safety import DownloadsSafetyPolicy

ORGANIZE_FOLDERS = {
    "document": "Documents",
    "pdf": "Documents",
    "image": "Images",
    "video": "Videos",
    "audio": "Audio",
    "archive": "Archives",
    "installer": "Installers",
    "other": "Other",
}

DESTINATION_ALIASES = {
    "documents": "Documents",
    "pictures": "Pictures",
    "images": "Pictures",
    "videos": "Videos",
    "music": "Music",
}


class DownloadsOrganizer:
    """Move downloads without overwriting existing destination files."""

    def __init__(self, safety: DownloadsSafetyPolicy) -> None:
        self.safety = safety

    def move_items(self, items: tuple[DownloadItem, ...], destination: Path) -> tuple[Path, ...]:
        destination = self.safety.safe_destination(destination)
        destination.mkdir(parents=True, exist_ok=True)
        moved = []
        for item in items:
            source = self.safety.ensure_allowed_root(item.path)
            target = self.safety.destination_without_overwrite(destination / item.name)
            shutil.move(str(source), str(target))
            moved.append(target)
        return tuple(moved)

    def organize_items(self, root: Path, items: tuple[DownloadItem, ...]) -> tuple[Path, ...]:
        moved = []
        for item in items:
            folder = ORGANIZE_FOLDERS.get(item.kind, "Other")
            moved.extend(self.move_items((item,), root / folder))
        return tuple(moved)

    def archive_items(self, root: Path, items: tuple[DownloadItem, ...]) -> tuple[Path, ...]:
        return self.move_items(items, root / "Archives")


def destination_for_name(name: str) -> Path:
    home = Path.home()
    folder = DESTINATION_ALIASES.get(name.casefold(), name)
    if folder in {"Documents", "Pictures", "Videos", "Music"}:
        return home / folder
    return Path(folder).expanduser()


__all__ = ["DESTINATION_ALIASES", "ORGANIZE_FOLDERS", "DownloadsOrganizer", "destination_for_name"]
