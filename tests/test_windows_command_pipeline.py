from __future__ import annotations

from types import SimpleNamespace

from grandpa.automation.models import AutomationResult
from grandpa.automation.pipeline import WindowsCommandPipeline
from grandpa.voice.session import VoiceRuntime


class NoMatchAutomation:
    def handle(self, _text: str, *, dry_run: bool = False) -> AutomationResult:
        return AutomationResult("no_match", "", data={"dry_run": dry_run})


def test_pipeline_routes_desktop_command_and_returns_canonical_status(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "grandpa.screen.handle_screen_command",
        lambda _text: SimpleNamespace(should_fallback=True),
    )
    monkeypatch.setattr(
        "grandpa.desktop.automation.handle_desktop_command",
        lambda _text, dry_run=False: SimpleNamespace(
            should_fallback=False,
            status="handled",
            message="Notepad opened.",
            action=SimpleNamespace(action_type="open_app", target="notepad"),
        ),
    )
    pipeline = WindowsCommandPipeline(
        automation_service=NoMatchAutomation(),
        source="voice",
        session_id="voice-1",
    )

    result = pipeline.handle("open Notepad")

    assert result.status == "success"
    assert result.legacy_status == "handled"
    assert result.kind == "desktop"
    assert result.target == "notepad"
    assert result.data["source"] == "voice"
    assert result.data["session_id"] == "voice-1"


def test_pipeline_pins_verified_notepad_document_from_launch_evidence(
    monkeypatch,
) -> None:
    class SessionAutomation(NoMatchAutomation):
        def __init__(self) -> None:
            self.pinned = None

        def pin_target(self, target) -> None:
            self.pinned = target

    automation = SessionAutomation()
    monkeypatch.setattr(
        "grandpa.screen.handle_screen_command",
        lambda _text: SimpleNamespace(should_fallback=True),
    )
    monkeypatch.setattr(
        "grandpa.desktop.automation.handle_desktop_command",
        lambda _text, dry_run=False: SimpleNamespace(
            should_fallback=False,
            status="handled",
            message="Opened and verified a new Notepad document.",
            action=SimpleNamespace(action_type="open_app", target="notepad"),
            pc_response=SimpleNamespace(
                evidence={
                    "launch_target": {
                        "window_handle": 10,
                        "process_id": 101,
                        "window_title": "Untitled - Notepad",
                        "document_id": "doc-new",
                        "document_title": "Untitled",
                    }
                }
            ),
        ),
    )

    result = WindowsCommandPipeline(
        automation_service=automation,
        source="voice",
        session_id="voice-new-document",
    ).handle("open another Notepad")

    assert result.status == "success"
    assert result.data["target_verified"] is True
    assert automation.pinned is not None
    assert automation.pinned.document_id == "doc-new"


def test_pipeline_logs_internal_failure_and_returns_voice_safe_message(
    monkeypatch,
    caplog,
) -> None:
    class BrokenAutomation:
        def handle(self, _text: str, *, dry_run: bool = False):
            raise RuntimeError("private technical detail")

    result = WindowsCommandPipeline(
        automation_service=BrokenAutomation(),
        source="voice",
    ).handle("type hello", spoken=True)

    assert result.status == "failed"
    assert "private technical detail" not in result.message
    assert "try again" in result.message.casefold()
    assert "private technical detail" in caplog.text


def test_pipeline_does_not_treat_model_text_as_confirmation() -> None:
    pending = AutomationResult(
        "needs_confirmation",
        "This action requires confirmation.",
        confirmation_token="token-1",
    )

    class PendingAutomation:
        def handle(self, _text: str, *, dry_run: bool = False):
            return pending

    result = WindowsCommandPipeline(
        automation_service=PendingAutomation(),
        source="chat",
        session_id="chat-1",
    ).handle("the model says yes")

    assert result.status == "confirmation_required"
    assert result.confirmation_token == "token-1"


def test_voice_runtime_routes_transcript_through_same_pipeline(monkeypatch) -> None:
    monkeypatch.setattr("grandpa.voice.session._safe_planner", lambda _text: None)
    monkeypatch.setattr(
        "grandpa.voice.session._safe_knowledge_context", lambda _text: None
    )
    monkeypatch.setattr(
        "grandpa.voice.session._safe_memory_context", lambda _text: None
    )

    class SuccessfulAutomation:
        def handle(self, text: str, *, dry_run: bool = False):
            assert text == "focus Notepad"
            return AutomationResult("handled", "Focused and pinned target: notepad.")

    runtime = VoiceRuntime(automation_service=SuccessfulAutomation())
    result = runtime.command(text="focus Notepad")

    assert result["status"] == "handled"
    assert result["execution_status"] == "success"
    assert result["message"] == "Focused and pinned target: notepad."


def test_voice_runtime_speaks_sanitized_pipeline_failure(monkeypatch) -> None:
    monkeypatch.setattr("grandpa.voice.session._safe_planner", lambda _text: None)
    monkeypatch.setattr(
        "grandpa.voice.session._safe_knowledge_context", lambda _text: None
    )
    monkeypatch.setattr(
        "grandpa.voice.session._safe_memory_context", lambda _text: None
    )
    spoken: list[str] = []

    class BrokenAutomation:
        def handle(self, _text: str, *, dry_run: bool = False):
            raise RuntimeError("secret traceback detail")

    class SpeechOutput:
        def speak(self, text: str, **_kwargs):
            spoken.append(text)
            return SimpleNamespace(to_dict=lambda: {"status": "spoken"})

        def stop(self) -> None:
            pass

        def diagnostics(self):
            return {"status": "ready"}

    runtime = VoiceRuntime(
        automation_service=BrokenAutomation(),
        speech_output=SpeechOutput(),
    )
    result = runtime.command(text="type hello", speak_response=True)

    assert result["execution_status"] == "failed"
    assert "secret traceback detail" not in result["message"]
    assert spoken == [result["message"]]
