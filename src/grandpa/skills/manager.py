"""SkillManager — coordinates skill discovery, catalog, tool wrapping, and execution."""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any, Dict, List, Optional

from grandpa.core.events import EventBus
from grandpa.skills.dependency import validate_dependencies
from grandpa.skills.executor import SkillExecutor, SkillResult
from grandpa.skills.loader import discover_skills
from grandpa.skills.tool_adapter import SkillTool
from grandpa.skills.types import SkillManifest
from grandpa.tools._stubs import BaseTool, ToolExecutor


class SkillManager:
    """Coordinate skill discovery, resolution, catalog generation, and execution.

    Parameters
    ----------
    bus:
        Event bus for publishing lifecycle events.
    capability_policy:
        Optional capability policy passed through to tool executors.
    """

    def __init__(
        self,
        bus: EventBus,
        *,
        capability_policy: Optional[Any] = None,
    ) -> None:
        self._bus = bus
        self._capability_policy = capability_policy
        self._skills: Dict[str, SkillManifest] = {}
        self._tool_executor: Optional[ToolExecutor] = None

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def discover(self, paths: Optional[List[Path]] = None) -> None:
        """Scan directories in order and register skills.

        First-seen name wins (workspace path listed first = highest precedence).
        After loading, the full dependency graph is validated.

        Parameters
        ----------
        paths:
            Directories to scan. If *None* or empty, no skills are loaded.
        """
        if paths:
            for directory in paths:
                manifests = discover_skills(directory)
                for manifest in manifests:
                    # First-seen wins: do not overwrite an already-registered skill
                    if manifest.name not in self._skills:
                        self._skills[manifest.name] = manifest

            # Validate the dependency graph after loading skills
            if self._skills:
                validate_dependencies(self._skills)

    # ------------------------------------------------------------------
    # Resolve / introspect
    # ------------------------------------------------------------------

    def resolve(self, name: str) -> SkillManifest:
        """Return the manifest for a skill by name.

        Raises
        ------
        KeyError
            If *name* is not registered.
        """
        if name not in self._skills:
            raise KeyError(f"Skill '{name}' not found")
        return self._skills[name]

    def skill_names(self) -> List[str]:
        """Return the names of all registered skills."""
        return list(self._skills.keys())

    # ------------------------------------------------------------------
    # Tool wrapping
    # ------------------------------------------------------------------

    def get_skill_tools(
        self, *, tool_executor: Optional[ToolExecutor] = None
    ) -> List[BaseTool]:
        """Wrap each registered skill as a :class:`SkillTool` (a :class:`BaseTool`).

        Parameters
        ----------
        tool_executor:
            Tool executor to use when running skill pipelines.  Falls back to
            the one set via :meth:`set_tool_executor` if not provided here.

        Returns
        -------
        list[BaseTool]
            One :class:`SkillTool` per registered skill.
        """
        executor = tool_executor or self._tool_executor
        tools: List[BaseTool] = []

        for manifest in self._skills.values():
            real_executor = executor or _NullToolExecutor()
            skill_exec = SkillExecutor(real_executor, bus=self._bus)

            # Wire sub-skill resolver so nested skill_name steps can delegate back
            skill_exec.set_skill_resolver(self._make_resolver())

            skill_tool = SkillTool(manifest, skill_exec, skill_manager=self)
            tools.append(skill_tool)

        return tools

    def _make_resolver(self):
        """Return a resolver callback that delegates sub-skill execution."""

        def _resolver(name: str, context: Dict[str, Any]) -> SkillResult:
            manifest = self.resolve(name)
            skill_exec = SkillExecutor(
                self._tool_executor or _NullToolExecutor(),
                bus=self._bus,
            )
            skill_exec.set_skill_resolver(_resolver)
            return skill_exec.run(manifest, initial_context=context)

        return _resolver

    # ------------------------------------------------------------------
    # Catalog
    # ------------------------------------------------------------------

    def get_catalog_xml(self) -> str:
        """Generate an ``<available_skills>`` XML catalog.

        Skills with ``disable_model_invocation=True`` are excluded so that
        internal or automation-only skills are not surfaced to the model.
        """
        lines: List[str] = ["<available_skills>"]

        for manifest in self._skills.values():
            if manifest.disable_model_invocation:
                continue
            escaped_name = html.escape(manifest.name)
            escaped_desc = html.escape(manifest.description or manifest.name)
            lines.append(
                f"  <skill name={escaped_name!r} description={escaped_desc!r} />"
            )

        lines.append("</available_skills>")
        return "\n".join(lines)

    def get_few_shot_examples(self) -> List[str]:
        """Return formatted few-shot example strings ready for system prompt.

        Pulls from ``manifest.metadata.grandpa.few_shot`` for every
        registered skill.  Returns one formatted string per example.
        """
        examples: List[str] = []
        for name, manifest in self._skills.items():
            oj = (
                manifest.metadata.get("grandpa") or manifest.metadata.get("Grandpa", {})
                if manifest.metadata
                else {}
            )
            few_shot = oj.get("few_shot", []) or []
            for ex in few_shot:
                if not isinstance(ex, dict):
                    continue
                inp = str(ex.get("input", ""))
                out = str(ex.get("output", ""))
                if inp or out:
                    examples.append(f"### {name}\nInput: {inp}\nOutput: {out}")
        return examples

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def execute(
        self,
        name: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> SkillResult:
        """Resolve and execute a skill by name.

        Parameters
        ----------
        name:
            Skill name to execute.
        context:
            Initial context dict passed to the executor.

        Returns
        -------
        SkillResult
        """
        manifest = self.resolve(name)
        executor = SkillExecutor(
            self._tool_executor or _NullToolExecutor(),
            bus=self._bus,
        )
        executor.set_skill_resolver(self._make_resolver())
        return executor.run(manifest, initial_context=context)

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def set_tool_executor(self, tool_executor: ToolExecutor) -> None:
        """Attach a :class:`ToolExecutor` for running tool steps in skill pipelines."""
        self._tool_executor = tool_executor

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def find_installed_paths(
        self, name: str, *, roots: Optional[List[Path]] = None
    ) -> List[Path]:
        """Return on-disk skill directories matching ``name``.

        A directory matches when it contains ``skill.toml`` or ``SKILL.md``
        and either the directory name equals ``name`` or its parsed
        manifest's ``name`` field equals ``name``.
        """
        if roots is None:
            roots = [Path("~/.grandpa/skills/").expanduser(), Path("./skills")]

        matches: List[Path] = []
        for root in roots:
            if not root.exists():
                continue
            for candidate in root.rglob("*"):
                if not candidate.is_dir():
                    continue
                toml = candidate / "skill.toml"
                md = candidate / "SKILL.md"
                if not (toml.exists() or md.exists()):
                    continue
                if candidate.name == name:
                    matches.append(candidate)
                    continue
                # Fall back to parsed manifest name
                try:
                    from grandpa.skills.loader import load_skill_directory

                    manifest = load_skill_directory(candidate)
                    if manifest is not None and manifest.name == name:
                        matches.append(candidate)
                except Exception:
                    continue
        return matches

    def remove(self, name: str, *, roots: Optional[List[Path]] = None) -> List[Path]:
        """Remove an installed skill by name.

        Returns the list of directories that were removed.  Raises
        :class:`FileNotFoundError` when no matching skill exists on disk.
        """
        import shutil

        paths = self.find_installed_paths(name, roots=roots)
        if not paths:
            raise FileNotFoundError(f"No installed skill named {name!r}")
        for p in paths:
            shutil.rmtree(p)
        # Drop from in-memory catalog
        self._skills.pop(name, None)
        return paths


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


class _NullToolExecutor(ToolExecutor):
    """A no-op ToolExecutor used when no real executor is available.

    Allows SkillTool/SkillExecutor construction to succeed even before a
    real tool executor is wired in; any actual tool call will produce an
    error ToolResult rather than raising.
    """

    def __init__(self) -> None:
        super().__init__(tools=[], bus=None)


__all__ = ["SkillManager"]
