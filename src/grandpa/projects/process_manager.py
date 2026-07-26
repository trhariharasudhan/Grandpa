"""Owned process metadata and Windows-safe PID validation."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from grandpa.core.config import DEFAULT_CONFIG_DIR

logger = logging.getLogger(__name__)
SCHEMA_VERSION = 1
DEFAULT_PROCESS_STATE_PATH = DEFAULT_CONFIG_DIR / "project-processes.json"


@dataclass(frozen=True)
class ProjectProcess:
    project_id: str
    pid: int
    command: tuple[str, ...]
    working_directory: str
    started_at: str
    log_path: str
    executable: str

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["command"] = list(self.command)
        return data


class ProjectProcessStore:
    def __init__(self, path: Path = DEFAULT_PROCESS_STATE_PATH) -> None:
        self.path = Path(path)

    def load(self) -> dict[str, ProjectProcess]:
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if payload.get("schema_version") != SCHEMA_VERSION:
                return {}
            return {
                item["project_id"]: ProjectProcess(
                    project_id=item["project_id"],
                    pid=int(item["pid"]),
                    command=tuple(item.get("command", ())),
                    working_directory=item.get("working_directory", ""),
                    started_at=item.get("started_at", ""),
                    log_path=item.get("log_path", ""),
                    executable=item.get("executable", ""),
                )
                for item in payload.get("processes", [])
            }
        except (OSError, ValueError, KeyError, TypeError):
            return {}

    def save(self, values: dict[str, ProjectProcess]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                {
                    "schema_version": SCHEMA_VERSION,
                    "processes": [item.to_dict() for item in values.values()],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        os.replace(temporary, self.path)

    def get_owned(self, project_id: str) -> ProjectProcess | None:
        values = self.load()
        state = values.get(project_id)
        if state is None:
            return None
        if not process_matches(state):
            logger.info("Removed stale project PID %s for %s", state.pid, project_id)
            values.pop(project_id, None)
            self.save(values)
            return None
        return state

    def put(self, state: ProjectProcess) -> None:
        values = self.load()
        values[state.project_id] = state
        self.save(values)

    def remove(self, project_id: str) -> None:
        values = self.load()
        values.pop(project_id, None)
        self.save(values)


def process_matches(state: ProjectProcess) -> bool:
    if state.pid <= 0:
        return False
    try:
        import psutil

        process = psutil.Process(state.pid)
        if not process.is_running() or process.status() == psutil.STATUS_ZOMBIE:
            return False
        executable = str(process.exe() or "")
        command = tuple(str(item) for item in process.cmdline())
        expected_executable = Path(state.executable).name.casefold()
        actual_executable = Path(executable).name.casefold()
        if expected_executable and actual_executable != expected_executable:
            return False
        expected_tokens = tuple(
            Path(item).name.casefold() for item in state.command[:2]
        )
        actual_text = " ".join(command).casefold()
        return all(token in actual_text for token in expected_tokens if token)
    except Exception:
        return False


__all__ = [
    "DEFAULT_PROCESS_STATE_PATH",
    "ProjectProcess",
    "ProjectProcessStore",
    "process_matches",
]
