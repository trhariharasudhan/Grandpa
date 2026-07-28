"""Regression tests for lightweight top-level package imports."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import tomllib


def test_top_level_import_does_not_eagerly_load_sdk() -> None:
    code = "import sys, grandpa; print('grandpa.sdk' in sys.modules)"
    result = subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == "False"


def test_public_sdk_exports_still_resolve_lazily() -> None:
    code = (
        "import sys, grandpa; "
        "assert 'grandpa.sdk' not in sys.modules; "
        "assert grandpa.Grandpa.__name__ == 'Grandpa'; "
        "assert 'grandpa.sdk' in sys.modules"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_core_dependencies_do_not_install_deprecated_pynvml() -> None:
    project = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = project["project"]["dependencies"]

    assert not any(item.casefold().startswith("pynvml") for item in dependencies)
    assert not any(item.casefold().startswith("nvidia-ml-py") for item in dependencies)
