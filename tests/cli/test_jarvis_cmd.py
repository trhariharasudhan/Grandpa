from pathlib import Path

from click.testing import CliRunner

from grandpa.cli import cli
from grandpa.jarvis.voice_input import JarvisVoiceTranscript
from grandpa.voice.errors import (
    MicrophoneUnavailableError,
    VoiceDependencyError,
    VoiceRecognitionError,
)


def test_jarvis_dry_run_behavior(monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "Grandpa"
    project.mkdir()
    (project / ".git").mkdir()
    monkeypatch.setattr(
        "grandpa.jarvis.context_resolver.default_approved_roots",
        lambda: [tmp_path],
    )
    run_calls = []
    monkeypatch.setattr(
        "grandpa.cli.jarvis_cmd.run_local_action",
        lambda payload: run_calls.append(payload),
    )

    result = CliRunner().invoke(
        cli,
        ["jarvis", "--dry-run", "open my Grandpa project in VS Code"],
    )

    assert result.exit_code == 0
    assert '"action_type": "open_app"' in result.output
    assert '"target": "vscode"' in result.output
    assert run_calls == []


def test_jarvis_uses_pc_control_for_execution(monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "Grandpa"
    project.mkdir()
    (project / ".git").mkdir()
    monkeypatch.setattr(
        "grandpa.jarvis.context_resolver.default_approved_roots",
        lambda: [tmp_path],
    )
    calls = []

    class Response:
        ok = True
        status = "completed"
        message = "Dry run: open_app would run."

    def fake_run_local_action(payload):
        calls.append(payload)
        return Response()

    monkeypatch.setattr(
        "grandpa.cli.jarvis_cmd.run_local_action", fake_run_local_action
    )

    result = CliRunner().invoke(
        cli,
        ["jarvis", "open my Grandpa project in VS Code"],
    )

    assert result.exit_code == 0
    assert calls
    assert calls[0]["target"] == "vscode"


def test_jarvis_unknown_command(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "grandpa.jarvis.context_resolver.default_approved_roots",
        lambda: [tmp_path],
    )

    result = CliRunner().invoke(cli, ["jarvis", "make me coffee"])

    assert result.exit_code != 0
    assert "don't know how to route" in result.output
    assert "Try: open my Grandpa project in VS Code" in result.output
    assert "Traceback" not in result.output


def test_jarvis_no_direct_shell_execution(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "grandpa.jarvis.context_resolver.default_approved_roots",
        lambda: [tmp_path],
    )
    monkeypatch.setattr(
        "subprocess.run",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("shell executed")),
    )

    result = CliRunner().invoke(cli, ["jarvis", "run command dir"])

    assert result.exit_code != 0
    assert "blocked" in result.output.lower()


def test_jarvis_voice_recognized_text_routes_to_pc_control(
    monkeypatch, tmp_path: Path
) -> None:
    project = tmp_path / "Grandpa"
    project.mkdir()
    (project / ".git").mkdir()
    monkeypatch.setattr(
        "grandpa.jarvis.context_resolver.default_approved_roots",
        lambda: [tmp_path],
    )
    monkeypatch.setattr(
        "grandpa.cli.jarvis_cmd.listen_for_jarvis_command",
        lambda: JarvisVoiceTranscript("open my Grandpa project in VS Code", "test"),
    )
    calls = []

    class Response:
        ok = True
        status = "completed"
        message = "Opened VS Code."

    monkeypatch.setattr(
        "grandpa.cli.jarvis_cmd.run_local_action",
        lambda payload: calls.append(payload) or Response(),
    )

    result = CliRunner().invoke(cli, ["jarvis", "--voice"])

    assert result.exit_code == 0
    assert "Speak now. Press Ctrl+C to cancel." in result.output
    assert "Recognized: open my Grandpa project in VS Code" in result.output
    assert calls
    assert calls[0]["target"] == "vscode"


def test_jarvis_voice_dry_run_does_not_execute(monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "Grandpa"
    project.mkdir()
    (project / ".git").mkdir()
    monkeypatch.setattr(
        "grandpa.jarvis.context_resolver.default_approved_roots",
        lambda: [tmp_path],
    )
    monkeypatch.setattr(
        "grandpa.cli.jarvis_cmd.listen_for_jarvis_command",
        lambda: JarvisVoiceTranscript("open my Grandpa project in VS Code", "test"),
    )
    monkeypatch.setattr(
        "grandpa.cli.jarvis_cmd.run_local_action",
        lambda _payload: (_ for _ in ()).throw(AssertionError("should not execute")),
    )

    result = CliRunner().invoke(cli, ["jarvis", "--voice", "--dry-run"])

    assert result.exit_code == 0
    assert "Speak now. Press Ctrl+C to cancel." in result.output
    assert "Recognized: open my Grandpa project in VS Code" in result.output
    assert '"dry_run": true' in result.output


def test_jarvis_voice_dependency_missing_is_friendly(monkeypatch) -> None:
    monkeypatch.setattr(
        "grandpa.cli.jarvis_cmd.listen_for_jarvis_command",
        lambda: (_ for _ in ()).throw(
            VoiceDependencyError("Install local voice dependencies.")
        ),
    )

    result = CliRunner().invoke(cli, ["jarvis", "--voice"])

    assert result.exit_code != 0
    assert "Speak now. Press Ctrl+C to cancel." in result.output
    assert "Install local voice dependencies." in result.output


def test_jarvis_voice_microphone_unavailable_is_friendly(monkeypatch) -> None:
    monkeypatch.setattr(
        "grandpa.cli.jarvis_cmd.listen_for_jarvis_command",
        lambda: (_ for _ in ()).throw(MicrophoneUnavailableError()),
    )

    result = CliRunner().invoke(cli, ["jarvis", "--voice"])

    assert result.exit_code != 0
    assert "Speak now. Press Ctrl+C to cancel." in result.output
    assert "No usable microphone was detected." in result.output


def test_jarvis_voice_recognition_error_is_friendly_without_traceback(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "grandpa.cli.jarvis_cmd.listen_for_jarvis_command",
        lambda: (_ for _ in ()).throw(
            VoiceRecognitionError(detail="float16 unsupported")
        ),
    )

    result = CliRunner().invoke(cli, ["jarvis", "--voice", "--dry-run"])

    assert result.exit_code != 0
    assert "Speak now. Press Ctrl+C to cancel." in result.output
    assert "I could not understand the audio." in result.output
    assert "Traceback" not in result.output


def test_jarvis_voice_non_interactive_mode_does_not_hang(monkeypatch) -> None:
    monkeypatch.setattr(
        "grandpa.cli.jarvis_cmd.listen_for_jarvis_command",
        lambda: JarvisVoiceTranscript("make me coffee", "test"),
    )

    result = CliRunner().invoke(cli, ["jarvis", "--voice"])

    assert result.exit_code != 0
    assert "Speak now. Press Ctrl+C to cancel." in result.output
    assert "Recognized: make me coffee" in result.output
    assert "Try: open my Grandpa project in VS Code" in result.output
    assert "Traceback" not in result.output


def test_jarvis_voice_unknown_recognized_text_exits_cleanly(monkeypatch) -> None:
    monkeypatch.setattr(
        "grandpa.cli.jarvis_cmd.listen_for_jarvis_command",
        lambda: JarvisVoiceTranscript("Pintak Raja Pintak Raja Pintak Raja", "test"),
    )

    result = CliRunner().invoke(cli, ["jarvis", "--voice", "--dry-run"])

    assert result.exit_code != 0
    assert "I don't know how to route that Jarvis command yet." in result.output
    assert "Recognized: Pintak Raja Pintak Raja Pintak Raja" in result.output
    assert "Try: open my Grandpa project in VS Code" in result.output
    assert "Traceback" not in result.output
