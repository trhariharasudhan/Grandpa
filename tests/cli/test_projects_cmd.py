"""Project Manager CLI tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from grandpa.cli import cli
from grandpa.projects.models import Project
from grandpa.projects.registry import ProjectRegistry
from grandpa.projects.service import ProjectService


def _service(tmp_path: Path) -> ProjectService:
    root = tmp_path / "Example"
    root.mkdir()
    registry = ProjectRegistry(tmp_path / "projects.json")
    registry.save([Project("example", "Example", str(root), project_type="python")])
    return ProjectService(registry=registry)


def test_projects_list_and_alias(tmp_path: Path) -> None:
    service = _service(tmp_path)
    with patch("grandpa.cli.projects_cmd._service", return_value=service):
        result = CliRunner().invoke(cli, ["projects", "list"])
        alias = CliRunner().invoke(cli, ["project", "list"])
    assert result.exit_code == 0
    assert "Example [example]" in result.output
    assert alias.exit_code == 0


def test_projects_show(tmp_path: Path) -> None:
    service = _service(tmp_path)
    with patch("grandpa.cli.projects_cmd._service", return_value=service):
        result = CliRunner().invoke(cli, ["projects", "show", "example"])
    assert result.exit_code == 0
    assert "Project: Example" in result.output
    assert "Type: python" in result.output


def test_projects_unregister_requires_confirmation(tmp_path: Path) -> None:
    service = _service(tmp_path)
    with patch("grandpa.cli.projects_cmd._service", return_value=service):
        result = CliRunner().invoke(
            cli, ["projects", "unregister", "example"], input="n\n"
        )
    assert result.exit_code != 0
    assert service.registry.list()
