"""Tests for the doctor 'Background tasks' section."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from grandpa.cli import _bg_state
from grandpa.cli.doctor_cmd import _check_background_tasks, doctor


def _write_model_marker(home: Path, model_id: str, state: str) -> None:
    marker = _bg_state.model_marker_name(model_id, state)
    (home / ".state" / "models" / marker).write_text("")


def test_doctor_shows_bg_section_when_state_present(tmp_grandpa_home: Path) -> None:
    (tmp_grandpa_home / ".state" / "extension-built").write_text("")
    _write_model_marker(tmp_grandpa_home, "qwen3.5:9b", "ready")
    checks = _check_background_tasks()
    assert any(check.name == "Rust extension background task" for check in checks)
    assert any(check.name == "Background model: qwen3.5:9b" for check in checks)
    assert any(check.status == "ok" and check.message == "Ready" for check in checks)

    runner = CliRunner()
    result = runner.invoke(doctor, [], catch_exceptions=False)
    assert "Grandpa Doctor Dashboard" in result.output
    assert result.exit_code == 0


def test_doctor_exit_code_when_bg_failed(tmp_grandpa_home: Path) -> None:
    (tmp_grandpa_home / ".state" / "extension-failed").write_text("oom")
    runner = CliRunner()
    result = runner.invoke(doctor, [], catch_exceptions=False)
    # Doctor should exit non-zero when any bg task is failed.
    assert result.exit_code != 0
    assert "failed" in result.output.lower()


def test_doctor_no_bg_section_when_state_dir_empty(tmp_grandpa_home: Path) -> None:
    """Empty .state/ reports no tracked model downloads in the unified dashboard."""
    checks = _check_background_tasks()
    model_check = next(check for check in checks if check.name == "Background model downloads")
    assert model_check.status == "ok"
    assert model_check.details == "No model downloads are currently tracked."

    runner = CliRunner()
    result = runner.invoke(doctor, [], catch_exceptions=False)
    assert "Grandpa Doctor Dashboard" in result.output
