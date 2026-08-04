"""Downloads folder scanner and classifier."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

from grandpa.downloads.models import DownloadItem
from grandpa.downloads.safety import DownloadsSafetyPolicy, default_download_roots

KIND_EXTENSIONS = {
    "pdf": {".pdf"},
    "image": {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff"},
    "video": {".mp4", ".mov", ".mkv", ".avi", ".webm"},
    "audio": {".mp3", ".wav", ".m4a", ".flac", ".ogg"},
    "document": {
        ".doc",
        ".docx",
        ".txt",
        ".rtf",
        ".md",
        ".xls",
        ".xlsx",
        ".ppt",
        ".pptx",
        ".csv",
    },
    "archive": {".zip", ".rar", ".7z", ".tar", ".gz"},
    "installer": {".exe", ".msi"},
}


class DownloadsScanner:
    """Non-recursive scanner for configured Downloads roots."""

    def __init__(
        self,
        roots: tuple[Path, ...] | None = None,
        safety: DownloadsSafetyPolicy | None = None,
    ) -> None:
        self.roots = tuple(
            Path(root).expanduser() for root in (roots or default_download_roots())
        )
        self.safety = safety or DownloadsSafetyPolicy(self.roots)

    def status(self) -> tuple[str, str]:
        try:
            for root in self.roots:
                self.safety.ensure_allowed_root(root)
                if not root.exists():
                    return "missing", f"Downloads folder missing: {root}"
                if not root.is_dir():
                    return (
                        "missing",
                        f"Configured Downloads path is not a folder: {root}",
                    )
                next(root.iterdir(), None)
            return "ready", "Downloads directory ready."
        except PermissionError as exc:
            return "permission_denied", f"Downloads permission denied: {exc}"
        except Exception as exc:
            return "error", f"Downloads scanner unavailable: {exc}"

    def scan(self) -> tuple[DownloadItem, ...]:
        items: list[DownloadItem] = []
        for root in self.roots:
            root_path = self.safety.ensure_allowed_root(root)
            if not root_path.exists() or not root_path.is_dir():
                continue
            for path in root_path.iterdir():
                if path.is_file():
                    items.append(self._item(path))
        return tuple(
            sorted(
                items,
                key=lambda item: item.path.stat().st_mtime if item.path.exists() else 0,
                reverse=True,
            )
        )

    def recent(self, *, limit: int = 10) -> tuple[DownloadItem, ...]:
        return self.scan()[:limit]

    def today(self) -> tuple[DownloadItem, ...]:
        start = (
            datetime.now(timezone.utc)
            .astimezone()
            .replace(hour=0, minute=0, second=0, microsecond=0)
        )
        return tuple(
            item for item in self.scan() if _modified_datetime(item.path) >= start
        )

    def large(self, *, min_bytes: int = 100 * 1024 * 1024) -> tuple[DownloadItem, ...]:
        return tuple(item for item in self.scan() if item.size_bytes >= min_bytes)

    def incomplete(self) -> tuple[DownloadItem, ...]:
        return tuple(item for item in self.scan() if item.incomplete)

    def search(self, query: str) -> tuple[DownloadItem, ...]:
        needle = query.casefold().strip()
        if not needle:
            return ()
        if needle in {"pdf", "pdfs"}:
            return self.by_kind("pdf")
        if needle in {"image", "images", "pictures"}:
            return self.by_kind("image")
        return tuple(
            item
            for item in self.scan()
            if needle in item.name.casefold() or needle in item.kind
        )

    def by_kind(self, kind: str) -> tuple[DownloadItem, ...]:
        return tuple(item for item in self.scan() if item.kind == kind)

    def older_than(self, days: int) -> tuple[DownloadItem, ...]:
        cutoff = datetime.now(timezone.utc).astimezone() - timedelta(days=days)
        return tuple(
            item for item in self.scan() if _modified_datetime(item.path) < cutoff
        )

    def duplicates(self) -> tuple[DownloadItem, ...]:
        groups: dict[tuple[int, str], list[DownloadItem]] = {}
        for item in self.scan():
            if item.incomplete:
                continue
            digest = _sha256(item.path)
            groups.setdefault((item.size_bytes, digest), []).append(item)
        duplicates = []
        for digest, items in groups.items():
            if len(items) > 1:
                duplicates.extend(
                    _with_duplicate_group(item, str(digest[1])[:12]) for item in items
                )
        return tuple(duplicates)

    def latest(self) -> DownloadItem | None:
        items = self.scan()
        return items[0] if items else None

    def _item(self, path: Path) -> DownloadItem:
        stat = path.stat()
        return DownloadItem(
            path=path,
            name=path.name,
            size_bytes=stat.st_size,
            modified_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
            .astimezone()
            .isoformat(),
            kind=classify_file(path),
            safe_to_open=self.safety.is_safe_to_open(path),
            incomplete=self.safety.is_incomplete(path),
        )


def classify_file(path: Path) -> str:
    suffix = path.suffix.casefold()
    for kind, extensions in KIND_EXTENSIONS.items():
        if suffix in extensions:
            return kind
    return "other"


def _modified_datetime(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).astimezone()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _with_duplicate_group(item: DownloadItem, group: str) -> DownloadItem:
    return DownloadItem(
        path=item.path,
        name=item.name,
        size_bytes=item.size_bytes,
        modified_at=item.modified_at,
        kind=item.kind,
        safe_to_open=item.safe_to_open,
        incomplete=item.incomplete,
        duplicate_group=group,
    )


__all__ = ["DownloadsScanner", "KIND_EXTENSIONS", "classify_file"]
