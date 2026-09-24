from __future__ import annotations

import argparse

import pytest
from scripts.validate_daily_use import (
    ValidationStep,
    _run_step,
    build_steps,
)

from scripts import validate_daily_use


def test_build_steps_can_skip_app_launch() -> None:
    args = argparse.Namespace(
        skip_app_launch=True,
    )

    steps = build_steps(args)
    names = {step.name for step in steps}

    assert "safe app command parser" in names
    assert "open safe app command" not in names


@pytest.mark.real_actions(
    reason="runs a real `python -c` through subprocess.Popen, which is the thing "
    "under test; VALIDATION_HOME is redirected to tmp_path so the step's own "
    "GRANDPA_HOME is not the repository's"
)
def test_run_step_checks_expected_text(monkeypatch, tmp_path) -> None:
    # _run_step mkdirs VALIDATION_HOME, which the script defines as
    # <repo>/runtime/daily-use-home. That is a reasonable place for a script a
    # person runs by hand, and the wrong place for a test.
    monkeypatch.setattr(validate_daily_use, "VALIDATION_HOME", tmp_path / "home")
    result = _run_step(
        ValidationStep(
            "sample",
            ["python", "-c", "print('Grandpa ready')"],
            expected_text="ready",
            timeout=30,
        )
    )

    assert result.status == "ok"


@pytest.mark.real_actions(
    reason="runs a real `python -c` through subprocess.Popen to check a mismatch "
    "is reported; VALIDATION_HOME is redirected to tmp_path so nothing is written "
    "into the repository"
)
def test_run_step_reports_expected_text_mismatch(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(validate_daily_use, "VALIDATION_HOME", tmp_path / "home")
    result = _run_step(
        ValidationStep(
            "sample",
            ["python", "-c", "print('Grandpa ready')"],
            expected_text="blocked",
            timeout=30,
        )
    )

    assert result.status == "fail"
    assert "expected" in result.detail
