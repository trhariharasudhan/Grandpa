from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from grandpa.server.api_routes import voice_router
from grandpa.voice import (
    SpeechInputEngine,
    SpeechOutputEngine,
    VoiceRuntime,
    WakeWordConfig,
    WakeWordDetector,
)


def test_wake_word_detection_extracts_command():
    detector = WakeWordDetector(WakeWordConfig(enabled=True, phrases=("hey grandpa", "grandpa")))

    match = detector.detect("Hey Grandpa desktop summary")

    assert match.matched is True
    assert match.phrase == "hey grandpa"
    assert match.command_text == "desktop summary"
    assert match.confidence > 0.8


def test_disabled_wake_word_does_not_gate_transcript():
    detector = WakeWordDetector(WakeWordConfig(enabled=False))

    match = detector.detect("Grandpa desktop summary")

    assert match.matched is False
    assert match.command_text == "Grandpa desktop summary"


def test_speech_input_accepts_existing_transcript():
    engine = SpeechInputEngine()

    result = engine.listen(text="open notepad")

    assert result.status == "completed"
    assert result.transcript == "open notepad"
    assert result.engine == "browser_or_mobile_transcript"
    assert result.confidence == 0.99


def test_speech_output_dry_run_and_stop():
    output = SpeechOutputEngine()

    spoken = output.speak("Grandpa is ready.", dry_run=True)
    stopped = output.stop()

    assert spoken.status == "dry_run"
    assert spoken.spoken_text == "Grandpa is ready."
    assert stopped["status"] == "stopped"
    assert output.diagnostics()["state"] == "idle"


def test_voice_runtime_blocks_high_risk_voice_action():
    runtime = VoiceRuntime()

    result = runtime.listen(text="Hey Grandpa shutdown the computer")

    assert result["status"] == "blocked"
    assert result["risk_level"] == "HIGH"
    assert result["approval_required"] is True
    assert "approval flow" in result["message"].lower()


def test_voice_runtime_routes_read_only_command(monkeypatch, tmp_path):
    monkeypatch.setenv("GRANDPA_KNOWLEDGE_DB", str(tmp_path / "knowledge.db"))
    monkeypatch.setenv("GRANDPA_PERSONAL_MEMORY_DB", str(tmp_path / "memory.db"))
    monkeypatch.setenv("GRANDPA_KNOWLEDGE_EMBEDDING_MODE", "fallback")
    runtime = VoiceRuntime()

    result = runtime.listen(text="Hey Grandpa desktop summary")

    assert result["status"] in {"handled", "unsupported"}
    assert result["command_text"] == "desktop summary"
    assert result["planner"] is not None
    assert result["knowledge_context"] is not None
    assert result["memory_context"] is not None


def test_voice_runtime_wake_gate():
    runtime = VoiceRuntime()

    result = runtime.listen(text="desktop summary", require_wake_word=True)

    assert result["status"] == "wake_word_not_detected"
    assert result["ok"] is False


def test_voice_api_routes(monkeypatch, tmp_path):
    monkeypatch.setenv("GRANDPA_KNOWLEDGE_DB", str(tmp_path / "knowledge.db"))
    monkeypatch.setenv("GRANDPA_PERSONAL_MEMORY_DB", str(tmp_path / "memory.db"))
    monkeypatch.setenv("GRANDPA_KNOWLEDGE_EMBEDDING_MODE", "fallback")
    app = FastAPI()
    app.include_router(voice_router)
    client = TestClient(app)

    assert client.get("/v1/voice/status").status_code == 200
    assert client.post("/v1/voice/start").json()["status"] == "started"

    listened = client.post("/v1/voice/listen", json={"text": "Hey Grandpa desktop summary"})
    assert listened.status_code == 200
    assert listened.json()["command_text"] == "desktop summary"

    spoken = client.post("/v1/voice/speak", json={"text": "Grandpa voice ready.", "dry_run": True})
    assert spoken.status_code == 200
    assert spoken.json()["status"] == "dry_run"

    assert client.post("/v1/voice/stop").json()["status"] == "stopped"
