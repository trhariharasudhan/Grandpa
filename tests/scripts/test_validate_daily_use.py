from __future__ import annotations

import argparse
import subprocess

from scripts.validate_daily_use import (
    ValidationStep,
    _docker_daemon_ready,
    _run_step,
    build_steps,
)


def test_build_steps_can_skip_app_launch_and_docker() -> None:
    args = argparse.Namespace(
        skip_app_launch=True,
        skip_frontend=True,
        skip_docker=True,
    )

    steps = build_steps(args)
    names = {step.name for step in steps}

    assert "safe app command parser" in names
    assert "open safe app command" not in names
    assert "docker build" not in names


def test_run_step_checks_expected_text() -> None:
    result = _run_step(
        ValidationStep(
            "sample",
            ["python", "-c", "print('Grandpa ready')"],
            expected_text="ready",
            timeout=30,
        )
    )

    assert result.status == "ok"


def test_run_step_reports_expected_text_mismatch() -> None:
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


def test_docker_daemon_ready_handles_command_failure(monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: "docker")
    monkeypatch.setattr(
        "subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1),
    )

    assert _docker_daemon_ready() is False
