import pytest

from grandpa.jarvis import voice_input
from grandpa.jarvis.voice_input import listen_for_jarvis_command
from grandpa.voice.errors import VoiceDependencyError, VoiceRecognitionError
from grandpa.voice.speech_input import SpeechInputResult


class FakeRecorder:
    def __init__(self, audio: bytes = b"wav") -> None:
        self.audio = audio

    def record_wav(self) -> bytes:
        return self.audio


class FakeSpeechEngine:
    def __init__(self, transcript: str) -> None:
        self.transcript = transcript
        self.calls: list[tuple[bytes, str]] = []

    def listen(self, *, audio_bytes: bytes | None = None, audio_format: str = "wav", **_kwargs):
        self.calls.append((audio_bytes or b"", audio_format))
        return SpeechInputResult(
            status="completed",
            transcript=self.transcript,
            engine="fake_stt",
            duration_seconds=1.25,
        )


def test_voice_input_transcribes_recorded_microphone_audio() -> None:
    engine = FakeSpeechEngine("open my Grandpa project in VS Code")

    result = listen_for_jarvis_command(recorder=FakeRecorder(b"audio"), speech_engine=engine)

    assert result.transcript == "open my Grandpa project in VS Code"
    assert result.engine == "fake_stt"
    assert result.duration_seconds == 1.25
    assert engine.calls == [(b"audio", "wav")]


def test_voice_input_rejects_empty_transcript() -> None:
    with pytest.raises(VoiceRecognitionError):
        listen_for_jarvis_command(recorder=FakeRecorder(), speech_engine=FakeSpeechEngine(" "))


def test_sounddevice_dependency_missing_is_friendly(monkeypatch) -> None:
    def fake_import_module(name: str):
        raise ImportError(name)

    monkeypatch.setattr(voice_input.importlib, "import_module", fake_import_module)

    with pytest.raises(VoiceDependencyError) as exc_info:
        voice_input.SoundDeviceMicrophoneRecorder().record_wav()

    assert "Jarvis voice input is not fully installed." in str(exc_info.value)
    assert "sounddevice" in str(exc_info.value)
