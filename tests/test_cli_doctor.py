from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.core


def test_grandpa_doctor_smoke_without_optional_services() -> None:
    """The real doctor CLI should not crash when optional services are absent."""
    env = os.environ.copy()
    env.update(
        {
            "CI": "1",
            "GRANDPA_NO_UPDATE_CHECK": "1",
            "Grandpa_NO_UPDATE_CHECK": "1",
            "PYTHONIOENCODING": "utf-8",
        }
    )

    result = subprocess.run(
        [sys.executable, "-m", "grandpa.cli", "doctor"],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        text=True,
        timeout=90,
    )

    output = f"{result.stdout}\n{result.stderr}"
    assert result.returncode in {0, 1}, output
    assert result.returncode < 2, output
    assert "Grandpa Doctor Dashboard" in output
    assert "Core Runtime" in output
    assert "Final Summary" in output
