"""Tests for ephemeral live audio, preferred backend routing, and cleanup."""

from __future__ import annotations

import io
import json
import subprocess
import tempfile
import wave
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from grandpa.core.config import GrandpaConfig
from grandpa.core.registry import TTSRegistry
from grandpa.speech.tts import TTSResult
from grandpa.voice.speech_output import SpeechOutputEngine, SpeechOutputResult, _play_audio_bytes
from grandpa.voice_service.post_processing import (
    CharacterVoiceProcessingError,
    CharacterVoiceSettings,
    FFmpegCharacterVoiceProcessor,
)


def _make_dummy_wav_bytes(sample_rate: int = 24_000, duration_seconds: float = 0.05) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        num_frames = int(sample_rate * duration_seconds)
        wav_file.writeframes(b"\x00\x00" * num_frames)
    return buffer.getvalue()


@pytest.fixture(autouse=True)
def _ensure_speech_registered():
    import importlib
    import sys
    import grandpa.speech.grandpa_voice_tts
    import grandpa.speech.kokoro_tts

    importlib.reload(sys.modules["grandpa.speech.grandpa_voice_tts"])
    importlib.reload(sys.modules["grandpa.speech.kokoro_tts"])


def test_preferred_backend_is_grandpa_voice(monkeypatch):
    config = GrandpaConfig()
    config.tts.backend = "grandpa_voice"

    monkeypatch.setattr("grandpa.core.config.load_config", lambda: config)

    # Mock health checks for backends
    class FakeGrandpaBackend:
        def health(self):
            return True

    monkeypatch.setattr(TTSRegistry, "get", lambda name: FakeGrandpaBackend)
    monkeypatch.setattr(TTSRegistry, "contains", lambda name: True)

    engine = SpeechOutputEngine()
    candidates = engine.available_local_engines()

    assert candidates[0] == "grandpa_voice"
    assert "pyttsx3" in candidates


def test_successful_grandpa_voice_uses_normal_playback_route(monkeypatch):
    dummy_wav = _make_dummy_wav_bytes()

    class FakeGrandpaBackend:
        def synthesize(self, text, **kwargs):
            return TTSResult(audio=dummy_wav, format="wav", voice_id="grandpa")

        def health(self):
            return True

    config = GrandpaConfig()
    config.tts.backend = "grandpa_voice"
    monkeypatch.setattr("grandpa.core.config.load_config", lambda: config)

    monkeypatch.setattr(TTSRegistry, "get", lambda name: FakeGrandpaBackend)
    monkeypatch.setattr(TTSRegistry, "contains", lambda name: True)

    played_bytes = []

    def mock_play(audio_bytes, eng):
        played_bytes.append(audio_bytes)

    monkeypatch.setattr("grandpa.voice.speech_output._play_audio_bytes", mock_play)

    engine = SpeechOutputEngine()
    result = engine.speak("Hello Hari. Grandpa is ready.")

    assert result.status == "completed"
    assert result.engine == "grandpa_voice"
    assert len(played_bytes) == 1
    assert played_bytes[0] == dummy_wav


def test_pyttsx3_fallback_when_grandpa_voice_fails(monkeypatch):
    class FailingGrandpaBackend:
        def synthesize(self, text, **kwargs):
            raise RuntimeError("F5 service connection refused")

        def health(self):
            return True

    config = GrandpaConfig()
    config.tts.backend = "grandpa_voice"
    monkeypatch.setattr("grandpa.core.config.load_config", lambda: config)

    monkeypatch.setattr(TTSRegistry, "get", lambda name: FailingGrandpaBackend)
    monkeypatch.setattr(TTSRegistry, "contains", lambda name: True)

    pyttsx3_called = []

    def mock_pyttsx3(text, voice="", rate=185):
        pyttsx3_called.append(text)

    monkeypatch.setattr("grandpa.voice.speech_output._speak_with_pyttsx3", mock_pyttsx3)

    engine = SpeechOutputEngine()
    result = engine.speak("Testing fallback to pyttsx3.")

    assert result.status == "completed"
    assert result.engine == "pyttsx3"
    assert len(pyttsx3_called) == 1
    assert "Testing fallback" in pyttsx3_called[0]


