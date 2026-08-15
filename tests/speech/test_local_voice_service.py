from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from grandpa.voice_service.service import (
    DEFAULT_CFG_STRENGTH,
    DEFAULT_CPU_THREADS,
    DEFAULT_HOST,
    DEFAULT_NFE_STEP,
    DEFAULT_PORT,
    MAX_TEXT_LENGTH,
    SynthesizeRequest,
    VoiceServiceRuntime,
    create_app,
)


class FakeModel:
    def infer(self, **kwargs):
        assert kwargs["gen_text"] == "Hello"
        assert kwargs["speed"] == 1.25
        assert kwargs["nfe_step"] == DEFAULT_NFE_STEP
        assert kwargs["cfg_strength"] == DEFAULT_CFG_STRENGTH
        return [1, 2, 3], 24000, None


class PassthroughProcessor:
    def process(self, audio: bytes) -> bytes:
        return audio


class PrefixProcessor:
    def process(self, audio: bytes) -> bytes:
        return b"processed-" + audio


def _ready_runtime(reference: Path) -> VoiceServiceRuntime:
    return VoiceServiceRuntime(
        reference_audio=str(reference),
        reference_text="Reference text",
        model_loader=FakeModel,
        audio_encoder=lambda wav, rate: b"RIFF-fake-wav",
        cpu_thread_configurer=lambda _threads: None,
        character_processor=PassthroughProcessor(),
    )


def test_service_defaults_to_dedicated_loopback_port():
    assert DEFAULT_HOST == "127.0.0.1"
    assert DEFAULT_PORT == 8765


def test_runtime_uses_proven_cpu_inference_defaults(tmp_path):
    reference = tmp_path / "reference.wav"
    reference.write_bytes(b"reference")
    configured_threads = []
    runtime = VoiceServiceRuntime(
        reference_audio=str(reference),
        reference_text="Reference text",
        model_loader=FakeModel,
        audio_encoder=lambda wav, rate: b"RIFF-fake-wav",
        cpu_thread_configurer=configured_threads.append,
        character_processor=PassthroughProcessor(),
    )

    runtime.initialize()

    assert configured_threads == [DEFAULT_CPU_THREADS]
    assert runtime.nfe_step == 8
    assert runtime.cfg_strength == 0.0


def test_zero_cfg_is_passed_explicitly(tmp_path):
    reference = tmp_path / "reference.wav"
    reference.write_bytes(b"reference")
    captured = {}

    class CapturingModel:
        def infer(self, **kwargs):
            captured.update(kwargs)
            return [1, 2, 3], 24000, None

    runtime = VoiceServiceRuntime(
        reference_audio=str(reference),
        reference_text="Reference text",
        model_loader=CapturingModel,
        audio_encoder=lambda wav, rate: b"RIFF-fake-wav",
        cpu_thread_configurer=lambda _threads: None,
        cfg_strength=0.0,
        character_processor=PassthroughProcessor(),
    )
    runtime.initialize()

    runtime.synthesize(SynthesizeRequest(text="Hello"))

    assert "cfg_strength" in captured
    assert captured["cfg_strength"] == 0.0
    assert captured["nfe_step"] == 8
    assert runtime.last_raw_audio == b"RIFF-fake-wav"


def test_missing_f5_reports_not_ready(monkeypatch):
    monkeypatch.setattr(
        "grandpa.voice_service.service.importlib.util.find_spec", lambda name: None
    )
    runtime = VoiceServiceRuntime()

    runtime.initialize()

    assert runtime.health_payload() == {
        "ready": False,
        "engine": "f5",
        "reason": "dependency_not_installed",
        "voice_id": "grandpa",
    }


def test_missing_reference_transcript_reports_not_ready(tmp_path, monkeypatch):
    reference = tmp_path / "reference.wav"
    reference.write_bytes(b"reference")
    monkeypatch.setattr(
        "grandpa.voice_service.service.importlib.util.find_spec", lambda name: object()
    )
    runtime = VoiceServiceRuntime(
        reference_audio=str(reference),
        reference_text="",
        model_loader=FakeModel,
    )

    runtime.initialize()

    assert runtime.health_payload()["reason"] == "reference_text_invalid"


