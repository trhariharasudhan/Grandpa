from __future__ import annotations

from click.testing import CliRunner

from grandpa.cli import cli
from grandpa.voice.diagnostics import (
    check_voice_dependencies,
    voice_runtime_diagnostics,
)


def test_voice_command_registration() -> None:
    result = CliRunner().invoke(cli, ["voice", "--help"])

    assert result.exit_code == 0
    assert "--no-tts" in result.output
    assert "--wake-word" in result.output
    assert "--wake-phrase" in result.output
    assert "--no-wake-response" in result.output
    assert "--list-microphones" in result.output
    assert "--list-voices" in result.output


def test_voice_command_runs_session(monkeypatch) -> None:
    calls = {}

    class FakeSession:
        def run(self) -> int:
            calls["ran"] = True
            return 0

    def fake_build_voice_session(**kwargs):
        calls.update(kwargs)
        return FakeSession()

    monkeypatch.setattr("grandpa.cli.voice_cmd.build_voice_session", fake_build_voice_session)

    result = CliRunner().invoke(cli, ["voice", "--model", "tiny.en", "--language", "en", "--device", "cpu", "--no-tts"])

    assert result.exit_code == 0
    assert calls["model"] == "tiny.en"
    assert calls["language"] == "en"
    assert calls["device"] == "cpu"
    assert calls["no_tts"] is True
    assert calls["wake_word"] is False
    assert calls["ran"] is True


def test_voice_command_passes_wake_word_options(monkeypatch) -> None:
    calls = {}

    class FakeSession:
        def run(self) -> int:
            calls["ran"] = True
            return 0

    def fake_build_voice_session(**kwargs):
        calls.update(kwargs)
        return FakeSession()

    monkeypatch.setattr("grandpa.cli.voice_cmd.build_voice_session", fake_build_voice_session)

    result = CliRunner().invoke(
        cli,
        [
            "voice",
            "--wake-word",
            "--wake-phrase",
            "computer",
            "--wake-phrase",
            "hey computer",
            "--no-wake-response",
        ],
    )

    assert result.exit_code == 0
    assert calls["wake_word"] is True
    assert calls["wake_phrases"] == ("computer", "hey computer")
    assert calls["wake_response_enabled"] is False
    assert calls["ran"] is True


def test_voice_list_microphones(monkeypatch) -> None:
    device = type("Device", (), {"index": 2, "name": "Microphone Array", "input_channels": 1, "default": True})()
    monkeypatch.setattr("grandpa.cli.voice_cmd.list_input_devices", lambda: (device,))

    result = CliRunner().invoke(cli, ["voice", "--list-microphones"])

    assert result.exit_code == 0
    assert "2: Microphone Array" in result.output
    assert "*default*" in result.output


def test_voice_list_voices(monkeypatch) -> None:
    monkeypatch.setattr("grandpa.cli.voice_cmd.list_system_voices", lambda: ["Microsoft David"])

    result = CliRunner().invoke(cli, ["voice", "--list-voices"])

    assert result.exit_code == 0
    assert "Microsoft David" in result.output


def test_voice_missing_dependency_message(monkeypatch) -> None:
    from grandpa.voice.errors import VoiceDependencyError

    class FakeSession:
        def run(self) -> int:
            raise VoiceDependencyError()

    monkeypatch.setattr("grandpa.cli.voice_cmd.build_voice_session", lambda **_kwargs: FakeSession())

    result = CliRunner().invoke(cli, ["voice"])

    assert result.exit_code != 0
    assert "Voice mode is not fully installed." in result.output
    assert "Traceback" not in result.output


def test_voice_dependency_check_reports_only_missing_module(monkeypatch) -> None:
    def fake_import(name: str):
        if name == "sounddevice":
            raise ModuleNotFoundError("No module named 'sounddevice'", name="sounddevice")
        return object()

    monkeypatch.setattr("grandpa.voice.diagnostics.importlib.import_module", fake_import)

    status = check_voice_dependencies()

    assert status.missing_required == ("sounddevice",)


def test_voice_dependency_internal_import_failure_is_not_missing(monkeypatch) -> None:
    def fake_import(name: str):
        if name == "sounddevice":
            raise ModuleNotFoundError("No module named 'cffi'", name="cffi")
        return object()

    monkeypatch.setattr("grandpa.voice.diagnostics.importlib.import_module", fake_import)

    status = check_voice_dependencies()

    sounddevice = next(check for check in status.checks if check.module == "sounddevice")
    assert sounddevice.status == "error"
    assert "sounddevice" not in status.missing_required


def test_voice_runtime_diagnostics_reports_active_interpreter() -> None:
    diagnostics = voice_runtime_diagnostics()

    assert diagnostics["python_executable"]
    assert diagnostics["virtual_environment"]
    assert diagnostics["project_root"].endswith("Grandpa")


def test_voice_diagnose_option(monkeypatch) -> None:
    monkeypatch.setattr(
        "grandpa.cli.voice_cmd.run_voice_doctor",
        lambda **_kwargs: [
            {"status": "pass", "name": "Python executable", "message": r"D:\Grandpa\.venv\Scripts\python.exe"}
        ],
    )

    result = CliRunner().invoke(cli, ["voice", "--diagnose"])

    assert result.exit_code == 0
    assert "Python executable" in result.output
