"""Multi-project registry for managing and tracking multiple software projects simultaneously."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class ProjectInfo:
    """Registry metadata for a tracked project."""

    project_id: str
    project_name: str
    project_path: str
    description: str = ""
    active_branch: str = "main"
    repository_health: str = "healthy"
    created_at: float = 0.0
    updated_at: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "project_name": self.project_name,
            "project_path": self.project_path,
            "description": self.description,
            "active_branch": self.active_branch,
            "repository_health": self.repository_health,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ProjectInfo:
        return cls(
            project_id=data["project_id"],
            project_name=data["project_name"],
            project_path=data["project_path"],
            description=data.get("description", ""),
            active_branch=data.get("active_branch", "main"),
            repository_health=data.get("repository_health", "healthy"),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
        )


class MultiProjectRegistry:
    """Manages project registrations, list queries, active project switching, and configuration persistence."""

    def __init__(self, registry_file: Optional[str] = None) -> None:
        if registry_file:
            self.registry_file = Path(registry_file).resolve()
        else:
            grandpa_home = os.environ.get("GRANDPA_HOME", Path.home() / ".grandpa")
            self.registry_file = (
                Path(grandpa_home).expanduser() / "projects_registry.json"
            )

        self.registry_file.parent.mkdir(parents=True, exist_ok=True)
        self.active_project_id: Optional[str] = None
        self.projects: Dict[str, ProjectInfo] = {}
        self.load()

    def load(self) -> None:
        """Load projects registry from disk."""
        if not self.registry_file.exists():
            self.active_project_id = None
            self.projects = {}
            return

        try:
            data = json.loads(self.registry_file.read_text(encoding="utf-8"))
            self.active_project_id = data.get("active_project_id")
            self.projects = {
                pid: ProjectInfo.from_dict(pdata)
                for pid, pdata in data.get("projects", {}).items()
            }
        except Exception:
            self.active_project_id = None
            self.projects = {}

    def save(self) -> None:
        """Persist project registry to disk."""
        data = {
            "active_project_id": self.active_project_id,
            "projects": {pid: pinfo.to_dict() for pid, pinfo in self.projects.items()},
        }
        self.registry_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def register_project(
        self, name: str, path: str, description: str = ""
    ) -> ProjectInfo:
        """Register an existing project path in the registry, preventing duplicate paths or names."""
        clean_path = str(Path(path).resolve())
        clean_name_lower = name.strip().lower()

        # Check for duplicates
        for pid, p in self.projects.items():
            if str(Path(p.project_path).resolve()) == clean_path:
                raise ValueError(f"Project already registered at path: {path}")
            if p.project_name.strip().lower() == clean_name_lower:
                raise ValueError(f"Project name '{name}' is already taken.")

        project_id = f"prj_{clean_name_lower.replace(' ', '_')}"
        now = time.time()
        pinfo = ProjectInfo(
            project_id=project_id,
            project_name=name.strip(),
            project_path=clean_path,
            description=description,
            created_at=now,
            updated_at=now,
        )

        self.projects[project_id] = pinfo
        # Automatically make it the active project if none is active
        if not self.active_project_id:
            self.active_project_id = project_id

        self.save()
        return pinfo

    def create_project(
        self, name: str, path: str, description: str = ""
    ) -> ProjectInfo:
        """Create a new project folder and register it."""
        target_path = Path(path).resolve()
        target_path.mkdir(parents=True, exist_ok=True)
        # Touch a default state JSON file inside to initialize it
        dot_grandpa = target_path / ".grandpa"
        dot_grandpa.mkdir(parents=True, exist_ok=True)
        state_file = dot_grandpa / "development_state.json"
        if not state_file.exists():
            state_data = {
                "project_name": name,
                "project_path": str(target_path),
                "tasks": [],
                "roadmap": {},
            }
            state_file.write_text(json.dumps(state_data, indent=2), encoding="utf-8")

        return self.register_project(name, str(target_path), description)

    def remove_project(self, project_id: str) -> None:
        """Remove a project from the registry."""
        if project_id not in self.projects:
            raise KeyError(f"Project ID '{project_id}' not found in registry.")

        del self.projects[project_id]
        if self.active_project_id == project_id:
            self.active_project_id = (
                list(self.projects.keys())[0] if self.projects else None
            )

        self.save()

    def switch_project(self, identifier: str) -> ProjectInfo:
        """Switch the active project using ID or Name."""
        target_proj: Optional[ProjectInfo] = None

        # Check by project_id
        if identifier in self.projects:
            target_proj = self.projects[identifier]
        else:
            # Check by project_name (case-insensitive)
            clean_ident = identifier.strip().lower()
            for p in self.projects.values():
                if p.project_name.strip().lower() == clean_ident:
                    target_proj = p
                    break

        if not target_proj:
            raise KeyError(f"Project '{identifier}' not found in registry.")

        self.active_project_id = target_proj.project_id
        self.save()
        return target_proj

    def get_active_project(self) -> Optional[ProjectInfo]:
        """Return the currently active ProjectInfo."""
        if not self.active_project_id or self.active_project_id not in self.projects:
            return None
        return self.projects[self.active_project_id]

    def list_projects(self) -> List[ProjectInfo]:
        """Return a list of all registered projects."""
        return list(self.projects.values())
