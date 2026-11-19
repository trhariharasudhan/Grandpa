"""The ElevenLabs voice (Captain's clone): opt-in, and never the only voice.

Nothing here reaches the network: a fake client stands in for the API.
"""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

import pytest

from grandpa.speech import elevenlabs_tts as el
from grandpa.ui import lipsync

pytestmark = pytest.mark.core


def _pcm(ms: int = 400) -> bytes:
    n = el.SAMPLE_RATE * ms // 1000
    return b"".join(
        struct.pack("<h", int(12000 * math.sin(2 * math.pi * 200 * i / el.SAMPLE_RATE)))
        for i in range(n)
    )


class FakeResponse:
    def __init__(self, status: int = 200, content: bytes = b"") -> None:
        self.status_code = status
        self.content = content
        self.text = "" if status == 200 else '{"detail":"quota_exceeded"}'


class FakeClient:
    def __init__(self, status: int = 200) -> None:
        self.status = status
        self.calls: list[dict] = []

    def post(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        return FakeResponse(self.status, _pcm() if self.status == 200 else b"")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch, tmp_path):
    monkeypatch.setattr(el, "default_cache_dir", lambda: tmp_path / "voice-cache")
    for name in (
        *el.ENV_KEYS,
        el.ENV_VOICE,
        el.ENV_TAMIL_VOICE,
        el.ENV_MODEL,
        lipsync.ENV_VOICE_ENGINE,
    ):
        monkeypatch.delenv(name, raising=False)
    el.mark_up()
    yield
    el.mark_up()


def test_no_key_means_no_cloud_voice() -> None:
    assert el.api_key() == ""
    assert not el.ready()
    assert lipsync._cloud_synth() is None


