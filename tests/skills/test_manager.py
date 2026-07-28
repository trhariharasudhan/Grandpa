"""Tests for SkillManager — discovery, catalog, tools, and resolve."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from grandpa.core.events import EventBus
from grandpa.core.types import ToolResult
from grandpa.skills.manager import SkillManager
from grandpa.tools._stubs import BaseTool, ToolExecutor, ToolSpec  # noqa: F401

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_toml_skill(directory: Path, name: str, description: str = "") -> None:
    skill_dir = directory / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "skill.toml").write_text(
        textwrap.dedent(f"""\
            [skill]
            name = "{name}"
            description = "{description or name}"
            tags = ["test"]

            [[skill.steps]]
            tool_name = "echo"
            arguments_template = '{{"text": "{{input}}"}}'
            output_key = "result"
        """)
    )


class EchoTool(BaseTool):
    tool_id = "echo"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name="echo", description="Echo input")

    def execute(self, **params) -> ToolResult:
        return ToolResult(
            tool_name="echo", content=params.get("text", ""), success=True
        )


# ---------------------------------------------------------------------------
# TestSkillManagerDiscovery
# ---------------------------------------------------------------------------


class TestSkillManagerDiscovery:
    def test_discover_single_dir(self, tmp_path: Path) -> None:
        """discover() loads skills from a single directory."""
        _write_toml_skill(tmp_path, "alpha")
        _write_toml_skill(tmp_path, "beta")

        mgr = SkillManager(bus=EventBus())
        mgr.discover(paths=[tmp_path])

        names = mgr.skill_names()
        assert "alpha" in names
        assert "beta" in names

    def test_discover_precedence_workspace_over_user(self, tmp_path: Path) -> None:
        """First path (workspace) wins when the same name appears in multiple dirs."""
        workspace = tmp_path / "workspace"
        user = tmp_path / "user"
        workspace.mkdir()
        user.mkdir()

        # Both dirs have a skill named "shared"
        _write_toml_skill(workspace, "shared", description="workspace version")
        _write_toml_skill(user, "shared", description="user version")

        mgr = SkillManager(bus=EventBus())
        # workspace is listed first → highest precedence
        mgr.discover(paths=[workspace, user])

        manifest = mgr.resolve("shared")
        assert manifest.description == "workspace version"

    def test_discover_empty_dir(self, tmp_path: Path) -> None:
        """discover() does not raise on an empty directory."""
        mgr = SkillManager(bus=EventBus())
        mgr.discover(paths=[tmp_path])
        assert mgr.skill_names() == []

    def test_discover_nonexistent_dir(self, tmp_path: Path) -> None:
        """discover() silently skips paths that do not exist."""
        mgr = SkillManager(bus=EventBus())
        mgr.discover(paths=[tmp_path / "does_not_exist"])
        assert mgr.skill_names() == []

    def test_discover_multiple_dirs_accumulates(self, tmp_path: Path) -> None:
        """Skills from all directories are accumulated (modulo precedence)."""
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir()
        dir_b.mkdir()

        _write_toml_skill(dir_a, "skill_a")
        _write_toml_skill(dir_b, "skill_b")

        mgr = SkillManager(bus=EventBus())
        mgr.discover(paths=[dir_a, dir_b])

        names = mgr.skill_names()
        assert "skill_a" in names
        assert "skill_b" in names


# ---------------------------------------------------------------------------
# TestSkillManagerCatalog
# ---------------------------------------------------------------------------


class TestSkillManagerCatalog:
    def test_catalog_xml_contains_skill_names(self, tmp_path: Path) -> None:
        """get_catalog_xml() includes discovered skill names."""
        _write_toml_skill(tmp_path, "greet", description="Greet the user")

        mgr = SkillManager(bus=EventBus())
        mgr.discover(paths=[tmp_path])

        xml = mgr.get_catalog_xml()
        assert "greet" in xml
        assert "<available_skills>" in xml

    def test_catalog_xml_empty_when_no_skills(self) -> None:
        """get_catalog_xml() returns a well-formed empty block when no skills loaded."""
        mgr = SkillManager(bus=EventBus())
        xml = mgr.get_catalog_xml()
        assert "<available_skills>" in xml
        assert "</available_skills>" in xml

    def test_catalog_excludes_model_disabled_skills(self, tmp_path: Path) -> None:
        """Skills with disable_model_invocation=true are excluded from the catalog."""
        skill_dir = tmp_path / "hidden"
        skill_dir.mkdir()
        (skill_dir / "skill.toml").write_text(
            textwrap.dedent("""\
                [skill]
                name = "hidden"
                description = "Hidden skill"
                disable_model_invocation = true

                [[skill.steps]]
                tool_name = "echo"
                output_key = "x"
            """)
        )
        mgr = SkillManager(bus=EventBus())
        mgr.discover(paths=[tmp_path])
        xml = mgr.get_catalog_xml()
        assert "hidden" not in xml

    def test_catalog_escapes_xml_special_chars(self, tmp_path: Path) -> None:
        """Descriptions with XML-special chars are escaped in the catalog."""
        skill_dir = tmp_path / "special"
        skill_dir.mkdir()
        (skill_dir / "skill.toml").write_text(
            textwrap.dedent("""\
                [skill]
                name = "special"
                description = "A skill with <tags> & 'quotes'"
                tags = ["test"]

                [[skill.steps]]
                tool_name = "echo"
                output_key = "r"
            """)
        )
        mgr = SkillManager(bus=EventBus())
        mgr.discover(paths=[tmp_path])
        xml = mgr.get_catalog_xml()
        # Raw < must not appear unescaped inside the XML body
        assert "<tags>" not in xml
        assert "&lt;" in xml or "special" in xml  # description is escaped or safe

    def test_catalog_includes_visible_but_not_hidden(self, tmp_path: Path) -> None:
        """Catalog includes user_invocable skills and excludes model-disabled ones."""
        _write_toml_skill(tmp_path, "visible")
        skill_dir = tmp_path / "invisible"
        skill_dir.mkdir()
        (skill_dir / "skill.toml").write_text(
            textwrap.dedent("""\
                [skill]
                name = "invisible"
                description = "Not for models"
                disable_model_invocation = true

                [[skill.steps]]
                tool_name = "echo"
                output_key = "r"
            """)
        )
        mgr = SkillManager(bus=EventBus())
        mgr.discover(paths=[tmp_path])
        xml = mgr.get_catalog_xml()
        assert "visible" in xml
        assert "invisible" not in xml


# ---------------------------------------------------------------------------
# TestSkillManagerTools
# ---------------------------------------------------------------------------


class TestSkillManagerTools:
    def test_get_skill_tools_returns_base_tool_instances(self, tmp_path: Path) -> None:
        """get_skill_tools() returns a list of BaseTool instances."""
        _write_toml_skill(tmp_path, "tool_skill")

        tool_executor = ToolExecutor([EchoTool()])
        mgr = SkillManager(bus=EventBus())
        mgr.discover(paths=[tmp_path])
        mgr.set_tool_executor(tool_executor)

        tools = mgr.get_skill_tools()
        assert len(tools) == 1
        assert isinstance(tools[0], BaseTool)

    def test_get_skill_tools_accepts_tool_executor_kwarg(self, tmp_path: Path) -> None:
        """get_skill_tools() accepts an optional tool_executor keyword argument."""
        _write_toml_skill(tmp_path, "kwarg_skill")

        tool_executor = ToolExecutor([EchoTool()])
        mgr = SkillManager(bus=EventBus())
        mgr.discover(paths=[tmp_path])

        tools = mgr.get_skill_tools(tool_executor=tool_executor)
        assert len(tools) == 1
        assert isinstance(tools[0], BaseTool)

    def test_get_skill_tools_empty_when_no_skills(self) -> None:
        """get_skill_tools() returns an empty list when no skills are loaded."""
        mgr = SkillManager(bus=EventBus())
        tools = mgr.get_skill_tools()
        assert tools == []

    def test_get_skill_tools_names_prefixed(self, tmp_path: Path) -> None:
        """Each SkillTool has a name prefixed with 'skill_'."""
        _write_toml_skill(tmp_path, "my_skill")

        mgr = SkillManager(bus=EventBus())
        mgr.discover(paths=[tmp_path])

        tools = mgr.get_skill_tools()
        assert any(t.spec.name == "skill_my_skill" for t in tools)


# ---------------------------------------------------------------------------
# TestSkillManagerResolve
# ---------------------------------------------------------------------------


class TestSkillManagerResolve:
    def test_resolve_existing_skill(self, tmp_path: Path) -> None:
        """resolve() returns the SkillManifest for a known skill name."""
        _write_toml_skill(tmp_path, "resolve_me")

        mgr = SkillManager(bus=EventBus())
        mgr.discover(paths=[tmp_path])

        manifest = mgr.resolve("resolve_me")
        assert manifest.name == "resolve_me"

    def test_resolve_missing_raises_key_error(self) -> None:
        """resolve() raises KeyError for an unknown skill name."""
        mgr = SkillManager(bus=EventBus())
        with pytest.raises(KeyError):
            mgr.resolve("nonexistent_skill")

    def test_resolve_after_multiple_discovers(self, tmp_path: Path) -> None:
        """resolve() works correctly after calling discover() multiple times."""
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir()
        dir_b.mkdir()

        _write_toml_skill(dir_a, "skill_one")
        _write_toml_skill(dir_b, "skill_two")

        mgr = SkillManager(bus=EventBus())
        mgr.discover(paths=[dir_a])
        mgr.discover(paths=[dir_b])

        assert mgr.resolve("skill_one").name == "skill_one"
        assert mgr.resolve("skill_two").name == "skill_two"


class TestSkillManagerSourcedLayout:
    def test_discovers_skills_under_source_subdirs(self, tmp_path: Path):
        """SkillManager.discover() finds skills in <source>/<name>/ layout."""
        from grandpa.core.events import EventBus
        from grandpa.skills.manager import SkillManager

        # Build workspace/<name>/ and user-local/<name>/ subdirs
        for source, name in [("workspace", "apple-notes"), ("user-local", "etherscan")]:
            d = tmp_path / source / name
            d.mkdir(parents=True)
            (d / "SKILL.md").write_text(
                f"---\nname: {name}\ndescription: from {source}\n---\nBody"
            )

        mgr = SkillManager(bus=EventBus())
        mgr.discover(paths=[tmp_path])
        names = mgr.skill_names()
        assert "apple-notes" in names
        assert "etherscan" in names

    def test_flat_and_sourced_layout_coexist(self, tmp_path: Path):
        """Both flat ./<name>/ and ./<source>/<name>/ are discovered."""
        from grandpa.core.events import EventBus
        from grandpa.skills.manager import SkillManager

        # Flat layout
        flat = tmp_path / "my-flat-skill"
        flat.mkdir()
        (flat / "SKILL.md").write_text(
            "---\nname: my-flat-skill\ndescription: flat\n---\n"
        )

        # Sourced layout
        sourced = tmp_path / "workspace" / "my-sourced-skill"
        sourced.mkdir(parents=True)
        (sourced / "SKILL.md").write_text(
            "---\nname: my-sourced-skill\ndescription: sourced\n---\n"
        )

        mgr = SkillManager(bus=EventBus())
        mgr.discover(paths=[tmp_path])
        names = mgr.skill_names()
        assert "my-flat-skill" in names
        assert "my-sourced-skill" in names


class TestSkillManagerRemove:
    def test_find_installed_paths_returns_empty_when_missing(
        self, tmp_path: Path
    ) -> None:
        mgr = SkillManager(bus=EventBus())
        assert mgr.find_installed_paths("ghost", roots=[tmp_path]) == []

    def test_find_installed_paths_matches_directory_name(self, tmp_path: Path) -> None:
        _write_toml_skill(tmp_path, "alpha")
        mgr = SkillManager(bus=EventBus())
        paths = mgr.find_installed_paths("alpha", roots=[tmp_path])
        assert paths == [tmp_path / "alpha"]

    def test_find_installed_paths_matches_manifest_name(self, tmp_path: Path) -> None:
        # Directory name differs from manifest name (mimics imported layout)
        skill_dir = tmp_path / "some-other-dirname"
        skill_dir.mkdir()
        (skill_dir / "skill.toml").write_text(
            textwrap.dedent("""\
                [skill]
                name = "real-name"
                description = "renamed"

                [[skill.steps]]
                tool_name = "echo"
                output_key = "x"
            """)
        )
        mgr = SkillManager(bus=EventBus())
        paths = mgr.find_installed_paths("real-name", roots=[tmp_path])
        assert paths == [skill_dir]

    def test_remove_deletes_directory_and_drops_from_catalog(
        self, tmp_path: Path
    ) -> None:
        _write_toml_skill(tmp_path, "doomed")
        mgr = SkillManager(bus=EventBus())
        mgr.discover(paths=[tmp_path])
        assert "doomed" in mgr.skill_names()

        removed = mgr.remove("doomed", roots=[tmp_path])
        assert removed == [tmp_path / "doomed"]
        assert not (tmp_path / "doomed").exists()
        assert "doomed" not in mgr.skill_names()

    def test_remove_raises_when_skill_missing(self, tmp_path: Path) -> None:
        mgr = SkillManager(bus=EventBus())
        with pytest.raises(FileNotFoundError):
            mgr.remove("ghost", roots=[tmp_path])
