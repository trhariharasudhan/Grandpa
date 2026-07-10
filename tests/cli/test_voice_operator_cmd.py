from click.testing import CliRunner

from grandpa.cli import cli
from grandpa.voice.speech_output import SpeechOutputResult


def test_voice_operator_command_typed_quit() -> None:
    result = CliRunner().invoke(cli, ["voice-operator"], input="quit\n")

    assert result.exit_code == 0
    assert "Voice Operator Mode started" in result.output
    assert "Understood: quit" in result.output
    assert "Voice Operator Mode stopped." in result.output


def test_voice_operator_command_typed_fallback_action(monkeypatch) -> None:
    calls = []

    def fake_runner(payload):
        calls.append(payload)

        class Response:
            ok = True
            status = "completed"
            message = "Dry run: open_app would run."
            approval_required = False

        return Response()

    monkeypatch.setattr("grandpa.voice.operator.run_local_action", fake_runner)

    result = CliRunner().invoke(cli, ["voice-operator", "--dry-run"], input="open notepad\nquit\n")

    assert result.exit_code == 0
    assert calls[0]["action_type"] == "open_app"
    assert calls[0]["target"] == "notepad"


def test_voice_operator_typed_mode_does_not_call_microphone(monkeypatch) -> None:
    captured = {}

    def fake_loop(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr("grandpa.cli.voice_operator_cmd.run_voice_operator_loop", fake_loop)

    result = CliRunner().invoke(cli, ["voice-operator", "--typed"])

    assert result.exit_code == 0
    assert captured["prefer_voice"] is False


def test_voice_operator_duration_option_is_parsed(monkeypatch) -> None:
    captured = {}

    def fake_loop(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr("grandpa.cli.voice_operator_cmd.run_voice_operator_loop", fake_loop)

    result = CliRunner().invoke(cli, ["voice-operator", "--duration", "7"])

    assert result.exit_code == 0
    assert captured["duration_seconds"] == 7.0


def test_voice_operator_debug_option_is_parsed(monkeypatch) -> None:
    captured = {}

    def fake_loop(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr("grandpa.cli.voice_operator_cmd.run_voice_operator_loop", fake_loop)

    result = CliRunner().invoke(cli, ["voice-operator", "--debug"])

    assert result.exit_code == 0
    assert captured["debug"] is True


def test_voice_operator_invalid_device_is_clear() -> None:
    result = CliRunner().invoke(cli, ["voice-operator", "--device", "-1"])

    assert result.exit_code != 0
    assert "Invalid microphone device index" in result.output


def test_speak_command_invokes_tts(monkeypatch) -> None:
    calls = []

    def fake_speak(self, text, *, interrupt=False, dry_run=False):
        calls.append((text, interrupt, dry_run))
        return SpeechOutputResult("completed", "mock_tts", "Speech output spoken.", text)

    monkeypatch.setattr("grandpa.voice.speech_output.SpeechOutputEngine.speak", fake_speak)

    result = CliRunner().invoke(cli, ["speak", "Hello world"])

    assert result.exit_code == 0
    assert calls == [("Hello world", True, False)]
    assert "Speech output spoken." in result.output


def test_speak_command_print_only_fallback(monkeypatch) -> None:
    def fake_speak(self, text, *, interrupt=False, dry_run=False):
        return SpeechOutputResult("fallback", "print_only", "No TTS backend available; printed response only.", text)

    monkeypatch.setattr("grandpa.voice.speech_output.SpeechOutputEngine.speak", fake_speak)

    result = CliRunner().invoke(cli, ["speak", "Hello world"])

    assert result.exit_code == 0
    assert "Hello world" in result.output
    assert "printed response only" in result.output


def test_voice_test_speaks_grandpa_phrase(monkeypatch) -> None:
    calls = []

    def fake_speak(self, text, *, interrupt=False, dry_run=False):
        calls.append(text)
        return SpeechOutputResult("completed", "mock_tts", "Speech output spoken.", text)

    monkeypatch.setattr("grandpa.voice.speech_output.SpeechOutputEngine.speak", fake_speak)

    result = CliRunner().invoke(cli, ["voice", "test"])

    assert result.exit_code == 0
    assert calls == ["Hello, I am Grandpa."]
