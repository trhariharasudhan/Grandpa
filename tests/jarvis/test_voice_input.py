import pytest

from grandpa.core import config as core_config
from grandpa.jarvis import voice_input
from grandpa.jarvis.voice_input import (
    SoundDeviceMicrophoneRecorder,
    calculate_pcm16_rms,
    listen_for_jarvis_command,
)
from grandpa.voice.errors import (
    MicrophoneUnavailableError,
    VoiceDependencyError,
    VoiceRecognitionError,
)
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


class FakeRecording:
    def __init__(self, frames: bytes, frame_count: int) -> None:
        self.frames = frames
        self.frame_count = frame_count

    def tobytes(self) -> bytes:
        return self.frames

    def __len__(self) -> int:
        return self.frame_count


class FakeSoundDevice:
    def __init__(self, *, default_device, frames: bytes) -> None:
        self.default = type("Default", (), {"device": default_device})()
        self.frames = frames
        self.rec_calls: list[dict] = []
        self.devices = [
            {"name": "Output Only", "max_input_channels": 0},
            {"name": "Microphone Array (AMD Audio Device)", "max_input_channels": 2},
            {"name": "USB Microphone", "max_input_channels": 1},
        ]

    def query_devices(self):
        return self.devices

    def rec(self, frame_count, *, samplerate, channels, dtype, device):
        self.rec_calls.append(
            {
                "frame_count": frame_count,
                "samplerate": samplerate,
                "channels": channels,
                "dtype": dtype,
                "device": device,
            }
        )
        return FakeRecording(self.frames, frame_count)

    def wait(self) -> None:
        return None


def _pcm16_frames(value: int = 1000, count: int = 16000) -> bytes:
    return value.to_bytes(2, "little", signed=True) * count


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


def test_silence_detection_threshold() -> None:
    assert calculate_pcm16_rms(b"\x00\x00" * 100) == 0.0


def test_sounddevice_recorder_accepts_valid_rms_audio(monkeypatch) -> None:
    sounddevice = FakeSoundDevice(default_device=[1, -1], frames=_pcm16_frames())
    monkeypatch.setattr(voice_input.importlib, "import_module", lambda _name: sounddevice)

    recorder = SoundDeviceMicrophoneRecorder(duration_seconds=1)
    audio = recorder.record_wav()

    assert audio.startswith(b"RIFF")
    assert recorder.last_rms > 250
    assert recorder.last_diagnostics is not None
    assert recorder.last_diagnostics.requested_device_id is None
    assert recorder.last_diagnostics.selected_device_id == 1
    assert recorder.last_diagnostics.device_name == "Microphone Array (AMD Audio Device)"
    assert recorder.last_diagnostics.channels == 1
    assert recorder.last_diagnostics.sample_rate == 16000
    assert recorder.last_diagnostics.captured_frame_count == 16000


def test_sounddevice_recorder_uses_first_input_when_no_default_device(monkeypatch) -> None:
    sounddevice = FakeSoundDevice(default_device=[-1, -1], frames=_pcm16_frames())
    monkeypatch.setattr(voice_input.importlib, "import_module", lambda _name: sounddevice)

    recorder = SoundDeviceMicrophoneRecorder(duration_seconds=1)
    recorder.record_wav()

    assert sounddevice.rec_calls[0]["device"] == 1
    assert recorder.last_diagnostics is not None
    assert recorder.last_diagnostics.requested_device_id is None
    assert recorder.last_diagnostics.selected_device_id == 1


def test_sounddevice_recorder_honors_explicit_device_selection(monkeypatch) -> None:
    sounddevice = FakeSoundDevice(default_device=[1, -1], frames=_pcm16_frames())
    monkeypatch.setattr(voice_input.importlib, "import_module", lambda _name: sounddevice)

    recorder = SoundDeviceMicrophoneRecorder(duration_seconds=1, device=2)
    recorder.record_wav()

    assert sounddevice.rec_calls[0]["device"] == 2
    assert recorder.last_diagnostics is not None
    assert recorder.last_diagnostics.requested_device_id == 2
    assert recorder.last_diagnostics.selected_device_id == 2
    assert recorder.last_diagnostics.device_name == "USB Microphone"


