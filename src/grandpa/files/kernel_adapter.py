"""Compatibility translation between FileAutomation and AssistantKernel."""

from __future__ import annotations

from pathlib import Path

from grandpa.files.models import FileAction, FileOperationResult
from grandpa.files.paths import (
    find_matches,
    latest_by_suffix,
    resolve_alias,
    resolve_destination,
    resolve_path,
)
from grandpa.files.safety import FileSafetyPolicy
from grandpa.kernel.compat import build_file_compatibility_kernel
from grandpa.kernel.models import (
    AssistantRequest,
    AssistantSource,
    ResponseStatus,
    ToolStatus,
)


class KernelFileAutomationAdapter:
    """Route migrated legacy file actions through the canonical kernel."""

    def __init__(self, *, roots: tuple[Path, ...]) -> None:
        self._roots = roots
        self._kernel = build_file_compatibility_kernel(roots=roots)

    def handle(self, text: str, action: FileAction) -> FileOperationResult:
        response = self._kernel.handle(
            AssistantRequest.create(
                session_id="files-automation-compat",
                source=AssistantSource.SDK,
                text=text,
            )
        )
        if response.status is ResponseStatus.COMPLETED and response.actions:
            tool_result = response.actions[0]
            if action.action == "copy":
                return self._translate_copy(action, response, tool_result)
            if action.action == "create_folder":
                return self._translate_create_folder(action, tool_result)
            if action.action == "properties":
                return self._translate_properties(action, response.text, tool_result)
            matches = tuple(Path(path) for path in tool_result.data.get("matches", ()))
            primary = tool_result.data.get("primary_path")
            return FileOperationResult(
                "handled",
                response.text,
                action,
                Path(primary) if isinstance(primary, str) else None,
                matches=matches,
            )
        if action.action == "copy":
            return self._translate_copy(
                action,
                response,
                response.actions[0] if response.actions else None,
            )
        if response.actions and response.actions[0].status is ToolStatus.FAILED:
            tool_result = response.actions[0]
            error = tool_result.data.get("error")
            return FileOperationResult(
                "error",
                response.text,
                action,
                error=str(error) if error else "kernel_error",
            )
        if action.action == "create_folder" and any(
            marker in response.text.casefold()
            for marker in ("protected", "traversal", "outside the allowed")
        ):
            return FileOperationResult(
                "blocked",
                response.text,
                action,
                resolve_path(action.source, roots=self._roots),
            )
        return FileOperationResult(
            "error",
            response.text,
            action,
            error="kernel_error",
        )

    def _translate_copy(
        self,
        action: FileAction,
        response,
        tool_result,
    ) -> FileOperationResult:
        source, destination = self._copy_paths(action)
        if (
            response.status is ResponseStatus.COMPLETED
            and tool_result is not None
            and tool_result.status is ToolStatus.SUCCEEDED
            and tool_result.data.get("outcome") == "copied"
        ):
            return FileOperationResult(
                "handled",
                tool_result.safe_message,
                action,
                source,
                destination,
            )
        if (
            tool_result is not None
            and tool_result.status is ToolStatus.SUCCEEDED
            and tool_result.data.get("outcome") == "copied"
        ):
            return FileOperationResult(
                "error",
                response.text,
                action,
                source,
                destination,
                error="verification_failed",
            )
        compatibility = self._copy_compatibility(action)
        if compatibility is not None:
            return compatibility
        if tool_result is not None and tool_result.status is ToolStatus.FAILED:
            error = tool_result.data.get("error")
            return FileOperationResult(
                "error",
                response.text,
                action,
                source,
                destination,
                error=str(error) if error else "kernel_error",
            )
        if response.status is ResponseStatus.BLOCKED:
            return FileOperationResult(
                "blocked",
                response.text,
                action,
                source,
                destination,
            )
        return FileOperationResult(
            "error",
            response.text,
            action,
            source,
            destination,
            error="kernel_error",
        )

    def _copy_compatibility(
        self, action: FileAction
    ) -> FileOperationResult | None:
        source, matches = self._resolve_copy_source(action.source)
        if source is None:
            if len(matches) > 1:
                lines = ["I found multiple matching files. Choose one:"]
                lines.extend(
                    f"{index}. {match}"
                    for index, match in enumerate(matches[:10], start=1)
                )
                return FileOperationResult(
                    "ambiguous", "\n".join(lines), matches=matches
                )
            if action.source.casefold().startswith("latest pdf"):
                return FileOperationResult("handled", "No matching files found.")
            return FileOperationResult(
                "error",
                f"I could not find {action.source}.",
                action,
                error="missing_path",
            )
        destination = self._destination_for(action, source)
        safety = FileSafetyPolicy()
        if safety.blocks_traversal(action.source) or (
            action.destination and safety.blocks_traversal(action.destination)
        ):
            return FileOperationResult(
                "blocked", "Path traversal is blocked.", action, source, destination
            )
        if (
            safety.is_protected(source)
            or safety.is_protected(destination)
            or not self._is_within_roots(source)
            or not self._is_within_roots(destination)
        ):
            return FileOperationResult(
                "blocked",
                "That path is protected and cannot be modified.",
                action,
                source,
                destination,
            )
        if source.is_dir():
            return FileOperationResult(
                "unsupported",
                "Copying folders is not supported by the canonical file copy yet.",
                action,
                source,
                destination,
            )
        if destination == source:
            return FileOperationResult(
                "unsupported",
                "The copy destination must be different from the source.",
                action,
                source,
                destination,
            )
        if not destination.parent.exists() or not destination.parent.is_dir():
            return FileOperationResult(
                "unsupported",
                "The destination folder does not exist. Create it before copying.",
                action,
                source,
                destination,
            )
        if destination.exists():
            return FileOperationResult(
                "needs_confirmation",
                "Destination already exists. Confirm overwrite.",
                action,
                source,
                destination,
                requires_confirmation=True,
            )
        return None

    def _is_within_roots(self, path: Path) -> bool:
        canonical = path.resolve(strict=False)
        for root in self._roots:
            canonical_root = root.resolve(strict=False)
            if canonical == canonical_root:
                return True
            try:
                canonical.relative_to(canonical_root)
                return True
            except ValueError:
                continue
        return False

    def _copy_paths(self, action: FileAction) -> tuple[Path, Path]:
        source, _ = self._resolve_copy_source(action.source)
        if source is None:
            source = resolve_path(action.source, roots=self._roots)
        return source, self._destination_for(action, source)

    def _resolve_copy_source(
        self, requested_source: str
    ) -> tuple[Path | None, tuple[Path, ...]]:
        if requested_source.casefold().startswith("latest pdf"):
            latest = latest_by_suffix({".pdf"}, roots=self._roots)
            return latest, ()
        source = resolve_path(requested_source, roots=self._roots)
        if source.exists():
            return source.resolve(strict=False), ()
        matches = tuple(find_matches(requested_source, roots=self._roots))
        return (matches[0], matches) if len(matches) == 1 else (None, matches)

    def _destination_for(self, action: FileAction, source: Path) -> Path:
        if not action.destination:
            return source.with_name(f"{source.stem} copy{source.suffix}").resolve(
                strict=False
            )
        destination = resolve_destination(action.destination, roots=self._roots)
        if destination.exists() and destination.is_dir():
            return (destination / source.name).resolve(strict=False)
        if resolve_alias(action.destination) is not None:
            return (destination / source.name).resolve(strict=False)
        return destination.resolve(strict=False)

    @staticmethod
    def _translate_create_folder(
        action: FileAction,
        tool_result,
    ) -> FileOperationResult:
        target = Path(str(tool_result.data["path"]))
        if tool_result.data.get("outcome") in {
            "existing_directory",
            "existing_file",
        }:
            return FileOperationResult(
                "needs_confirmation",
                "Destination already exists. Confirm overwrite.",
                action,
                target,
                requires_confirmation=True,
            )
        if tool_result.data.get("outcome") == "created":
            return FileOperationResult(
                "handled",
                tool_result.safe_message,
                action,
                target,
            )
        return FileOperationResult("error", tool_result.safe_message, action)

    @staticmethod
    def _translate_properties(
        action: FileAction,
        message: str,
        tool_result,
    ) -> FileOperationResult:
        outcome = tool_result.data.get("outcome")
        matches = tuple(Path(path) for path in tool_result.data.get("matches", ()))
        if outcome == "resolved":
            return FileOperationResult(
                "handled",
                message,
                action,
                Path(str(tool_result.data["path"])),
            )
        if outcome == "ambiguous":
            return FileOperationResult("ambiguous", message, matches=matches)
        if outcome == "no_matches":
            return FileOperationResult("handled", message)
        if outcome == "missing":
            return FileOperationResult("error", message, error="missing_path")
        return FileOperationResult("error", message, action, error="kernel_error")


__all__ = ["KernelFileAutomationAdapter"]
