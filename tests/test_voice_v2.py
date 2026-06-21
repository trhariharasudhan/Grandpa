from __future__ import annotations

import base64
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import grandpa.local_actions as local_actions
import grandpa.voice.speech_output as speech_output
from grandpa.local_action_approvals import LocalActionApprovalStore
from grandpa.reminders import ReminderStore
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
from grandpa.voice.history import VOICE_HISTORY_LIMIT, VoiceCommandHistoryStore
from grandpa.voice.wake_word import DEFAULT_WAKE_PHRASE, WakeWordSession

pytestmark = pytest.mark.core


@pytest.fixture
def voice_client(tmp_path, monkeypatch):
    monkeypatch.setenv("GRANDPA_KNOWLEDGE_DB", str(tmp_path / "knowledge.db"))
    monkeypatch.setenv("GRANDPA_PERSONAL_MEMORY_DB", str(tmp_path / "memory.db"))
    monkeypatch.setenv("GRANDPA_KNOWLEDGE_EMBEDDING_MODE", "fallback")
    approval_store = LocalActionApprovalStore(tmp_path / "approvals.db")
    reminder_store = ReminderStore(tmp_path / "reminders.db")
    monkeypatch.setattr(local_actions, "LocalActionApprovalStore", lambda: approval_store)
    app = FastAPI()
    app.state.reminder_store = reminder_store
    app.state.voice_history_store = VoiceCommandHistoryStore(tmp_path / "voice_history.db")
    app.state.wake_word_session = WakeWordSession(tmp_path / "wake_word.json")
    app.include_router(voice_router)
    return TestClient(app)


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


def test_voice_runtime_capture_browser_transcript():
    runtime = VoiceRuntime()

    result = runtime.capture(text="turn on voice mode")

    assert result["ok"] is True
    assert result["status"] == "completed"
    assert result["transcript"] == "turn on voice mode"
    assert result["confidence"] == 0.99


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

    assert result["status"] == "tts_unavailable"
    assert "Voice output is not available." in result["message"]
    assert "text-to-speech backend" in result["message"]


def test_voice_runtime_speak_mocked_success():
    class ReadyOutput:
        def speak(self, text, **_kwargs):
            from grandpa.voice import SpeechOutputResult

            return SpeechOutputResult("completed", "mock_tts", "spoken", text)

        def stop(self):
            return {"status": "stopped"}

        def diagnostics(self):
            return {"status": "ready", "engine": "mock_tts"}

    runtime = VoiceRuntime(speech_output=ReadyOutput())  # type: ignore[arg-type]

    result = runtime.speak("Hello Grandpa")

    assert result["status"] == "completed"
    assert result["engine"] == "mock_tts"


def test_voice_runtime_blocks_high_risk_voice_action():
    runtime = VoiceRuntime()

    result = runtime.listen(text="Hey Grandpa shutdown the computer")

    assert result["status"] == "blocked"
    assert result["risk_level"] == "HIGH"
    assert result["approval_required"] is True
    assert "approval flow" in result["message"].lower()


def test_voice_runtime_command_text_path_does_not_bypass_action_permissions():
    runtime = VoiceRuntime()

    result = runtime.command(text="delete all files on my desktop")

    assert result["status"] == "blocked"
    assert result["approval_required"] is True
    assert result["risk_level"] == "HIGH"


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
    assert listened.json()["transcript"] == "Hey Grandpa desktop summary"

    commanded = client.post("/v1/voice/command", json={"transcript": "Hey Grandpa desktop summary"})
    assert commanded.status_code == 200
    assert commanded.json()["command_text"] == "desktop summary"
    assert commanded.json()["assistant_text"]

    spoken = client.post("/v1/voice/speak", json={"text": "Grandpa voice ready.", "dry_run": True})
    assert spoken.status_code == 200
    assert spoken.json()["status"] == "dry_run"

    assert client.post("/v1/voice/stop").json()["status"] == "stopped"


