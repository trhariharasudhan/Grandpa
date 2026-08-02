"""Data models for Autonomous Development Workflow V1, Project Engineer Mode V1, and Self-Planning Engine V1."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Task:
    """A single development task in the Task Registry."""

    task_id: str
    title: str
    status: str = "pending"  # pending, in_progress, completed, blocked
    priority: str = "medium"  # high, medium, low
    dependencies: List[str] = field(default_factory=list)
    completion_state: bool = False
    description: str = ""
    milestone: Optional[str] = None
    rationale: str = ""
    affected_areas: List[str] = field(default_factory=list)
    expected_artifacts: List[str] = field(default_factory=list)
    acceptance_criteria: List[str] = field(default_factory=list)
    validation_commands: List[str] = field(default_factory=list)
    risk_level: str = "low"  # low, medium, high

    @property
    def milestone_id(self) -> Optional[str]:
        return self.milestone

    @milestone_id.setter
    def milestone_id(self, val: Optional[str]) -> None:
        self.milestone = val

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "title": self.title,
            "status": self.status,
            "priority": self.priority,
            "dependencies": self.dependencies,
            "completion_state": self.completion_state,
            "description": self.description,
            "milestone": self.milestone,
            "rationale": self.rationale,
            "affected_areas": self.affected_areas,
            "expected_artifacts": self.expected_artifacts,
            "acceptance_criteria": self.acceptance_criteria,
            "validation_commands": self.validation_commands,
            "risk_level": self.risk_level,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Task:
        return cls(
            task_id=data["task_id"],
            title=data["title"],
            status=data.get("status", "pending"),
            priority=data.get("priority", "medium"),
            dependencies=data.get("dependencies", []),
            completion_state=data.get("completion_state", False),
            description=data.get("description", ""),
            milestone=data.get("milestone"),
            rationale=data.get("rationale", ""),
            affected_areas=data.get("affected_areas", []),
            expected_artifacts=data.get("expected_artifacts", []),
            acceptance_criteria=data.get("acceptance_criteria", []),
            validation_commands=data.get("validation_commands", []),
            risk_level=data.get("risk_level", "medium"),
        )


@dataclass
class Milestone:
    """A project milestone representing a key stage of development."""

    milestone_id: str
    title: str
    description: str = ""
    status: str = "pending"  # pending, in_progress, completed, blocked
    priority: str = "medium"  # high, medium, low
    dependencies: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    rationale: str = ""
    acceptance_criteria: List[str] = field(default_factory=list)
    validation_strategy: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "milestone_id": self.milestone_id,
            "title": self.title,
            "description": self.description,
            "status": self.status,
            "priority": self.priority,
            "dependencies": self.dependencies,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "rationale": self.rationale,
            "acceptance_criteria": self.acceptance_criteria,
            "validation_strategy": self.validation_strategy,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Milestone:
        return cls(
            milestone_id=data["milestone_id"],
            title=data["title"],
            description=data.get("description", ""),
            status=data.get("status", "pending"),
            priority=data.get("priority", "medium"),
            dependencies=data.get("dependencies", []),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
            rationale=data.get("rationale", ""),
            acceptance_criteria=data.get("acceptance_criteria", []),
            validation_strategy=data.get("validation_strategy", []),
        )


@dataclass
class Roadmap:
    """Roadmap Memory tracking milestones."""

    completed_milestones: List[str] = field(default_factory=list)
    current_milestone: Optional[str] = None
    planned_milestones: List[str] = field(default_factory=list)
    blocked_milestones: List[str] = field(default_factory=list)
    milestones: Dict[str, Milestone] = field(default_factory=dict)
    planning_history: List[Dict[str, Any]] = field(default_factory=list)
    roadmap_schema_version: int = 1
    generated_by: str = ""
    generation_goal: str = ""
    migrated_from_version: Optional[int] = None
    migration_timestamp: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "completed_milestones": self.completed_milestones,
            "current_milestone": self.current_milestone,
            "planned_milestones": self.planned_milestones,
            "blocked_milestones": self.blocked_milestones,
            "milestones": {mid: m.to_dict() for mid, m in self.milestones.items()},
            "planning_history": self.planning_history,
            "roadmap_schema_version": self.roadmap_schema_version,
            "generated_by": self.generated_by,
            "generation_goal": self.generation_goal,
            "migrated_from_version": self.migrated_from_version,
            "migration_timestamp": self.migration_timestamp,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Roadmap:
        return cls(
            completed_milestones=data.get("completed_milestones", []),
            current_milestone=data.get("current_milestone"),
            planned_milestones=data.get("planned_milestones", []),
            blocked_milestones=data.get("blocked_milestones", []),
            milestones={
                mid: Milestone.from_dict(mdata)
                for mid, mdata in data.get("milestones", {}).items()
            },
            planning_history=data.get("planning_history", []),
            roadmap_schema_version=data.get("roadmap_schema_version", 1),
            generated_by=data.get("generated_by", ""),
            generation_goal=data.get("generation_goal", ""),
            migrated_from_version=data.get("migrated_from_version"),
            migration_timestamp=data.get("migration_timestamp"),
        )


@dataclass
class ProjectState:
    """Project State Tracker holding registry, state, and roadmap metadata."""

    project_name: str
    project_path: str
    last_completed_feature: Optional[str] = None
    current_milestone: Optional[str] = None
    next_milestone: Optional[str] = None
    active_branch: str = "main"
    repository_health: str = "healthy"  # healthy, unhealthy
    timestamp: float = field(default_factory=time.time)
    tasks: List[Task] = field(default_factory=list)
    roadmap: Roadmap = field(default_factory=Roadmap)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_name": self.project_name,
            "project_path": self.project_path,
            "last_completed_feature": self.last_completed_feature,
            "current_milestone": self.current_milestone,
            "next_milestone": self.next_milestone,
            "active_branch": self.active_branch,
            "repository_health": self.repository_health,
            "timestamp": self.timestamp,
            "tasks": [t.to_dict() for t in self.tasks],
            "roadmap": self.roadmap.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ProjectState:
        return cls(
            project_name=data["project_name"],
            project_path=data["project_path"],
            last_completed_feature=data.get("last_completed_feature"),
            current_milestone=data.get("current_milestone"),
            next_milestone=data.get("next_milestone"),
            active_branch=data.get("active_branch", "main"),
            repository_health=data.get("repository_health", "healthy"),
            timestamp=data.get("timestamp", time.time()),
            tasks=[Task.from_dict(t) for t in data.get("tasks", [])],
            roadmap=Roadmap.from_dict(data.get("roadmap", {})),
        )


@dataclass
class Checkpoint:
    """A snapshot checkpoint representing a complete saved state."""

    checkpoint_id: str
    timestamp: float
    active_branch: str
    repository_health: str
    state: ProjectState

    def to_dict(self) -> Dict[str, Any]:
        return {
            "checkpoint_id": self.checkpoint_id,
            "timestamp": self.timestamp,
            "active_branch": self.active_branch,
            "repository_health": self.repository_health,
            "state": self.state.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Checkpoint:
        return cls(
            checkpoint_id=data["checkpoint_id"],
            timestamp=data["timestamp"],
            active_branch=data["active_branch"],
            repository_health=data["repository_health"],
            state=ProjectState.from_dict(data["state"]),
        )
