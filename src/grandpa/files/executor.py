"""Executor for Grandpa file automation."""

from __future__ import annotations

import os
import shutil
import zipfile
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any

from grandpa.files.metadata import format_properties_message, inspect_path_metadata
from grandpa.files.models import FileAction, FileOperationResult
from grandpa.files.paths import (
    describe_path,
    find_matches,
    latest_by_suffix,
    resolve_destination,
    resolve_path,
    safe_roots,
)
from grandpa.files.safety import FileSafetyPolicy
from grandpa.policy.boundary import MutationBoundary

ConfirmationCallback = Callable[[FileAction, Path | None, Path | None], bool]
OpenCallback = Callable[[Path], None]

#: A substitute for direct filesystem mutation, taking the same payload as
#: ``run_local_action`` and returning its response.
#:
#: Named by ``grandpa.policy`` rather than here. The seam is unchanged -- same
#: callable, same payload, same response -- but the layer that owns the
#: boundary now owns its name, which is what lets this package depend on
#: ``policy`` instead of on the execution module. The old alias is kept because
#: it is part of this module's public surface.
MutationRunner = MutationBoundary

#: The actions whose mutation can be routed through the actuator boundary, and
#: the existing pc_control action type each maps to.
#:
#: Every mutating action is here; the read-only ones -- ``search``,
#: ``properties``, ``open`` and the rest -- are absent because they have no
#: mutation to route, not because they route somewhere else.
#:
#: Routing is opt-in: it happens only when a caller supplies a
#: ``mutation_runner``, and what is routed is the *mutation alone*. Alias
#: resolution, ``_blocked_path``, ``blocks_recursive_delete`` and the overwrite
#: and delete confirmations all run first and are not replaced by anything
#: behind the boundary.
#:
#: Production entry surfaces get a runner from ``grandpa.composition``. A
#: caller that supplies none mutates the disk here, which is the compatibility
#: contract direct capability callers rely on.
_BOUNDARY_ACTION_TYPES: dict[str, str] = {
    "create_file": "file_create",
    "create_folder": "file_create",
    "copy": "file_copy",
    "delete": "file_delete",
    "move": "file_move",
    "rename": "file_rename",
}
BOUNDARY_ROUTED_ACTIONS = frozenset(_BOUNDARY_ACTION_TYPES)


def _result_from_response(
    action: FileAction,
    response: Any,
    target: Path,
    destination: Path | None,
    success: str,
) -> FileOperationResult:
    """Present a ``LocalActionResponse`` in this module's own result shape.

    The boundary's statuses map onto the ones callers already handle, so a
    staged approval reads as ``needs_confirmation`` and a policy refusal as
    ``blocked`` -- the same words this module used for the same outcomes.
    """
    status = str(getattr(response, "status", "error"))
    mapped = {
        "completed": "handled",
        "dry_run": "handled",
        "approval_required": "needs_confirmation",
        "blocked": "blocked",
        "unsupported": "unsupported",
    }.get(status, "error")
    message = str(getattr(response, "message", "") or "")
    return FileOperationResult(
        mapped,  # type: ignore[arg-type]
        success if mapped == "handled" and success else message,
        action,
        target,
        destination,
        requires_confirmation=mapped == "needs_confirmation",
    )