def test_live_synthesis_leaves_no_persistent_wav_files(tmp_path, monkeypatch):
    dummy_wav = _make_dummy_wav_bytes()

    class FakeGrandpaBackend:
        def synthesize(self, text, **kwargs):
            return TTSResult(audio=dummy_wav, format="wav", voice_id="grandpa")

        def health(self):
            return True

    config = GrandpaConfig()
    config.tts.backend = "grandpa_voice"
    monkeypatch.setattr("grandpa.core.config.load_config", lambda: config)

    monkeypatch.setattr(TTSRegistry, "get", lambda name: FakeGrandpaBackend)
    monkeypatch.setattr(TTSRegistry, "contains", lambda name: True)

    monkeypatch.setattr("grandpa.voice.speech_output._play_audio_bytes", lambda b, e: None)

    outputs_dir = Path("D:/Grandpa/voice_runtime/outputs")
    initial_files = set(outputs_dir.glob("*.wav")) if outputs_dir.exists() else set()

    engine = SpeechOutputEngine()
    result = engine.speak("Live assistant speech test.")

    assert result.status == "completed"

    final_files = set(outputs_dir.glob("*.wav")) if outputs_dir.exists() else set()
    new_files = final_files - initial_files

    assert len(new_files) == 0, f"Live synthesis created persistent WAV files: {new_files}"


def test_temporary_files_removed_after_successful_post_processing():
    source_bytes = _make_dummy_wav_bytes()
    created_temp_dirs: list[Path] = []

    orig_tempdir = tempfile.TemporaryDirectory

    class TrackedTempDir:
        def __init__(self, *args, **kwargs):
            self._td = orig_tempdir(*args, **kwargs)
            self.path = Path(self._td.name)
            created_temp_dirs.append(self.path)

        def __enter__(self):
            return self._td.__enter__()

        def __exit__(self, exc_type, exc_val, exc_tb):
            return self._td.__exit__(exc_type, exc_val, exc_tb)

    measurement = {
        "input_i": "-20.0",
        "input_tp": "-5.0",
        "input_lra": "2.0",
        "input_thresh": "-30.0",
        "target_offset": "0.2",
    }

    def fake_run(command):
        command = list(command)
        if command[-1] == "NUL":
            return subprocess.CompletedProcess(command, 0, stdout="", stderr=json.dumps(measurement))
        output = Path(command[-1])
        output.write_bytes(source_bytes)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    with patch("tempfile.TemporaryDirectory", TrackedTempDir):
        processor = FFmpegCharacterVoiceProcessor(
            CharacterVoiceSettings(eq_profile="grandpa_presence"),
            ffmpeg_path="ffmpeg.exe",
            command_runner=fake_run,
        )
        processed = processor.process(source_bytes)

    assert processed == source_bytes
    assert len(created_temp_dirs) == 1
    # Verify the temporary directory was deleted automatically
    assert not created_temp_dirs[0].exists()


def test_temporary_files_removed_after_post_processing_failure():
    source_bytes = _make_dummy_wav_bytes()
    created_temp_dirs: list[Path] = []

    orig_tempdir = tempfile.TemporaryDirectory

    class TrackedTempDir:
        def __init__(self, *args, **kwargs):
            self._td = orig_tempdir(*args, **kwargs)
            self.path = Path(self._td.name)
            created_temp_dirs.append(self.path)

        def __enter__(self):
            return self._td.__enter__()

        def __exit__(self, exc_type, exc_val, exc_tb):
            return self._td.__exit__(exc_type, exc_val, exc_tb)

    def failing_run(command):
        return subprocess.CompletedProcess(list(command), 1, stdout="", stderr="FFmpeg filter error")

    with patch("tempfile.TemporaryDirectory", TrackedTempDir):
        processor = FFmpegCharacterVoiceProcessor(
            CharacterVoiceSettings(eq_profile="grandpa_presence"),
            ffmpeg_path="ffmpeg.exe",
            command_runner=failing_run,
        )
        with pytest.raises(CharacterVoiceProcessingError):
            processor.process(source_bytes)

    assert len(created_temp_dirs) == 1
    # Verify the temporary directory was deleted even after failure
    assert not created_temp_dirs[0].exists()


def test_unrelated_tts_configuration_remains_intact():
    config = GrandpaConfig()
    assert config.grandpa_voice.engine == "f5"
    assert config.grandpa_voice.device == "cpu"
    assert config.grandpa_voice.voice_id == "grandpa"
    assert config.grandpa_voice.service_url == "http://127.0.0.1:8765"
    assert config.grandpa_voice.synthesis_timeout_seconds == 600.0
