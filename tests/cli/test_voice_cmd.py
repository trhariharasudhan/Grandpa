from __future__ import annotations

import io
import wave
from array import array
from pathlib import Path
from types import SimpleNamespace

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

    monkeypatch.setattr(
        "grandpa.cli.voice_cmd.build_voice_session", fake_build_voice_session
    )

    result = CliRunner().invoke(
        cli,
        [
            "voice",
            "--model",
            "tiny.en",
            "--language",
            "en",
            "--device",
            "cpu",
            "--no-tts",
        ],
    )

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

    monkeypatch.setattr(
        "grandpa.cli.voice_cmd.build_voice_session", fake_build_voice_session
    )

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
    device = type(
        "Device",
        (),
        {"index": 2, "name": "Microphone Array", "input_channels": 1, "default": True},
    )()
    monkeypatch.setattr("grandpa.cli.voice_cmd.list_input_devices", lambda: (device,))

    result = CliRunner().invoke(cli, ["voice", "--list-microphones"])

    assert result.exit_code == 0
    assert "INDEX | NAME | HOST API" in result.output
    assert "2 | Microphone Array | unknown | 1 | 16000 Hz | yes" in result.output


def test_voice_list_voices(monkeypatch) -> None:
    monkeypatch.setattr(
        "grandpa.cli.voice_cmd.list_system_voices", lambda: ["Microsoft David"]
    )

    result = CliRunner().invoke(cli, ["voice", "--list-voices"])

    assert result.exit_code == 0
    assert "Microsoft David" in result.output


def test_voice_missing_dependency_message(monkeypatch) -> None:
    from grandpa.voice.errors import VoiceDependencyError

    class FakeSession:
        def run(self) -> int:
            raise VoiceDependencyError()

    monkeypatch.setattr(
        "grandpa.cli.voice_cmd.build_voice_session", lambda **_kwargs: FakeSession()
    )

    result = CliRunner().invoke(cli, ["voice"])

    assert result.exit_code != 0
    assert "Voice mode is not fully installed." in result.output
    assert "Traceback" not in result.output


def test_voice_dependency_check_reports_only_missing_module(monkeypatch) -> None:
    def fake_import(name: str):
        if name == "sounddevice":
            raise ModuleNotFoundError(
                "No module named 'sounddevice'", name="sounddevice"
            )
        return object()

    monkeypatch.setattr(
        "grandpa.voice.diagnostics.importlib.import_module", fake_import
    )

    status = check_voice_dependencies()

    assert status.missing_required == ("sounddevice",)


def test_voice_dependency_internal_import_failure_is_not_missing(monkeypatch) -> None:
    def fake_import(name: str):
        if name == "sounddevice":
            raise ModuleNotFoundError("No module named 'cffi'", name="cffi")
        return object()

    monkeypatch.setattr(
        "grandpa.voice.diagnostics.importlib.import_module", fake_import
    )

    status = check_voice_dependencies()

    sounddevice = next(
        check for check in status.checks if check.module == "sounddevice"
    )
    assert sounddevice.status == "error"
    assert "sounddevice" not in status.missing_required


def test_voice_runtime_diagnostics_reports_active_interpreter() -> None:
    diagnostics = voice_runtime_diagnostics()

    assert diagnostics["python_executable"]
    assert diagnostics["virtual_environment"]
    # Assert the property that matters — project_root points at the repository
    # root — rather than the directory's name. The previous assertion required
    # the checkout to be named exactly "Grandpa", so the suite could not pass
    # from a clone, worktree, or CI path with any other name.
    project_root = Path(diagnostics["project_root"])
    assert project_root.is_dir()
    assert (project_root / "pyproject.toml").is_file()
    assert (project_root / "src" / "grandpa").is_dir()


def test_voice_runtime_diagnostics_ignores_stale_path_launcher(
    monkeypatch, tmp_path
) -> None:
    project_scripts = tmp_path / "project" / ".venv" / "Scripts"
    project_scripts.mkdir(parents=True)
    python = project_scripts / "python.exe"
    launcher = project_scripts / "grandpa.exe"
    for path in (python, launcher):
        path.touch()

    monkeypatch.setattr("grandpa.voice.diagnostics.sys.executable", str(python))
    monkeypatch.setattr("grandpa.voice.diagnostics.sys.argv", [str(launcher)])
    monkeypatch.setenv("PATH", str(tmp_path / "global" / "Scripts"))

    diagnostics = voice_runtime_diagnostics()

    assert diagnostics["grandpa_executable"] == str(launcher.resolve())


def test_voice_diagnose_option(monkeypatch) -> None:
    monkeypatch.setattr(
        "grandpa.cli.voice_cmd.run_voice_doctor",
        lambda **_kwargs: [
            {
                "status": "pass",
                "name": "Python executable",
                "message": r"D:\Grandpa\.venv\Scripts\python.exe",
            }
        ],
    )

    result = CliRunner().invoke(cli, ["voice", "--diagnose"])

    assert result.exit_code == 0
    assert "Python executable" in result.output


