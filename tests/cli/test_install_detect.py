"""Tests for install-method detection.

Non-checkout installs deliberately report no upgrade command: the PyPI name
``grandpa`` belongs to an unrelated project, so any pip/uv upgrade command
would install someone else's package. Only a git checkout can self-update.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from grandpa.cli._install_detect import (
    NO_DISTRIBUTION_REASON,
    InstallInfo,
    detect_install,
)


def _patch_pkg_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point ``grandpa.__file__`` at ``tmp_path / grandpa / __init__.py``."""
    pkg_dir = tmp_path / "grandpa"
    pkg_dir.mkdir(parents=True, exist_ok=True)
    init = pkg_dir / "__init__.py"
    init.write_text("__version__ = '0.0.0+test'\n")

    import grandpa

    monkeypatch.setattr(grandpa, "__file__", str(init))
    return init


def test_editable_git_install_detected(tmp_path, monkeypatch):
    # Layout: <tmp>/repo/.git, <tmp>/repo/pyproject.toml,
    #         <tmp>/repo/src/grandpa/__init__.py
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / "pyproject.toml").write_text("[project]\nname='grandpa'\n")
    src = repo / "src"
    _patch_pkg_file(src, monkeypatch)

    info = detect_install()
    assert info.kind == "editable-git"
    assert "git pull" in info.upgrade_command
    assert "uv sync" in info.upgrade_command
    assert info.repo_root == repo


def test_uv_tool_install_detected(tmp_path, monkeypatch):
    fake = tmp_path / "share" / "uv" / "tools" / "grandpa" / "lib" / "python3.12"
    fake.mkdir(parents=True)
    _patch_pkg_file(fake, monkeypatch)

    info = detect_install()
    assert info.kind == "uv-tool"
    # Was ``uv tool upgrade grandpa`` — that installs an unrelated project.
    assert info.upgrade_command == ""
    assert info.can_upgrade is False
    assert info.unsupported_reason == NO_DISTRIBUTION_REASON


def test_pypi_install_detected(tmp_path, monkeypatch):
    fake = tmp_path / "venv" / "lib" / "python3.12" / "site-packages"
    fake.mkdir(parents=True)
    _patch_pkg_file(fake, monkeypatch)

    info = detect_install()
    assert info.kind == "pypi"
    # Was ``pip install --upgrade grandpa`` — that installs an unrelated project.
    assert info.upgrade_command == ""
    assert info.can_upgrade is False
    assert info.unsupported_reason == NO_DISTRIBUTION_REASON


def test_unknown_install_offers_no_upgrade(tmp_path, monkeypatch):
    fake = tmp_path / "somewhere" / "weird"
    fake.mkdir(parents=True)
    _patch_pkg_file(fake, monkeypatch)

    info = detect_install()
    assert info.kind == "unknown"
    assert info.upgrade_command == ""
    assert info.can_upgrade is False


def test_missing_grandpa_file_offers_no_upgrade(monkeypatch):
    """grandpa unimportable / no __file__ — must not guess at an upgrade."""
    with patch("grandpa.cli._install_detect.Path") as mock_path:
        mock_path.side_effect = Exception("boom")
        info = detect_install()
    assert info.kind == "unknown"
    assert info.upgrade_command == ""
    assert info.can_upgrade is False


def test_returns_install_info_dataclass():
    info = detect_install()
    assert isinstance(info, InstallInfo)
    assert info.kind in {"pypi", "uv-tool", "editable-git", "unknown"}
    # A command is only offered when it is verifiably safe to run.
    assert info.can_upgrade == bool(info.upgrade_command)


@pytest.mark.parametrize(
    "layout",
    [
        ("venv", "lib", "python3.12", "site-packages"),
        ("share", "uv", "tools", "grandpa", "lib", "python3.12"),
        ("somewhere", "weird"),
    ],
)
def test_no_install_shape_ever_targets_the_pypi_grandpa_package(
    layout, tmp_path, monkeypatch
):
    """Regression guard for the supply-chain hazard.

    ``grandpa`` on PyPI is a different project. No detected install shape may
    produce a command that installs it.
    """
    fake = tmp_path.joinpath(*layout)
    fake.mkdir(parents=True)
    _patch_pkg_file(fake, monkeypatch)

    command = detect_install().upgrade_command
    assert "pip install" not in command
    assert "uv tool upgrade" not in command
    assert command == ""
