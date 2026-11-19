"""E0: a launcher that survives Smart App Control / Device Guard.

Windows refuses to start ``.venv\\Scripts\\grandpa.exe`` on Captain's laptop.
``grandpa.cmd`` and the shim from ``scripts/install_launcher.ps1`` start Grandpa
through ``uv run python -m grandpa`` instead, and ``grandpa doctor`` says which
launcher is in use and whether the .exe is blocked.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from grandpa.cli import doctor_cmd
from grandpa.cli.doctor_cmd import _active_launcher, _check_launcher, _probe_executable

REPO = Path(__file__).resolve().parents[2]
REPO_CMD = REPO / "grandpa.cmd"
INSTALLER = REPO / "scripts" / "install_launcher.ps1"


class _BlockedError(OSError):
    """OSError as Windows raises it for a blocked program (winerror set)."""

    def __init__(self, winerror: int) -> None:
        super().__init__("An Application Control policy has blocked this file")
        self.winerror = winerror


# --- the files themselves --------------------------------------------------


def test_repo_launcher_runs_the_module_not_the_exe() -> None:
    text = REPO_CMD.read_text(encoding="utf-8")
    assert 'uv run --project "%~dp0." python -m grandpa %*' in text
    commands = [
        line for line in text.splitlines() if not line.lower().startswith("rem ")
    ]
    assert not any(".exe" in line for line in commands)
    assert "exit /b %ERRORLEVEL%" in text
    assert "GRANDPA_LAUNCHER=grandpa.cmd" in text


def test_installer_writes_a_shim_that_runs_the_module() -> None:
    text = INSTALLER.read_text(encoding="utf-8")
    assert 'python -m grandpa %*"' in text
    assert "GRANDPA_LAUNCHER=shim" in text
    # PATH entries such as %USERPROFILE%\bin must survive the rewrite.
    assert "DoNotExpandEnvironmentNames" in text
    assert "ExpandString" in text
    assert "-NoPath" in text or "$NoPath" in text


def test_cmd_files_are_checked_out_with_crlf() -> None:
    attributes = (REPO / ".gitattributes").read_text(encoding="utf-8")
    assert "*.cmd text eol=crlf" in attributes


# --- doctor ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("env", "active", "expected"),
    [
        ("grandpa.cmd", "x", "grandpa.cmd (repo folder)"),
        ("shim", "x", "install_launcher.ps1"),
        ("", "D:\\Grandpa\\.venv\\Scripts\\grandpa.exe", "grandpa.exe"),
        ("", "C:\\py\\python.exe (Python module invocation)", "python -m grandpa"),
    ],
)
def test_doctor_names_the_running_launcher(monkeypatch, env, active, expected) -> None:
    monkeypatch.setenv("GRANDPA_LAUNCHER", env)
    assert expected in _active_launcher(active)


def _fake_repo(tmp_path: Path) -> Path:
    scripts = tmp_path / ".venv" / "Scripts"
    scripts.mkdir(parents=True)
    (scripts / "grandpa.exe").write_bytes(b"")
    (tmp_path / "grandpa.cmd").write_text("@echo off\n", encoding="utf-8")
    return tmp_path


def test_blocked_exe_without_shim_warns_with_the_exact_fix(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.delenv("GRANDPA_LAUNCHER", raising=False)
    root = _fake_repo(tmp_path)
    with (
        patch.object(doctor_cmd.sys, "platform", "win32"),
        patch.object(doctor_cmd.shutil, "which", return_value=None),
        patch.object(
            doctor_cmd, "_probe_executable", return_value=("blocked", "blocked")
        ) as probe,
    ):
        result = _check_launcher(root, "python.exe (Python module invocation)")

    probe.assert_called_once_with(str(root / ".venv" / "Scripts" / "grandpa.exe"))
    assert result.status == "warn"
    assert "blocked" in result.message
    assert "install_launcher.ps1" in str(result.details)
    assert "grandpa shim on PATH: not installed" in str(result.details)


def test_blocked_exe_with_shim_is_fine(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GRANDPA_LAUNCHER", "shim")
    root = _fake_repo(tmp_path)
    shim = "C:\\Users\\ASUS\\AppData\\Local\\Grandpa\\bin\\grandpa.cmd"
    with (
        patch.object(doctor_cmd.sys, "platform", "win32"),
        patch.object(doctor_cmd.shutil, "which", return_value=shim),
        patch.object(
            doctor_cmd, "_probe_executable", return_value=("blocked", "blocked")
        ),
    ):
        result = _check_launcher(root, "x")

    assert result.status == "ok"
    assert "shim works" in result.message
    assert shim in str(result.details)


def test_working_exe_is_ok(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("GRANDPA_LAUNCHER", raising=False)
    root = _fake_repo(tmp_path)
    with (
        patch.object(doctor_cmd.sys, "platform", "win32"),
        patch.object(doctor_cmd.shutil, "which", return_value=None),
        patch.object(
            doctor_cmd, "_probe_executable", return_value=("works", "Grandpa 1.0")
        ),
    ):
        result = _check_launcher(root, str(root / ".venv/Scripts/grandpa.exe"))

    assert result.status == "ok"
    assert "works (Grandpa 1.0)" in str(result.details)


def test_non_windows_never_probes(monkeypatch) -> None:
    with (
        patch.object(doctor_cmd.sys, "platform", "linux"),
        patch.object(doctor_cmd, "_probe_executable") as probe,
    ):
        result = _check_launcher(Path("/repo"), "/repo/.venv/bin/grandpa")
    probe.assert_not_called()
    assert result.status == "ok"


@pytest.mark.parametrize("winerror", [1260, 4551, 225])
def test_probe_reads_windows_block_errors(winerror) -> None:
    with patch.object(
        doctor_cmd.subprocess, "run", side_effect=_BlockedError(winerror)
    ):
        state, detail = _probe_executable("grandpa.exe")
    assert state == "blocked"
    assert "Smart App Control" in detail


def test_probe_reports_version_when_it_runs() -> None:
    done = MagicMock(returncode=0, stdout="Grandpa, version 1.0.3\n", stderr="")
    with patch.object(doctor_cmd.subprocess, "run", return_value=done):
        assert _probe_executable("grandpa.exe") == ("works", "Grandpa, version 1.0.3")


def test_probe_other_failure_is_not_called_blocked() -> None:
    done = MagicMock(returncode=2, stdout="", stderr="Traceback ...")
    with patch.object(doctor_cmd.subprocess, "run", return_value=done):
        assert _probe_executable("grandpa.exe") == ("failed", "exit code 2")


# --- real Windows runs -------------------------------------------------------

windows_only = pytest.mark.skipif(
    sys.platform != "win32" or shutil.which("uv") is None,
    reason="runs grandpa.cmd through cmd.exe and uv",
)


def _sandbox_env(tmp_path: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["GRANDPA_HOME"] = str(tmp_path / "home")  # the child only, not pytest
    env["UV_NO_SYNC"] = "1"  # use the CI environment as it is; never re-sync
    return env


@windows_only
@pytest.mark.real_actions(
    reason="starts grandpa.cmd --version: prints the version, its GRANDPA_HOME is tmp"
)
def test_repo_cmd_starts_grandpa_on_windows(tmp_path) -> None:
    proc = subprocess.run(
        ["cmd.exe", "/d", "/c", str(REPO_CMD), "--version"],
        capture_output=True,
        text=True,
        timeout=180,
        cwd=tmp_path,
        env=_sandbox_env(tmp_path),
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "Grandpa" in proc.stdout


@windows_only
@pytest.mark.real_actions(
    reason="runs install_launcher.ps1 -NoPath into tmp_path (PATH untouched), "
    "then the shim with --version"
)
def test_installed_shim_starts_grandpa_on_windows(tmp_path) -> None:
    bin_dir = tmp_path / "bin"
    install = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(INSTALLER),
            "-BinDir",
            str(bin_dir),
            "-NoPath",
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert install.returncode == 0, install.stdout + install.stderr
    shim = bin_dir / "grandpa.cmd"
    assert str(REPO).casefold() in shim.read_text(encoding="ascii").casefold()

    proc = subprocess.run(
        ["cmd.exe", "/d", "/c", str(shim), "--version"],
        capture_output=True,
        text=True,
        timeout=180,
        cwd=tmp_path,
        env=_sandbox_env(tmp_path),
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "Grandpa" in proc.stdout
