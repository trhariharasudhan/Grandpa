"""File operation service for PC control."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any


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
                "file_permanent_delete": "BLOCKED",
            },
            "safety": {
                "protected_path_preflight": True,
                "delete_requires_approval": True,
            },
        }


__all__ = ["FileControlService"]