def test_the_request_carries_the_clone_and_the_key_only_in_a_header(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("ELEVENLABS_API_KEY", "sk-test")
    client = FakeClient()
    out = tmp_path / "say.wav"
    el.synthesize_wav("Hello Captain.", out, client=client)
    (call,) = client.calls
    assert call["url"].endswith(f"/text-to-speech/{el.DEFAULT_VOICE_ID}")
    assert call["headers"]["xi-api-key"] == "sk-test"
    assert "sk-test" not in call["url"]
    assert call["params"] == {"output_format": "pcm_24000"}
    assert call["json"]["model_id"] == "eleven_flash_v2_5"
    assert "language_code" not in call["json"]
    with wave.open(str(out)) as wav:
        assert wav.getframerate() == 24_000 and wav.getnchannels() == 1
        assert abs(wav.getnframes() / 24_000 - 0.4) < 0.01


def test_tamil_asks_for_tamil_and_can_use_its_own_voice(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ELEVENLABS_API_KEY", "sk-test")
    monkeypatch.setenv(el.ENV_TAMIL_VOICE, "tamilVoice123")
    client = FakeClient()
    el.synthesize_wav("வணக்கம் கேப்டன்", tmp_path / "ta.wav", tamil=True, client=client)
    (call,) = client.calls
    assert call["url"].endswith("/tamilVoice123")
    assert call["json"]["language_code"] == "ta"


def test_settings_come_from_the_environment(monkeypatch) -> None:
    monkeypatch.setenv(el.ENV_VOICE, "otherVoice")
    monkeypatch.setenv(el.ENV_MODEL, "eleven_multilingual_v2")
    assert el.voice_id() == "otherVoice"
    assert el.voice_id(tamil=True) == "otherVoice"  # Tamil falls back to it
    assert el.model_id() == "eleven_multilingual_v2"


def test_an_api_error_is_an_error_not_silence(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ELEVENLABS_API_KEY", "sk-test")
    with pytest.raises(RuntimeError, match="401"):
        el.synthesize_wav("Hi.", tmp_path / "x.wav", client=FakeClient(401))


def _local(calls: list[str]):
    def synth(text: str, path: Path) -> None:
        calls.append(text)
        el.pcm_to_wav(_pcm(200), path)

    return synth


def test_the_avatar_uses_the_clone_first(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ELEVENLABS_API_KEY", "sk-test")
    cloud_calls: list[str] = []
    monkeypatch.setattr(
        el,
        "synthesize_wav",
        lambda text, path, tamil=False: (
            cloud_calls.append(text),
            el.pcm_to_wav(_pcm(), path),
        ),
    )
    local: list[str] = []
    speaker, line = lipsync._with_cloud(el, _local(local), "Piper (alan)", None)
    speaker.synthesize("Hello there Captain.", tmp_path / "a.wav")
    assert cloud_calls == ["Hello there Captain."] and local == []
    assert "ElevenLabs" in line and "falls back to Piper" in line


def test_a_cloud_failure_falls_back_and_cools_down(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ELEVENLABS_API_KEY", "sk-test")
    tries: list[str] = []

    def broken(text, path, tamil=False):
        tries.append(text)
        raise RuntimeError("no internet")

    monkeypatch.setattr(el, "synthesize_wav", broken)
    local: list[str] = []
    speaker, _ = lipsync._with_cloud(el, _local(local), "Piper", None)
    speaker.synthesize("First sentence here.", tmp_path / "1.wav")
    speaker.synthesize("Second sentence here.", tmp_path / "2.wav")
    assert tries == ["First sentence here."]  # one timeout, not one per sentence
    assert local == ["First sentence here.", "Second sentence here."]
    assert not el.ready()


def test_tamil_falls_back_to_the_tamil_voice(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ELEVENLABS_API_KEY", "sk-test")
    el.mark_down()
    english: list[str] = []
    tamil: list[str] = []
    speaker, _ = lipsync._with_cloud(el, _local(english), "Piper", _local(tamil))
    speaker.synthesize("வணக்கம் கேப்டன் எப்படி இருக்கீங்க", tmp_path / "t.wav")
    assert tamil and not english


def test_staying_local_ignores_the_key(monkeypatch) -> None:
    monkeypatch.setenv("ELEVENLABS_API_KEY", "sk-test")
    assert lipsync._cloud_synth() is el
    monkeypatch.setenv(lipsync.ENV_VOICE_ENGINE, "piper")
    assert lipsync._cloud_synth() is None


def test_the_backend_is_registered() -> None:
    from grandpa.core.registry import TTSRegistry

    if "elevenlabs" not in TTSRegistry.keys():  # conftest clears registries
        TTSRegistry.register("elevenlabs")(el.ElevenLabsTTSBackend)
    assert "elevenlabs" in TTSRegistry.keys()


def test_the_command_line_runs_without_a_double_registration(monkeypatch) -> None:
    """``python -m grandpa.speech.elevenlabs_tts`` used to crash on import."""
    import runpy
    import sys

    monkeypatch.setattr(sys, "argv", ["elevenlabs_tts"])
    with pytest.raises(SystemExit) as done:
        runpy.run_module("grandpa.speech.elevenlabs_tts", run_name="__main__")
    assert done.value.code == 2  # usage, not ValueError


# --- H1: the audio cache and the doctor line ----------------------------------


def test_a_sentence_said_twice_is_fetched_once(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ELEVENLABS_API_KEY", "sk-test")
    client = FakeClient()
    first = el.synthesize_pcm("Done. Anything else?", client=client, cache_dir=tmp_path)
    second = el.synthesize_pcm(
        "Done. Anything else?", client=client, cache_dir=tmp_path
    )
    assert first == second
    assert len(client.calls) == 1  # the second one cost nothing
    el.synthesize_pcm("Opening Chrome now.", client=client, cache_dir=tmp_path)
    assert len(client.calls) == 2


def test_the_cache_works_without_the_network_or_a_key(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ELEVENLABS_API_KEY", "sk-test")
    el.synthesize_pcm("Good morning Captain.", client=FakeClient(), cache_dir=tmp_path)
    monkeypatch.delenv("ELEVENLABS_API_KEY")
    assert el.synthesize_pcm(
        "Good morning Captain.", client=FakeClient(500), cache_dir=tmp_path
    )


def test_a_different_voice_or_language_is_a_different_clip() -> None:
    a = el.cache_key("Vanakkam", "v1", "m", None)
    assert a != el.cache_key("Vanakkam", "v2", "m", None)
    assert a != el.cache_key("Vanakkam", "v1", "m", "ta")
    assert a != el.cache_key("Vanakkam", "v1", "m2", None)


def test_the_cache_can_be_turned_off(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ELEVENLABS_API_KEY", "sk-test")
    monkeypatch.setenv(el.ENV_CACHE, "0")
    client = FakeClient()
    el.synthesize_pcm("Hi.", client=client, cache_dir=tmp_path)
    el.synthesize_pcm("Hi.", client=client, cache_dir=tmp_path)
    assert len(client.calls) == 2 and not list(tmp_path.glob("*.pcm"))


def test_the_cache_stays_under_its_size_cap(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(el, "CACHE_MAX_BYTES", 30_000)
    for i in range(5):
        el._cache_put(f"k{i}", b"\x00" * 10_000, tmp_path, el.CACHE_MAX_BYTES)
    clips, size = el.cache_stats(tmp_path)
    assert size <= 30_000 and clips == 3


def test_the_doctor_line_never_shows_the_key(monkeypatch) -> None:
    assert el.status_line()[0] == "info"
    monkeypatch.setenv("ELEVENLABS_API_KEY", "sk-very-secret-123")
    status, message = el.status_line()
    assert status == "ok" and "sk-very-secret" not in message
    assert el.DEFAULT_VOICE_ID in message
