"""Tests for the chat startup banner."""

from __future__ import annotations

from pathlib import Path

from grandpa.cli import _bg_state
from grandpa.cli._chat_banner import render_startup_banner


def _write_model_marker(home: Path, model_id: str, state: str) -> None:
    marker = _bg_state.model_marker_name(model_id, state)
    (home / ".state" / "models" / marker).write_text("")


def test_banner_empty_when_all_ready(tmp_grandpa_home: Path) -> None:
    (tmp_grandpa_home / ".state" / "extension-built").write_text("")
    _write_model_marker(tmp_grandpa_home, "qwen3.5:9b", "ready")
    s = _bg_state.get_status()
    banner = render_startup_banner(s)
    assert banner == ""


def test_banner_shows_rust_building(tmp_grandpa_home: Path) -> None:
    """Pending rust ext (no marker file) is shown as 'building'."""
    s = _bg_state.get_status()  # all pending
    banner = render_startup_banner(s)
    assert "Rust extension" in banner
    assert "building" in banner.lower()


def test_banner_shows_model_downloading(tmp_grandpa_home: Path) -> None:
    (tmp_grandpa_home / ".state" / "extension-built").write_text("")
    _write_model_marker(tmp_grandpa_home, "qwen3.5:9b", "downloading")
    s = _bg_state.get_status()
    banner = render_startup_banner(s)
    assert "qwen3.5:9b" in banner
    assert "downloading" in banner.lower()


def test_banner_shows_failed_in_dim_warning(tmp_grandpa_home: Path) -> None:
    (tmp_grandpa_home / ".state" / "extension-failed").write_text("error tail")
    s = _bg_state.get_status()
    banner = render_startup_banner(s)
    assert "failed" in banner.lower()
    assert "doctor" in banner.lower()
