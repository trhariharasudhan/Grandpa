"""Tests for local-only ``grandpa skill`` commands."""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from grandpa.cli import cli


def _write_skill(root: Path, name: str, description: str = "A test skill") -> Path:
    skill_dir = root / name
    skill_dir.mkdir()
    (skill_dir / "skill.toml").write_text(
        textwrap.dedent(
            f"""\
            [skill]
            name = "{name}"
            description = "{description}"

            [[skill.steps]]
            tool_name = "echo"
            output_key = "result"
            """
        ),
        encoding="utf-8",
    )
    return skill_dir


class TestSkillCmd:
    def test_group_exposes_local_commands_only(self) -> None:
        result = CliRunner().invoke(cli, ["skill", "--help"])

        assert result.exit_code == 0
        assert "list" in result.output
        assert "info" in result.output
        assert "run" in result.output
        assert "remove" in result.output
        assert "\n  install " not in result.output
        assert "sync" not in result.output
        assert "discover" not in result.output

    def test_command_help(self) -> None:
        runner = CliRunner()
        for command in ("list", "info", "run", "remove"):
            result = runner.invoke(cli, ["skill", command, "--help"])
            assert result.exit_code == 0, result.output

    def test_list_shows_discovered_local_skill(self, tmp_path: Path) -> None:
        _write_skill(tmp_path, "my_skill")
        with patch("grandpa.cli.skill_cmd._get_skill_paths", return_value=[tmp_path]):
            result = CliRunner().invoke(cli, ["skill", "list"])

        assert result.exit_code == 0
        assert "my_skill" in result.output

    def test_info_shows_local_skill_details(self, tmp_path: Path) -> None:
        _write_skill(tmp_path, "info_skill", "Detailed skill")
        with patch("grandpa.cli.skill_cmd._get_skill_paths", return_value=[tmp_path]):
            result = CliRunner().invoke(cli, ["skill", "info", "info_skill"])

        assert result.exit_code == 0
        assert "info_skill" in result.output
        assert "Detailed skill" in result.output

    def test_remove_missing_skill(self, tmp_path: Path) -> None:
        with patch("grandpa.cli.skill_cmd._get_skill_paths", return_value=[tmp_path]):
            result = CliRunner().invoke(cli, ["skill", "remove", "ghost", "--yes"])

        assert result.exit_code != 0
        assert "no installed skill" in result.output.lower()

    def test_remove_deletes_local_directory(self, tmp_path: Path) -> None:
        skill_dir = _write_skill(tmp_path, "to_remove")
        with patch("grandpa.cli.skill_cmd._get_skill_paths", return_value=[tmp_path]):
            result = CliRunner().invoke(
                cli,
                ["skill", "remove", "to_remove", "--yes"],
            )

        assert result.exit_code == 0, result.output
        assert "Removed" in result.output
        assert not skill_dir.exists()
