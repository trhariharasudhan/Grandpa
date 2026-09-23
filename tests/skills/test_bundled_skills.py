"""The skills that ship in the package stay loadable, and stay read-only.

Three bugs kept these eighteen manifests invisible, and each hid the next:

1. ``_get_skill_paths()`` never looked in the packaged directory, so
   ``skill list`` said "No skills installed" with eighteen of them on disk;
2. the provenance gate refuses a manifest that does not say who wrote it, and
   none of them declared ``provenance = "bundled"`` -- the value
   ``TRUSTED_PROVENANCE`` exists for; and
3. the CLI built a ``SkillManager`` with no tool executor, so every
   ``skill run`` answered "Unknown tool: think".

Fixing any one alone changes nothing a user can see. These tests pin all three,
plus the two manifest defects that only became visible once the skills ran at
all.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import tomllib

from grandpa.skills.bundled import BUNDLED_DIR, PROVENANCE, bundled_names

MANIFESTS = sorted(BUNDLED_DIR.glob("*.toml"))


def _registered_tools() -> frozenset[str]:
    """Tool names, snapshotted at import.

    conftest's autouse ``_clean_registries`` empties the tool registry before
    every test, and ``load_builtin_tools`` cannot refill it -- it works by
    importing modules, so the ``@ToolRegistry.register`` decorators do not run
    a second time. Collection happens before the fixtures, so this is the one
    point where the real registry is populated.
    """
    from grandpa.core.registry import ToolRegistry
    from grandpa.tools import load_builtin_tools

    load_builtin_tools()
    return frozenset(ToolRegistry.keys())


REGISTERED_TOOLS = _registered_tools()


def _skill(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8")).get("skill", {})


def test_there_are_manifests_to_check() -> None:
    """An empty directory would make every assertion below vacuous."""
    assert len(MANIFESTS) >= 18


@pytest.mark.parametrize("path", MANIFESTS, ids=lambda p: p.stem)
def test_every_bundled_manifest_declares_its_provenance(path: Path) -> None:
    """This is the enforcement, not the convention.

    ``SkillManager.discover()`` will not load a manifest that does not say who
    wrote it. A bundled skill added without this line does not load, and
    nothing else would tell you -- so it fails here instead.
    """
    assert _skill(path).get("provenance") == PROVENANCE, (
        f'{path.name} must declare provenance = "{PROVENANCE}" in its [skill] '
        f"table, or SkillManager.discover() will refuse to load it."
    )


@pytest.mark.parametrize("path", MANIFESTS, ids=lambda p: p.stem)
def test_every_step_names_a_tool_that_exists(path: Path) -> None:
    """``translate-doc`` named ``llm_call``, which has never existed.

    A step naming a missing tool fails at run time with "Unknown tool", which
    nobody saw while the skills were unreachable.
    """
    missing = [
        step.get("tool_name")
        for step in _skill(path).get("steps", [])
        if step.get("tool_name") and step["tool_name"] not in REGISTERED_TOOLS
    ]

    assert missing == [], f"{path.name} names tools that do not exist: {missing}"


@pytest.mark.parametrize("path", MANIFESTS, ids=lambda p: p.stem)
def test_every_template_is_valid_json_once_filled(path: Path) -> None:
    """``pdf-summarize`` sent ``path`` to a tool whose parameter is ``file_path``.

    Rendering with a Windows-shaped value also catches the class of bug that
    made every file-taking skill fail: a raw backslash is an invalid JSON
    escape.
    """
    from grandpa.skills.executor import SkillExecutor

    for step in _skill(path).get("steps", []):
        template = step.get("arguments_template", "{}")
        keys = re.findall(r"\{(\w+)\}", template)
        context = {key: r"C:\Users\someone\a file.txt" for key in keys}
        rendered = SkillExecutor._render_template(template, context)

        json.loads(rendered)  # raises if the fill produced invalid JSON


def test_discover_loads_all_of_them() -> None:
    """The three bugs together, checked as one property."""
    from grandpa.skills.manager import SkillManager

    manager = SkillManager(None)
    manager.discover(paths=[BUNDLED_DIR])

    assert manager.skipped == [], f"refused: {manager.skipped}"
    assert len(manager.skill_names()) == len(MANIFESTS)


def test_the_cli_search_path_includes_them() -> None:
    from grandpa.cli.skill_cmd import _get_skill_paths

    assert BUNDLED_DIR in _get_skill_paths()


def test_the_cli_manager_can_actually_run_a_tool() -> None:
    """Without an executor every run answered "Unknown tool: think"."""
    from grandpa.cli.skill_cmd import _get_manager

    manager = _get_manager()

    assert manager._tool_executor is not None


def test_a_bundled_skill_cannot_be_removed() -> None:
    from grandpa.skills.manager import SkillManager

    name = sorted(bundled_names())[0]
    manager = SkillManager(None)

    with pytest.raises(PermissionError, match="ships with Grandpa"):
        manager.remove(name, roots=[BUNDLED_DIR])

    assert (BUNDLED_DIR / f"{name}.toml").exists()


def test_skill_manage_cannot_overwrite_or_delete_one(tmp_path: Path) -> None:
    """The model-facing tool is refused by name, not by luck of the directory."""
    from grandpa.tools.skill_manage import SkillManageTool

    name = sorted(bundled_names())[0]
    tool = SkillManageTool(skills_dir=tmp_path)

    created = tool.execute(action="create", name=name, steps=[{"tool_name": "think"}])
    deleted = tool.execute(action="delete", name=name)

    assert created.success is False
    assert deleted.success is False
    assert "ships with Grandpa" in created.content
    assert not (tmp_path / f"{name}.toml").exists()


def test_a_user_skill_of_the_same_name_shadows_the_bundled_one(tmp_path: Path) -> None:
    """How a user replaces something they cannot edit."""
    from grandpa.skills.manager import SkillManager

    name = sorted(bundled_names())[0]
    (tmp_path / f"{name}.toml").write_text(
        f'[skill]\nname = "{name}"\ndescription = "mine"\nprovenance = "user"\n',
        encoding="utf-8",
    )

    manager = SkillManager(None)
    manager.discover(paths=[tmp_path, BUNDLED_DIR])

    assert manager.resolve(name).description == "mine"