def test_voice_diagnose_subcommand_does_not_record(monkeypatch) -> None:
    calls = {}

    def fake_doctor(**kwargs):
        calls.update(kwargs)
        return [
            {"status": "pass", "name": "selected input device", "message": "2: USB Mic"}
        ]

    monkeypatch.setattr("grandpa.cli.voice_cmd.run_voice_doctor", fake_doctor)

    result = CliRunner().invoke(cli, ["voice", "diagnose", "--device", "2"])

    assert result.exit_code == 0
    assert calls == {"device": 2, "duration_seconds": 0}
    assert "USB Mic" in result.output


def _diagnostic_wav() -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16_000)
        wav_file.writeframes(array("h", [0, 800, -800] * 2_000).tobytes())
    return buffer.getvalue()


def test_voice_microphone_test_replays_transcribes_and_cleans_up(
    monkeypatch, tmp_path
) -> None:
    calls: list[str] = []
    audio = SimpleNamespace(
        data=_diagnostic_wav(),
        speech_onset_seconds=0.2,
        speech_active_seconds=0.8,
        trailing_silence_seconds=1.2,
        finalization_reason="trailing_silence",
    )

    class FakeCapture:
        last_device = SimpleNamespace(
            index=15,
            name="Microphone Array",
            driver="Windows WASAPI",
        )

        def __init__(self, **_kwargs):
            pass

        def capture(self):
            calls.append("capture")
            return audio

        def close(self):
            calls.append("close")

    class FakeTranscriber:
        last_result = SimpleNamespace(language="en")

        def __init__(self, **_kwargs):
            pass

        def transcribe(self, captured):
            assert captured is audio
            calls.append("transcribe")
            return "Hello Grandpa."

        def transcribe_file(self, path):
            assert path.read_bytes() == audio.data
            calls.append("direct_transcribe")
            return "Hello Grandpa."

        @property
        def backend_diagnostics(self):
            return None

    temporary = tmp_path / "diagnostic.wav"

    class TemporaryFile:
        def __enter__(self):
            self.handle = temporary.open("wb")
            return self.handle

        def __exit__(self, *_args):
            self.handle.close()

    monkeypatch.setattr("grandpa.cli.voice_cmd.MicrophoneCapture", FakeCapture)
    selected_device = SimpleNamespace(index=15)

    class FakeManager:
        def __init__(self, _sounddevice):
            pass

        def select(self, **_kwargs):
            return SimpleNamespace(device=selected_device)

    monkeypatch.setattr("grandpa.cli.voice_cmd.import_sounddevice", lambda: object())
    monkeypatch.setattr("grandpa.cli.voice_cmd.MicrophoneDeviceManager", FakeManager)
    monkeypatch.setattr(
        "grandpa.cli.voice_cmd.FasterWhisperSpeechToText", FakeTranscriber
    )
    monkeypatch.setattr(
        "grandpa.cli.voice_cmd.play_wav_bytes",
        lambda _audio: calls.append("playback"),
    )
    monkeypatch.setattr("grandpa.cli.voice_cmd.time.sleep", lambda _seconds: None)
    monkeypatch.setattr(
        "grandpa.cli.voice_cmd.tempfile.NamedTemporaryFile",
        lambda **_kwargs: TemporaryFile(),
    )

    result = CliRunner().invoke(
        cli,
        ["voice", "microphone-test", "--device", "15"],
        input="y\ny\n",
    )

    assert result.exit_code == 0
    assert calls == [
        "capture",
        "playback",
        "transcribe",
        "direct_transcribe",
        "close",
    ]
    assert "Windows WASAPI" in result.output
    assert "Production transcript: Hello Grandpa." in result.output
    assert "Direct same-WAV transcript: Hello Grandpa." in result.output
    assert "Captured bytes identical to diagnostic WAV: True" in result.output
    assert "Human playback assessment: clear" in result.output
    assert not temporary.exists()


def test_voice_microphone_test_accepts_supervised_sentence(monkeypatch) -> None:
    monkeypatch.setattr(
        "grandpa.cli.voice_cmd.MicrophoneCapture",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("must not capture")),
    )

    result = CliRunner().invoke(
        cli,
        ["voice", "microphone-test", "--sentence", "Hello Grandpa"],
        input="n\n",
    )

    assert result.exit_code == 0
    assert 'Say: "Hello Grandpa"' in result.output


def test_voice_microphone_test_can_cancel_before_capture(monkeypatch) -> None:
    monkeypatch.setattr(
        "grandpa.cli.voice_cmd.MicrophoneCapture",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("must not capture")),
    )

    result = CliRunner().invoke(cli, ["voice", "microphone-test"], input="n\n")

    assert result.exit_code == 0
    assert "cancelled" in result.output
