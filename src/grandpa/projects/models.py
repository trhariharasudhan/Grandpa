"""Typed data models for registered projects and workflows."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class ProjectCommand:
    args: tuple[str, ...]
    timeout_seconds: int = 300
    long_running: bool = False
    requires_confirmation: bool = False

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["args"] = list(self.args)
        return data

    @classmethod
    def from_dict(cls, value: Any) -> ProjectCommand | None:
        if not value:
            return None
        if isinstance(value, list):
            return cls(tuple(str(item) for item in value))
        if not isinstance(value, dict):
            return None
        return cls(
            args=tuple(str(item) for item in value.get("args", ())),
            timeout_seconds=max(1, int(value.get("timeout_seconds", 300))),
            long_running=bool(value.get("long_running", False)),
            requires_confirmation=bool(value.get("requires_confirmation", False)),
        )


@dataclass(frozen=True)
class Project:
    id: str
    name: str
    root_path: str
    aliases: tuple[str, ...] = ()
    project_type: str = "unknown"
    editor: str = "visual studio code"
    description: str = ""
    default_branch: str = ""
    commands: dict[str, ProjectCommand] = field(default_factory=dict)
    test_profiles: dict[str, ProjectCommand] = field(default_factory=dict)
    log_paths: tuple[str, ...] = ()
    environment: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "aliases": list(self.aliases),
            "root_path": self.root_path,
            "project_type": self.project_type,
            "editor": self.editor,
            "description": self.description,
            "default_branch": self.default_branch,
            "commands": {
                name: command.to_dict() for name, command in self.commands.items()
            },
            "test_profiles": {
                name: command.to_dict() for name, command in self.test_profiles.items()
            },
            "log_paths": list(self.log_paths),
            # Persist variable names only; values may contain credentials.
            "environment": {name: "" for name in self.environment},
            "metadata": dict(self.metadata),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Project:
        commands = {
            str(name): command
            for name, value in dict(data.get("commands", {})).items()
            if (command := ProjectCommand.from_dict(value)) is not None
        }
        profiles = {
            str(name): command
            for name, value in dict(data.get("test_profiles", {})).items()
            if (command := ProjectCommand.from_dict(value)) is not None
        }
        return cls(
            id=str(data.get("id", "")),
            name=str(data.get("name", "")),
            aliases=tuple(str(item) for item in data.get("aliases", ())),
            root_path=str(data.get("root_path", "")),
            project_type=str(data.get("project_type", "unknown")),
            editor=str(data.get("editor", "visual studio code")),
            description=str(data.get("description", "")),
            default_branch=str(data.get("default_branch", "")),
            commands=commands,
            test_profiles=profiles,
            log_paths=tuple(str(item) for item in data.get("log_paths", ())),
            environment={
                str(key): str(value)
                for key, value in dict(data.get("environment", {})).items()
            },
            metadata=dict(data.get("metadata", {})),
            created_at=str(data.get("created_at", "")),
            updated_at=str(data.get("updated_at", "")),
        )


@dataclass(frozen=True)
class ProjectCandidate:
    path: str
    project_type: str


@dataclass(frozen=True)
class WorkflowResult:
    status: str
    message: str
    exit_code: int | None = None
    output: str = ""
    log_path: str = ""
    pid: int | None = None


@dataclass(frozen=True)
class ProjectCommandResult:
    status: str
    message: str
    action: str = ""
    project_id: str = ""

    @property
    def should_fallback(self) -> bool:
        return self.status == "no_match"


__all__ = [
    "Project",
    "ProjectCandidate",
    "ProjectCommand",
    "ProjectCommandResult",
    "WorkflowResult",
]
