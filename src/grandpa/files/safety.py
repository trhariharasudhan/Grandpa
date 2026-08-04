"""Safety policy for Grandpa file automation."""

from __future__ import annotations

from pathlib import Path, PureWindowsPath

PROTECTED_WINDOWS_ROOT_NAMES = {"windows", "program files", "program files (x86)"}
PROTECTED_PARTS = {
    "$recycle.bin",
    "system volume information",
    "system32",
    ".ssh",
}
CONFIG_NAMES = {".grandpa"}


class FileSafetyPolicy:
    """Conservative local file safety checks."""

    def is_protected(self, path: Path) -> bool:
        parts = _normalised_parts(path)
        if (
            len(parts) >= 2
            and parts[0].endswith(":")
            and parts[1] in PROTECTED_WINDOWS_ROOT_NAMES
        ):
            return True
        if set(parts) & PROTECTED_PARTS:
            return True
        if any(part in CONFIG_NAMES for part in parts):
            return True
        return False

    def blocks_traversal(self, raw: str) -> bool:
        return any(
            part == ".." for part in PureWindowsPath(str(raw).replace("/", "\\")).parts
        )

    def delete_requires_confirmation(self, path: Path) -> bool:
        return True

    def blocks_recursive_delete(self, path: Path) -> bool:
        protected_names = {
            "desktop",
            "documents",
            "downloads",
            "pictures",
            "music",
            "videos",
        }
        return path.is_dir() and path.name.casefold() in protected_names


def _normalised_parts(path: Path) -> tuple[str, ...]:
    raw = str(path.expanduser().resolve(strict=False)).replace("/", "\\")
    if len(raw) >= 2 and raw[1] == ":":
        return tuple(
            part.rstrip("\\/").casefold()
            for part in PureWindowsPath(raw).parts
            if part.rstrip("\\/")
        )
    return tuple(
        part.casefold()
        for part in path.expanduser().resolve(strict=False).parts
        if part
    )


__all__ = ["FileSafetyPolicy"]
