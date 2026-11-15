"""B4: the local Tamil voice (MMS tam via sherpa-onnx) and the per-reply choice.

A fake ``sherpa_onnx`` returns a short tone, so neither the 114 MB model nor
the package is needed to test the plumbing.
"""

from __future__ import annotations

import io
import math
import sys
import types
import wave
from pathlib import Path

import pytest

from grandpa.speech import piper_tts, tamil_tts
from grandpa.ui import lipsync

pytestmark = pytest.mark.core


class _Audio:
    def __init__(self, n, rate=16000):
        self.samples = [0.3 * math.sin(2 * math.pi * 200 * i / rate) for i in range(n)]
        self.sample_rate = rate


class _FakeTts:
    made = 0
    said: list[str] = []

    def __init__(self, config):
        type(self).made += 1
        self.config = config

    def generate(self, text, sid=0, speed=1.0):
        type(self).said.append(text)
        return _Audio(1600 * max(1, len(text.split())))


def _ns(**kw):
    return types.SimpleNamespace(**kw)


@pytest.fixture
def fake_sherpa(monkeypatch, tmp_path):
    module = types.ModuleType("sherpa_onnx")
    module.OfflineTts = _FakeTts
    module.OfflineTtsConfig = _ns
    module.OfflineTtsModelConfig = _ns
    module.OfflineTtsVitsModelConfig = _ns
    monkeypatch.setitem(sys.modules, "sherpa_onnx", module)
    monkeypatch.setattr(tamil_tts, "sherpa_installed", lambda: True)
    monkeypatch.setenv(tamil_tts.ENV_MODEL_DIR, str(tmp_path / "mms-tam"))
    tamil_tts._loaded.clear()
    _FakeTts.made = 0
    _FakeTts.said = []
    return tmp_path / "mms-tam"


def _install_model(folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "model.onnx").write_bytes(b"onnx")
    (folder / "tokens.txt").write_text("_ 0\n", encoding="utf-8")


@pytest.mark.parametrize(
    ("text", "tamil"),
    [
        ("வணக்கம் கேப்டன், நான் தாத்தா", True),
        ("Hello Captain, I am Grandpa", False),
        ("Vanakkam Captain, epdi irukeenga?", False),  # Thanglish stays English
        ("சரி, I will open VS Code", False),  # mostly English letters
        ("", False),
    ],
)
def test_tamil_script_is_recognised(text, tamil):
    assert tamil_tts.is_tamil(text) is tamil


def test_not_ready_without_the_model(fake_sherpa):
    assert not tamil_tts.model_ready()
    assert not tamil_tts.ready()


def test_synthesize_writes_a_wav_and_loads_once(fake_sherpa, tmp_path):
    _install_model(fake_sherpa)
    out = tmp_path / "t.wav"
    tamil_tts.synthesize_wav("வணக்கம் கேப்டன்", out)
    tamil_tts.synthesize_wav("நன்றி", out)
    with wave.open(str(out), "rb") as wav:
        assert wav.getframerate() == 16000 and wav.getnframes() > 0
    assert _FakeTts.made == 1


def test_backend_registers_and_returns_wav(fake_sherpa):
    from grandpa.core.registry import TTSRegistry

    TTSRegistry.register_or_replace("mms_tamil", tamil_tts.TamilTTSBackend)
    _install_model(fake_sherpa)
    backend = TTSRegistry.get("mms_tamil")()
    assert backend.health() and backend.available_voices() == ["mms-tam"]
    result = backend.synthesize("வணக்கம்")
    with wave.open(io.BytesIO(result.audio), "rb") as wav:
        assert wav.getnframes() > 0


def test_avatar_routes_each_reply_by_script(fake_sherpa, monkeypatch, tmp_path):
    _install_model(fake_sherpa)
    english_said = []

    def fake_english(text, path):
        english_said.append(text)
        tamil_tts.synthesize_wav("english stand-in", path)  # any valid WAV

    monkeypatch.setattr(lipsync, "_piper_synth", lambda: (fake_english, "Piper (test)"))
    monkeypatch.setattr(
        "grandpa.core.config.load_config", lambda: _ns(tts=_ns(enabled=True))
    )
    speaker, line = lipsync.default_speaker()
    assert "Piper (test) + Tamil (MMS)" in line
    speaker.play = lambda path: None
    speaker.sleep = lambda s: None
    assert speaker.speak("வணக்கம் கேப்டன், நான் தாத்தா", lambda track, start: None)
    assert speaker.speak("Hello Captain", lambda track, start: None)
    assert english_said == ["Hello Captain"]
    assert any("வணக்கம்" in t for t in _FakeTts.said)


def test_without_the_tamil_model_the_english_voice_speaks_alone(
    fake_sherpa, monkeypatch
):
    monkeypatch.setattr(
        lipsync, "_piper_synth", lambda: (lambda t, p: None, "Piper (test)")
    )
    monkeypatch.setattr(
        "grandpa.core.config.load_config", lambda: _ns(tts=_ns(enabled=True))
    )
    _speaker, line = lipsync.default_speaker()
    assert "Tamil" not in line and "Piper (test)" in line


def test_download_fetches_both_files(fake_sherpa, monkeypatch):
    urls = []

    class _Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *e):
            return False

    monkeypatch.setattr(
        tamil_tts.urllib.request,
        "urlopen",
        lambda url, timeout=0: (urls.append(url), _Resp(b"x"))[1],
    )
    folder = tamil_tts.download()
    assert folder == fake_sherpa and tamil_tts.model_ready()
    assert urls == [tamil_tts.MODEL_URL.format(file=name) for name in tamil_tts.FILES]


def test_piper_module_still_loads_alongside(fake_sherpa):
    # both optional voices import without their packages installed
    assert hasattr(piper_tts, "synthesize_wav") and hasattr(tamil_tts, "synthesize_wav")


def test_punctuation_becomes_pauses_for_the_model():
    assert tamil_tts.clean_for_model("வணக்கம் கேப்டன். எப்படி?") == "வணக்கம் கேப்டன் எப்படி"
    assert tamil_tts.clean_for_model("சரி, VS Code!") == "சரி vs code"
