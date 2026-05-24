"""Smoke test that the tmp_grandpa_home fixture works."""

from __future__ import annotations

from pathlib import Path

from grandpa.core import config as config_mod


def test_fixture_redirects_default_config_dir(tmp_grandpa_home: Path) -> None:
    assert config_mod.DEFAULT_CONFIG_DIR == tmp_grandpa_home
    assert tmp_grandpa_home.exists()
    assert (tmp_grandpa_home / ".state").exists()
    assert (tmp_grandpa_home / ".state" / "models").exists()


def test_fixture_redirects_config_path(tmp_grandpa_home: Path) -> None:
    assert config_mod.DEFAULT_CONFIG_PATH == tmp_grandpa_home / "config.toml"
