"""Known user folders for high-level desktop automation."""

from __future__ import annotations

from pathlib import Path

FOLDER_ALIASES: dict[str, tuple[str, str]] = {
    "downloads": ("downloads", "Downloads"),
    "downloads folder": ("downloads", "Downloads"),
    "documents": ("documents", "Documents"),
    "documents folder": ("documents", "Documents"),
    "desktop": ("desktop", "Desktop"),
    "desktop folder": ("desktop", "Desktop"),
    "pictures": ("pictures", "Pictures"),
    "pictures folder": ("pictures", "Pictures"),
    "music": ("music", "Music"),
    "music folder": ("music", "Music"),
    "videos": ("videos", "Videos"),
    "videos folder": ("videos", "Videos"),
}


def resolve_folder(value: str) -> tuple[str, str] | None:
    """Resolve a natural folder name to a safe folder id and label."""

    return FOLDER_ALIASES.get(value.strip().casefold())


def folder_path(folder_id: str) -> Path:
    """Return the Windows user folder path for a known folder id."""

    return Path.home() / folder_id.title()


__all__ = ["FOLDER_ALIASES", "folder_path", "resolve_folder"]
