"""User-facing formatting for Downloads Manager results."""

from __future__ import annotations

from grandpa.downloads.models import DownloadItem


def format_download_list(items: tuple[DownloadItem, ...], *, empty_message: str = "No downloads found.") -> str:
    if not items:
        return empty_message
    lines = ["Downloads:"]
    for item in items:
        flags = []
        if item.incomplete:
            flags.append("incomplete")
        if not item.safe_to_open:
            flags.append("unsafe to open")
        flag_text = f" [{' / '.join(flags)}]" if flags else ""
        lines.append(f"- {item.name} — {item.kind}, {_format_size(item.size_bytes)}, modified {item.modified_at}{flag_text}")
    return "\n".join(lines)


def format_download_info(item: DownloadItem) -> str:
    return "\n".join(
        (
            f"Name: {item.name}",
            f"Path: {item.path}",
            f"Type: {item.kind}",
            f"Size: {_format_size(item.size_bytes)}",
            f"Modified: {item.modified_at}",
            f"Safe to open: {'yes' if item.safe_to_open else 'no'}",
            f"Incomplete: {'yes' if item.incomplete else 'no'}",
        )
    )


def format_duplicate_groups(items: tuple[DownloadItem, ...]) -> str:
    if not items:
        return "No duplicate downloads found."
    lines = ["Duplicate downloads:"]
    for item in items:
        lines.append(f"- [{item.duplicate_group}] {item.name} — {_format_size(item.size_bytes)}")
    return "\n".join(lines)


def format_operation_plan(action: str, items: tuple[DownloadItem, ...]) -> str:
    total = sum(item.size_bytes for item in items)
    return f"{action.capitalize()} {len(items)} download{'s' if len(items) != 1 else ''} ({_format_size(total)})? [y/N]"


def _format_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{size} B"


__all__ = ["format_download_info", "format_download_list", "format_duplicate_groups", "format_operation_plan"]