class FileExecutor:
    """Execute file actions using pathlib/shutil/zipfile with safety checks."""

    def __init__(
        self,
        *,
        roots: tuple[Path, ...] = (),
        safety: FileSafetyPolicy | None = None,
        opener: OpenCallback | None = None,
        mutation_runner: MutationRunner | None = None,
        origin: str = "direct",
        dry_run: bool = False,
    ) -> None:
        self.roots = roots or safe_roots()
        self.safety = safety or FileSafetyPolicy()
        self.opener = opener or _default_open
        # Request-scoped configuration, set once here and never reassigned.
        # An instance is built per request, so this state cannot outlive or
        # escape the request it was made for -- which is why the caller
        # replaces the executor rather than reconfiguring a shared one.
        self.mutation_runner = mutation_runner
        self.origin = origin
        self.dry_run = dry_run

    def execute(
        self, action: FileAction, *, confirm: ConfirmationCallback | None = None
    ) -> FileOperationResult:
        try:
            if action.action == "create_folder":
                return self._create(action, folder=True)
            if action.action == "create_file":
                return self._create(action, folder=False)
            if action.action == "rename":
                return self._rename(action)
            if action.action == "copy":
                return self._copy(action)
            if action.action == "move":
                return self._move(action)
            if action.action == "delete":
                return self._delete(action, confirm=confirm)
            if action.action == "search":
                return self._search(action)
            if action.action == "open":
                return self._open(action)
            if action.action == "open_containing_folder":
                return self._open_containing_folder(action)
            if action.action == "zip":
                return self._zip(action)
            if action.action == "extract":
                return self._extract(action)
            if action.action == "properties":
                return self._properties(action)
        except OSError as exc:
            return FileOperationResult(
                "error",
                f"I could not complete that file action: {exc}",
                action,
                error=exc.__class__.__name__,
            )
        return FileOperationResult(
            "unsupported", "This file action is not supported yet.", action
        )

    def _route(
        self,
        action: FileAction,
        action_type: str,
        target: Path,
        *,
        args: dict[str, Any] | None = None,
        destination: Path | None = None,
        success: str = "",
    ) -> FileOperationResult | None:
        """Perform this mutation through the actuator, or None to do it here.

        Returns None when no runner was configured, which is every caller that
        has not opted in -- their behaviour is untouched.

        Only the mutation moves. Alias resolution, ``_blocked_path``,
        ``blocks_recursive_delete`` and the overwrite confirmation have all
        already run by the time this is reached, because they are file-domain
        safety with no equivalent inside ``run_local_action`` and routing must
        not quietly drop them.

        Reads configuration; never writes it.
        """
        if self.mutation_runner is None or action.action not in BOUNDARY_ROUTED_ACTIONS:
            return None
        payload: dict[str, Any] = {
            "action_type": action_type,
            "target": str(target),
            "args": dict(args or {}),
            "origin": self.origin,
            "dry_run": self.dry_run,
            "require_approval": False,
        }
        if destination is not None:
            payload["args"]["destination"] = str(destination)
        response = self.mutation_runner(payload)
        return _result_from_response(action, response, target, destination, success)

    def _create(self, action: FileAction, *, folder: bool) -> FileOperationResult:
        path = self._resolve_new_path(action.source)
        blocked = self._blocked_path(path, action)
        if blocked:
            return blocked
        if path.exists() and not action.overwrite:
            return FileOperationResult(
                "needs_confirmation",
                "Destination already exists. Confirm overwrite.",
                action,
                path,
                requires_confirmation=True,
            )
        label = "Folder" if folder else "File"
        # Both kinds route. The folder branch used to return here, one line
        # after the overwrite check and before ``_route`` was ever reached, so
        # a folder appeared on disk without the tier, stop, dry run, audit or
        # provenance every other file mutation gets. The boundary's
        # ``file_create`` already understands ``kind``, so this needed no new
        # action type and no new tier.
        routed = self._route(
            action,
            "file_create",
            path,
            args={"kind": "folder" if folder else "file", "content": ""},
            success=f"{label} created: {describe_path(path)}",
        )
        if routed is not None:
            return routed
        if folder:
            path.mkdir(parents=True, exist_ok=action.overwrite)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("", encoding="utf-8")
        return FileOperationResult(
            "handled", f"{label} created: {describe_path(path)}", action, path
        )

    def _rename(self, action: FileAction) -> FileOperationResult:
        source = self._resolve_existing(action.source)
        if isinstance(source, FileOperationResult):
            return source
        destination = source.with_name(action.destination)
        return self._move_or_copy(
            action, source, destination, move=True, label="renamed"
        )

    def _copy(self, action: FileAction) -> FileOperationResult:
        source = self._resolve_existing(action.source)
        if isinstance(source, FileOperationResult):
            return source
        destination = self._destination_for(action, source)
        return self._move_or_copy(
            action, source, destination, move=False, label="copied"
        )

    def _move(self, action: FileAction) -> FileOperationResult:
        source = self._resolve_existing(action.source)
        if isinstance(source, FileOperationResult):
            return source
        destination = self._destination_for(action, source)
        return self._move_or_copy(action, source, destination, move=True, label="moved")

    def _delete(
        self, action: FileAction, *, confirm: ConfirmationCallback | None
    ) -> FileOperationResult:
        source = self._resolve_existing(action.source)
        if isinstance(source, FileOperationResult):
            return source
        blocked = self._blocked_path(source, action)
        if blocked:
            return blocked
        if self.safety.blocks_recursive_delete(source):
            return FileOperationResult(
                "blocked",
                "Recursive deletion of that user folder is blocked.",
                action,
                source,
            )
        if confirm is None or not confirm(action, source, None):
            return FileOperationResult(
                "needs_confirmation",
                f"Delete {describe_path(source)}? (y/N)",
                action,
                source,
                requires_confirmation=True,
            )
        routed = self._route(
            action, "file_delete", source, success=f"Deleted: {describe_path(source)}"
        )
        if routed is not None:
            return routed
        if source.is_dir():
            shutil.rmtree(source)
        else:
            source.unlink()
        return FileOperationResult(
            "handled", f"Deleted: {describe_path(source)}", action, source
        )

    def _search(self, action: FileAction) -> FileOperationResult:
        if action.args.get("latest"):
            path = latest_by_suffix(
                set(action.args.get("suffixes") or ()), roots=self.roots
            )
            if path is None:
                return FileOperationResult(
                    "handled", "No matching files found.", action
                )
            return FileOperationResult(
                "handled",
                f"Latest match: {describe_path(path)}",
                action,
                path,
                matches=(path,),
            )
        matches = tuple(find_matches(action.query, roots=self.roots))
        suffixes = {
            str(suffix).casefold() for suffix in action.args.get("suffixes", ())
        }
        if suffixes:
            matches = tuple(
                path for path in matches if path.suffix.casefold() in suffixes
            )
        if not matches:
            return FileOperationResult("handled", "No matching files found.", action)
        lines = [f"Found {len(matches)} matching file(s):"]
        lines.extend(
            f"{index}. {path}" for index, path in enumerate(matches[:10], start=1)
        )
        return FileOperationResult("handled", "\n".join(lines), action, matches=matches)

    def _open(self, action: FileAction) -> FileOperationResult:
        source = self._resolve_existing(action.source)
        if isinstance(source, FileOperationResult):
            return source
        self.opener(source)
        return FileOperationResult(
            "handled", f"Opening {describe_path(source)}.", action, source
        )

    def _open_containing_folder(self, action: FileAction) -> FileOperationResult:
        source = self._resolve_existing(action.source)
        if isinstance(source, FileOperationResult):
            return source
        folder = source if source.is_dir() else source.parent
        self.opener(folder)
        return FileOperationResult(
            "handled",
            f"Opening containing folder: {describe_path(folder)}.",
            action,
            folder,
        )

    def _zip(self, action: FileAction) -> FileOperationResult:
        source = self._resolve_existing(action.source)
        if isinstance(source, FileOperationResult):
            return source
        destination = source.with_suffix(".zip")
        if destination.exists() and not action.overwrite:
            return FileOperationResult(
                "needs_confirmation",
                "Destination archive already exists. Confirm overwrite.",
                action,
                source,
                destination,
                requires_confirmation=True,
            )
        blocked = self._blocked_path(destination, action)
        if blocked:
            return blocked
        with zipfile.ZipFile(
            destination, "w", compression=zipfile.ZIP_DEFLATED
        ) as archive:
            if source.is_dir():
                for path in source.rglob("*"):
                    if path.is_file():
                        archive.write(path, path.relative_to(source.parent))
            else:
                archive.write(source, source.name)
        return FileOperationResult(
            "handled",
            f"Archive created: {describe_path(destination)}",
            action,
            source,
            destination,
        )

    def _extract(self, action: FileAction) -> FileOperationResult:
        source = self._resolve_existing(action.source)
        if isinstance(source, FileOperationResult):
            return source
        if source.suffix.casefold() != ".zip":
            return FileOperationResult(
                "unsupported",
                "This archive format is not supported yet.",
                action,
                source,
            )
        destination = (
            resolve_destination(action.destination, roots=self.roots)
            if action.destination
            else source.with_suffix("")
        )
        blocked = self._blocked_path(destination, action)
        if blocked:
            return blocked
        destination.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(source, "r") as archive:
            for member in archive.infolist():
                member_path = PurePosixPath(member.filename)
                if member_path.is_absolute() or ".." in member_path.parts:
                    return FileOperationResult(
                        "blocked",
                        "Archive contains unsafe paths.",
                        action,
                        source,
                        destination,
                    )
                target = (destination / member.filename).resolve(strict=False)
                if (
                    not str(target)
                    .casefold()
                    .startswith(str(destination.resolve(strict=False)).casefold())
                ):
                    return FileOperationResult(
                        "blocked",
                        "Archive contains unsafe paths.",
                        action,
                        source,
                        destination,
                    )
            archive.extractall(destination)
        return FileOperationResult(
            "handled",
            f"Archive extracted to {describe_path(destination)}",
            action,
            source,
            destination,
        )

    def _properties(self, action: FileAction) -> FileOperationResult:
        source = self._resolve_existing(action.source)
        if isinstance(source, FileOperationResult):
            return source
        metadata = inspect_path_metadata(source)
        return FileOperationResult(
            "handled", format_properties_message(metadata), action, metadata.path
        )

    def _move_or_copy(
        self,
        action: FileAction,
        source: Path,
        destination: Path,
        *,
        move: bool,
        label: str,
    ) -> FileOperationResult:
        blocked = self._blocked_path(destination, action) or self._blocked_path(
            source, action
        )
        if blocked:
            return blocked
        if destination.exists() and not action.overwrite:
            return FileOperationResult(
                "needs_confirmation",
                "Destination already exists. Confirm overwrite.",
                action,
                source,
                destination,
                requires_confirmation=True,
            )
        # Copies route as well as moves. The ``if move:`` that used to guard
        # this meant a copy fell straight through to ``shutil.copy2`` -- a
        # mutation with no tier, no stop, no dry run and no audit, while the
        # move a line below it had all four. ``file_copy`` already exists at
        # MEDIUM, so this is routing, not a policy change.
        routed = self._route(
            action,
            _BOUNDARY_ACTION_TYPES.get(
                action.action, "file_move" if move else "file_copy"
            ),
            source,
            destination=destination,
            success=f"File {label} to {describe_path(destination)}.",
        )
        if routed is not None:
            return routed
        destination.parent.mkdir(parents=True, exist_ok=True)
        if move:
            shutil.move(str(source), str(destination))
        elif source.is_dir():
            shutil.copytree(source, destination)
        else:
            shutil.copy2(source, destination)
        return FileOperationResult(
            "handled",
            f"File {label} to {describe_path(destination)}.",
            action,
            source,
            destination,
        )

    def _destination_for(self, action: FileAction, source: Path) -> Path:
        if action.destination:
            destination = resolve_destination(action.destination, roots=self.roots)
            if destination.exists() and destination.is_dir():
                return destination / source.name
            if action.destination.casefold() in {
                "desktop",
                "documents",
                "downloads",
                "pictures",
                "music",
                "videos",
                "home",
                "project",
                "grandpa project",
            }:
                return destination / source.name
            return destination
        return source.with_name(f"{source.stem} copy{source.suffix}")

    def _resolve_new_path(self, value: str) -> Path:
        return resolve_path(value, roots=self.roots)

    def _resolve_existing(self, value: str) -> Path | FileOperationResult:
        raw = str(value or "").strip()
        if raw.lower().startswith("latest pdf"):
            latest = latest_by_suffix({".pdf"}, roots=self.roots)
            if latest is None:
                return FileOperationResult("handled", "No matching files found.")
            return latest
        path = resolve_path(raw, roots=self.roots)
        if path.exists():
            return path
        matches = find_matches(raw, roots=self.roots)
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            lines = ["I found multiple matching files. Choose one:"]
            lines.extend(
                f"{index}. {match}" for index, match in enumerate(matches[:10], start=1)
            )
            return FileOperationResult(
                "ambiguous", "\n".join(lines), matches=tuple(matches)
            )
        return FileOperationResult(
            "error", f"I could not find {raw}.", error="missing_path"
        )

    def _blocked_path(
        self, path: Path, action: FileAction
    ) -> FileOperationResult | None:
        if self.safety.blocks_traversal(action.source) or (
            action.destination and self.safety.blocks_traversal(action.destination)
        ):
            return FileOperationResult(
                "blocked", "Path traversal is blocked.", action, path
            )
        if self.safety.is_protected(path):
            return FileOperationResult(
                "blocked",
                "That path is protected and cannot be modified.",
                action,
                path,
            )
        return None


def _default_open(path: Path) -> None:
    if os.name != "nt":
        raise OSError("Opening files is only supported on Windows desktop here.")
    os.startfile(path)  # type: ignore[attr-defined]  # noqa: S606


__all__ = ["ConfirmationCallback", "FileExecutor", "OpenCallback"]