def test_sounddevice_recorder_resolves_device_name(monkeypatch) -> None:
    sounddevice = FakeSoundDevice(default_device=[1, -1], frames=_pcm16_frames())
    monkeypatch.setattr(voice_input.importlib, "import_module", lambda _name: sounddevice)

    recorder = SoundDeviceMicrophoneRecorder(duration_seconds=1, device_name="USB")
    recorder.record_wav()

    assert sounddevice.rec_calls[0]["device"] == 2
    assert recorder.last_diagnostics is not None
    assert recorder.last_diagnostics.requested_device_name == "USB"
    assert recorder.last_diagnostics.selected_device_id == 2
    assert recorder.last_diagnostics.device_name == "USB Microphone"


def test_sounddevice_recorder_uses_saved_microphone_preference(monkeypatch, tmp_path) -> None:
    sounddevice = FakeSoundDevice(default_device=[-1, -1], frames=_pcm16_frames())
    sounddevice.devices.insert(1, {"name": "USB Microphone", "max_input_channels": 1})
    monkeypatch.setattr(voice_input.importlib, "import_module", lambda _name: sounddevice)
    monkeypatch.setattr(core_config, "DEFAULT_CONFIG_PATH", tmp_path / "config.toml")
    core_config.DEFAULT_CONFIG_PATH.write_text('[voice]\npreferred_microphone = "USB Microphone"\n', encoding="utf-8")

    recorder = SoundDeviceMicrophoneRecorder(duration_seconds=1)
    recorder.record_wav()

    assert sounddevice.rec_calls[0]["device"] == 1
    assert recorder.last_diagnostics is not None
    assert recorder.last_diagnostics.requested_device_name == "USB Microphone"
    assert recorder.last_diagnostics.selected_device_id == 1


def test_sounddevice_recorder_warns_and_falls_back_when_saved_microphone_missing(monkeypatch, tmp_path) -> None:
    sounddevice = FakeSoundDevice(default_device=[-1, -1], frames=_pcm16_frames())
    monkeypatch.setattr(voice_input.importlib, "import_module", lambda _name: sounddevice)
    monkeypatch.setattr(core_config, "DEFAULT_CONFIG_PATH", tmp_path / "config.toml")
    core_config.DEFAULT_CONFIG_PATH.write_text('[voice]\npreferred_microphone = "Missing Mic"\n', encoding="utf-8")

    recorder = SoundDeviceMicrophoneRecorder(duration_seconds=1)
    recorder.record_wav()

    assert sounddevice.rec_calls[0]["device"] == 1
    assert recorder.last_diagnostics is not None
    assert recorder.last_diagnostics.warning is not None
    assert "Missing Mic" in recorder.last_diagnostics.warning


def test_sounddevice_recorder_rejects_explicit_output_device(monkeypatch) -> None:
    sounddevice = FakeSoundDevice(default_device=[1, -1], frames=_pcm16_frames())
    sounddevice.devices.insert(2, {"name": "Speakers", "max_input_channels": 0})
    monkeypatch.setattr(voice_input.importlib, "import_module", lambda _name: sounddevice)

    recorder = SoundDeviceMicrophoneRecorder(duration_seconds=1, device=2)

    with pytest.raises(MicrophoneUnavailableError) as exc_info:
        recorder.record_wav()

    assert sounddevice.rec_calls == []
    assert "Microphone device 2 has no input channels." in str(exc_info.value)
    assert "Available input devices:" in str(exc_info.value)
    assert "3: USB Microphone" in str(exc_info.value)


def test_sounddevice_recorder_rejects_invalid_explicit_device(monkeypatch) -> None:
    sounddevice = FakeSoundDevice(default_device=[1, -1], frames=_pcm16_frames())
    monkeypatch.setattr(voice_input.importlib, "import_module", lambda _name: sounddevice)

    recorder = SoundDeviceMicrophoneRecorder(duration_seconds=1, device=99)

    with pytest.raises(MicrophoneUnavailableError) as exc_info:
        recorder.record_wav()

    assert "Microphone device 99 was not found." in str(exc_info.value)
    assert "Available input devices:" in str(exc_info.value)


def test_sounddevice_dependency_missing_is_friendly(monkeypatch) -> None:
    def fake_import_module(name: str):
        raise ImportError(name)

    monkeypatch.setattr(voice_input.importlib, "import_module", fake_import_module)

    with pytest.raises(VoiceDependencyError) as exc_info:
        voice_input.SoundDeviceMicrophoneRecorder().record_wav()

    assert "Jarvis voice input is not fully installed." in str(exc_info.value)
    assert "sounddevice" in str(exc_info.value)
