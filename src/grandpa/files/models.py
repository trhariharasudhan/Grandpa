"""Models for Grandpa file automation."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

FileActionType = Literal[
    "create_folder",
    "create_file",
    "rename",
    "copy",
    "move",
    "delete",
    "search",
    "open",
    "open_containing_folder",
    "zip",
    "extract",
    "properties",
]

FileActionStatus = Literal[
    "handled",
    "needs_confirmation",
    "blocked",
    "unsupported",
    "no_match",
    "error",
    "ambiguous",
]


@dataclass(frozen=True)
class FileAction:
    """Parsed file automation action."""

    action: FileActionType
    source: str = ""
    destination: str = ""
    query: str = ""
    overwrite: bool = False
    permanent: bool = False
    args: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FileOperationResult:
    """Result returned by the file automation engine."""

    status: FileActionStatus
    message: str
    action: FileAction | None = None
    path: Path | None = None
    destination: Path | None = None
    matches: tuple[Path, ...] = ()
    requires_confirmation: bool = False
    error: str | None = None

    @property
    def should_fallback(self) -> bool:
        return self.status == "no_match"


__all__ = ["FileAction", "FileActionStatus", "FileActionType", "FileOperationResult"]
