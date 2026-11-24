"""P1: one-command install, a first-run wizard, and a doctor that says the fix.

``scripts/install.ps1`` installs uv, Python and the packages, then runs
``grandpa setup --yes``. The wizard writes the config, builds the Ollama models
and fetches the offline voices, each only when missing. ``grandpa doctor`` ends
with either "All green" or a numbered fix for every warn/fail line.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from grandpa.cli import cli, setup_cmd
from grandpa.cli._first_run import needs_first_run
from grandpa.cli.doctor_cmd import (
    CheckResult,
    DoctorSection,
    _with_prefix,
    cli_prefix,
    fix_for,
)
from grandpa.intelligence.odin_registry import SetupPlan, SetupStep

REPO = Path(__file__).resolve().parents[2]
INSTALLER = REPO / "scripts" / "install.ps1"


# --- doctor: the exact fix per item ------------------------------------------


@pytest.mark.parametrize(
    ("launcher", "prefix"),
    [
        ("", "uv run python -m grandpa"),
        ("shim", "grandpa"),
        ("grandpa.cmd", ".\\grandpa.cmd"),
    ],
)
def test_fix_commands_use_the_launcher_that_works(
    monkeypatch, launcher, prefix
) -> None:
    monkeypatch.setenv("GRANDPA_LAUNCHER", launcher)
    assert cli_prefix() == prefix
    fix = fix_for(CheckResult("Config file", "warn", "Not found at x/config.toml"))
    assert fix == f"{prefix} setup"
    # grandpa.exe is blocked on Captain's laptop: no fix may tell him to run it.
    assert "grandpa.exe" not in fix


def test_fix_for_known_lines(monkeypatch) -> None:
    monkeypatch.delenv("GRANDPA_LAUNCHER", raising=False)
    g = "uv run python -m grandpa"
    assert "ollama serve" in fix_for(
        CheckResult("Engine: ollama", "warn", "Unreachable")
    )
    assert (
        fix_for(
            CheckResult(
                "Default model", "warn", "grandpa-brain:latest not found on any engine"
            )
        )
        == f"{g} models setup --yes"
    )
    down = fix_for(
        CheckResult("Vision model", "warn", "Unavailable", "Unreachable at http://x")
    )
    assert "ollama serve" in down and down.endswith(f"{g} models setup --yes")
    assert fix_for(
        CheckResult("Security profile", "warn", "No security profile set")
    ) == (f"{g} config set security.profile personal")
    assert fix_for(
        CheckResult("Known app: Chrome", "warn", "Missing/optional")
    ).startswith("Optional: install Chrome")


def test_fix_for_reads_the_fix_line_in_details(monkeypatch) -> None:
    monkeypatch.delenv("GRANDPA_LAUNCHER", raising=False)
    check = CheckResult(
        "Credentials at rest",
        "warn",
        "NOT encrypted",
        details="Fix (Linux): uv pip install keyring secretstorage, then: grandpa vault migrate",
    )
    assert fix_for(check) == (
        "uv pip install keyring secretstorage, then: uv run python -m grandpa vault migrate"
    )
    server = CheckResult("REST API", "warn", "Missing", "Run `uv sync --extra server`.")
    assert fix_for(server) == "Run `uv sync --extra server`."
    unknown = CheckResult("Something", "fail", "Broken", "no hint here")
    assert (
        fix_for(unknown)
        == "See the details with: uv run python -m grandpa doctor --json"
    )


def test_with_prefix_leaves_prose_alone() -> None:
    assert _with_prefix("Grandpa works without it", "X") == "Grandpa works without it"
    assert _with_prefix("run `grandpa doctor`", "X") == "run `X doctor`"


def test_security_profile_fix_is_a_real_config_key() -> None:
    from grandpa.core.config import validate_config_key

    validate_config_key("security.profile")


def _doctor_with(checks):
    sections = [DoctorSection("Core Runtime", checks)]
    with patch("grandpa.cli.doctor_cmd._build_doctor_dashboard", return_value=sections):
        return CliRunner().invoke(cli, ["doctor"], env={"COLUMNS": "200"})


def test_doctor_ends_all_green_when_nothing_is_wrong() -> None:
    result = _doctor_with(
        [CheckResult("A", "ok", "Ready"), CheckResult("B", "info", "Not created yet")]
    )
    assert result.exit_code == 0, result.output
    assert "All green. Nothing to fix." in result.output
    assert "How to fix" not in result.output


def test_doctor_ends_with_a_numbered_fix_per_problem(monkeypatch) -> None:
    monkeypatch.delenv("GRANDPA_LAUNCHER", raising=False)
    result = _doctor_with(
        [
            CheckResult("A", "ok", "Ready"),
            CheckResult("Engine: ollama", "warn", "Unreachable"),
            CheckResult("Default model", "fail", "missing"),
        ]
    )
    assert result.exit_code == 0, result.output
    tail = result.output.split("How to fix", 1)[1]
    assert "1. Engine: ollama: Install Ollama" in tail
    assert "2. Default model: uv run python -m grandpa models setup --yes" in tail
    assert "All green" not in result.output


# --- the wizard ----------------------------------------------------------------


class _Piper:
    DEFAULT_VOICE = "en_GB-alan-medium"

    def __init__(self, installed=True, present=False):
        self.installed, self.present, self.downloads = installed, present, 0

    def piper_installed(self):
        return self.installed

    def voice_path(self):
        return Path("v.onnx") if self.present else None

    def download_voice(self):
        self.downloads += 1
        return Path("v.onnx")


class _Tamil:
    def __init__(self, installed=True, ready=False):
        self.installed, self.ready, self.downloads = installed, ready, 0

    def sherpa_installed(self):
        return self.installed

    def model_ready(self):
        return self.ready

    def download(self):
        self.downloads += 1
        return Path("mms-tam")


@pytest.fixture
def wizard(monkeypatch, tmp_path):
    """The wizard with Ollama, the voices and the config path faked."""
    config = tmp_path / "config.toml"
    config.write_text("[user]\n", encoding="utf-8")
    monkeypatch.setattr(setup_cmd, "DEFAULT_CONFIG_PATH", config)
    state = {"tags": set(), "plan": SetupPlan(), "built": 0}

    def fake_run_setup(plan, client, *a):
        state["built"] += 1
        for step in plan.runnable:
            step.done = True
        return plan

    monkeypatch.setattr(setup_cmd, "_ollama", lambda: (MagicMock(), state["tags"]))
    monkeypatch.setattr(
        "grandpa.intelligence.odin_registry.plan_setup", lambda tags: state["plan"]
    )
    monkeypatch.setattr("grandpa.intelligence.odin_registry.run_setup", fake_run_setup)
    piper, tamil = _Piper(), _Tamil()
    monkeypatch.setattr(
        "grandpa.speech.piper_tts.piper_installed", piper.piper_installed
    )
    monkeypatch.setattr("grandpa.speech.piper_tts.voice_path", piper.voice_path)
    monkeypatch.setattr("grandpa.speech.piper_tts.download_voice", piper.download_voice)
    monkeypatch.setattr(
        "grandpa.speech.tamil_tts.sherpa_installed", tamil.sherpa_installed
    )
    monkeypatch.setattr("grandpa.speech.tamil_tts.model_ready", tamil.model_ready)
    monkeypatch.setattr("grandpa.speech.tamil_tts.download", tamil.download)
    state.update(piper=piper, tamil=tamil)
    return state


def _run(*args, input=None):
    return CliRunner().invoke(cli, ["setup", "--no-doctor", *args], input=input)


def test_wizard_yes_builds_models_and_downloads_voices(wizard) -> None:
    wizard["plan"] = SetupPlan(
        [SetupStep("brain", "create", "ollama create grandpa-brain")]
    )
    result = _run("--yes")
    assert result.exit_code == 0, result.output
    assert wizard["built"] == 1
    assert wizard["piper"].downloads == 1 and wizard["tamil"].downloads == 1
    assert "Built 1 model(s)" in result.output
    assert "Profile: Not asked (--yes)" in result.output


def test_wizard_does_nothing_when_everything_is_there(wizard) -> None:
    wizard["piper"].present = True
    wizard["tamil"].ready = True
    result = _run("--yes")
    assert result.exit_code == 0, result.output
    assert wizard["built"] == 0
    assert wizard["piper"].downloads == 0 and wizard["tamil"].downloads == 0
    assert "Every Ollama role is installed" in result.output


def test_wizard_asks_before_each_download(wizard, monkeypatch) -> None:
    monkeypatch.setattr(
        setup_cmd,
        "step_profile",
        lambda console, interactive: setup_cmd.StepResult("Profile", "done", "Saved"),
    )
    wizard["plan"] = SetupPlan(
        [SetupStep("brain", "create", "ollama create grandpa-brain")]
    )
    result = _run(input="n\nn\nn\n")
    assert result.exit_code == 0, result.output
    assert wizard["built"] == 0
    assert wizard["piper"].downloads == 0 and wizard["tamil"].downloads == 0
    assert "Fix: uv run python -m grandpa models setup --yes" in result.output


def test_wizard_without_ollama_fails_with_the_fix(wizard, monkeypatch) -> None:
    monkeypatch.delenv("GRANDPA_LAUNCHER", raising=False)
    wizard["tags"] = None
    result = _run("--yes", "--skip-voice")
    assert result.exit_code == 1
    assert "Ollama is not reachable" in result.output
    from grandpa.platform_hints import ollama_installer

    assert ollama_installer() in result.output


def test_the_ollama_hint_matches_the_system() -> None:
    from grandpa.platform_hints import install_ollama_hint

    assert "download/windows" in install_ollama_hint("win32")
    assert "download/mac" in install_ollama_hint("darwin")
    assert "install.sh | sh" in install_ollama_hint("linux")


def test_wizard_skips_voices_whose_package_is_missing(wizard) -> None:
    wizard["piper"].installed = False
    wizard["tamil"].installed = False
    result = _run("--yes", "--skip-models")
    assert result.exit_code == 0, result.output
    assert "uv sync --extra piper" in result.output
    assert "uv sync --extra tamil-voice" in result.output


def test_wizard_writes_a_config_when_there_is_none(
    wizard, monkeypatch, tmp_path
) -> None:
    missing = tmp_path / "new" / "config.toml"
    monkeypatch.setattr(setup_cmd, "DEFAULT_CONFIG_PATH", missing)
    calls = []

    import grandpa.cli.init_cmd as init_cmd

    def fake_init(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(init_cmd.init, "callback", fake_init)
    result = _run("--yes", "--skip-models", "--skip-voice")
    assert result.exit_code == 0, result.output
    assert calls and calls[0]["from_bare_grandpa"] and calls[0]["no_download"]


def test_bare_grandpa_does_not_start_the_wizard_in_tests(monkeypatch) -> None:
    monkeypatch.setenv("GRANDPA_TESTING", "1")
    assert needs_first_run() is False


# --- scripts/install.ps1 ---------------------------------------------------------


def test_installer_covers_every_step_without_grandpa_exe() -> None:
    text = INSTALLER.read_text(encoding="utf-8")
    for needle in (
        "https://astral.sh/uv/install.ps1",
        '"python", "install", "3.11"',
        '"sync"',
        "api/tags",
        "install_launcher.ps1",
        '"-m", "grandpa", "setup", "--yes"',
        "--skip-models",
        "--skip-voice",
        "CreateShortcut",
        '"-m", "grandpa", "doctor"',
        "$DryRun",
    ):
        assert needle in text, needle
    assert "grandpa.exe" not in text.split("#>", 1)[1]
    # A native command's output must not leak into Run's return value.
    assert "| Out-Host" in text
    # install_launcher.ps1 ends with `exit`: it must run in a child process.
    assert "& .\\scripts\\install_launcher.ps1" not in text
