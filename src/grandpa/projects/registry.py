"""Versioned, atomic project registry persistence."""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from grandpa.core.config import DEFAULT_CONFIG_DIR
from grandpa.projects.discovery import detect_project_type
from grandpa.projects.errors import (
    InvalidProjectPathError,
    ProjectAlreadyRegisteredError,
)
from grandpa.projects.models import Project, ProjectCommand

logger = logging.getLogger(__name__)
SCHEMA_VERSION = 1
DEFAULT_PROJECT_REGISTRY_PATH = DEFAULT_CONFIG_DIR / "projects.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_project_id(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return normalized or "project"


class ProjectRegistry:
    def __init__(self, path: Path = DEFAULT_PROJECT_REGISTRY_PATH) -> None:
        self.path = Path(path)

    def list(self) -> list[Project]:
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            logger.warning("Project registry could not be read: %s", self.path)
            return []
        if int(payload.get("schema_version", 0)) != SCHEMA_VERSION:
            logger.warning(
                "Unsupported project registry schema: %s", payload.get("schema_version")
            )
            return []
        return [Project.from_dict(item) for item in payload.get("projects", [])]

    def save(self, projects: list[Project]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": SCHEMA_VERSION,
            "projects": [item.to_dict() for item in projects],
        }
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(temporary, self.path)

    def register(
        self,
        root_path: str | Path,
        *,
        name: str | None = None,
        aliases: tuple[str, ...] = (),
        editor: str = "visual studio code",
        project_id: str | None = None,
        bootstrap: bool = False,
    ) -> Project:
        root = Path(root_path).expanduser().resolve(strict=False)
        if not root.exists() or not root.is_dir():
            raise InvalidProjectPathError(f"Project folder does not exist: {root}")
        projects = self.list()
        if any(Path(item.root_path) == root for item in projects):
            raise ProjectAlreadyRegisteredError(
                f"Project is already registered: {root}"
            )
        display_name = (name or root.name).strip()
        identifier = normalize_project_id(project_id or display_name)
        if any(item.id == identifier for item in projects):
            raise ProjectAlreadyRegisteredError(
                f"Project ID is already registered: {identifier}"
            )
        timestamp = _now()
        project_type = detect_project_type(root)
        commands, profiles, logs = (
            _grandpa_bootstrap(root)
            if bootstrap
            else (_suggest_commands(root, project_type), {}, ())
        )
        project = Project(
            id=identifier,
            name=display_name,
            root_path=str(root),
            aliases=tuple(
                dict.fromkeys((identifier, display_name.casefold(), *aliases))
            ),
            project_type=project_type,
            editor=editor,
            commands=commands,
            test_profiles=profiles,
            log_paths=logs,
            metadata={"grandpa_lifecycle": bootstrap},
            created_at=timestamp,
            updated_at=timestamp,
        )
        projects.append(project)
        self.save(projects)
        logger.info("Registered project %s at %s", project.id, project.root_path)
        return project

    def unregister(self, project_id: str) -> Project | None:
        projects = self.list()
        removed = next((item for item in projects if item.id == project_id), None)
        if removed is None:
            return None
        self.save([item for item in projects if item.id != project_id])
        logger.info("Unregistered project %s", project_id)
        return removed

    def ensure_grandpa(self, root: Path | None = None) -> Project | None:
        root = (root or Path(__file__).resolve().parents[3]).resolve()
        if (
            not (root / "pyproject.toml").exists()
            or not (root / "src" / "grandpa").is_dir()
        ):
            return None
        existing = next(
            (
                item
                for item in self.list()
                if item.id == "grandpa" or Path(item.root_path) == root
            ),
            None,
        )
        if existing is not None:
            if not existing.metadata.get("grandpa_lifecycle"):
                commands, profiles, logs = _grandpa_bootstrap(root)
                updated = replace(
                    existing,
                    commands={**existing.commands, **commands},
                    test_profiles={**existing.test_profiles, **profiles},
                    log_paths=tuple(dict.fromkeys((*existing.log_paths, *logs))),
                    metadata={**existing.metadata, "grandpa_lifecycle": True},
                    updated_at=_now(),
                )
                self.save(
                    [
                        updated if item.id == existing.id else item
                        for item in self.list()
                    ]
                )
                return updated
            return existing
        return self.register(
            root,
            name="Grandpa",
            aliases=("grandpa project", "local assistant"),
            bootstrap=True,
        )


def _grandpa_bootstrap(
    root: Path,
) -> tuple[dict[str, ProjectCommand], dict[str, ProjectCommand], tuple[str, ...]]:
    python = "python"
    commands = {
        "test": ProjectCommand((python, "-m", "pytest", "-q"), timeout_seconds=1800),
        "lint": ProjectCommand(
            (python, "-m", "ruff", "check", "src", "tests"), timeout_seconds=600
        ),
    }
    profiles = {
        "voice": ProjectCommand(
            (
                python,
                "-m",
                "pytest",
                "tests/test_voice_cli_session.py",
                "tests/cli/test_voice_cmd.py",
                "-q",
            ),
            timeout_seconds=900,
        ),
        "chat": ProjectCommand(
            (python, "-m", "pytest", "tests/cli/test_chat_cmd.py", "-q"),
            timeout_seconds=900,
        ),
        "apps": ProjectCommand(
            (
                python,
                "-m",
                "pytest",
                "tests/test_app_inventory.py",
                "tests/test_pc_control.py",
                "-q",
            ),
            timeout_seconds=900,
        ),
    }
    return commands, profiles, (str(DEFAULT_CONFIG_DIR / "server.log"),)


def _suggest_commands(root: Path, project_type: str) -> dict[str, ProjectCommand]:
    """Infer conservative workflows from project files without running them."""
    if "python" not in project_type:
        return {}
    pyproject_path = root / "pyproject.toml"
    pyproject = (
        pyproject_path.read_text(encoding="utf-8", errors="ignore")
        if pyproject_path.exists()
        else ""
    )
    commands: dict[str, ProjectCommand] = {}
    if (root / "tests").is_dir() or "pytest" in pyproject.casefold():
        commands["test"] = ProjectCommand(
            ("python", "-m", "pytest", "-q"), timeout_seconds=1800
        )
    if "ruff" in pyproject.casefold():
        commands["lint"] = ProjectCommand(
            ("python", "-m", "ruff", "check", "."), timeout_seconds=600
        )
    return commands


__all__ = [
    "DEFAULT_PROJECT_REGISTRY_PATH",
    "ProjectRegistry",
    "SCHEMA_VERSION",
    "normalize_project_id",
]
