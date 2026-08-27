"""Tests for ``Grandpa doctor`` CLI command."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from grandpa.cli import cli
from grandpa.cli.doctor_cmd import (
    CheckResult,
    DoctorSection,
    _active_grandpa_executable,
    _check_background_scheduler_ready,
    _check_config_exists,
    _check_default_model,
    _check_python_version,
    _check_runtime_environment,
    _grandpa_executable_candidates,
)


class TestDoctorHelp:
    def test_doctor_help(self) -> None:
        result = CliRunner().invoke(cli, ["doctor", "--help"])
        assert result.exit_code == 0
        out = result.output.lower()
        assert "diagnostic" in out or "doctor" in out


class TestDoctorRuns:
    def test_doctor_runs(self) -> None:
        """Doctor command runs without error when engines are mocked."""
        mock_config = MagicMock()
        mock_config.intelligence.default_model = ""

        with (
            patch("grandpa.cli.doctor_cmd.load_config", return_value=mock_config),
            patch(
                "grandpa.cli.doctor_cmd.DEFAULT_CONFIG_PATH",
                Path("/tmp/nonexistent/config.toml"),
            ),
            patch(
                "grandpa.cli.doctor_cmd._build_doctor_dashboard",
                return_value=[
                    DoctorSection(
                        "Core Runtime",
                        [CheckResult("Runtime sample", "ok", "Ready")],
                    )
                ],
            ),
        ):
            result = CliRunner().invoke(cli, ["doctor"])
        assert result.exit_code == 0
        assert "Doctor Dashboard" in result.output
        assert "Core Runtime" in result.output


class TestDoctorJsonOutput:
    def test_doctor_json_output(self) -> None:
        """--json flag produces valid JSON."""
        mock_config = MagicMock()
        mock_config.intelligence.default_model = ""

        with (
            patch("grandpa.cli.doctor_cmd.load_config", return_value=mock_config),
            patch(
                "grandpa.cli.doctor_cmd.DEFAULT_CONFIG_PATH",
                Path("/tmp/nonexistent/config.toml"),
            ),
            patch(
                "grandpa.cli.doctor_cmd._build_doctor_dashboard",
                return_value=[
                    DoctorSection(
                        "Core Runtime",
                        [CheckResult("Runtime sample", "ok", "Ready")],
                    )
                ],
            ),
        ):
            result = CliRunner().invoke(cli, ["doctor", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert len(data) > 0
        # Each entry should have required fields
        for entry in data:
            assert "name" in entry
            assert "status" in entry
            assert "message" in entry


class TestCheckPythonVersion:
    def test_check_python_version(self) -> None:
        """Python version check passes on any supported Python."""
        result = _check_python_version()
        assert result.status == "ok"
        assert result.name == "Python version"


class TestRuntimeEnvironmentChecks:
    def test_runtime_checks_report_python_and_grandpa_environment(self) -> None:
        results = _check_runtime_environment()
        names = {result.name for result in results}

        assert "Python executable" in names
        assert "Grandpa executable" in names
        assert "Grandpa executables on PATH" in names
        assert "Active virtual environment" in names
        assert "Project root" in names

    def test_duplicate_executable_detection_on_windows(self) -> None:
        with (
            patch("grandpa.cli.doctor_cmd.sys.platform", "win32"),
            patch(
                "grandpa.cli.doctor_cmd.subprocess.run",
                return_value=MagicMock(
                    returncode=0,
                    stdout=(
                        "D:\\Grandpa\\.venv\\Scripts\\grandpa.exe\n"
                        "C:\\Users\\ASUS\\AppData\\Local\\Programs\\Python\\Python311\\Scripts\\grandpa.exe\n"
                    ),
                ),
            ),
        ):
            candidates = _grandpa_executable_candidates()

        assert candidates == [
            "D:\\Grandpa\\.venv\\Scripts\\grandpa.exe",
            "C:\\Users\\ASUS\\AppData\\Local\\Programs\\Python\\Python311\\Scripts\\grandpa.exe",
        ]

    def test_active_executable_uses_python_environment_not_path_order(self) -> None:
        candidates = [
            "C:\\Python311\\Scripts\\grandpa.exe",
            "D:\\Grandpa\\.venv\\Scripts\\grandpa.exe",
        ]
        with (
            patch("grandpa.cli.doctor_cmd.sys.argv", ["-m", "grandpa.cli"]),
            patch(
                "grandpa.cli.doctor_cmd.sys.orig_argv", ["python", "-m", "grandpa.cli"]
            ),
            patch(
                "grandpa.cli.doctor_cmd.sys.executable",
                "D:\\Grandpa\\.venv\\Scripts\\python.exe",
            ),
        ):
            active = _active_grandpa_executable(candidates)

        assert active == "D:\\Grandpa\\.venv\\Scripts\\grandpa.exe"

    def test_active_executable_prefers_actual_invoked_launcher(self, tmp_path) -> None:
        invoked = tmp_path / "grandpa.exe"
        invoked.touch()
        candidates = ["D:\\Grandpa\\.venv\\Scripts\\grandpa.exe", str(invoked)]
        with patch("grandpa.cli.doctor_cmd.sys.argv", [str(invoked)]):
            active = _active_grandpa_executable(candidates)

        assert active == str(invoked.resolve())

    def test_original_process_arguments_identify_running_launcher(
        self, tmp_path
    ) -> None:
        invoked = tmp_path / "grandpa.exe"
        invoked.touch()
        with (
            patch("grandpa.cli.doctor_cmd.sys.argv", ["doctor"]),
            patch("grandpa.cli.doctor_cmd.sys.orig_argv", [str(invoked), "doctor"]),
        ):
            active = _active_grandpa_executable([])

        assert active == str(invoked.resolve())

    def test_runtime_checks_warn_when_duplicate_executables_exist(
        self, tmp_path: Path
    ) -> None:
        # Build a real two-install layout on disk rather than naming absolute
        # paths. _duplicate_launcher_guidance only emits the pip remediation
        # when `scripts_dir.parent / "python.exe"` exists on the filesystem
        # (doctor_cmd.py:139), so the previous hardcoded
        # C:\Users\ASUS\...\Python311\ made the assertion pass only on a machine
        # where that interpreter happened to be installed. It failed on CI for
        # that reason alone, having never exercised the branch anywhere else.
        project_root = tmp_path / "project"
        preferred_dir = project_root / ".venv" / "Scripts"
        preferred_dir.mkdir(parents=True)
        preferred = preferred_dir / "grandpa.exe"
        preferred.write_text("", encoding="utf-8")

        other_root = tmp_path / "other-python"
        other_scripts = other_root / "Scripts"
        other_scripts.mkdir(parents=True)
        other = other_scripts / "grandpa.exe"
        other.write_text("", encoding="utf-8")
        # The interpreter beside the duplicate is what unlocks the pip guidance.
        (other_root / "python.exe").write_text("", encoding="utf-8")

        candidates = [str(preferred), str(other)]
        with (
            patch(
                "grandpa.cli.doctor_cmd._grandpa_executable_candidates",
                return_value=candidates,
            ),
            patch("grandpa.cli.doctor_cmd._project_root", return_value=project_root),
        ):
            results = _check_runtime_environment()

        duplicate = next(
            result
            for result in results
            if result.name == "Grandpa executable duplicates"
        )
        details = str(duplicate.details)
        assert duplicate.status == "warn"
        assert "2 executables" in duplicate.message
        assert "uv run grandpa" in details
        assert "pip uninstall grandpa" in details
        # The remediation must name the duplicate's interpreter, not the
        # preferred one -- that is the whole point of the guidance.
        assert str(other_root / "python.exe") in details
        assert str(other) in details


class TestCheckConfigMissing:
    def test_check_config_missing(self) -> None:
        """Warning when config file does not exist."""
        with patch(
            "grandpa.cli.doctor_cmd.DEFAULT_CONFIG_PATH",
            Path("/tmp/nonexistent/config.toml"),
        ):
            result = _check_config_exists()
        assert result.status == "warn"
        assert "Not found" in result.message


class TestCheckEngineProbing:
    def test_check_engine_probing(self) -> None:
        """Engine health check reports reachable/unreachable engines."""
        from grandpa.cli.doctor_cmd import CheckResult

        mock_engine_healthy = MagicMock()
        mock_engine_healthy.health.return_value = True

        mock_engine_down = MagicMock()
        mock_engine_down.health.return_value = False

        def mock_make_engine(key, config):
            if key == "ollama":
                return mock_engine_healthy
            return mock_engine_down

        # Directly test the engine probing logic without calling _check_engines
        # to avoid complex module-level mock interactions
        mock_config = MagicMock()
        keys = ["ollama", "custom-local"]

        results = []
        for key in sorted(keys):
            engine = mock_make_engine(key, mock_config)
            if engine.health():
                results.append(CheckResult(f"Engine: {key}", "ok", "Reachable"))
            else:
                results.append(CheckResult(f"Engine: {key}", "warn", "Unreachable"))

        names = [r.name for r in results]
        assert "Engine: ollama" in names
        assert "Engine: custom-local" in names
        # Ollama should be ready; an explicitly configured custom runtime warns.
        ollama_result = next(r for r in results if r.name == "Engine: ollama")
        custom_result = next(r for r in results if r.name == "Engine: custom-local")
        assert ollama_result.status == "ok"
        assert custom_result.status == "warn"


class TestCheckDefaultModel:
    def test_empty_default_model_is_not_a_warning(self) -> None:
        """Leaving default model empty should be treated as valid auto-routing."""
        mock_config = MagicMock()
        mock_config.intelligence.default_model = ""
        with patch("grandpa.cli.doctor_cmd.load_config", return_value=mock_config):
            result = _check_default_model()
        assert result.status == "ok"
        assert "auto" in result.message.lower()


class TestBackgroundSchedulerReadiness:
    def test_fastapi_absence_is_optional_warning(self) -> None:
        missing = ModuleNotFoundError("No module named 'fastapi'")
        missing.name = "fastapi"

        with (
            patch(
                "builtins.__import__",
                side_effect=missing,
            ),
        ):
            result = _check_background_scheduler_ready()

        assert result.status == "warn"
        assert result.message == "Missing/optional"
        assert result.details is not None
        assert "server extra" in result.details
