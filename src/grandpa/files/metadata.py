"""Pure, read-only filesystem metadata helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class PathMetadata:
    path: Path
    name: str
    kind: str
    size: int
    extension: str
    created_timestamp: float
    modified_timestamp: float
    created: str
    modified: str
    device: int
    inode: int


def inspect_path_metadata(path: Path) -> PathMetadata:
    """Read metadata without opening file contents or mutating the path."""

    canonical = path.expanduser().resolve(strict=True)
    stat = canonical.stat()
    is_directory = canonical.is_dir()
    extension = "" if is_directory else canonical.suffix.lower().lstrip(".")
    kind = "folder" if is_directory else (extension or "file")
    return PathMetadata(
        path=canonical,
        name=canonical.name,
        kind=kind,
        size=stat.st_size,
        extension=extension,
        created_timestamp=stat.st_ctime,
        modified_timestamp=stat.st_mtime,
        created=datetime.fromtimestamp(stat.st_ctime).isoformat(timespec="seconds"),
        modified=datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
        device=stat.st_dev,
        inode=stat.st_ino,
    )


def format_properties_message(metadata: PathMetadata) -> str:
    return (
        f"Properties for {metadata.name}:\n"
        f"- Path: {metadata.path}\n"
        f"- Type: {metadata.kind}\n"
        f"- Size: {size_label(metadata.size)}\n"
        f"- Created: {metadata.created}\n"
        f"- Modified: {metadata.modified}"
    )


def size_label(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


__all__ = [
    "PathMetadata",
    "format_properties_message",
    "inspect_path_metadata",
    "size_label",
]