def test_voice_command_routes_desktop_action_to_confirmation(voice_client):
    response = voice_client.post(
        "/v1/voice/command",
        json={"transcript": "type hello in notepad"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["transcript"] == "type hello in notepad"
    assert body["action"]["type"] == "desktop"
    assert body["action"]["status"] == "needs_confirmation"
    assert body["action"]["message"] == "This action needs confirmation."
    assert body["confirmation_token"] == body["action"]["pending_action"]["id"]
    assert body["action"]["kind"] == "automation"
    assert body["action"]["target"] == "focus|notepad||type|hello"
    assert body["action"]["pending_action"]["id"]


def test_voice_command_confirmed_desktop_action_executes_with_mocked_automation(
    monkeypatch,
    voice_client,
):
    calls: list[str] = []

    monkeypatch.setattr(local_actions.sys, "platform", "win32")

    def fake_execute_automation(spec: str):
        from grandpa.desktop_automation import AutomationResult

        calls.append(spec)
        return AutomationResult("handled", spec, "Typed hello.", "Typed hello.")

    monkeypatch.setattr(
        "grandpa.desktop_automation.execute_automation",
        fake_execute_automation,
    )

    response = voice_client.post(
        "/v1/voice/command",
        json={"transcript": "type hello in notepad", "confirmed": True},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["action"]["type"] == "desktop"
    assert body["action"]["status"] == "handled"
    assert body["assistant_text"] == "Done."
    assert calls == ["focus|notepad||type|hello"]


def test_voice_confirm_token_executes_with_mocked_automation(monkeypatch, voice_client):
    calls: list[str] = []
    monkeypatch.setattr(local_actions.sys, "platform", "win32")

    def fake_execute_automation(spec: str):
        from grandpa.desktop_automation import AutomationResult

        calls.append(spec)
        return AutomationResult("handled", spec, "Typed hello.", "Typed hello.")

    monkeypatch.setattr(
        "grandpa.desktop_automation.execute_automation",
        fake_execute_automation,
    )

    pending = voice_client.post(
        "/v1/voice/command",
        json={"transcript": "type hello in notepad"},
    ).json()

    response = voice_client.post(
        "/v1/voice/confirm",
        json={"confirmation_token": pending["confirmation_token"]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["action"]["status"] == "handled"
    assert body["assistant_text"] == "Done."
    assert calls == ["focus|notepad||type|hello"]


def test_voice_confirm_token_cannot_be_reused(monkeypatch, voice_client):
    monkeypatch.setattr(local_actions.sys, "platform", "win32")

    def fake_execute_automation(spec: str):
        from grandpa.desktop_automation import AutomationResult

        return AutomationResult("handled", spec, "Typed hello.", "Typed hello.")

    monkeypatch.setattr(
        "grandpa.desktop_automation.execute_automation",
        fake_execute_automation,
    )
    pending = voice_client.post(
        "/v1/voice/command",
        json={"transcript": "type hello in notepad"},
    ).json()

    first = voice_client.post(
        "/v1/voice/confirm",
        json={"confirmation_token": pending["confirmation_token"]},
    )
    second = voice_client.post(
        "/v1/voice/confirm",
        json={"confirmation_token": pending["confirmation_token"]},
    )

    assert first.json()["action"]["status"] == "handled"
    assert second.json()["action"]["status"] == "blocked"
    assert second.json()["assistant_text"] == "That action is blocked for safety."


def test_voice_command_blocked_command_returns_blocked(voice_client):
    response = voice_client.post(
        "/v1/voice/command",
        json={"transcript": "delete system32"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["action"]["type"] == "desktop"
    assert body["action"]["status"] == "blocked"
    assert body["assistant_text"] == "That action is blocked for safety."
    assert body["ok"] is False


def test_voice_command_reminder_creates_reminder(monkeypatch, voice_client):
    monkeypatch.setattr(
        "grandpa.reminder_parser.default_reminder_timezone",
        lambda: UTC,
    )

    response = voice_client.post(
        "/v1/voice/command",
        json={"transcript": "remind me tomorrow at 7 PM to call Arjun"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["action"]["type"] == "reminder"
    assert body["action"]["status"] == "handled"
    assert body["assistant_text"] == "Reminder created successfully."
    assert body["reminder"]["message"] == "call Arjun"
    assert datetime.fromisoformat(body["reminder"]["due_at"]).tzinfo is not None


def test_voice_command_unsupported_returns_friendly_response(voice_client):
    response = voice_client.post(
        "/v1/voice/command",
        json={"transcript": "tell me a story about Saturn"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["action"]["type"] == "chat"
    assert body["action"]["status"] == "unsupported"
    assert body["assistant_text"] == "I don't know how to do that yet."


def test_voice_command_missing_transcript_returns_validation_error(voice_client):
    response = voice_client.post("/v1/voice/command", json={})

    assert response.status_code == 400
    assert response.json()["detail"] == "I didn't hear anything."


def test_voice_history_records_commands(voice_client):
    voice_client.post("/v1/voice/command", json={"transcript": "what is my voice status"})

    response = voice_client.get("/v1/voice/history")

    assert response.status_code == 200
    history = response.json()["history"]
    assert len(history) == 1
    assert history[0]["transcript"] == "what is my voice status"
    assert history[0]["action_type"] == "none"
    assert history[0]["action_status"] == "handled"


def test_voice_history_limit(voice_client):
    for index in range(VOICE_HISTORY_LIMIT + 5):
        voice_client.post(
            "/v1/voice/command",
            json={"transcript": f"unsupported command {index}"},
        )

    history = voice_client.get("/v1/voice/history").json()["history"]

    assert len(history) == VOICE_HISTORY_LIMIT
    assert history[0]["transcript"] == f"unsupported command {VOICE_HISTORY_LIMIT + 4}"
    assert history[-1]["transcript"] == "unsupported command 5"


def test_voice_history_clear(voice_client):
    voice_client.post("/v1/voice/command", json={"transcript": "what is my voice status"})

    cleared = voice_client.post("/v1/voice/history/clear")
    history = voice_client.get("/v1/voice/history")

    assert cleared.status_code == 200
    assert cleared.json()["status"] == "cleared"
    assert history.json()["history"] == []


def test_wake_word_session_defaults_disabled(tmp_path):
    session = WakeWordSession(tmp_path / "wake_word.json")

    status = session.status()

    assert status["enabled"] is False
    assert status["listening"] is False
    assert status["wake_phrase"] == DEFAULT_WAKE_PHRASE
    assert status["always_listening"] is False
    assert status["microphone_required"] is False


def test_wake_word_api_status_default_disabled(voice_client):
    response = voice_client.get("/v1/voice/wake-word/status")

    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is False
    assert body["listening"] is False
    assert body["wake_phrase"] == DEFAULT_WAKE_PHRASE


def test_wake_word_api_enable_and_disable(voice_client):
    enabled = voice_client.post("/v1/voice/wake-word/enable")
    disabled = voice_client.post("/v1/voice/wake-word/disable")

    assert enabled.status_code == 200
    assert enabled.json()["enabled"] is True
    assert enabled.json()["listening"] is True
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False
    assert disabled.json()["listening"] is False


def test_wake_word_test_detects_mock_phrase_case_insensitive(voice_client):
    voice_client.post("/v1/voice/wake-word/enable")

    response = voice_client.post(
        "/v1/voice/wake-word/test",
        json={"text": "HEY GRANDPA are you there"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["detected"] is True
    assert body["phrase"] == DEFAULT_WAKE_PHRASE
    assert body["last_detection_time"]


def test_wake_word_test_rejects_invalid_phrase(voice_client):
    voice_client.post("/v1/voice/wake-word/enable")

    response = voice_client.post(
        "/v1/voice/wake-word/test",
        json={"text": "hello assistant"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["detected"] is False
    assert body["phrase"] == DEFAULT_WAKE_PHRASE
    assert body["last_detection_time"] is None


def test_wake_word_test_does_not_detect_when_disabled(voice_client):
    response = voice_client.post(
        "/v1/voice/wake-word/test",
        json={"text": "hey grandpa"},
    )

    assert response.status_code == 200
    assert response.json()["detected"] is False


def test_wake_word_session_persists_enabled_and_phrase(tmp_path):
    settings_path = tmp_path / "wake_word.json"
    session = WakeWordSession(settings_path)
    session.wake_phrase = "grandpa computer"
    session.enable()

    reloaded = WakeWordSession(settings_path)

    assert reloaded.status()["enabled"] is True
    assert reloaded.status()["listening"] is True
    assert reloaded.status()["wake_phrase"] == "grandpa computer"


def test_wake_word_session_mock_detection_updates_time(tmp_path):
    session = WakeWordSession(tmp_path / "wake_word.json")
    session.enable()

    result = session.detect_mock("please listen, hey grandpa")

    assert result["detected"] is True
    assert result["last_detection_time"] is not None
    assert session.status()["last_detection_time"] == result["last_detection_time"]


def test_voice_api_returns_clean_expected_error_status(monkeypatch):
    app = FastAPI()
    app.include_router(voice_router)
    client = TestClient(app)
    monkeypatch.setattr(speech_output.importlib.util, "find_spec", lambda _name: None)
    monkeypatch.setattr(speech_output.platform, "system", lambda: "Linux")

    response = client.post("/v1/voice/speak", json={"text": "Hello"})

    assert response.status_code == 503
    assert "Voice output is not available." in response.json()["detail"]


def test_voice_api_unrelated_runtime_error_is_not_mislabeled(monkeypatch):
    class BuggyRuntime:
        def capture(self, **_kwargs):
            raise RuntimeError("unexpected bug")

    monkeypatch.setattr("grandpa.voice.get_voice_runtime", lambda: BuggyRuntime())
    app = FastAPI()
    app.include_router(voice_router)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post("/v1/voice/listen", json={"text": "hello"})

    assert response.status_code == 500
    assert "Voice mode is not fully installed" not in response.text
