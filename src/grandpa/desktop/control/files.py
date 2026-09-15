"""File operation service for PC control."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MAX_READ_BYTES = 256 * 1024
"""Ceiling on one file read. A quarter of a megabyte is a long document and
still small enough to sit in a model's context without crowding out the
conversation; anything bigger is a data file, not something to read aloud."""


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root.resolve(strict=False))
    except ValueError:
        return False
    return True


@dataclass(frozen=True)
class FileControlService:
    """Create, rename, move, copy, and approval-gated delete operations."""

    name: str = "files"

    def execute(self, request: Any, action: str):
        from grandpa.pc_control import LocalActionResponse

        target = self.resolve_path(request.target)
        destination = (
            self.resolve_path(str(request.args.get("destination", "")))
            if request.args.get("destination")
            else None
        )
        if action == "file_create":
            kind = request.args.get("kind", "file")
            if kind == "folder":
                target.mkdir(parents=True, exist_ok=False)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(
                    str(request.args.get("content", "")), encoding="utf-8"
                )
            return LocalActionResponse(
                True,
                None,
                "completed",
                f"Created {kind}.",
                False,
                "LOW",
                {"path": str(target), "kind": kind},
            )
        if action == "file_rename":
            if destination is None:
                destination = target.with_name(str(request.args["new_name"]))
            destination.parent.mkdir(parents=True, exist_ok=True)
            target.rename(destination)
            return LocalActionResponse(
                True,
                None,
                "completed",
                "Renamed item.",
                False,
                "MEDIUM",
                {"from": str(target), "to": str(destination)},
            )
        if action == "file_move":
            if destination is None:
                raise ValueError("destination is required")
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(target), str(destination))
            return LocalActionResponse(
                True,
                None,
                "completed",
                "Moved item.",
                False,
                "MEDIUM",
                {"from": str(target), "to": str(destination)},
            )
        if action == "file_copy":
            if destination is None:
                raise ValueError("destination is required")
            if target.is_dir():
                shutil.copytree(target, destination)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, destination)
            return LocalActionResponse(
                True,
                None,
                "completed",
                "Copied item.",
                False,
                "MEDIUM",
                {"from": str(target), "to": str(destination)},
            )
        if action == "file_delete":
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
            return LocalActionResponse(
                True,
                None,
                "completed",
                "Deleted item.",
                False,
                "HIGH",
                {"path": str(target)},
            )
        return LocalActionResponse(
            False,
            None,
            "blocked",
            "I blocked this file action for safety.",
            False,
            "BLOCKED",
            error="blocked_by_policy",
        )

    def resolve_path(self, path: str) -> Path:
        if not path:
            raise ValueError("path is required")
        candidate = Path(path).expanduser()
        return candidate.resolve(strict=False)

    def execute_read(self, request: Any):
        """Read a text file back, bounded and inside the searchable roots.

        Reading is the half of file handling that was missing: everything else
        here writes. Two limits make it safe to hand to a model. It refuses
        anything outside ``grandpa.files.paths.safe_roots()`` -- the same roots
        file search already walks, so this reads exactly what the user can
        already find -- and it refuses a file over ``max_bytes``, because a
        model that reads a 2 GB log puts it in the prompt.
        """
        from grandpa.files.paths import safe_roots
        from grandpa.pc_control import LocalActionResponse

        target = self.resolve_path(request.target)
        limit = max(
            1, min(int(request.args.get("max_bytes", MAX_READ_BYTES)), MAX_READ_BYTES)
        )

        roots = safe_roots()
        if not any(_is_within(target, root) for root in roots):
            return LocalActionResponse(
                False,
                None,
                "blocked",
                f"I only read files under {', '.join(str(root) for root in roots[:4])} "
                "and the other searchable folders.",
                False,
                "LOW",
                {"path": str(target)},
                error="outside_safe_roots",
            )
        if not target.exists() or not target.is_file():
            return LocalActionResponse(
                False,
                None,
                "failed",
                f"I could not find the file: {request.target}",
                False,
                "LOW",
                {"path": str(target)},
                error="missing_file",
            )
        size = target.stat().st_size
        if size > limit:
            return LocalActionResponse(
                False,
                None,
                "blocked",
                f"That file is {size} bytes, over the {limit}-byte read limit.",
                False,
                "LOW",
                {"path": str(target), "size": size, "max_bytes": limit},
                error="file_too_large",
            )
        try:
            text = target.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return LocalActionResponse(
                False,
                None,
                "unsupported",
                "That file is not UTF-8 text, so there is nothing to read out.",
                False,
                "LOW",
                {"path": str(target), "size": size},
                error="not_text",
            )
        return LocalActionResponse(
            True,
            None,
            "completed",
            f"Read {size} bytes from {target.name}.",
            False,
            "LOW",
            {"path": str(target), "size": size, "content": text},
        )

    def diagnostics(self) -> dict[str, Any]:
        return {
            "service": self.name,
            "ready": True,
            "risk_levels": {
                "file_create": "LOW",
                "file_rename": "MEDIUM",
                "file_move": "MEDIUM",
                "file_copy": "MEDIUM",
                "file_delete": "HIGH",
                "file_read": "LOW",
                "file_permanent_delete": "BLOCKED",
            },
            "safety": {
                "protected_path_preflight": True,
                "delete_requires_approval": True,
            },
        }


__all__ = ["FileControlService"]
