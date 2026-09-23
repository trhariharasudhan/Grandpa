"""Leftovers closed out after the e2e suite found them.

- telemetry clear crashed with "no such table" on a home with no telemetry yet
- file search scanned a hardcoded D:\\Grandpa
- the ddgs whitespace shim failed silently if ddgs changed underneath it
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from grandpa.files.paths import configured_workspace, safe_roots, user_folder_aliases
from grandpa.telemetry.aggregator import TelemetryAggregator


def test_telemetry_works_on_a_home_that_never_recorded_anything(tmp_path) -> None:
    aggregator = TelemetryAggregator(tmp_path / "telemetry.db")

    try:
        assert aggregator.record_count() == 0
        assert aggregator.clear() == 0
    finally:
        aggregator.close()

    tables = sqlite3.connect(tmp_path / "telemetry.db").execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )
    assert ("telemetry",) in tables.fetchall()


def test_file_search_roots_have_no_hardcoded_project_path(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(
        "grandpa.files.paths.configured_workspace", lambda: None, raising=False
    )
    # safe_roots() always includes the working directory, so this only tested
    # what it claims to when the suite is not run from D:\Grandpa itself.
    # Running it there -- which is what happens in the main checkout -- put
    # d:/grandpa in the roots legitimately, as the cwd, and failed.
    monkeypatch.chdir(tmp_path)

    # The working directory is always searched; the hardcoded roots are not.
    roots = {
        str(path).replace("\\", "/").rstrip("/").casefold() for path in safe_roots()
    }

    assert "d:/grandpa" not in roots, roots
    assert "d:/projects" not in roots, roots


def _config_with_workspace(value: str):
    tools = type("Tools", (), {"workspace": value})()
    return lambda: type("Config", (), {"tools": tools})()


def test_configured_workspace_is_searched_when_it_is_set(monkeypatch, tmp_path) -> None:
    workspace = tmp_path / "work"
    workspace.mkdir()

    monkeypatch.setattr(
        "grandpa.core.config.load_config", _config_with_workspace(str(workspace))
    )

    assert configured_workspace() == workspace
    assert workspace in safe_roots()
    assert user_folder_aliases()["workspace"] == workspace


def test_missing_workspace_setting_falls_back_to_the_working_directory(
    monkeypatch,
) -> None:
    monkeypatch.setattr("grandpa.core.config.load_config", _config_with_workspace(""))

    assert configured_workspace() is None
    assert user_folder_aliases()["workspace"] == Path.cwd()


def test_ddgs_shim_warns_loudly_when_ddgs_changes(monkeypatch) -> None:
    base = pytest.importorskip("ddgs.base")
    import grandpa.web_search.duckduckgo as duckduckgo

    def _someone_elses_extract(self, html_text):  # pragma: no cover - never called
        return []

    monkeypatch.setattr(
        base.BaseSearchEngine, "extract_results", _someone_elses_extract
    )
    monkeypatch.setattr(duckduckgo, "_ddgs_whitespace_fix_applied", False)

    with pytest.warns(RuntimeWarning, match="glued"):
        duckduckgo._keep_whitespace_between_tags()

    # It gave up rather than patching a method it did not recognise.
    assert base.BaseSearchEngine.extract_results is _someone_elses_extract
