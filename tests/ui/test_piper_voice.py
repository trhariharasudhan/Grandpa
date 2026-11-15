"""B3: Piper as Grandpa's local neural voice, and the avatar's lip-sync using it.

The real Piper and its 60 MB voices are not needed: a fake ``piper`` module
writes a short tone, which is enough to test the plumbing (voice lookup, WAV
output, the speaker the avatar picks, the backend registry, the downloader).
"""

from __future__ import annotations

import io
import math
import struct
import sys
import types
import wave
from pathlib import Path

import pytest

from grandpa.speech import piper_tts
from grandpa.ui import lipsync

pytestmark = pytest.mark.core

RATE = 22050


class _FakeVoice:
    loads = 0

    @classmethod
    def load(cls, path: str) -> "_FakeVoice":
        cls.loads += 1
        voice = cls()
        voice.path = path
        return voice

    def synthesize_wav(self, text, wav, syn_config=None):
        seconds = (
            0.05
            * max(1, len(text.split()))
            * (syn_config.length_scale if syn_config else 1.0)
        )
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(RATE)
        frames = b"".join(
            struct.pack("<h", int(8000 * math.sin(2 * math.pi * 220 * i / RATE)))
            for i in range(int(RATE * seconds))
        )
        wav.writeframes(frames)


class _FakeConfig:
    def __init__(self, length_scale=1.0):
        self.length_scale = length_scale


@pytest.fixture
def fake_piper(monkeypatch, tmp_path):
    module = types.ModuleType("piper")
    module.PiperVoice = _FakeVoice
    module.SynthesisConfig = _FakeConfig
    module.__spec__ = types.SimpleNamespace(name="piper")
    monkeypatch.setitem(sys.modules, "piper", module)
    monkeypatch.setattr(piper_tts, "piper_installed", lambda: True)
    monkeypatch.setattr(piper_tts, "voices_dir", lambda: tmp_path)
    monkeypatch.delenv(piper_tts.ENV_VOICE, raising=False)
    monkeypatch.delenv(lipsync.ENV_VOICE_ENGINE, raising=False)
    piper_tts._loaded.clear()
    _FakeVoice.loads = 0
    return tmp_path


def _install_voice(folder: Path, name: str = piper_tts.DEFAULT_VOICE) -> Path:
    model = folder / f"{name}.onnx"
    model.write_bytes(b"onnx")
    (folder / f"{name}.onnx.json").write_text("{}")
    return model


def test_no_voice_means_not_ready(fake_piper):
    assert piper_tts.voice_path() is None
    assert not piper_tts.ready()


def test_a_voice_needs_its_json_too(fake_piper):
    (fake_piper / f"{piper_tts.DEFAULT_VOICE}.onnx").write_bytes(b"onnx")
    assert piper_tts.voice_path() is None


def test_default_and_env_voice_are_found(fake_piper, monkeypatch):
    default = _install_voice(fake_piper)
    other = _install_voice(fake_piper, "en_US-ryan-medium")
    assert piper_tts.voice_path() == default
    monkeypatch.setenv(piper_tts.ENV_VOICE, "en_US-ryan-medium")
    assert piper_tts.voice_path() == other
    monkeypatch.setenv(piper_tts.ENV_VOICE, str(default))
    assert piper_tts.voice_path() == default


def test_synthesize_writes_a_wav_and_loads_the_voice_once(fake_piper, tmp_path):
    _install_voice(fake_piper)
    out = tmp_path / "say.wav"
    piper_tts.synthesize_wav("hello captain how are you", out)
    piper_tts.synthesize_wav("again", out)
    with wave.open(str(out), "rb") as wav:
        assert wav.getframerate() == RATE and wav.getnframes() > 0
    assert _FakeVoice.loads == 1


def test_synthesize_without_a_voice_says_where_it_looked(fake_piper, tmp_path):
    with pytest.raises(RuntimeError, match="No Piper voice"):
        piper_tts.synthesize_wav("hello", tmp_path / "x.wav")


def test_backend_is_registered_and_returns_wav(fake_piper):
    from grandpa.core.registry import TTSRegistry

    # conftest clears the registries before every test; register as the import does
    TTSRegistry.register_or_replace("piper", piper_tts.PiperTTSBackend)
    _install_voice(fake_piper)
    backend = TTSRegistry.get("piper")()
    assert backend.health()
    assert backend.available_voices() == [piper_tts.DEFAULT_VOICE]
    result = backend.synthesize("hello there")
    assert result.format == "wav" and result.duration_seconds > 0
    with wave.open(io.BytesIO(result.audio), "rb") as wav:
        assert wav.getnframes() > 0


def test_avatar_prefers_piper_when_it_is_ready(fake_piper, monkeypatch):
    _install_voice(fake_piper)
    monkeypatch.setattr(
        "grandpa.core.config.load_config",
        lambda: types.SimpleNamespace(tts=types.SimpleNamespace(enabled=True)),
    )
    speaker, line = lipsync.default_speaker()
    assert speaker is not None
    assert "Piper (en_GB-alan-medium)" in line


def test_avatar_speaker_with_piper_produces_a_mouth_track(fake_piper, tmp_path):
    _install_voice(fake_piper)
    speaker = lipsync.LipSyncSpeaker(
        synthesize=lambda text, path: piper_tts.synthesize_wav(text, path),
        play=lambda path: None,
        sleep=lambda s: None,
    )
    seen = []
    assert speaker.speak(
        "Hello Captain, I am Grandpa.", lambda track, start: seen.append(track)
    )
    track = seen[0]
    assert track[-1]["v"] == "rest"
    assert any(entry["v"] != "rest" for entry in track)


def test_env_keeps_the_old_voice(fake_piper, monkeypatch):
    _install_voice(fake_piper)
    monkeypatch.setenv(lipsync.ENV_VOICE_ENGINE, "pyttsx3")
    monkeypatch.setattr(
        "grandpa.core.config.load_config",
        lambda: types.SimpleNamespace(tts=types.SimpleNamespace(enabled=True)),
    )
    speaker, line = lipsync.default_speaker()
    assert "Piper" not in line


def test_download_builds_the_voice_urls(fake_piper, monkeypatch):
    fetched = []

    class _Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(url, timeout=0):
        fetched.append(url)
        return _Response(b"data")

    monkeypatch.setattr(piper_tts.urllib.request, "urlopen", fake_urlopen)
    path = piper_tts.download_voice("en_GB-alan-medium", dest=fake_piper)
    assert path == fake_piper / "en_GB-alan-medium.onnx"
    assert fetched == [
        "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/alan/medium/en_GB-alan-medium.onnx",
        "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/alan/medium/en_GB-alan-medium.onnx.json",
    ]
    assert piper_tts.voice_path("en_GB-alan-medium") == path
