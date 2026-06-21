from __future__ import annotations

import base64
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import grandpa.local_actions as local_actions
import grandpa.voice.speech_output as speech_output
from grandpa.local_action_approvals import LocalActionApprovalStore
from grandpa.memory.context import ConversationContextBuilder
from grandpa.memory.conversation import MAX_CONVERSATION_MESSAGES, ConversationSession
from grandpa.reminders import ReminderStore
from grandpa.server.api_routes import conversation_router, voice_router
from grandpa.speech._stubs import TranscriptionResult
from grandpa.voice import (
    SpeechInputEngine,
    SpeechInputResult,
    SpeechOutputEngine,
    VoiceDependencyError,
    VoiceRecognitionError,
    VoiceRuntime,
    WakeWordConfig,
    WakeWordDetector,
)
from grandpa.voice.history import VOICE_HISTORY_LIMIT, VoiceCommandHistoryStore
from grandpa.voice.loop import VoiceLoopSession
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
    app.include_router(conversation_router)
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


def test_voice_listen_api_accepts_browser_transcript(voice_client):
    response = voice_client.post("/v1/voice/listen", json={"text": "open notepad"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["transcript"] == "open notepad"
    assert body["speech_input"]["engine"] == "browser_or_mobile_transcript"


def test_voice_listen_api_audio_missing_dependency_is_friendly(monkeypatch, voice_client):
    monkeypatch.setattr("grandpa.voice.session._RUNTIME", None)
    monkeypatch.setattr("grandpa.voice.speech_input.importlib.util.find_spec", lambda _name: None)

    response = voice_client.post(
        "/v1/voice/listen",
        json={"audio_base64": base64.b64encode(b"audio").decode("ascii")},
    )

    assert response.status_code == 503
    assert "Voice mode is not fully installed." in response.json()["detail"]
    assert "uv sync --extra speech" in response.json()["detail"]


def test_voice_listen_api_invalid_audio_is_friendly(monkeypatch, voice_client):
    class InvalidAudioBackend:
        def transcribe(self, *_args, **_kwargs):
            raise RuntimeError("invalid audio data")

    monkeypatch.setattr("grandpa.voice.session._RUNTIME", None)
    monkeypatch.setattr("grandpa.voice.speech_input.importlib.util.find_spec", lambda _name: object())
    monkeypatch.setattr(SpeechInputEngine, "_create_backend", lambda _self: InvalidAudioBackend())

    response = voice_client.post(
        "/v1/voice/listen",
        json={"audio_base64": base64.b64encode(b"not real audio").decode("ascii")},
    )

    assert response.status_code == 422
    assert "I could not understand the audio." in response.json()["detail"]


def test_voice_stt_status_endpoint_reports_model(monkeypatch, voice_client):
    monkeypatch.setattr("grandpa.voice.speech_input.importlib.util.find_spec", lambda _name: object())

    response = voice_client.get("/v1/voice/stt/status")

    assert response.status_code == 200
    body = response.json()
    assert body["engine"] == "faster_whisper"
    assert body["model"]
    assert body["ready"] is True
    assert body["device"]
    assert body["compute_type"]


def test_voice_doctor_endpoint_returns_checks(voice_client):
    response = voice_client.get("/v1/voice/doctor")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["checks"]
    assert {check["status"] for check in body["checks"]}.issubset({"pass", "warn", "fail"})
    assert "server import" in {check["name"] for check in body["checks"]}
    assert "voice command logic" in {check["name"] for check in body["checks"]}


def test_voice_doctor_missing_speech_dependency_warns(monkeypatch):
    from grandpa.voice.doctor import run_voice_doctor

    monkeypatch.setattr(
        "grandpa.voice.doctor.importlib.util.find_spec",
        lambda _name: None,
    )

    body = run_voice_doctor(
        voice_status_provider=lambda: {"mode": "browser_transcript"},
        stt_status_provider=lambda: {
            "engine": "push_to_talk_transcript",
            "model": "base",
            "ready": False,
        },
        wake_word_status_provider=lambda: {"wake_phrase": "hey grandpa"},
        loop_status_provider=lambda: {"mode": "idle"},
        conversation_status_provider=lambda: {"message_count": 0},
        voice_history_provider=lambda: [],
        command_provider=lambda: {"ok": True, "status": "handled"},
    )

    dependency_check = next(check for check in body["checks"] if check["name"] == "speech dependencies")
    model_check = next(check for check in body["checks"] if check["name"] == "local model readiness")

    assert dependency_check["status"] == "warn"
    assert model_check["status"] == "warn"
    assert body["ok"] is True


def test_speech_input_successful_local_whisper_transcription(monkeypatch):
    class FakeBackend:
        def transcribe(self, audio: bytes, *, format: str = "wav", language: str | None = None):
            assert audio == b"audio"
            assert format == "webm"
            assert language is None
            return TranscriptionResult(
                text="hello grandpa",
                language="en",
                confidence=0.91,
                duration_seconds=1.25,
            )

    monkeypatch.setattr("grandpa.voice.speech_input.importlib.util.find_spec", lambda _name: object())
    monkeypatch.setattr(SpeechInputEngine, "_create_backend", lambda _self: FakeBackend())

    result = SpeechInputEngine().listen(audio_bytes=b"audio", audio_format="webm")

    assert result.status == "completed"
    assert result.transcript == "hello grandpa"
    assert result.language == "en"
    assert result.duration_seconds == 1.25
    assert result.engine == "faster_whisper"


def test_speech_input_empty_audio_is_friendly():
    with pytest.raises(VoiceRecognitionError) as excinfo:
        SpeechInputEngine().listen(audio_bytes=b"", audio_format="wav")

    assert "Empty audio was received." in str(excinfo.value.detail)


def test_speech_input_missing_model_is_friendly(monkeypatch):
    class MissingModelBackend:
        def transcribe(self, *_args, **_kwargs):
            raise RuntimeError("model not found")

    monkeypatch.setattr("grandpa.voice.speech_input.importlib.util.find_spec", lambda _name: object())
    monkeypatch.setattr(SpeechInputEngine, "_create_backend", lambda _self: MissingModelBackend())

    with pytest.raises(VoiceDependencyError) as excinfo:
        SpeechInputEngine().listen(audio_bytes=b"audio", audio_format="wav")

    assert "Local Whisper model is missing" in str(excinfo.value)


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


def test_conversation_session_creation_and_message_add():
    session = ConversationSession()

    user = session.add_user_message("hello")
    assistant = session.add_assistant_message("hi there")
    history = session.history()

    assert history["session_id"] == session.session_id
    assert history["message_count"] == 2
    assert user["role"] == "user"
    assert assistant["role"] == "assistant"
    assert history["messages"][0]["content"] == "hello"


def test_conversation_session_keeps_latest_20_messages():
    session = ConversationSession()

    for index in range(MAX_CONVERSATION_MESSAGES + 5):
        session.add_user_message(f"message {index}")

    history = session.history()

    assert history["message_count"] == MAX_CONVERSATION_MESSAGES
    assert history["messages"][0]["content"] == "message 5"
    assert history["messages"][-1]["content"] == f"message {MAX_CONVERSATION_MESSAGES + 4}"


def test_conversation_session_clear_and_summary():
    session = ConversationSession()
    session.add_user_message("what is my voice status")
    session.add_assistant_message("Voice push-to-talk is ready.")

    summary = session.summary()
    cleared = session.clear()

    assert "what is my voice status" in summary["summary"]
    assert cleared["cleared"] == 2
    assert session.history()["messages"] == []


def test_conversation_api_endpoints(voice_client):
    status = voice_client.get("/v1/conversation/status")
    history = voice_client.get("/v1/conversation/history")
    summary = voice_client.post("/v1/conversation/summary")
    cleared = voice_client.post("/v1/conversation/clear")

    assert status.status_code == 200
    assert status.json()["message_count"] == 0
    assert history.json()["messages"] == []
    assert summary.json()["summary"] == "No recent conversation yet."
    assert cleared.json()["status"] == "cleared"


def test_conversation_context_builder_uses_latest_n_messages():
    session = ConversationSession()
    for index in range(5):
        session.add_user_message(f"user {index}")

    context = ConversationContextBuilder(session, max_messages=3).build()

    assert context["message_count"] == 3
    assert [message["content"] for message in context["messages"]] == [
        "user 2",
        "user 3",
        "user 4",
    ]
    assert context["context_text"] == "user: user 2\nuser: user 3\nuser: user 4"


def test_conversation_context_builder_trims_by_max_chars():
    session = ConversationSession()
    session.add_user_message("alpha beta gamma")
    session.add_assistant_message("delta epsilon")

    context = ConversationContextBuilder(session, max_messages=6, max_chars=24).build()

    assert len(context["context_text"]) <= 24
    assert context["message_count"] >= 1


def test_conversation_context_builder_ignores_empty_messages_and_preserves_order():
    session = ConversationSession()
    session.add_user_message("first")
    session.add_user_message("   ")
    session.add_assistant_message("second")

    context = ConversationContextBuilder(session).build()

    assert [message["role"] for message in context["messages"]] == ["user", "assistant"]
    assert [message["content"] for message in context["messages"]] == ["first", "second"]


def test_conversation_context_endpoint(voice_client):
    voice_client.post("/v1/voice/command", json={"transcript": "what is my voice status"})

    response = voice_client.get("/v1/conversation/context?max_messages=1&max_chars=200")

    assert response.status_code == 200
    body = response.json()
    assert body["message_count"] == 1
    assert len(body["messages"]) == 1
    assert body["context_text"]


def test_voice_command_returns_context_metadata(voice_client):
    first = voice_client.post(
        "/v1/voice/command",
        json={"transcript": "what is my voice status"},
    ).json()
    second = voice_client.post(
        "/v1/voice/command",
        json={"transcript": "tell me more about that"},
    ).json()

    assert first["context_used"] is False
    assert first["context_message_count"] == 0
    assert second["context_used"] is True
    assert second["context_message_count"] == 2
    assert second["assistant_text"] == "I can use recent context, but I don't know how to answer that yet."


def test_clear_conversation_resets_context(voice_client):
    voice_client.post("/v1/voice/command", json={"transcript": "what is my voice status"})
    voice_client.post("/v1/conversation/clear")

    context = voice_client.get("/v1/conversation/context").json()
    result = voice_client.post(
        "/v1/voice/command",
        json={"transcript": "tell me more"},
    ).json()

    assert context["message_count"] == 0
    assert context["context_text"] == ""
    assert result["context_used"] is False
    assert result["context_message_count"] == 0


def test_voice_context_has_no_ollama_dependency(voice_client, monkeypatch):
    monkeypatch.delenv("OLLAMA_HOST", raising=False)

    response = voice_client.post(
        "/v1/voice/command",
        json={"transcript": "tell me a story about Saturn"},
    )

    assert response.status_code == 200
    assert response.json()["assistant_text"] == "I don't know how to do that yet."


def test_voice_command_records_conversation_exchange(voice_client):
    response = voice_client.post(
        "/v1/voice/command",
        json={"transcript": "what is my voice status"},
    )
    history = voice_client.get("/v1/conversation/history")

    assert response.status_code == 200
    messages = history.json()["messages"]
    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "what is my voice status"
    assert messages[1]["role"] == "assistant"
    assert messages[1]["content"]


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


def test_voice_loop_defaults_disabled_and_stopped(tmp_path):
    loop = VoiceLoopSession(WakeWordSession(tmp_path / "wake_word.json"))

    status = loop.status()

    assert status["enabled"] is False
    assert status["running"] is False
    assert status["mode"] == "idle"
    assert status["microphone_required"] is False
    assert status["background_thread"] is False


def test_voice_loop_cannot_start_if_wake_word_disabled(tmp_path):
    loop = VoiceLoopSession(WakeWordSession(tmp_path / "wake_word.json"))
    loop.enable()

    status = loop.start()

    assert status["running"] is False
    assert status["mode"] == "error"
    assert status["last_error"] == "Wake word must be enabled before starting the voice loop."


def test_voice_loop_starts_after_wake_word_enabled(tmp_path):
    wake = WakeWordSession(tmp_path / "wake_word.json")
    wake.enable()
    loop = VoiceLoopSession(wake)
    loop.enable()

    status = loop.start()

    assert status["running"] is True
    assert status["mode"] == "waiting_for_wake_word"


def test_voice_loop_stop_returns_idle(tmp_path):
    wake = WakeWordSession(tmp_path / "wake_word.json")
    wake.enable()
    loop = VoiceLoopSession(wake)
    loop.enable()
    loop.start()

    status = loop.stop()

    assert status["running"] is False
    assert status["mode"] == "idle"


def test_voice_loop_simulate_wake_detected(tmp_path):
    wake = WakeWordSession(tmp_path / "wake_word.json")
    wake.enable()
    loop = VoiceLoopSession(wake)
    loop.enable()
    loop.start()

    result = loop.simulate_wake("HEY GRANDPA")

    assert result["detected"] is True
    assert result["mode"] == "listening_for_command"
    assert result["last_wake_detected_at"] is not None


def test_voice_loop_simulate_wake_invalid_returns_to_waiting(tmp_path):
    wake = WakeWordSession(tmp_path / "wake_word.json")
    wake.enable()
    loop = VoiceLoopSession(wake)
    loop.enable()
    loop.start()

    result = loop.simulate_wake("hello assistant")

    assert result["detected"] is False
    assert result["mode"] == "waiting_for_wake_word"


def test_voice_loop_simulate_command_routes_with_mocked_handler(tmp_path):
    wake = WakeWordSession(tmp_path / "wake_word.json")
    wake.enable()
    routed: list[str] = []

    def fake_router(transcript: str):
        routed.append(transcript)
        return {
            "assistant_text": "Done.",
            "action": {"type": "none", "status": "handled", "detail": "Done."},
        }

    loop = VoiceLoopSession(wake, command_router=fake_router)
    loop.enable()
    loop.start()
    loop.simulate_wake("hey grandpa")

    result = loop.simulate_command("what is my voice status")

    assert routed == ["what is my voice status"]
    assert result["mode"] == "waiting_for_wake_word"
    assert result["last_command_transcript"] == "what is my voice status"
    assert result["command"]["assistant_text"] == "Done."


def test_voice_loop_api_cannot_start_if_wake_word_disabled(voice_client):
    voice_client.post("/v1/voice/loop/enable")

    response = voice_client.post("/v1/voice/loop/start")

    assert response.status_code == 200
    body = response.json()
    assert body["running"] is False
    assert body["mode"] == "error"
    assert body["last_error"] == "Wake word must be enabled before starting the voice loop."


def test_voice_loop_api_simulates_wake_and_command(voice_client):
    voice_client.post("/v1/voice/wake-word/enable")
    voice_client.post("/v1/voice/loop/enable")
    started = voice_client.post("/v1/voice/loop/start")
    wake = voice_client.post("/v1/voice/loop/simulate-wake", json={"text": "hey grandpa"})
    command = voice_client.post(
        "/v1/voice/loop/simulate-command",
        json={"transcript": "what is my voice status"},
    )

    assert started.json()["mode"] == "waiting_for_wake_word"
    assert wake.json()["detected"] is True
    assert wake.json()["mode"] == "listening_for_command"
    assert command.status_code == 200
    body = command.json()
    assert body["mode"] == "waiting_for_wake_word"
    assert body["last_command_transcript"] == "what is my voice status"
    assert body["command"]["action"]["status"] == "handled"


def test_voice_loop_api_stop(voice_client):
    voice_client.post("/v1/voice/wake-word/enable")
    voice_client.post("/v1/voice/loop/enable")
    voice_client.post("/v1/voice/loop/start")

    response = voice_client.post("/v1/voice/loop/stop")

    assert response.status_code == 200
    assert response.json()["running"] is False
    assert response.json()["mode"] == "idle"


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
