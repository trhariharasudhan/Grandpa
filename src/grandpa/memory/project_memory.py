"""Project-scoped Memory management for Grandpa."""

from __future__ import annotations

from typing import Any

from grandpa.memory.models import MemoryItem
from grandpa.memory.store import MemoryStore


class ProjectMemory:
    """Project-scoped memory manager backed by MemoryStore."""

    def __init__(self, store: MemoryStore | None = None) -> None:
        self.store = store or MemoryStore()

    def update_project_info(
        self,
        project_name: str,
        content: str,
        key_suffix: str = "summary",
        project_path: str | None = None,
        latest_feature: str | None = None,
        latest_commit: str | None = None,
        next_task: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryItem:
        """Store or update project memory information."""
        clean_proj = project_name.strip().lower().replace(" ", "_")
        key = f"proj_{clean_proj}_{key_suffix}"
        meta = {
            "project_name": project_name,
            "project_path": project_path,
            "latest_feature": latest_feature,
            "latest_commit": latest_commit,
            "next_task": next_task,
            **(metadata or {}),
        }
        item = MemoryItem(
            key=key,
            content=content,
            category="project",
            project_name=project_name,
            metadata=meta,
        )
        return self.store.insert(item)

    def get_project_summary(self, project_name: str) -> MemoryItem | None:
        """Get summary memory item for a project."""
        clean_proj = project_name.strip().lower().replace(" ", "_")
        key = f"proj_{clean_proj}_summary"
        item = self.store.get_by_key(key)
        if not item:
            # Fallback to search by project name
            items = self.store.list_all(category="project", project_name=project_name, limit=1)
            return items[0] if items else None
        return item

    def list_projects(self) -> list[dict[str, Any]]:
        """List all tracked projects and their summary metadata."""
        items = self.store.list_all(category="project", limit=100)
        projects: dict[str, dict[str, Any]] = {}
        for item in items:
            pname = item.project_name or item.metadata.get("project_name") or "unknown"
            if pname not in projects or item.updated_at > projects[pname].get("updated_at", 0):
                projects[pname] = {
                    "project_name": pname,
                    "key": item.key,
                    "summary": item.content,
                    "path": item.metadata.get("project_path"),
                    "latest_feature": item.metadata.get("latest_feature"),
                    "latest_commit": item.metadata.get("latest_commit"),
                    "next_task": item.metadata.get("next_task"),
                    "updated_at": item.updated_at,
                }
        return list(projects.values())

    def search_project(self, query: str, project_name: str | None = None, limit: int = 10) -> list[MemoryItem]:
        """Search memory within project scope."""
        return self.store.search(query, category="project", project_name=project_name, limit=limit)
