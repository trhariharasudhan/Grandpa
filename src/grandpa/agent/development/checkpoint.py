"""Checkpoint management for Autonomous Development Workflow V1."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Optional, Tuple

from grandpa.agent.development.models import Checkpoint, ProjectState


class CheckpointManager:
    """Manages creation, retrieval, validation, and restoration of project checkpoints."""

    def __init__(self, project_path: str) -> None:
        self.project_path = Path(project_path).resolve()
        self.checkpoint_dir = self.project_path / ".grandpa" / "checkpoints"
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

    def save_checkpoint(
        self, state: ProjectState, checkpoint_id: Optional[str] = None
    ) -> Checkpoint:
        """Create and persist a new snapshot checkpoint of the current project state."""
        if not checkpoint_id:
            checkpoint_id = f"chk_{str(uuid.uuid4())[:8]}"

        checkpoint = Checkpoint(
            checkpoint_id=checkpoint_id,
            timestamp=time.time(),
            active_branch=state.active_branch,
            repository_health=state.repository_health,
            state=state,
        )

        target_file = self.checkpoint_dir / f"{checkpoint_id}.json"
        target_file.write_text(
            json.dumps(checkpoint.to_dict(), indent=2), encoding="utf-8"
        )
        return checkpoint

    def load_checkpoint(self, checkpoint_id: str) -> Checkpoint:
        """Load a saved checkpoint by ID from disk."""
        target_file = self.checkpoint_dir / f"{checkpoint_id}.json"
        if not target_file.exists():
            raise FileNotFoundError(
                f"Checkpoint file '{checkpoint_id}' not found at {target_file}."
            )

        try:
            data = json.loads(target_file.read_text(encoding="utf-8"))
            return Checkpoint.from_dict(data)
        except Exception as exc:
            raise ValueError(f"Failed to parse checkpoint JSON data: {exc}") from exc

    def validate_checkpoint(
        self, checkpoint: Checkpoint, current_branch: str, current_health: str
    ) -> bool:
        """Validate if the checkpoint matches the current repository branch and health status."""
        if checkpoint.active_branch != current_branch:
            return False
        if checkpoint.repository_health != current_health:
            return False
        return True

    def list_checkpoints(self) -> list[str]:
        """Return a list of all saved checkpoint IDs."""
        if not self.checkpoint_dir.exists():
            return []
        return [p.stem for p in self.checkpoint_dir.glob("*.json")]

    def restore_checkpoint(self, checkpoint_id: str) -> Tuple[bool, str]:
        """Restore project state to the specified checkpoint."""
        try:
            checkpoint = self.load_checkpoint(checkpoint_id)
            state_file = self.project_path / ".grandpa" / "development_state.json"
            state_file.write_text(
                json.dumps(checkpoint.state.to_dict(), indent=2), encoding="utf-8"
            )
            return (
                True,
                f"Successfully restored project state to checkpoint '{checkpoint_id}'.",
            )
        except Exception as exc:
            return False, f"Failed to restore checkpoint: {exc}"
