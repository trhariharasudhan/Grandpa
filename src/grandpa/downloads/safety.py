"""Safety policy for Downloads scanning and file operations."""

from __future__ import annotations

import os
from pathlib import Path

DANGEROUS_EXTENSIONS = {".bat", ".cmd", ".com", ".exe", ".js", ".msi", ".ps1", ".scr", ".vbs"}
INCOMPLETE_EXTENSIONS = {".crdownload", ".part", ".tmp"}


class DownloadsSafetyPolicy:
    """Keep Downloads actions scoped, non-executable, and confirmation-gated."""

    def __init__(self, roots: tuple[Path, ...]) -> None:
        self.roots = tuple(Path(root).expanduser() for root in roots)

    def ensure_allowed_root(self, path: Path) -> Path:
        resolved = path.expanduser().resolve()
        for root in self.roots:
            root_resolved = root.expanduser().resolve()
            if resolved == root_resolved or root_resolved in resolved.parents:
                return resolved
        raise DownloadsSafetyError("Blocked path outside configured Downloads folders.")

    def safe_destination(self, destination: Path) -> Path:
        resolved = destination.expanduser().resolve()
        home = Path.home().resolve()
        allowed = {
            home / "Documents",
            home / "Pictures",
            home / "Videos",
            home / "Music",
            *(root.expanduser().resolve() for root in self.roots),
        }
        if any(resolved == target or target in resolved.parents for target in allowed):
            return resolved
        raise DownloadsSafetyError("Blocked destination outside approved user folders.")

    def is_safe_to_open(self, path: Path) -> bool:
        return path.suffix.casefold() not in DANGEROUS_EXTENSIONS and not self.is_incomplete(path)

    def is_incomplete(self, path: Path) -> bool:
        return path.suffix.casefold() in INCOMPLETE_EXTENSIONS

    def requires_confirmation(self, action: str, *, count: int = 1) -> bool:
        return action in {"delete", "organize", "archive"} or (action == "move" and count > 1)

    def destination_without_overwrite(self, destination: Path) -> Path:
        if not destination.exists():
            return destination
        stem = destination.stem
        suffix = destination.suffix
        parent = destination.parent
        counter = 2
        while True:
            candidate = parent / f"{stem}-{counter}{suffix}"
            if not candidate.exists():
                return candidate
            counter += 1


class DownloadsSafetyError(RuntimeError):
    """Raised when a Downloads operation violates local safety rules."""


def default_download_roots() -> tuple[Path, ...]:
    configured = os.environ.get("GRANDPA_DOWNLOADS_DIR", "").strip()
    if configured:
        return (Path(configured).expanduser(),)
    return (Path.home() / "Downloads",)


__all__ = [
    "DANGEROUS_EXTENSIONS",
    "INCOMPLETE_EXTENSIONS",
    "DownloadsSafetyError",
    "DownloadsSafetyPolicy",
    "default_download_roots",
]
