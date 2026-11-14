"""`python -m grandpa` must reach the same CLI as the `grandpa` script."""

import subprocess
import sys

import pytest


@pytest.mark.real_actions(
    reason="spawns `python -m grandpa --version`, which only prints the version"
)
def test_python_m_grandpa_prints_version():
    result = subprocess.run(
        [sys.executable, "-m", "grandpa", "--version"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert "Grandpa, version" in result.stdout
