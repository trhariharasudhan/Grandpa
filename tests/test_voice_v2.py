from __future__ import annotations

import base64

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import grandpa.voice.speech_output as speech_output
from grandpa.server.api_routes import voice_router
from grandpa.voice import (
    SpeechInputEngine,
    SpeechInputResult,
    SpeechOutputEngine,
    VoiceRecognitionError,
    VoiceRuntime,
    WakeWordConfig,
    WakeWordDetector,
)

pytestmark = pytest.mark.core


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


def test_voice_runtime_reports_missing_speech_dependency(monkeypatch):
    monkeypatch.setattr("grandpa.voice.speech_input.importlib.util.find_spec", lambda _name: None)
    runtime = VoiceRuntime()

    result = runtime.listen(audio_base64=base64.b64encode(b"audio").decode("ascii"))

    assert result["status"] == "dependency_missing"
    assert "Voice mode is not fully installed." in result["message"]
    assert "uv sync --extra speech" in result["message"]
    assert "Traceback" not in result["message"]


def test_voice_runtime_reports_missing_microphone():
    runtime = VoiceRuntime()

    result = runtime.listen()

    assert result["status"] == "microphone_unavailable"
    assert "No usable microphone was detected." in result["message"]
    assert "Windows microphone permissions" in result["message"]


def test_voice_runtime_recognition_failure_is_clean():
    class FailingInput:
        def listen(self, **_kwargs):
            raise VoiceRecognitionError()

    runtime = VoiceRuntime(speech_input=FailingInput())  # type: ignore[arg-type]

    result = runtime.listen(text="ignored")

    assert result["status"] == "recognition_failed"
    assert "I could not understand the audio." in result["message"]
    assert "Traceback" not in result["message"]


def test_voice_runtime_does_not_mislabel_programming_errors():
    class BuggyInput:
        def listen(self, **_kwargs):
            raise RuntimeError("unexpected bug")

    runtime = VoiceRuntime(speech_input=BuggyInput())  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="unexpected bug"):
        runtime.listen(text="ignored")


def test_voice_runtime_normal_mocked_input_still_works(monkeypatch, tmp_path):
    monkeypatch.setenv("GRANDPA_KNOWLEDGE_DB", str(tmp_path / "knowledge.db"))
    monkeypatch.setenv("GRANDPA_PERSONAL_MEMORY_DB", str(tmp_path / "memory.db"))
    monkeypatch.setenv("GRANDPA_KNOWLEDGE_EMBEDDING_MODE", "fallback")

    class ReadyInput:
        def listen(self, **_kwargs):
            return SpeechInputResult(
                status="completed",
                transcript="Hey Grandpa desktop summary",
                engine="mock",
                confidence=0.98,
            )

    runtime = VoiceRuntime(speech_input=ReadyInput())  # type: ignore[arg-type]

    result = runtime.listen()

    assert result["command_text"] == "desktop summary"
    assert result["speech_input"]["engine"] == "mock"


def test_speech_output_dry_run_and_stop():
    output = SpeechOutputEngine()

    spoken = output.speak("Grandpa is ready.", dry_run=True)
    stopped = output.stop()

    assert spoken.status == "dry_run"
    assert spoken.spoken_text == "Grandpa is ready."
    assert stopped["status"] == "stopped"
    assert output.diagnostics()["state"] == "idle"


def test_voice_speak_reports_missing_tts_dependency(monkeypatch):
    monkeypatch.setattr(speech_output.importlib.util, "find_spec", lambda _name: None)
    monkeypatch.setattr(speech_output.platform, "system", lambda: "Linux")
    runtime = VoiceRuntime()

    result = runtime.speak("Hello Grandpa")

    assert result["status"] == "dependency_missing"
    assert "Voice mode is not fully installed." in result["message"]
    assert "uv sync --extra speech" in result["message"]


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

    missing_input = client.post("/v1/voice/listen", json={})
    assert missing_input.status_code == 400
    assert "No usable microphone was detected." in missing_input.json()["detail"]

    listened = client.post("/v1/voice/listen", json={"text": "Hey Grandpa desktop summary"})
    assert listened.status_code == 200
    assert listened.json()["command_text"] == "desktop summary"

    spoken = client.post("/v1/voice/speak", json={"text": "Grandpa voice ready.", "dry_run": True})
    assert spoken.status_code == 200
    assert spoken.json()["status"] == "dry_run"

    assert client.post("/v1/voice/stop").json()["status"] == "stopped"
