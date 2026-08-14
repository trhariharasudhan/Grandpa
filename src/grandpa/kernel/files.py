"""Canonical file tools used by the AssistantKernel compatibility slice."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Any, Mapping

from grandpa.kernel.errors import (
    SecurityInvariantError,
    ToolArgumentValidationError,
    ToolNotFoundError,
)
from grandpa.kernel.interfaces import ToolDefinition
from grandpa.kernel.models import (
    AssistantContext,
    AssistantRequest,
    ExecutionAuthorization,
    PlannedAction,
    PolicyDecision,
    PolicyOutcome,
    RiskLevel,
    ToolResult,
    ToolStatus,
    VerificationResult,
    VerificationStatus,
)

LIST_DIRECTORY_TOOL = "files.list_directory"
SEARCH_FILES_TOOL = "files.search"
STAT_PATH_TOOL = "files.stat_path"
CREATE_FOLDER_TOOL = "files.create_folder"
COPY_PATH_TOOL = "files.copy_path"
LIST_DIRECTORY_SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "properties": {"path": {"type": "string", "minLength": 1}},
    "required": ["path"],
    "additionalProperties": False,
}
SEARCH_FILES_SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "minLength": 1},
        "roots": {"type": "array", "items": {"type": "string"}},
        "suffixes": {"type": "array", "items": {"type": "string"}},
        "latest": {"type": "boolean"},
        "recent": {"type": "boolean"},
        "contains": {"type": "boolean"},
    },
    "required": ["query", "roots"],
    "additionalProperties": False,
}
STAT_PATH_SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "minLength": 1},
        "roots": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["path", "roots"],
    "additionalProperties": False,
}
CREATE_FOLDER_SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "minLength": 1},
        "roots": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["path", "roots"],
    "additionalProperties": False,
}
COPY_PATH_SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "properties": {
        "source": {"type": "string", "minLength": 1},
        "destination": {"type": "string"},
        "roots": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["source", "destination", "roots"],
    "additionalProperties": False,
}


class ListDirectoryToolDefinition:
    name = LIST_DIRECTORY_TOOL
    argument_schema = LIST_DIRECTORY_SCHEMA

    def validate_arguments(self, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        if set(arguments) != {"path"}:
            raise ToolArgumentValidationError(
                "files.list_directory accepts exactly one 'path' argument.",
                safe_message="Provide exactly one directory path.",
            )
        raw_path = arguments.get("path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise ToolArgumentValidationError(
                "Directory path must be a non-empty string.",
                safe_message="Provide a valid directory path.",
            )
        try:
            path = Path(raw_path.strip()).expanduser().resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ToolArgumentValidationError(
                f"Directory path does not exist: {raw_path}",
                safe_message="That directory does not exist.",
            ) from exc
        if not path.is_dir():
            raise ToolArgumentValidationError(
                f"Path is not a directory: {path}",
                safe_message="That path is not a directory.",
            )
        return {"path": str(path)}


class SingleToolRegistry:
    def __init__(self, tool: ToolDefinition | None = None) -> None:
        self._tool = tool or ListDirectoryToolDefinition()

    def resolve(self, name: str) -> ToolDefinition:
        if name != self._tool.name:
            raise ToolNotFoundError(
                f"Unknown kernel tool: {name}",
                safe_message="The requested capability is not available.",
            )
        return self._tool


class SearchFilesToolDefinition:
    name = SEARCH_FILES_TOOL
    argument_schema = SEARCH_FILES_SCHEMA

    def validate_arguments(self, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        allowed = {"query", "roots", "suffixes", "latest", "recent", "contains"}
        if set(arguments) - allowed or not {"query", "roots"} <= set(arguments):
            raise ToolArgumentValidationError(
                "files.search received missing or unexpected arguments.",
                safe_message="The file-search arguments are invalid.",
            )
        query = arguments.get("query")
        roots = arguments.get("roots")
        suffixes = arguments.get("suffixes", ())
        if not isinstance(query, str) or not query.strip():
            raise ToolArgumentValidationError(
                "Search query must be a non-empty string.",
                safe_message="Provide a file name to search for.",
            )
        if not isinstance(roots, (list, tuple)) or not roots:
            raise ToolArgumentValidationError(
                "Search roots must be a non-empty sequence.",
                safe_message="No safe file-search roots are configured.",
            )
        if not all(isinstance(root, str) and root.strip() for root in roots):
            raise ToolArgumentValidationError(
                "Every search root must be a non-empty string.",
                safe_message="The configured file-search roots are invalid.",
            )
        if not isinstance(suffixes, (list, tuple)) or not all(
            isinstance(suffix, str) for suffix in suffixes
        ):
            raise ToolArgumentValidationError(
                "Search suffixes must be strings.",
                safe_message="The file-search suffix filter is invalid.",
            )
        for name in ("latest", "recent", "contains"):
            if name in arguments and not isinstance(arguments[name], bool):
                raise ToolArgumentValidationError(
                    f"{name} must be a boolean.",
                    safe_message="The file-search options are invalid.",
                )

        from grandpa.files.safety import FileSafetyPolicy

        safety = FileSafetyPolicy()
        canonical_roots = []
        for raw_root in roots:
            root = Path(raw_root).expanduser().resolve(strict=False)
            if safety.is_protected(root):
                raise ToolArgumentValidationError(
                    f"Protected search root: {root}",
                    safe_message="That location is protected from file search.",
                )
            canonical_roots.append(str(root))
        return {
            "query": query.strip(),
            "roots": canonical_roots,
            "suffixes": [suffix.casefold() for suffix in suffixes],
            "latest": bool(arguments.get("latest", False)),
            "recent": bool(arguments.get("recent", False)),
            "contains": bool(arguments.get("contains", False)),
        }


class StatPathToolDefinition:
    name = STAT_PATH_TOOL
    argument_schema = STAT_PATH_SCHEMA

    def validate_arguments(self, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        if set(arguments) != {"path", "roots"}:
            raise ToolArgumentValidationError(
                "files.stat_path accepts exactly 'path' and 'roots'.",
                safe_message="The file-properties arguments are invalid.",
            )
        raw_path = arguments.get("path")
        roots = arguments.get("roots")
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise ToolArgumentValidationError(
                "Stat path must be a non-empty string.",
                safe_message="Provide a valid path for file properties.",
            )
        if (
            not isinstance(roots, (list, tuple))
            or not roots
            or not all(isinstance(root, str) and root.strip() for root in roots)
        ):
            raise ToolArgumentValidationError(
                "Stat roots must be a non-empty sequence of strings.",
                safe_message="The configured file roots are invalid.",
            )
        try:
            return _resolve_stat_arguments(raw_path.strip(), tuple(roots))
        except ToolArgumentValidationError:
            raise
        except OSError as exc:
            raise ToolArgumentValidationError(
                f"Could not resolve stat path: {exc}",
                safe_message=f"I could not complete that file action: {exc}",
            ) from exc


class CreateFolderToolDefinition:
    name = CREATE_FOLDER_TOOL
    argument_schema = CREATE_FOLDER_SCHEMA

    def validate_arguments(self, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        if set(arguments) != {"path", "roots"}:
            raise ToolArgumentValidationError(
                "files.create_folder accepts exactly 'path' and 'roots'.",
                safe_message="The folder-creation arguments are invalid.",
            )
        raw_path = arguments.get("path")
        roots = arguments.get("roots")
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise ToolArgumentValidationError(
                "Folder path must be a non-empty string.",
                safe_message="Provide a valid folder path.",
            )
        if (
            not isinstance(roots, (list, tuple))
            or not roots
            or not all(isinstance(root, str) and root.strip() for root in roots)
        ):
            raise ToolArgumentValidationError(
                "Folder roots must be a non-empty sequence of strings.",
                safe_message="The configured file roots are invalid.",
            )
        try:
            return _resolve_create_folder_arguments(raw_path.strip(), tuple(roots))
        except ToolArgumentValidationError:
            raise
        except (OSError, RuntimeError, ValueError) as exc:
            raise ToolArgumentValidationError(
                f"Could not resolve folder path: {exc}",
                safe_message=f"I could not complete that file action: {exc}",
            ) from exc


class CopyPathToolDefinition:
    name = COPY_PATH_TOOL
    argument_schema = COPY_PATH_SCHEMA

    def validate_arguments(self, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        if set(arguments) != {"source", "destination", "roots"}:
            raise ToolArgumentValidationError(
                "files.copy_path accepts exactly 'source', 'destination', and 'roots'.",
                safe_message="The file-copy arguments are invalid.",
            )
        source = arguments.get("source")
        destination = arguments.get("destination")
        roots = arguments.get("roots")
        if not isinstance(source, str) or not source.strip():
            raise ToolArgumentValidationError(
                "Copy source must be a non-empty string.",
                safe_message="Provide a file to copy.",
            )
        if not isinstance(destination, str):
            raise ToolArgumentValidationError(
                "Copy destination must be a string.",
                safe_message="Provide a valid copy destination.",
            )
        if (
            not isinstance(roots, (list, tuple))
            or not roots
            or not all(isinstance(root, str) and root.strip() for root in roots)
        ):
            raise ToolArgumentValidationError(
                "Copy roots must be a non-empty sequence of strings.",
                safe_message="The configured file roots are invalid.",
            )
        try:
            return _resolve_copy_path_arguments(
                source.strip(), destination.strip(), tuple(roots)
            )
        except ToolArgumentValidationError:
            raise
        except (OSError, RuntimeError, ValueError) as exc:
            raise ToolArgumentValidationError(
                f"Could not resolve copy paths: {exc}",
                safe_message=f"I could not complete that file action: {exc}",
            ) from exc


class FileReadOnlyToolRegistry:
    def __init__(self) -> None:
        tools = (
            ListDirectoryToolDefinition(),
            SearchFilesToolDefinition(),
            StatPathToolDefinition(),
        )
        self._tools = {tool.name: tool for tool in tools}

    def resolve(self, name: str) -> ToolDefinition:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ToolNotFoundError(
                f"Unknown read-only file tool: {name}",
                safe_message="The requested file capability is not available.",
            ) from exc


class FileCompatibilityToolRegistry:
    def __init__(self) -> None:
        self._read_only = FileReadOnlyToolRegistry()
        self._create_folder = CreateFolderToolDefinition()
        self._copy_path = CopyPathToolDefinition()

    def resolve(self, name: str) -> ToolDefinition:
        if name == CREATE_FOLDER_TOOL:
            return self._create_folder
        if name == COPY_PATH_TOOL:
            return self._copy_path
        return self._read_only.resolve(name)


class ListDirectoryPolicy:
    def evaluate(
        self,
        request: AssistantRequest,
        context: AssistantContext,
        action: PlannedAction,
        action_digest: str,
    ) -> PolicyDecision:
        del request, context
        if action.tool_name != LIST_DIRECTORY_TOOL:
            return PolicyDecision(
                outcome=PolicyOutcome.BLOCK,
                risk=RiskLevel.CRITICAL,
                reason="This Phase 1 policy does not allow that tool.",
                action_digest=action_digest,
            )
        return PolicyDecision(
            outcome=PolicyOutcome.ALLOW,
            risk=RiskLevel.LOW,
            reason="Reading immediate directory metadata is a low-risk action.",
            action_digest=action_digest,
            constraints={"read_only": True, "recursive": False},
        )


class FileReadOnlyPolicy:
    _ALLOWED_TOOLS = {LIST_DIRECTORY_TOOL, SEARCH_FILES_TOOL, STAT_PATH_TOOL}

    def evaluate(
        self,
        request: AssistantRequest,
        context: AssistantContext,
        action: PlannedAction,
        action_digest: str,
    ) -> PolicyDecision:
        del request, context
        if action.tool_name not in self._ALLOWED_TOOLS:
            return PolicyDecision(
                outcome=PolicyOutcome.BLOCK,
                risk=RiskLevel.CRITICAL,
                reason="The read-only file policy does not allow that tool.",
                action_digest=action_digest,
            )
        return PolicyDecision(
            outcome=PolicyOutcome.ALLOW,
            risk=RiskLevel.LOW,
            reason="The file operation is read-only and limited to validated roots.",
            action_digest=action_digest,
            constraints={"read_only": True, "shell": False},
        )


class FileCompatibilityPolicy:
    def __init__(self) -> None:
        self._read_only = FileReadOnlyPolicy()

    def evaluate(
        self,
        request: AssistantRequest,
        context: AssistantContext,
        action: PlannedAction,
        action_digest: str,
    ) -> PolicyDecision:
        if action.tool_name == COPY_PATH_TOOL:
            if action.arguments.get("destination_exists"):
                return PolicyDecision(
                    outcome=PolicyOutcome.BLOCK,
                    risk=RiskLevel.MEDIUM,
                    reason="Destination already exists. Confirm overwrite.",
                    action_digest=action_digest,
                    constraints={"overwrite": False, "shell": False},
                )
            return PolicyDecision(
                outcome=PolicyOutcome.ALLOW,
                risk=RiskLevel.MEDIUM,
                reason=(
                    "Copying one regular file to a new path inside validated roots "
                    "is a bounded, non-destructive mutation."
                ),
                action_digest=action_digest,
                constraints={
                    "mutation": "copy_regular_file",
                    "overwrite": False,
                    "source_preserved": True,
                    "shell": False,
                    "source_path": action.arguments["source_path"],
                    "destination_path": action.arguments["destination_path"],
                },
            )
        if action.tool_name != CREATE_FOLDER_TOOL:
            return self._read_only.evaluate(
                request, context, action, action_digest
            )
        return PolicyDecision(
            outcome=PolicyOutcome.ALLOW,
            risk=RiskLevel.MEDIUM,
            reason=(
                "Creating a new directory inside a validated root is a bounded, "
                "non-destructive mutation."
            ),
            action_digest=action_digest,
            constraints={
                "mutation": "create_directory",
                "overwrite": False,
                "shell": False,
            },
        )


class ListDirectoryExecutor:
    def execute(
        self,
        tool: ToolDefinition,
        action: PlannedAction,
        canonical_arguments: Mapping[str, Any],
        context: AssistantContext,
        authorization: ExecutionAuthorization,
    ) -> ToolResult:
        del context
        if action.tool_name != LIST_DIRECTORY_TOOL or tool.name != LIST_DIRECTORY_TOOL:
            raise SecurityInvariantError("Wrong executor selected for action.")
        if authorization.decision.action_digest == "":
            raise SecurityInvariantError(
                "Execution authorization has no action digest."
            )

        validated = tool.validate_arguments(canonical_arguments)
        directory = Path(str(validated["path"]))
        entries = []
        for entry in sorted(directory.iterdir(), key=lambda item: item.name.casefold()):
            entry_path = directory / entry.name
            kind = (
                "directory"
                if entry.is_dir()
                else "file"
                if entry.is_file()
                else "other"
            )
            entries.append(
                {
                    "name": entry.name,
                    "path": str(entry_path),
                    "kind": kind,
                }
            )
        return ToolResult(
            status=ToolStatus.SUCCEEDED,
            data={
                "directory": str(directory),
                "entries": entries,
                "count": len(entries),
            },
            safe_message=f"Found {len(entries)} entries in {directory}.",
            evidence=({"canonical_directory": str(directory)},),
        )


class SearchFilesExecutor:
    def execute(
        self,
        tool: ToolDefinition,
        action: PlannedAction,
        canonical_arguments: Mapping[str, Any],
        context: AssistantContext,
        authorization: ExecutionAuthorization,
    ) -> ToolResult:
        del context
        if action.tool_name != SEARCH_FILES_TOOL or tool.name != SEARCH_FILES_TOOL:
            raise SecurityInvariantError("Wrong executor selected for file search.")
        if authorization.decision.action_digest == "":
            raise SecurityInvariantError(
                "Execution authorization has no action digest."
            )
        validated = tool.validate_arguments(canonical_arguments)
        try:
            matches = _search_matches(validated)
        except OSError as exc:
            return ToolResult(
                status=ToolStatus.FAILED,
                data={"error": exc.__class__.__name__},
                safe_message=f"I could not complete that file action: {exc}",
            )

        paths = [str(path) for path in matches]
        if validated["latest"]:
            message = (
                f"Latest match: `{matches[0]}`"
                if matches
                else "No matching files found."
            )
        elif not matches:
            message = "No matching files found."
        else:
            lines = [f"Found {len(matches)} matching file(s):"]
            lines.extend(
                f"{index}. {path}" for index, path in enumerate(matches[:10], start=1)
            )
            message = "\n".join(lines)
        return ToolResult(
            status=ToolStatus.SUCCEEDED,
            data={
                "matches": paths,
                "primary_path": paths[0] if validated["latest"] and paths else None,
                "count": len(paths),
            },
            safe_message=message,
            evidence=({"roots": list(validated["roots"]), "match_count": len(paths)},),
        )


class StatPathExecutor:
    def execute(
        self,
        tool: ToolDefinition,
        action: PlannedAction,
        canonical_arguments: Mapping[str, Any],
        context: AssistantContext,
        authorization: ExecutionAuthorization,
    ) -> ToolResult:
        del context
        if action.tool_name != STAT_PATH_TOOL or tool.name != STAT_PATH_TOOL:
            raise SecurityInvariantError("Wrong executor selected for path metadata.")
        if authorization.decision.action_digest == "":
            raise SecurityInvariantError(
                "Execution authorization has no action digest."
            )
        _validate_canonical_stat_arguments(canonical_arguments)
        resolution = canonical_arguments["resolution"]
        matches = list(canonical_arguments["matches"])
        requested = str(canonical_arguments["requested_path"])
        if resolution == "missing":
            return ToolResult(
                status=ToolStatus.SUCCEEDED,
                data={"outcome": "missing", "matches": []},
                safe_message=f"I could not find {requested}.",
            )
        if resolution == "no_matches":
            return ToolResult(
                status=ToolStatus.SUCCEEDED,
                data={"outcome": "no_matches", "matches": []},
                safe_message="No matching files found.",
            )
        if resolution == "ambiguous":
            lines = ["I found multiple matching files. Choose one:"]
            lines.extend(
                f"{index}. {match}" for index, match in enumerate(matches[:10], start=1)
            )
            return ToolResult(
                status=ToolStatus.SUCCEEDED,
                data={"outcome": "ambiguous", "matches": matches},
                safe_message="\n".join(lines),
            )

        try:
            metadata = _inspect_path_metadata(
                Path(str(canonical_arguments["path"]))
            )
        except OSError as exc:
            return ToolResult(
                status=ToolStatus.FAILED,
                data={"error": exc.__class__.__name__},
                safe_message=f"I could not complete that file action: {exc}",
            )
        return ToolResult(
            status=ToolStatus.SUCCEEDED,
            data={
                "outcome": "resolved",
                "path": str(metadata.path),
                "name": metadata.name,
                "type": metadata.kind,
                "size": metadata.size,
                "extension": metadata.extension,
                "created": metadata.created,
                "modified": metadata.modified,
                "created_timestamp": metadata.created_timestamp,
                "modified_timestamp": metadata.modified_timestamp,
                "device": metadata.device,
                "inode": metadata.inode,
            },
            safe_message=_format_properties_message(metadata),
            evidence=({"canonical_path": str(metadata.path)},),
        )


class CreateFolderExecutor:
    def execute(
        self,
        tool: ToolDefinition,
        action: PlannedAction,
        canonical_arguments: Mapping[str, Any],
        context: AssistantContext,
        authorization: ExecutionAuthorization,
    ) -> ToolResult:
        del context
        if (
            action.tool_name != CREATE_FOLDER_TOOL
            or tool.name != CREATE_FOLDER_TOOL
        ):
            raise SecurityInvariantError("Wrong executor selected for folder creation.")
        if authorization.decision.action_digest == "":
            raise SecurityInvariantError(
                "Execution authorization has no action digest."
            )
        if authorization.decision.outcome is not PolicyOutcome.ALLOW:
            raise SecurityInvariantError(
                "Folder creation requires an allowed execution authorization."
            )
        _validate_canonical_create_folder_arguments(canonical_arguments)
        target = Path(str(canonical_arguments["target_path"]))
        existing_type = canonical_arguments["existing_type"]
        if existing_type == "directory":
            return ToolResult(
                status=ToolStatus.SUCCEEDED,
                data={
                    "outcome": "existing_directory",
                    "path": str(target),
                    "newly_created": False,
                    "previously_existed": True,
                },
                safe_message="Destination already exists. Confirm overwrite.",
                evidence=({"canonical_target": str(target)},),
            )
        if existing_type != "missing":
            return ToolResult(
                status=ToolStatus.SUCCEEDED,
                data={
                    "outcome": "existing_file",
                    "path": str(target),
                    "newly_created": False,
                    "previously_existed": True,
                },
                safe_message="Destination already exists. Confirm overwrite.",
                evidence=({"canonical_target": str(target)},),
            )

        try:
            _mkdir(target)
        except OSError as exc:
            return ToolResult(
                status=ToolStatus.FAILED,
                data={"error": exc.__class__.__name__},
                safe_message=f"I could not complete that file action: {exc}",
            )
        return ToolResult(
            status=ToolStatus.SUCCEEDED,
            data={
                "outcome": "created",
                "path": str(target),
                "newly_created": True,
                "previously_existed": False,
                "created_chain": list(canonical_arguments["missing_chain"]),
            },
            safe_message=f"Folder created: `{target}`",
            evidence=(
                {
                    "canonical_target": str(target),
                    "newly_created": True,
                    "previously_existed": False,
                },
            ),
        )


class CopyPathExecutor:
    def execute(
        self,
        tool: ToolDefinition,
        action: PlannedAction,
        canonical_arguments: Mapping[str, Any],
        context: AssistantContext,
        authorization: ExecutionAuthorization,
    ) -> ToolResult:
        del context
        if action.tool_name != COPY_PATH_TOOL or tool.name != COPY_PATH_TOOL:
            raise SecurityInvariantError("Wrong executor selected for file copy.")
        if authorization.decision.action_digest == "":
            raise SecurityInvariantError(
                "Execution authorization has no action digest."
            )
        if authorization.decision.outcome is not PolicyOutcome.ALLOW:
            raise SecurityInvariantError(
                "File copy requires an allowed execution authorization."
            )
        _validate_canonical_copy_arguments(canonical_arguments)
        constraints = authorization.decision.constraints
        if (
            constraints.get("mutation") != "copy_regular_file"
            or constraints.get("overwrite") is not False
            or constraints.get("shell") is not False
            or constraints.get("source_path") != canonical_arguments["source_path"]
            or constraints.get("destination_path")
            != canonical_arguments["destination_path"]
        ):
            raise SecurityInvariantError(
                "File-copy authorization does not match the canonical paths."
            )

        source = Path(str(canonical_arguments["source_path"]))
        destination = Path(str(canonical_arguments["destination_path"]))
        _validate_copy_boundary(source, destination, canonical_arguments)
        try:
            shutil.copy2(source, destination)
        except OSError as exc:
            return ToolResult(
                status=ToolStatus.FAILED,
                data={"error": exc.__class__.__name__},
                safe_message=f"I could not complete that file action: {exc}",
            )
        return ToolResult(
            status=ToolStatus.SUCCEEDED,
            data={
                "outcome": "copied",
                "source": str(source),
                "destination": str(destination),
            },
            safe_message=f"File copied to `{destination}`.",
            evidence=(
                {
                    "canonical_source": str(source),
                    "canonical_destination": str(destination),
                },
            ),
        )


class FileReadOnlyExecutor:
    def __init__(self) -> None:
        self._list = ListDirectoryExecutor()
        self._search = SearchFilesExecutor()
        self._stat = StatPathExecutor()

    def execute(
        self,
        tool: ToolDefinition,
        action: PlannedAction,
        canonical_arguments: Mapping[str, Any],
        context: AssistantContext,
        authorization: ExecutionAuthorization,
    ) -> ToolResult:
        if action.tool_name == LIST_DIRECTORY_TOOL:
            return self._list.execute(
                tool, action, canonical_arguments, context, authorization
            )
        if action.tool_name == SEARCH_FILES_TOOL:
            return self._search.execute(
                tool, action, canonical_arguments, context, authorization
            )
        if action.tool_name == STAT_PATH_TOOL:
            return self._stat.execute(
                tool, action, canonical_arguments, context, authorization
            )
        raise SecurityInvariantError("No read-only file executor is registered.")


class FileCompatibilityExecutor:
    def __init__(self) -> None:
        self._read_only = FileReadOnlyExecutor()
        self._create_folder = CreateFolderExecutor()
        self._copy_path = CopyPathExecutor()

    def execute(
        self,
        tool: ToolDefinition,
        action: PlannedAction,
        canonical_arguments: Mapping[str, Any],
        context: AssistantContext,
        authorization: ExecutionAuthorization,
    ) -> ToolResult:
        if action.tool_name == CREATE_FOLDER_TOOL:
            return self._create_folder.execute(
                tool, action, canonical_arguments, context, authorization
            )
        if action.tool_name == COPY_PATH_TOOL:
            return self._copy_path.execute(
                tool, action, canonical_arguments, context, authorization
            )
        return self._read_only.execute(
            tool, action, canonical_arguments, context, authorization
        )


class ListDirectoryVerifier:
    def verify(
        self,
        action: PlannedAction,
        canonical_arguments: Mapping[str, Any],
        result: ToolResult,
        context: AssistantContext,
    ) -> VerificationResult:
        del context
        if action.tool_name != LIST_DIRECTORY_TOOL:
            return VerificationResult(
                VerificationStatus.FAILED,
                "Unsupported verification target.",
            )
        try:
            directory = Path(str(canonical_arguments["path"])).resolve(strict=True)
        except (KeyError, OSError, RuntimeError):
            return VerificationResult(
                VerificationStatus.FAILED,
                "The target directory no longer exists.",
            )
        if not directory.is_dir():
            return VerificationResult(
                VerificationStatus.FAILED,
                "The target is no longer a directory.",
            )
        if result.status is not ToolStatus.SUCCEEDED:
            return VerificationResult(
                VerificationStatus.FAILED,
                "The directory listing did not succeed.",
            )
        if result.data.get("directory") != str(directory):
            return VerificationResult(
                VerificationStatus.FAILED,
                "The result belongs to a different directory.",
            )

        raw_entries = result.data.get("entries")
        if not isinstance(raw_entries, list):
            return VerificationResult(
                VerificationStatus.FAILED,
                "The directory listing has an invalid structure.",
            )
        current_names = {entry.name for entry in directory.iterdir()}
        returned_names: set[str] = set()
        for item in raw_entries:
            if not isinstance(item, Mapping):
                return VerificationResult(
                    VerificationStatus.FAILED,
                    "The directory listing contains an invalid entry.",
                )
            name = item.get("name")
            path_text = item.get("path")
            if not isinstance(name, str) or not isinstance(path_text, str):
                return VerificationResult(
                    VerificationStatus.FAILED,
                    "The directory listing contains incomplete metadata.",
                )
            entry_path = Path(path_text)
            if entry_path.parent != directory or entry_path.name != name:
                return VerificationResult(
                    VerificationStatus.FAILED,
                    "A result path is outside the requested directory.",
                )
            returned_names.add(name)
        if returned_names != current_names or result.data.get("count") != len(
            raw_entries
        ):
            return VerificationResult(
                VerificationStatus.FAILED,
                "The directory changed while the result was being verified.",
            )
        return VerificationResult(
            VerificationStatus.VERIFIED,
            "The directory and every returned entry were verified.",
            evidence=({"canonical_directory": str(directory)},),
        )


class SearchFilesVerifier:
    def verify(
        self,
        action: PlannedAction,
        canonical_arguments: Mapping[str, Any],
        result: ToolResult,
        context: AssistantContext,
    ) -> VerificationResult:
        del context
        if action.tool_name != SEARCH_FILES_TOOL:
            return VerificationResult(
                VerificationStatus.FAILED,
                "Unsupported file-search verification target.",
            )
        if result.status is not ToolStatus.SUCCEEDED:
            return VerificationResult(
                VerificationStatus.FAILED,
                "The file search did not succeed.",
            )
        try:
            expected = [str(path) for path in _search_matches(canonical_arguments)]
        except OSError:
            return VerificationResult(
                VerificationStatus.FAILED,
                "The file search could not be repeated for verification.",
            )
        returned = result.data.get("matches")
        if not isinstance(returned, list) or not all(
            isinstance(path, str) for path in returned
        ):
            return VerificationResult(
                VerificationStatus.FAILED,
                "The file-search result has an invalid structure.",
            )
        if returned != expected or result.data.get("count") != len(expected):
            return VerificationResult(
                VerificationStatus.FAILED,
                "The file-search result did not match independent verification.",
            )
        roots = [Path(root) for root in canonical_arguments["roots"]]
        if any(not _is_within_roots(Path(match), roots) for match in returned):
            return VerificationResult(
                VerificationStatus.FAILED,
                "A file-search result is outside the validated roots.",
            )
        return VerificationResult(
            VerificationStatus.VERIFIED,
            "The file-search results and validated roots were verified.",
            evidence=({"match_count": len(expected)},),
        )


class StatPathVerifier:
    def verify(
        self,
        action: PlannedAction,
        canonical_arguments: Mapping[str, Any],
        result: ToolResult,
        context: AssistantContext,
    ) -> VerificationResult:
        del context
        if action.tool_name != STAT_PATH_TOOL:
            return VerificationResult(
                VerificationStatus.FAILED,
                "Unsupported path-metadata verification target.",
            )
        if result.status is not ToolStatus.SUCCEEDED:
            return VerificationResult(
                VerificationStatus.FAILED,
                "The path metadata operation did not succeed.",
            )
        try:
            current = _resolve_stat_arguments(
                str(canonical_arguments["requested_path"]),
                tuple(canonical_arguments["roots"]),
            )
        except (OSError, ToolArgumentValidationError):
            return VerificationResult(
                VerificationStatus.FAILED,
                "The path could not be resolved during verification.",
            )
        if current["resolution"] != canonical_arguments["resolution"]:
            return VerificationResult(
                VerificationStatus.FAILED,
                "The path resolution changed before verification.",
            )
        if current["resolution"] != "resolved":
            if list(current["matches"]) != list(result.data.get("matches", ())):
                return VerificationResult(
                    VerificationStatus.FAILED,
                    "The path matches changed before verification.",
                )
            if result.data.get("outcome") != current["resolution"]:
                return VerificationResult(
                    VerificationStatus.FAILED,
                    "The path resolution result is inconsistent.",
                )
            return VerificationResult(
                VerificationStatus.VERIFIED,
                "The unresolved path result was independently verified.",
            )

        path = Path(str(current["path"]))
        try:
            stat = path.stat()
            is_directory = path.is_dir()
        except OSError:
            return VerificationResult(
                VerificationStatus.FAILED,
                "The path disappeared before verification.",
            )
        expected_extension = "" if is_directory else path.suffix.lower().lstrip(".")
        expected_type = "folder" if is_directory else (expected_extension or "file")
        if result.data.get("outcome") != "resolved":
            return VerificationResult(
                VerificationStatus.FAILED,
                "The result does not describe a resolved path.",
            )
        if result.data.get("path") != str(path) or result.data.get("name") != path.name:
            return VerificationResult(
                VerificationStatus.FAILED,
                "The returned metadata belongs to a different path.",
            )
        if (
            result.data.get("type") != expected_type
            or result.data.get("extension") != expected_extension
        ):
            return VerificationResult(
                VerificationStatus.FAILED,
                "The returned path type could not be verified.",
            )
        if not is_directory and result.data.get("size") != stat.st_size:
            return VerificationResult(
                VerificationStatus.FAILED,
                "The file size changed before verification.",
            )
        result_device = result.data.get("device")
        result_inode = result.data.get("inode")
        if stat.st_dev and result_device and stat.st_dev != result_device:
            return VerificationResult(
                VerificationStatus.FAILED,
                "The filesystem device identity changed before verification.",
            )
        if stat.st_ino and result_inode and stat.st_ino != result_inode:
            return VerificationResult(
                VerificationStatus.FAILED,
                "The filesystem object changed before verification.",
            )
        return VerificationResult(
            VerificationStatus.VERIFIED,
            "The canonical path, type, size, and filesystem identity were verified.",
            evidence=({"canonical_path": str(path)},),
        )


class CreateFolderVerifier:
    def verify(
        self,
        action: PlannedAction,
        canonical_arguments: Mapping[str, Any],
        result: ToolResult,
        context: AssistantContext,
    ) -> VerificationResult:
        del context
        if action.tool_name != CREATE_FOLDER_TOOL:
            return VerificationResult(
                VerificationStatus.FAILED,
                "Unsupported folder-creation verification target.",
            )
        if result.status is not ToolStatus.SUCCEEDED:
            return VerificationResult(
                VerificationStatus.FAILED,
                "The folder creation did not succeed.",
            )
        try:
            _validate_canonical_create_folder_arguments(canonical_arguments)
            target = Path(str(canonical_arguments["target_path"])).resolve(
                strict=True
            )
            expected_target = _resolve_created_target_for_verification(
                str(canonical_arguments["requested_path"]),
                tuple(canonical_arguments["roots"]),
            )
        except (KeyError, OSError, RuntimeError, ToolArgumentValidationError):
            return VerificationResult(
                VerificationStatus.FAILED,
                "The target path could not be verified.",
            )
        if target != expected_target:
            return VerificationResult(
                VerificationStatus.FAILED,
                "The created folder does not match the requested canonical path.",
            )
        roots = [Path(root) for root in canonical_arguments["roots"]]
        if not _is_within_roots(target, roots):
            return VerificationResult(
                VerificationStatus.FAILED,
                "The created folder is outside the validated roots.",
            )
        if result.data.get("path") != str(target):
            return VerificationResult(
                VerificationStatus.FAILED,
                "The result belongs to a different path.",
            )

        existing_type = canonical_arguments["existing_type"]
        outcome = result.data.get("outcome")
        if existing_type in {"file", "other"}:
            if not target.is_dir() and outcome == "existing_file":
                return VerificationResult(
                    VerificationStatus.VERIFIED,
                    "The existing non-directory conflict was independently verified.",
                )
            return VerificationResult(
                VerificationStatus.FAILED,
                "The existing file conflict could not be verified.",
            )
        if not target.is_dir():
            return VerificationResult(
                VerificationStatus.FAILED,
                "The requested folder does not exist as a directory.",
            )
        if existing_type == "directory":
            if outcome != "existing_directory":
                return VerificationResult(
                    VerificationStatus.FAILED,
                    "The existing-directory result is inconsistent.",
                )
            return VerificationResult(
                VerificationStatus.VERIFIED,
                "The existing directory was independently verified.",
                evidence=({"canonical_target": str(target)},),
            )
        if outcome != "created":
            return VerificationResult(
                VerificationStatus.FAILED,
                "The result does not describe a created directory.",
            )
        if not _verify_created_directory_chain(canonical_arguments):
            return VerificationResult(
                VerificationStatus.FAILED,
                "Unexpected filesystem changes appeared during folder creation.",
            )
        return VerificationResult(
            VerificationStatus.VERIFIED,
            "The canonical target and created directory chain were verified.",
            evidence=({"canonical_target": str(target)},),
        )


class CopyPathVerifier:
    def verify(
        self,
        action: PlannedAction,
        canonical_arguments: Mapping[str, Any],
        result: ToolResult,
        context: AssistantContext,
    ) -> VerificationResult:
        del context
        if action.tool_name != COPY_PATH_TOOL:
            return VerificationResult(
                VerificationStatus.FAILED,
                "Unsupported file-copy verification target.",
            )
        if result.status is not ToolStatus.SUCCEEDED:
            return VerificationResult(
                VerificationStatus.FAILED,
                "The file copy did not succeed.",
            )
        try:
            _validate_canonical_copy_arguments(canonical_arguments)
            source = Path(str(canonical_arguments["source_path"])).resolve(strict=True)
            destination = Path(
                str(canonical_arguments["destination_path"])
            ).resolve(strict=True)
            _verify_copy_paths(source, destination, canonical_arguments)
            source_digest = _sha256_file(source)
            destination_digest = _sha256_file(destination)
        except (KeyError, OSError, RuntimeError, ToolArgumentValidationError):
            return VerificationResult(
                VerificationStatus.FAILED,
                "The copied file could not be independently verified.",
            )
        if (
            result.data.get("outcome") != "copied"
            or result.data.get("source") != str(source)
            or result.data.get("destination") != str(destination)
        ):
            return VerificationResult(
                VerificationStatus.FAILED,
                "The copy result belongs to different paths.",
            )
        if source_digest != destination_digest:
            return VerificationResult(
                VerificationStatus.FAILED,
                "The copied file content does not match the source.",
            )
        if not _verify_copy_parent_snapshot(canonical_arguments):
            return VerificationResult(
                VerificationStatus.FAILED,
                "Unexpected filesystem changes appeared during file copy.",
            )
        return VerificationResult(
            VerificationStatus.VERIFIED,
            "The source identity, destination path, and copied content were verified.",
            evidence=(
                {
                    "canonical_source": str(source),
                    "canonical_destination": str(destination),
                    "sha256": source_digest,
                },
            ),
        )


class FileReadOnlyVerifier:
    def __init__(self) -> None:
        self._list = ListDirectoryVerifier()
        self._search = SearchFilesVerifier()
        self._stat = StatPathVerifier()

    def verify(
        self,
        action: PlannedAction,
        canonical_arguments: Mapping[str, Any],
        result: ToolResult,
        context: AssistantContext,
    ) -> VerificationResult:
        if action.tool_name == LIST_DIRECTORY_TOOL:
            return self._list.verify(action, canonical_arguments, result, context)
        if action.tool_name == SEARCH_FILES_TOOL:
            return self._search.verify(action, canonical_arguments, result, context)
        if action.tool_name == STAT_PATH_TOOL:
            return self._stat.verify(action, canonical_arguments, result, context)
        return VerificationResult(
            VerificationStatus.FAILED,
            "No verifier is registered for that file action.",
        )


class FileCompatibilityVerifier:
    def __init__(self) -> None:
        self._read_only = FileReadOnlyVerifier()
        self._create_folder = CreateFolderVerifier()
        self._copy_path = CopyPathVerifier()

    def verify(
        self,
        action: PlannedAction,
        canonical_arguments: Mapping[str, Any],
        result: ToolResult,
        context: AssistantContext,
    ) -> VerificationResult:
        if action.tool_name == CREATE_FOLDER_TOOL:
            return self._create_folder.verify(
                action, canonical_arguments, result, context
            )
        if action.tool_name == COPY_PATH_TOOL:
            return self._copy_path.verify(
                action, canonical_arguments, result, context
            )
        return self._read_only.verify(
            action, canonical_arguments, result, context
        )


def _search_matches(arguments: Mapping[str, Any]) -> tuple[Path, ...]:
    roots = tuple(Path(root) for root in arguments["roots"])
    suffixes = {str(suffix).casefold() for suffix in arguments["suffixes"]}
    if arguments["latest"]:
        latest = _latest_by_suffix(suffixes, roots=roots)
        return (latest,) if latest is not None else ()
    matches = tuple(_find_matches(str(arguments["query"]), roots=roots))
    if suffixes:
        matches = tuple(path for path in matches if path.suffix.casefold() in suffixes)
    return matches


def _find_matches(query: str, *, roots: tuple[Path, ...]) -> list[Path]:
    from grandpa.files.paths import find_matches

    return find_matches(query, roots=roots)


def _latest_by_suffix(suffixes: set[str], *, roots: tuple[Path, ...]) -> Path | None:
    from grandpa.files.paths import latest_by_suffix

    return latest_by_suffix(suffixes, roots=roots)


def _is_within_roots(path: Path, roots: list[Path]) -> bool:
    canonical = path.resolve(strict=False)
    for root in roots:
        canonical_root = root.resolve(strict=False)
        if canonical == canonical_root:
            return True
        try:
            canonical.relative_to(canonical_root)
            return True
        except ValueError:
            continue
    return False


def _resolve_stat_arguments(
    requested_path: str,
    roots: tuple[str, ...],
) -> Mapping[str, Any]:
    from grandpa.files.paths import resolve_path
    from grandpa.files.safety import FileSafetyPolicy

    safety = FileSafetyPolicy()
    if safety.blocks_traversal(requested_path):
        raise ToolArgumentValidationError(
            "Path traversal is blocked for files.stat_path.",
            safe_message="Path traversal is blocked.",
        )
    canonical_roots = tuple(
        Path(root).expanduser().resolve(strict=False) for root in roots
    )
    if any(safety.is_protected(root) for root in canonical_roots):
        raise ToolArgumentValidationError(
            "Protected root passed to files.stat_path.",
            safe_message="That location is protected from file metadata access.",
        )

    if requested_path.casefold().startswith("latest pdf"):
        latest = _latest_by_suffix({".pdf"}, roots=canonical_roots)
        if latest is None:
            return _canonical_stat_result(requested_path, canonical_roots, "no_matches")
        return _resolved_stat_result(requested_path, canonical_roots, latest, safety)

    candidate = resolve_path(requested_path, roots=canonical_roots)
    if candidate.exists():
        return _resolved_stat_result(requested_path, canonical_roots, candidate, safety)
    matches = tuple(_find_matches(requested_path, roots=canonical_roots))
    if len(matches) == 1:
        return _resolved_stat_result(
            requested_path, canonical_roots, matches[0], safety
        )
    if len(matches) > 1:
        return _canonical_stat_result(
            requested_path,
            canonical_roots,
            "ambiguous",
            matches=matches,
        )
    return _canonical_stat_result(requested_path, canonical_roots, "missing")


def _resolved_stat_result(
    requested_path: str,
    roots: tuple[Path, ...],
    path: Path,
    safety: Any,
) -> Mapping[str, Any]:
    canonical = path.expanduser().resolve(strict=True)
    if safety.is_protected(canonical) or not _is_within_roots(canonical, list(roots)):
        raise ToolArgumentValidationError(
            f"Path is outside validated roots: {canonical}",
            safe_message="That path is outside the allowed file roots.",
        )
    return _canonical_stat_result(
        requested_path,
        roots,
        "resolved",
        path=canonical,
        matches=(canonical,),
    )


def _canonical_stat_result(
    requested_path: str,
    roots: tuple[Path, ...],
    resolution: str,
    *,
    path: Path | None = None,
    matches: tuple[Path, ...] = (),
) -> Mapping[str, Any]:
    return {
        "requested_path": requested_path,
        "roots": [str(root) for root in roots],
        "resolution": resolution,
        "path": str(path) if path is not None else None,
        "matches": [str(match) for match in matches],
    }


def _validate_canonical_stat_arguments(arguments: Mapping[str, Any]) -> None:
    required = {"requested_path", "roots", "resolution", "path", "matches"}
    if set(arguments) != required:
        raise ToolArgumentValidationError("Canonical stat arguments are incomplete.")
    if arguments["resolution"] not in {
        "resolved",
        "missing",
        "no_matches",
        "ambiguous",
    }:
        raise ToolArgumentValidationError("Canonical stat resolution is invalid.")
    if not isinstance(arguments["roots"], list) or not isinstance(
        arguments["matches"], list
    ):
        raise ToolArgumentValidationError("Canonical stat paths are invalid.")


def _resolve_copy_path_arguments(
    requested_source: str,
    requested_destination: str,
    roots: tuple[str, ...],
) -> Mapping[str, Any]:
    from grandpa.files.paths import (
        find_matches,
        latest_by_suffix,
        resolve_alias,
        resolve_destination,
        resolve_path,
    )
    from grandpa.files.safety import FileSafetyPolicy

    safety = FileSafetyPolicy()
    if safety.blocks_traversal(requested_source) or (
        requested_destination and safety.blocks_traversal(requested_destination)
    ):
        raise ToolArgumentValidationError(
            "Path traversal is blocked for files.copy_path.",
            safe_message="Path traversal is blocked.",
        )
    canonical_roots = tuple(
        Path(root).expanduser().resolve(strict=False) for root in roots
    )
    if any(safety.is_protected(root) for root in canonical_roots):
        raise ToolArgumentValidationError(
            "Protected root passed to files.copy_path.",
            safe_message="That location is protected and cannot be modified.",
        )

    if requested_source.casefold().startswith("latest pdf"):
        source = latest_by_suffix({".pdf"}, roots=canonical_roots)
        if source is None:
            raise ToolArgumentValidationError(
                "No latest PDF source exists.",
                safe_message="No matching files found.",
            )
    else:
        direct_source = resolve_path(
            requested_source, roots=canonical_roots
        ).resolve(strict=False)
        if direct_source.exists():
            source = direct_source
        else:
            matches = find_matches(requested_source, roots=canonical_roots)
            if len(matches) > 1:
                lines = ["I found multiple matching files. Choose one:"]
                lines.extend(
                    f"{index}. {match}"
                    for index, match in enumerate(matches[:10], start=1)
                )
                raise ToolArgumentValidationError(
                    f"Ambiguous copy source: {requested_source}",
                    safe_message="\n".join(lines),
                )
            if not matches:
                raise ToolArgumentValidationError(
                    f"Missing copy source: {requested_source}",
                    safe_message=f"I could not find {requested_source}.",
                )
            source = matches[0]

    source = source.resolve(strict=True)
    if safety.is_protected(source) or not _is_within_roots(
        source, list(canonical_roots)
    ):
        raise ToolArgumentValidationError(
            f"Unsafe copy source: {source}",
            safe_message="That path is protected and cannot be modified.",
        )
    if not source.is_file():
        raise ToolArgumentValidationError(
            f"Directory copy is outside Phase 5 scope: {source}",
            safe_message=(
                "Copying folders is not supported by the canonical file copy yet."
            ),
        )

    if requested_destination:
        destination = resolve_destination(
            requested_destination, roots=canonical_roots
        ).resolve(strict=False)
        if destination.exists() and destination.is_dir():
            destination = (destination / source.name).resolve(strict=False)
        elif resolve_alias(requested_destination) is not None:
            destination = (destination / source.name).resolve(strict=False)
    else:
        destination = source.with_name(
            f"{source.stem} copy{source.suffix}"
        ).resolve(strict=False)

    if safety.is_protected(destination) or not _is_within_roots(
        destination, list(canonical_roots)
    ):
        raise ToolArgumentValidationError(
            f"Unsafe copy destination: {destination}",
            safe_message="That path is protected and cannot be modified.",
        )
    if destination == source:
        raise ToolArgumentValidationError(
            "Copy source and destination are identical.",
            safe_message="The copy destination must be different from the source.",
        )
    parent = destination.parent.resolve(strict=False)
    if not parent.exists() or not parent.is_dir():
        raise ToolArgumentValidationError(
            f"Copy destination parent does not exist: {parent}",
            safe_message=(
                "The destination folder does not exist. Create it before copying."
            ),
        )
    if safety.is_protected(parent) or not _is_within_roots(
        parent, list(canonical_roots)
    ):
        raise ToolArgumentValidationError(
            f"Unsafe copy destination parent: {parent}",
            safe_message="That path is protected and cannot be modified.",
        )

    source_stat = source.stat()
    return {
        "requested_source": requested_source,
        "requested_destination": requested_destination,
        "roots": [str(root) for root in canonical_roots],
        "source_path": str(source),
        "destination_path": str(destination),
        "destination_exists": destination.exists(),
        "source_size": source_stat.st_size,
        "source_mtime_ns": source_stat.st_mtime_ns,
        "source_device": source_stat.st_dev,
        "source_inode": source_stat.st_ino,
        "destination_parent": str(parent),
        "destination_parent_children": sorted(child.name for child in parent.iterdir()),
    }


def _validate_canonical_copy_arguments(arguments: Mapping[str, Any]) -> None:
    required = {
        "requested_source",
        "requested_destination",
        "roots",
        "source_path",
        "destination_path",
        "destination_exists",
        "source_size",
        "source_mtime_ns",
        "source_device",
        "source_inode",
        "destination_parent",
        "destination_parent_children",
    }
    if set(arguments) != required:
        raise ToolArgumentValidationError("Canonical file-copy arguments are incomplete.")
    if not isinstance(arguments["roots"], list) or not all(
        isinstance(item, str) for item in arguments["roots"]
    ):
        raise ToolArgumentValidationError("Canonical file-copy roots are invalid.")
    if not isinstance(arguments["destination_parent_children"], list) or not all(
        isinstance(item, str) for item in arguments["destination_parent_children"]
    ):
        raise ToolArgumentValidationError(
            "Canonical destination snapshot is invalid."
        )
    if not isinstance(arguments["destination_exists"], bool):
        raise ToolArgumentValidationError("Canonical destination state is invalid.")
    for key in ("source_path", "destination_path", "destination_parent"):
        if not isinstance(arguments[key], str) or not arguments[key]:
            raise ToolArgumentValidationError("Canonical file-copy path is invalid.")
    for key in ("source_size", "source_mtime_ns", "source_device", "source_inode"):
        if not isinstance(arguments[key], int):
            raise ToolArgumentValidationError("Canonical source identity is invalid.")


def _validate_copy_boundary(
    source: Path,
    destination: Path,
    arguments: Mapping[str, Any],
) -> None:
    from grandpa.files.safety import FileSafetyPolicy

    safety = FileSafetyPolicy()
    roots = [Path(root) for root in arguments["roots"]]
    try:
        current_source = source.resolve(strict=True)
        parent = destination.parent.resolve(strict=True)
        source_stat = current_source.stat()
        current_children = sorted(child.name for child in parent.iterdir())
    except OSError as exc:
        raise SecurityInvariantError("Copy paths changed before execution.") from exc
    if (
        current_source != source
        or not current_source.is_file()
        or destination.exists()
        or arguments["destination_exists"]
        or parent != Path(str(arguments["destination_parent"]))
        or current_children != arguments["destination_parent_children"]
        or current_source == destination
        or safety.is_protected(current_source)
        or safety.is_protected(destination)
        or not _is_within_roots(current_source, roots)
        or not _is_within_roots(destination, roots)
    ):
        raise SecurityInvariantError("File-copy boundary validation failed.")
    if not _source_identity_matches(source_stat, arguments):
        raise SecurityInvariantError("The copy source changed before execution.")


def _verify_copy_paths(
    source: Path,
    destination: Path,
    arguments: Mapping[str, Any],
) -> None:
    from grandpa.files.safety import FileSafetyPolicy

    safety = FileSafetyPolicy()
    roots = [Path(root) for root in arguments["roots"]]
    source_stat = source.stat()
    if (
        source != Path(str(arguments["source_path"]))
        or destination != Path(str(arguments["destination_path"]))
        or source == destination
        or not source.is_file()
        or not destination.is_file()
        or source_stat.st_size != destination.stat().st_size
        or not _source_identity_matches(source_stat, arguments)
        or safety.is_protected(source)
        or safety.is_protected(destination)
        or not _is_within_roots(source, roots)
        or not _is_within_roots(destination, roots)
    ):
        raise ToolArgumentValidationError("Copied paths failed independent validation.")


def _source_identity_matches(stat_result, arguments: Mapping[str, Any]) -> bool:
    return bool(
        stat_result.st_size == arguments["source_size"]
        and stat_result.st_mtime_ns == arguments["source_mtime_ns"]
        and (
            not stat_result.st_dev
            or not arguments["source_device"]
            or stat_result.st_dev == arguments["source_device"]
        )
        and (
            not stat_result.st_ino
            or not arguments["source_inode"]
            or stat_result.st_ino == arguments["source_inode"]
        )
    )


def _verify_copy_parent_snapshot(arguments: Mapping[str, Any]) -> bool:
    parent = Path(str(arguments["destination_parent"]))
    destination = Path(str(arguments["destination_path"]))
    try:
        expected = set(arguments["destination_parent_children"])
        expected.add(destination.name)
        return {child.name for child in parent.iterdir()} == expected
    except OSError:
        return False


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_create_folder_arguments(
    requested_path: str,
    roots: tuple[str, ...],
) -> Mapping[str, Any]:
    from grandpa.files.paths import resolve_path
    from grandpa.files.safety import FileSafetyPolicy

    safety = FileSafetyPolicy()
    if safety.blocks_traversal(requested_path):
        raise ToolArgumentValidationError(
            "Path traversal is blocked for files.create_folder.",
            safe_message="Path traversal is blocked.",
        )
    canonical_roots = tuple(
        Path(root).expanduser().resolve(strict=False) for root in roots
    )
    if any(safety.is_protected(root) for root in canonical_roots):
        raise ToolArgumentValidationError(
            "Protected root passed to files.create_folder.",
            safe_message="That location is protected and cannot be modified.",
        )
    target = resolve_path(requested_path, roots=canonical_roots).resolve(strict=False)
    if safety.is_protected(target):
        raise ToolArgumentValidationError(
            f"Protected folder target: {target}",
            safe_message="That path is protected and cannot be modified.",
        )
    if not _is_within_roots(target, list(canonical_roots)):
        raise ToolArgumentValidationError(
            f"Folder target is outside validated roots: {target}",
            safe_message="That path is outside the allowed file roots.",
        )

    if target.exists():
        existing_type = (
            "directory"
            if target.is_dir()
            else "file"
            if target.is_file()
            else "other"
        )
        missing_chain: list[Path] = []
        anchor = target.parent
        anchor_children: list[str] = []
    else:
        missing_chain = []
        cursor = target
        while not cursor.exists():
            if cursor.is_symlink():
                raise ToolArgumentValidationError(
                    f"Broken symlink in folder target: {cursor}",
                    safe_message="That folder path contains an unsafe symlink.",
                )
            missing_chain.append(cursor)
            parent = cursor.parent
            if parent == cursor:
                raise ToolArgumentValidationError(
                    "Folder target has no valid existing parent.",
                    safe_message="The parent folder is invalid.",
                )
            cursor = parent
        if not cursor.is_dir():
            raise ToolArgumentValidationError(
                f"Folder parent is not a directory: {cursor}",
                safe_message="The parent path is not a directory.",
            )
        missing_chain.reverse()
        existing_type = "missing"
        anchor = cursor.resolve(strict=True)
        anchor_children = sorted(child.name for child in anchor.iterdir())

    return {
        "requested_path": requested_path,
        "roots": [str(root) for root in canonical_roots],
        "target_path": str(target),
        "existing_type": existing_type,
        "missing_chain": [str(path) for path in missing_chain],
        "anchor_path": str(anchor),
        "anchor_children": anchor_children,
    }


def _validate_canonical_create_folder_arguments(
    arguments: Mapping[str, Any],
) -> None:
    required = {
        "requested_path",
        "roots",
        "target_path",
        "existing_type",
        "missing_chain",
        "anchor_path",
        "anchor_children",
    }
    if set(arguments) != required:
        raise ToolArgumentValidationError(
            "Canonical folder-creation arguments are incomplete."
        )
    if arguments["existing_type"] not in {
        "missing",
        "directory",
        "file",
        "other",
    }:
        raise ToolArgumentValidationError(
            "Canonical folder target type is invalid."
        )
    for key in ("roots", "missing_chain", "anchor_children"):
        if not isinstance(arguments[key], list) or not all(
            isinstance(item, str) for item in arguments[key]
        ):
            raise ToolArgumentValidationError(
                "Canonical folder paths are invalid."
            )
    if not isinstance(arguments["target_path"], str) or not isinstance(
        arguments["anchor_path"], str
    ):
        raise ToolArgumentValidationError("Canonical folder target is invalid.")


def _verify_created_directory_chain(arguments: Mapping[str, Any]) -> bool:
    missing_chain = [Path(path) for path in arguments["missing_chain"]]
    if not missing_chain:
        return False
    anchor = Path(str(arguments["anchor_path"]))
    try:
        expected_anchor_children = set(arguments["anchor_children"])
        expected_anchor_children.add(missing_chain[0].name)
        if {child.name for child in anchor.iterdir()} != expected_anchor_children:
            return False
        for index, directory in enumerate(missing_chain):
            if not directory.is_dir():
                return False
            expected_children = (
                {missing_chain[index + 1].name}
                if index + 1 < len(missing_chain)
                else set()
            )
            if {child.name for child in directory.iterdir()} != expected_children:
                return False
    except OSError:
        return False
    return True


def _resolve_created_target_for_verification(
    requested_path: str,
    roots: tuple[str, ...],
) -> Path:
    from grandpa.files.paths import resolve_path
    from grandpa.files.safety import FileSafetyPolicy

    safety = FileSafetyPolicy()
    canonical_roots = [Path(root).expanduser().resolve(strict=False) for root in roots]
    target = resolve_path(requested_path, roots=tuple(canonical_roots)).resolve(
        strict=True
    )
    if safety.blocks_traversal(requested_path):
        raise ToolArgumentValidationError("Path traversal detected during verification.")
    if safety.is_protected(target) or not _is_within_roots(target, canonical_roots):
        raise ToolArgumentValidationError(
            "Created folder failed protected-root verification."
        )
    return target


def _mkdir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=False)


def _inspect_path_metadata(path: Path):
    from grandpa.files.metadata import inspect_path_metadata

    return inspect_path_metadata(path)


def _format_properties_message(metadata) -> str:
    from grandpa.files.metadata import format_properties_message

    return format_properties_message(metadata)
