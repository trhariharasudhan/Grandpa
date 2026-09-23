"""SkillManageTool — create, list, load, or delete agent-authored skills."""

from __future__ import annotations

from pathlib import Path
from typing import Any, List

from grandpa.core.registry import ToolRegistry
from grandpa.core.types import ToolResult
from grandpa.tools._stubs import BaseTool, ToolSpec


@ToolRegistry.register("skill_manage")
class SkillManageTool(BaseTool):
    """Manage agent-authored procedural skills."""

    def __init__(self, skills_dir: Path | str = "~/.grandpa/skills/") -> None:
        self._skills_dir = Path(skills_dir).expanduser()

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="skill_manage",
            description="Create, list, load, or delete agent-authored skills.",
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["create", "list", "load", "delete"],
                        "description": "Action to perform.",
                    },
                    "name": {
                        "type": "string",
                        "description": "Skill name (for create/load/delete).",
                    },
                    "description": {
                        "type": "string",
                        "description": "Skill description (for create).",
                    },
                    "steps": {
                        "type": "array",
                        "description": (
                            "List of step dicts with tool_name and optional"
                            " arguments_template (for create)."
                        ),
                    },
                },
                "required": ["action"],
            },
            category="skill",
            # ``create`` and ``delete`` write and remove skill manifests under
            # ~/.grandpa/skills/, and a manifest is deferred execution: its
            # steps name tools, and it runs later with nobody reading it. This
            # tool is model-facing, so without this flag a model could author
            # one unprompted -- the same shape as the saved-skill hole, one
            # directory over.
            #
            # The flag is per-tool because ``ToolExecutor`` reads
            # ``spec.requires_confirmation`` before dispatch and cannot see the
            # params (tools/_stubs.py). So ``list`` and ``load``, which only
            # read, are gated too. That costs a prompt on two reads; the
            # alternative is teaching the one mandatory enforcement boundary to
            # inspect arguments, which is a larger change to the thing every
            # other tool depends on. Paying the prompt is the cheaper side.
            requires_confirmation=True,
        )

    def execute(self, **params: Any) -> ToolResult:
        action = params.get("action", "list")
        name = params.get("name", "")
        if action == "create":
            return self._create(
                name, params.get("description", ""), params.get("steps", [])
            )
        elif action == "list":
            return self._list()
        elif action == "load":
            return self._load(name)
        elif action == "delete":
            return self._delete(name)
        return ToolResult(
            tool_name=self.spec.name,
            success=False,
            content=f"Unknown action: {action}",
        )

    def _create(self, name: str, description: str, steps: List[dict]) -> ToolResult:
        if not name:
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content="Skill name is required.",
            )
        self._skills_dir.mkdir(parents=True, exist_ok=True)
        path = self._skills_dir / f"{name}.toml"
        lines = [
            "[skill]",
            f'name = "{name}"',
            f'description = "{description}"',
            # Recorded, not chosen: this tool is model-facing, so anything it
            # writes was written by a model. SkillManager.discover() refuses to
            # load it without someone agreeing first.
            'provenance = "model"',
            "",
        ]
        for step in steps:
            lines.append("[[skill.steps]]")
            lines.append(f'tool_name = "{step.get("tool_name", "")}"')
            if "arguments_template" in step:
                lines.append(f"arguments_template = '{step['arguments_template']}'")
            if "output_key" in step:
                lines.append(f'output_key = "{step["output_key"]}"')
            lines.append("")
        path.write_text("\n".join(lines))
        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            content=f"Created skill: {name}",
        )

    def _list(self) -> ToolResult:
        if not self._skills_dir.exists():
            return ToolResult(
                tool_name=self.spec.name,
                success=True,
                content="No skills directory found.",
            )
        skills = []
        for f in sorted(self._skills_dir.glob("*.toml")):
            skills.append(f.stem)
        if not skills:
            return ToolResult(
                tool_name=self.spec.name,
                success=True,
                content="No skills found.",
            )
        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            content="Available skills:\n" + "\n".join(f"- {s}" for s in skills),
        )

    def _load(self, name: str) -> ToolResult:
        path = self._skills_dir / f"{name}.toml"
        if not path.exists():
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content=f"Skill not found: {name}",
            )
        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            content=path.read_text(),
        )

    def _delete(self, name: str) -> ToolResult:
        path = self._skills_dir / f"{name}.toml"
        if not path.exists():
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content=f"Skill not found: {name}",
            )
        path.unlink()
        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            content=f"Deleted skill: {name}",
        )