def test_unavailable_service_refuses_synthesis(monkeypatch):
    monkeypatch.setattr(
        "grandpa.voice_service.service.importlib.util.find_spec", lambda name: None
    )
    runtime = VoiceServiceRuntime()
    runtime.initialize()

    with TestClient(create_app(runtime)) as client:
        response = client.post(
            "/synthesize",
            json={"text": "Hello", "voice_id": "grandpa", "speed": 1.0},
        )

    assert response.status_code == 503
    assert response.json()["detail"]["reason"] == "dependency_not_installed"


def test_ready_service_returns_wav_from_server_owned_reference(tmp_path):
    reference = tmp_path / "reference.wav"
    reference.write_bytes(b"reference")
    runtime = _ready_runtime(reference)

    with TestClient(create_app(runtime)) as client:
        response = client.post(
            "/synthesize",
            json={"text": "Hello", "voice_id": "grandpa", "speed": 1.25},
        )

    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert response.content == b"RIFF-fake-wav"


def test_service_returns_processed_audio_and_retains_raw_for_diagnostics(tmp_path):
    reference = tmp_path / "reference.wav"
    reference.write_bytes(b"reference")
    runtime = VoiceServiceRuntime(
        reference_audio=str(reference),
        reference_text="Reference text",
        model_loader=FakeModel,
        audio_encoder=lambda wav, rate: b"RIFF-raw-wav",
        cpu_thread_configurer=lambda _threads: None,
        character_processor=PrefixProcessor(),
    )

    with TestClient(create_app(runtime)) as client:
        response = client.post(
            "/synthesize",
            json={"text": "Hello", "voice_id": "grandpa", "speed": 1.25},
        )

    assert response.content == b"processed-RIFF-raw-wav"
    assert runtime.last_raw_audio == b"RIFF-raw-wav"


def test_runtime_reuses_one_loaded_model_across_syntheses(tmp_path):
    reference = tmp_path / "reference.wav"
    reference.write_bytes(b"reference")
    loads = []

    def load_model():
        loads.append("loaded")
        return FakeModel()

    runtime = VoiceServiceRuntime(
        reference_audio=str(reference),
        reference_text="Reference text",
        model_loader=load_model,
        audio_encoder=lambda wav, rate: b"RIFF-fake-wav",
        cpu_thread_configurer=lambda _threads: None,
        character_processor=PassthroughProcessor(),
    )
    runtime.initialize()

    runtime.synthesize(SynthesizeRequest(text="Hello", speed=1.25))
    runtime.synthesize(SynthesizeRequest(text="Hello", speed=1.25))

    assert loads == ["loaded"]


def test_service_rejects_unbounded_or_unknown_request_fields(tmp_path):
    reference = tmp_path / "reference.wav"
    reference.write_bytes(b"reference")
    runtime = _ready_runtime(reference)

    with TestClient(create_app(runtime)) as client:
        too_long = client.post(
            "/synthesize",
            json={"text": "x" * (MAX_TEXT_LENGTH + 1)},
        )
        bad_speed = client.post("/synthesize", json={"text": "Hello", "speed": 10})
        bad_voice = client.post(
            "/synthesize", json={"text": "Hello", "voice_id": "other"}
        )
        injected_path = client.post(
            "/synthesize",
            json={"text": "Hello", "reference_audio": "C:/secret.wav"},
        )

    assert {too_long.status_code, bad_speed.status_code, bad_voice.status_code} == {422}
    assert injected_path.status_code == 422


def test_service_exposes_only_health_and_synthesize(tmp_path):
    reference = tmp_path / "reference.wav"
    reference.write_bytes(b"reference")
    app = create_app(_ready_runtime(reference))
    paths = {route.path for route in app.routes}

    assert paths == {"/health", "/synthesize"}
