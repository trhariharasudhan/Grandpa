"""Tests for ``Grandpa doctor`` optional dependency labels."""

from __future__ import annotations

import json

from click.testing import CliRunner

from grandpa.cli import cli


class TestDoctorOptionalLabels:
    def test_labels_show_description(self) -> None:
        """Doctor output uses unified readiness labels, not raw package names."""
        runner = CliRunner()
        result = runner.invoke(cli, ["doctor", "--json"])
        data = json.loads(result.output)
        names = [c["name"] for c in data]
        assert "REST API server installed" in names
        assert "Desktop automation backend" in names
        assert "Voice frontend support" in names
        assert "Docker daemon reachable" in names
        assert "Optional: torch (for learning)" not in names
        assert "Optional: pynvml (GPU monitoring)" not in names

    def test_optional_items_are_non_blocking_warnings(self) -> None:
        """Optional environment gaps should be warnings, not failures."""
        runner = CliRunner()
        result = runner.invoke(cli, ["doctor", "--json"])
        data = json.loads(result.output)
        optional_checks = [
            c
            for c in data
            if c["name"] in {"Voice frontend support", "Docker daemon reachable"}
        ]
        assert optional_checks
        assert all(c["status"] in {"warn", "ok"} for c in optional_checks)

    def test_engine_labels_use_descriptive_names(self) -> None:
        """Engine readiness checks should be grouped by engine name."""
        runner = CliRunner()
        result = runner.invoke(cli, ["doctor", "--json"])
        data = json.loads(result.output)
        names = [c["name"] for c in data]
        assert "Default model" in names
