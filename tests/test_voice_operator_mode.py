from types import SimpleNamespace

from grandpa.voice.errors import MicrophoneUnavailableError, VoiceRecognitionError
from grandpa.voice.operator import (
    execute_voice_operator_intent,
    normalize_voice_operator_transcript,
    parse_voice_operator_command,
    run_voice_operator_loop,
)


def test_parse_open_chrome() -> None:
    intent = parse_voice_operator_command("open chrome")

    assert intent.kind == "local_action"
    assert intent.action == "open_app"
    assert intent.target == "chrome"


def test_parse_open_vscode() -> None:
    intent = parse_voice_operator_command("open vs code")

    assert intent.action == "open_app"
    assert intent.target == "vscode"


def test_parse_open_another_notepad_preserves_new_instance_intent() -> None:
    intent = parse_voice_operator_command("open another Notepad")

    assert intent.kind == "local_action"
    assert intent.action == "open_app"
    assert intent.target == "notepad"
    assert intent.args == {"new_instance": True}


def test_normalizes_common_launch_phrases() -> None:
    assert normalize_voice_operator_transcript("start notepad") == "open notepad"
    assert normalize_voice_operator_transcript("launch chrome") == "open chrome"
    assert normalize_voice_operator_transcript("run vscode") == "open vscode"


def test_normalizes_repeated_launch_words_and_app_phrases() -> None:
    assert (
        normalize_voice_operator_transcript("open open open notepad") == "open notepad"
    )
    assert normalize_voice_operator_transcript("Open note pad") == "open notepad"
    assert normalize_voice_operator_transcript("Open note bad") == "open notepad"
    assert normalize_voice_operator_transcript("open chrome browser") == "open chrome"


def test_parse_normalized_launch_commands() -> None:
    cases = [
        ("start notepad", "notepad"),
        ("launch chrome", "chrome"),
        ("run vscode", "vscode"),
        ("open open open notepad", "notepad"),
        ("open note pad", "notepad"),
    ]

    for transcript, target in cases:
        intent = parse_voice_operator_command(transcript)
        assert intent.kind == "local_action"
        assert intent.action == "open_app"
        assert intent.target == target


def test_parse_close_this_window() -> None:
    intent = parse_voice_operator_command("close this window")

    assert intent.action == "close_window"
    assert intent.target == "active"


def test_parse_minimize_this_window() -> None:
    intent = parse_voice_operator_command("minimize this window")

    assert intent.action == "minimize_window"
    assert intent.target == "active"


def test_parse_what_is_on_my_screen() -> None:
    intent = parse_voice_operator_command("what is on my screen")

    assert intent.kind == "screen"
    assert intent.action == "read"


def test_parse_type_hello() -> None:
    intent = parse_voice_operator_command("type hello")

    assert intent.action == "keyboard_type"
    assert intent.args == {"text": "hello"}


def test_parse_scan_my_apps() -> None:
    intent = parse_voice_operator_command("scan my apps")

    assert intent.kind == "app_inventory"
    assert intent.action == "scan"


def test_parse_what_apps_do_i_have() -> None:
    intent = parse_voice_operator_command("what apps do I have?")

    assert intent.kind == "app_inventory"
    assert intent.action == "list"


def test_parse_list_installed_applications_uses_desktop_router() -> None:
    intent = parse_voice_operator_command("list installed applications")

    assert intent.kind == "local_action"
    assert intent.action == "apps_list"


def test_parse_search_applications_for_blender() -> None:
    intent = parse_voice_operator_command("search applications for Blender")

    assert intent.kind == "local_action"
    assert intent.action == "apps_search"
    assert intent.target == "blender"


def test_open_unknown_app_maps_to_launch_action() -> None:
    intent = parse_voice_operator_command("open spotify")

    assert intent.kind == "local_action"
    assert intent.action == "open_app"
    assert intent.target == "spotify"


def test_unknown_app_gives_helpful_message() -> None:
    intent = parse_voice_operator_command("open spotify")

    result = execute_voice_operator_intent(
        intent,
        action_runner=lambda _payload: SimpleNamespace(
            ok=False,
            status="unsupported",
            message="I could not find an installed app named spotify. Try `grandpa apps scan`.",
            approval_required=False,
        ),
    )

    assert result.status == "unsupported"
    assert "grandpa apps scan" in result.message


def test_exit_command_stops_loop() -> None:
    output: list[str] = []

    code = run_voice_operator_loop(
        input_func=lambda _prompt: "stop listening",
        output_func=output.append,
        action_runner=lambda _payload: SimpleNamespace(
            ok=True, status="completed", message="done", approval_required=False
        ),
        prefer_voice=False,
    )

    assert code == 0
    assert "Voice Operator Mode started" in output
    assert "Voice Operator Mode stopped." in output


def test_empty_input_records_audio_in_voice_mode() -> None:
    output: list[str] = []
    calls = {"listen": 0}
    inputs = iter(["", "quit"])

    def listen() -> str:
        calls["listen"] += 1
        return "open notepad"

    code = run_voice_operator_loop(
        input_func=lambda _prompt: next(inputs),
        output_func=output.append,
        listen_func=listen,
        action_runner=lambda _payload: SimpleNamespace(
            ok=True,
            status="completed",
            message="Opened Notepad.",
            approval_required=False,
        ),
        prefer_voice=True,
    )

    assert code == 0
    assert calls["listen"] == 1
    assert "Recording for 4 seconds..." in output
    assert "Understood: open notepad" in output


def test_debug_prints_raw_and_normalized_transcript() -> None:
    output: list[str] = []
    inputs = iter(["", "quit"])

    code = run_voice_operator_loop(
        input_func=lambda _prompt: next(inputs),
        output_func=output.append,
        listen_func=lambda: "Start note pad",
        action_runner=lambda _payload: SimpleNamespace(
            ok=True,
            status="completed",
            message="Opened Notepad.",
            approval_required=False,
        ),
        prefer_voice=True,
        debug=True,
    )

    assert code == 0
    assert "Raw transcript: Start note pad" in output
    assert "Normalized transcript: open notepad" in output
    assert "Understood: open notepad" in output


def test_eof_exits_voice_operator_loop_gracefully() -> None:
    output: list[str] = []

    def input_func(_prompt: str) -> str:
        raise EOFError

    code = run_voice_operator_loop(
        input_func=input_func,
        output_func=output.append,
        prefer_voice=True,
    )

    assert code == 0
    assert "Voice Operator Mode stopped" in output


def test_typed_mode_empty_input_repompts_without_stopping() -> None:
    output: list[str] = []
    inputs = iter(["", "quit"])

    code = run_voice_operator_loop(
        input_func=lambda _prompt: next(inputs),
        output_func=output.append,
        prefer_voice=False,
    )

    assert code == 0
    assert "Understood: " not in output
    assert "Voice Operator Mode stopped." in output


def test_dangerous_command_is_blocked_and_not_executed() -> None:
    intent = parse_voice_operator_command("delete all files")
    calls = []

    result = execute_voice_operator_intent(
        intent,
        action_runner=lambda payload: calls.append(payload),
    )

    assert result.status == "blocked"
    assert calls == []


def test_voice_window_ambiguity_hides_native_ids_but_keeps_structured_details() -> None:
    from grandpa.automation.service import ScreenAutomationService
    from grandpa.automation.windows import WindowIdentity, WindowVerification

    choices = (
        WindowIdentity(10, "First.txt - Notepad", 101, "notepad.exe", "notepad"),
        WindowIdentity(20, "Second.txt - Notepad", 202, "notepad.exe", "notepad"),
    )

    class AmbiguousTargets:
        def focus_and_verify(self, target, *, dry_run: bool = False):
            return WindowVerification(False, "Multiple windows.", candidates=choices)

    service = ScreenAutomationService(window_targets=AmbiguousTargets())
    intent = parse_voice_operator_command("focus Notepad")

    result = execute_voice_operator_intent(intent, automation_service=service)

    assert result.message.splitlines() == [
        "I found multiple matching windows. Which one?",
        "1. First.txt - Notepad",
        "2. Second.txt - Notepad",
    ]
    assert "101" not in result.message
    assert "202" not in result.message
    assert result.action["window_choices"][0] == {
        "title": "First.txt - Notepad",
        "hwnd": 10,
        "pid": 101,
    }
    assert service.has_pending_window_choice is True

    followup = parse_voice_operator_command(
        "choose the first one",
        has_pending_window_choice=True,
    )
    assert followup.kind == "screen_automation"
    assert followup.action == "window_choice"


def test_voice_dialog_prompt_hides_native_ids_and_routes_followup() -> None:
    from grandpa.automation.service import ScreenAutomationService
    from grandpa.automation.windows import (
        DialogIdentity,
        WindowCloseResult,
        WindowIdentity,
        WindowVerification,
    )

    window = WindowIdentity(10, "Untitled - Notepad", 101, "notepad.exe", "notepad")
    dialog = DialogIdentity(20, "Notepad", 101, 10, "notepad_unsaved")

    class DialogTargets:
        def focus_and_verify(self, target, *, dry_run: bool = False):
            return WindowVerification(True, "Focused.", window, window)

        def close_and_verify(self, target, *, dry_run: bool = False):
            return WindowCloseResult(
                "dialog_pending",
                "Notepad has unsaved changes.",
                window,
                dialog,
            )

    service = ScreenAutomationService(window_targets=DialogTargets())
    service.handle("focus Notepad")
    pending = service.handle("close Notepad")
    result = service.confirm(pending.confirmation_token or "")

    assert result.message == (
        "Notepad has unsaved changes. Save, don't save, or cancel?"
    )
    assert "101" not in result.message
    assert "20" not in result.message

    followup = parse_voice_operator_command(
        "don't save",
        has_pending_dialog=True,
    )
    assert followup.kind == "screen_automation"
    assert followup.action == "dialog_response"


def test_typed_fallback_after_microphone_unavailable() -> None:
    output: list[str] = []
    actions: list[dict] = []
    inputs = iter(["", "open chrome", "quit"])

    def action_runner(payload):
        actions.append(payload)
        return SimpleNamespace(
            ok=True,
            status="completed",
            message="Opened Chrome.",
            approval_required=False,
        )

    code = run_voice_operator_loop(
        input_func=lambda _prompt: next(inputs),
        output_func=output.append,
        listen_func=lambda: (_ for _ in ()).throw(MicrophoneUnavailableError()),
        action_runner=action_runner,
        prefer_voice=True,
    )

    assert code == 0
    assert any("Falling back to typed input." in line for line in output)
    assert actions[0]["action_type"] == "open_app"
    assert actions[0]["target"] == "chrome"


def test_stt_exception_allows_retry_or_typed_input() -> None:
    output: list[str] = []
    inputs = iter(["", "quit"])

    code = run_voice_operator_loop(
        input_func=lambda _prompt: next(inputs),
        output_func=output.append,
        listen_func=lambda: (_ for _ in ()).throw(
            VoiceRecognitionError(
                "I did not hear anything. Check microphone or speak louder."
            )
        ),
        prefer_voice=True,
    )

    assert code == 0
    assert any("I did not hear anything" in line for line in output)
    assert any("try again" in line for line in output)


def test_voice_operator_routes_multistep_goal_to_executive_planner(monkeypatch) -> None:
    output: list[str] = []
    actions: list[dict] = []
    inputs = iter(["open chrome and search for fastapi", "quit"])
    monkeypatch.setattr(
        "grandpa.planner.routing.handle_executive_goal",
        lambda text, **_kwargs: (
            "Task completed." if "search for fastapi" in text.casefold() else None
        ),
    )

    code = run_voice_operator_loop(
        input_func=lambda _prompt: next(inputs),
        output_func=output.append,
        action_runner=lambda payload: actions.append(payload),
        prefer_voice=False,
        dry_run=True,
    )

    assert code == 0
    assert "Task completed." in output
    assert actions == []


class FakeAudio:
    pass


class FakeMicrophone:
    def __init__(
        self,
        count: int = 1,
        error: Exception | None = None,
    ) -> None:
        self.count = count
        self.error = error
        self.calls = 0
        self.closed = False
        self.reset_calls = 0

    def capture(self, stop_event=None):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return FakeAudio()

    def close(self) -> None:
        self.closed = True

    def reset(self) -> None:
        self.reset_calls += 1


class FakeTranscriber:
    def __init__(self, transcripts: list[str] | None = None) -> None:
        self.transcripts = list(transcripts or [])
        self.calls = 0

    def transcribe(self, _audio) -> str:
        self.calls += 1
        if not self.transcripts:
            return "stop listening"
        return self.transcripts.pop(0)


class FakeSpeaker:
    def __init__(self) -> None:
        self.spoken: list[str] = []
        self.stopped = False
        self.is_speaking = False

    def speak(self, text: str, stop_event=None) -> None:
        self.spoken.append(text)

    def stop(self) -> None:
        self.stopped = True

    def wait_until_finished(self, stop_event=None) -> bool:
        return True


def test_voice_operator_responder_routes_and_executes() -> None:
    from grandpa.voice.operator import VoiceOperatorResponder

    actions: list[dict] = []

    def mock_runner(payload: dict) -> SimpleNamespace:
        actions.append(payload)
        return SimpleNamespace(
            ok=True,
            status="completed",
            message="Opened Notepad successfully.",
            approval_required=False,
        )

    responder = VoiceOperatorResponder(action_runner=mock_runner)
    turn = responder.handle_user_input("Open note pad")

    assert turn.status == "handled"
    assert "Opened Notepad" in turn.text
    assert actions[0]["action_type"] == "open_app"
    assert actions[0]["target"] == "notepad"
    assert turn.exit_requested is False


def test_voice_operator_responder_handles_exit_phrase() -> None:
    from grandpa.voice.operator import VoiceOperatorResponder

    responder = VoiceOperatorResponder()
    turn = responder.handle_user_input("stop listening")

    assert turn.status == "exit"
    assert turn.exit_requested is True
    assert "stopped" in turn.text.lower()


def test_voice_operator_default_mode_runs_hands_free_without_terminal_input() -> None:
    from grandpa.voice.operator import build_voice_operator_session

    output: list[str] = []
    actions: list[dict] = []
    mic = FakeMicrophone()
    transcriber = FakeTranscriber(["open notepad", "stop listening"])
    speaker = FakeSpeaker()

    def mock_runner(payload: dict) -> SimpleNamespace:
        actions.append(payload)
        return SimpleNamespace(
            ok=True,
            status="completed",
            message="Opened Notepad.",
            approval_required=False,
        )

    session = build_voice_operator_session(
        microphone_capture=mic,
        transcriber=transcriber,
        speaker=speaker,
        action_runner=mock_runner,
        output=output.append,
    )

    exit_code = session.run()

    assert exit_code == 0
    assert mic.calls == 2
    assert transcriber.calls == 2
    assert actions[0]["action_type"] == "open_app"
    assert actions[0]["target"] == "notepad"
    assert any("Opened Notepad." in s for s in speaker.spoken)
    assert mic.closed is True


def test_voice_operator_hands_free_loop_cycles_turns_automatically() -> None:
    from grandpa.voice.operator import build_voice_operator_session

    output: list[str] = []
    actions: list[dict] = []
    mic = FakeMicrophone()
    transcriber = FakeTranscriber(["open chrome", "open vscode", "stop listening"])
    speaker = FakeSpeaker()

    def mock_runner(payload: dict) -> SimpleNamespace:
        actions.append(payload)
        return SimpleNamespace(
            ok=True,
            status="completed",
            message=f"Opened {payload.get('target')}.",
            approval_required=False,
        )

    session = build_voice_operator_session(
        microphone_capture=mic,
        transcriber=transcriber,
        speaker=speaker,
        action_runner=mock_runner,
        output=output.append,
    )

    exit_code = session.run()

    assert exit_code == 0
    assert mic.calls == 3
    assert len(actions) == 2
    assert actions[0]["target"] == "chrome"
    assert actions[1]["target"] == "vscode"


def test_voice_operator_empty_turn_continues_listening() -> None:
    from grandpa.voice.operator import build_voice_operator_session

    output: list[str] = []
    actions: list[dict] = []
    mic = FakeMicrophone()
    transcriber = FakeTranscriber(["", "open notepad", "stop listening"])
    speaker = FakeSpeaker()

    def mock_runner(payload: dict) -> SimpleNamespace:
        actions.append(payload)
        return SimpleNamespace(
            ok=True,
            status="completed",
            message="Opened Notepad.",
            approval_required=False,
        )

    session = build_voice_operator_session(
        microphone_capture=mic,
        transcriber=transcriber,
        speaker=speaker,
        action_runner=mock_runner,
        output=output.append,
    )

    exit_code = session.run()

    assert exit_code == 0
    assert mic.calls == 3
    assert len(actions) == 1
    assert actions[0]["target"] == "notepad"


def test_voice_operator_no_tts_disables_speaker() -> None:
    from grandpa.voice.operator import build_voice_operator_session

    output: list[str] = []
    actions: list[dict] = []
    mic = FakeMicrophone()
    transcriber = FakeTranscriber(["open notepad", "stop listening"])

    def mock_runner(payload: dict) -> SimpleNamespace:
        actions.append(payload)
        return SimpleNamespace(
            ok=True,
            status="completed",
            message="Opened Notepad.",
            approval_required=False,
        )

    session = build_voice_operator_session(
        microphone_capture=mic,
        transcriber=transcriber,
        no_tts=True,
        action_runner=mock_runner,
        output=output.append,
    )

    exit_code = session.run()

    assert exit_code == 0
    assert session.speaker is None
    assert len(actions) == 1
    assert actions[0]["target"] == "notepad"


def test_voice_operator_unrecoverable_microphone_error_exits_with_error_code() -> None:
    from grandpa.voice.errors import MicrophoneUnavailableError
    from grandpa.voice.operator import build_voice_operator_session

    output: list[str] = []
    mic = FakeMicrophone(error=MicrophoneUnavailableError("Device disconnected."))
    transcriber = FakeTranscriber()
    speaker = FakeSpeaker()

    session = build_voice_operator_session(
        microphone_capture=mic,
        transcriber=transcriber,
        speaker=speaker,
        output=output.append,
    )

    exit_code = session.run()

    assert exit_code == 1
    assert any(
        "Device disconnected" in line or "unavailable" in line.lower()
        for line in output
    )
    assert mic.closed is True


def test_voice_operator_vocative_prefix_grandpa_open_notepad() -> None:
    from grandpa.voice.operator import (
        normalize_voice_operator_transcript,
        parse_voice_operator_command,
    )

    norm = normalize_voice_operator_transcript("Grandpa, open Notepad")
    assert norm == "open notepad"

    intent = parse_voice_operator_command("Grandpa, open Notepad")
    assert intent.status == "handled"
    assert intent.kind == "local_action"
    assert intent.action == "open_app"
    assert intent.target == "notepad"


def test_voice_operator_vocative_prefix_hey_grandpa_open_chrome() -> None:
    from grandpa.voice.operator import (
        normalize_voice_operator_transcript,
        parse_voice_operator_command,
    )

    norm = normalize_voice_operator_transcript("Hey Grandpa, open Chrome")
    assert norm == "open chrome"

    intent = parse_voice_operator_command("Hey Grandpa, open Chrome")
    assert intent.status == "handled"
    assert intent.kind == "local_action"
    assert intent.action == "open_app"
    assert intent.target == "chrome"


def test_voice_operator_vocative_prefix_grandpa_please_minimize_window() -> None:
    from grandpa.voice.operator import (
        normalize_voice_operator_transcript,
        parse_voice_operator_command,
    )

    norm = normalize_voice_operator_transcript("Grandpa please minimize this window")
    assert norm == "minimize this window"

    intent = parse_voice_operator_command("Grandpa please minimize this window")
    assert intent.status == "handled"
    assert intent.kind == "local_action"
    assert intent.action == "minimize_window"


def test_voice_operator_type_command_preserves_grandpa_in_payload() -> None:
    from grandpa.voice.operator import (
        normalize_voice_operator_transcript,
        parse_voice_operator_command,
    )

    norm1 = normalize_voice_operator_transcript("type Grandpa is my assistant")
    assert norm1 == "type Grandpa is my assistant"

    intent1 = parse_voice_operator_command("type Grandpa is my assistant")
    assert intent1.status == "handled"
    assert intent1.kind == "screen_automation"
    assert intent1.action == "keyboard_type"
    assert intent1.args == {"text": "Grandpa is my assistant"}

    # Also test leading vocative stripped while payload preserved
    norm2 = normalize_voice_operator_transcript("Grandpa, type Grandpa is my assistant")
    assert norm2 == "type Grandpa is my assistant"

    intent2 = parse_voice_operator_command("Grandpa, type Grandpa is my assistant")
    assert intent2.status == "handled"
    assert intent2.args == {"text": "Grandpa is my assistant"}


def test_voice_operator_stt_the_pad_alias_maps_to_notepad() -> None:
    from grandpa.voice.operator import (
        normalize_voice_operator_transcript,
        parse_voice_operator_command,
    )

    assert normalize_voice_operator_transcript("open the pad") == "open notepad"
    assert (
        normalize_voice_operator_transcript("Grandpa, open the pad") == "open notepad"
    )
    assert normalize_voice_operator_transcript("launch the pad") == "open notepad"

    intent_open = parse_voice_operator_command("Grandpa, open the pad.")
    assert intent_open.action == "open_app"
    assert intent_open.target == "notepad"

    intent_focus = parse_voice_operator_command("focus the pad")
    assert intent_focus.action == "focus_window"
    assert intent_focus.target == "notepad"

    intent_close = parse_voice_operator_command("close the pad")
    assert intent_close.action == "close_window"
    assert intent_close.target == "notepad"


def test_voice_operator_unsupported_command_continues_listening() -> None:
    from grandpa.voice.operator import build_voice_operator_session

    output: list[str] = []
    mic = FakeMicrophone()
    # 1st: unsupported command, 2nd: valid command, 3rd: stop listening
    transcriber = FakeTranscriber(
        [
            "unsupported banana command",
            "open notepad",
            "stop listening",
        ]
    )
    speaker = FakeSpeaker()
    actions: list[dict] = []

    def mock_runner(payload: dict) -> SimpleNamespace:
        actions.append(payload)
        return SimpleNamespace(
            ok=True,
            status="completed",
            message="Opened Notepad.",
            approval_required=False,
        )

    session = build_voice_operator_session(
        microphone_capture=mic,
        transcriber=transcriber,
        speaker=speaker,
        action_runner=mock_runner,
        output=output.append,
    )

    exit_code = session.run()

    assert exit_code == 0
    assert mic.calls == 3
    assert len(actions) == 1
    assert actions[0]["target"] == "notepad"


def test_voice_operator_tts_disabled_consecutive_microphone_turns() -> None:
    from grandpa.voice.operator import build_voice_operator_session

    output: list[str] = []
    mic = FakeMicrophone()
    transcriber = FakeTranscriber(["open notepad", "open chrome", "stop listening"])
    actions: list[dict] = []

    def mock_runner(payload: dict) -> SimpleNamespace:
        actions.append(payload)
        return SimpleNamespace(
            ok=True,
            status="completed",
            message=f"Opened {payload.get('target')}.",
            approval_required=False,
        )

    session = build_voice_operator_session(
        microphone_capture=mic,
        transcriber=transcriber,
        no_tts=True,
        action_runner=mock_runner,
        output=output.append,
    )

    exit_code = session.run()

    assert exit_code == 0
    assert mic.calls == 3
    assert len(actions) == 2
    assert actions[0]["target"] == "notepad"
    assert actions[1]["target"] == "chrome"


def test_voice_operator_tts_failure_does_not_block_next_listening_turn() -> None:
    from grandpa.voice.operator import build_voice_operator_session

    class FailingSpeaker:
        def __init__(self) -> None:
            self.calls = 0

        @property
        def is_speaking(self) -> bool:
            return False

        def speak(self, text: str, stop_event=None) -> None:
            self.calls += 1
            raise RuntimeError("Audio hardware unavailable for playback.")

        def stop(self) -> None:
            pass

        def wait_until_finished(self, stop_event=None) -> bool:
            return True

    output: list[str] = []
    mic = FakeMicrophone()
    transcriber = FakeTranscriber(["open notepad", "open chrome", "stop listening"])
    speaker = FailingSpeaker()
    actions: list[dict] = []

    def mock_runner(payload: dict) -> SimpleNamespace:
        actions.append(payload)
        return SimpleNamespace(
            ok=True,
            status="completed",
            message=f"Opened {payload.get('target')}.",
            approval_required=False,
        )

    session = build_voice_operator_session(
        microphone_capture=mic,
        transcriber=transcriber,
        speaker=speaker,
        action_runner=mock_runner,
        output=output.append,
    )

    exit_code = session.run()

    assert exit_code == 0
    assert mic.calls == 3
    assert len(actions) == 2
    assert speaker.calls >= 2
    assert any("Audio hardware unavailable" in line for line in output)


def test_voice_operator_node_pad_normalization_variants() -> None:
    from grandpa.voice.operator import (
        normalize_voice_operator_transcript,
        parse_voice_operator_command,
    )

    assert normalize_voice_operator_transcript("open node pad") == "open notepad"
    assert (
        normalize_voice_operator_transcript("Grandpa, open node pad") == "open notepad"
    )
    assert (
        normalize_voice_operator_transcript("Hey Grandpa, launch node pad")
        == "open notepad"
    )
    assert normalize_voice_operator_transcript("focus node pad") == "focus notepad"
    assert normalize_voice_operator_transcript("close node pad") == "close notepad"

    intent = parse_voice_operator_command("Grandpa, open node pad")
    assert intent.status == "handled"
    assert intent.action == "open_app"
    assert intent.target == "notepad"


def test_voice_operator_typing_preserves_node_pad_text() -> None:
    from grandpa.voice.operator import (
        normalize_voice_operator_transcript,
        parse_voice_operator_command,
    )

    raw = "type install Node package into pad"
    assert normalize_voice_operator_transcript(raw) == raw

    intent = parse_voice_operator_command(raw)
    assert intent.status == "handled"
    assert intent.action == "keyboard_type"
    assert intent.args == {"text": "install Node package into pad"}


def test_voice_operator_echo_rejection_and_turn_recovery() -> None:
    from grandpa.voice.operator import build_voice_operator_session

    output: list[str] = []
    mic = FakeMicrophone()
    # 1st turn: "open notepad" -> speaks "Opened Notepad."
    # 2nd turn: distorted echo "Nice to meet you, Notepad." -> ignored as echo
    # 3rd turn: real command "open calculator" -> executed
    # 4th turn: "stop listening" -> exits
    transcriber = FakeTranscriber(
        [
            "open notepad",
            "Nice to meet you, Notepad.",
            "open calculator",
            "stop listening",
        ]
    )
    speaker = FakeSpeaker()
    actions: list[dict] = []

    def mock_runner(payload: dict) -> SimpleNamespace:
        actions.append(payload)
        return SimpleNamespace(
            ok=True,
            status="completed",
            message=f"Opened {payload.get('target')}.",
            approval_required=False,
        )

    session = build_voice_operator_session(
        microphone_capture=mic,
        transcriber=transcriber,
        speaker=speaker,
        action_runner=mock_runner,
        output=output.append,
    )

    exit_code = session.run()

    assert exit_code == 0
    assert mic.calls == 4
    assert len(actions) == 2
    assert actions[0]["target"] == "notepad"
    assert actions[1]["target"] == "calculator"
    assert any("Ignoring probable speaker echo" in line for line in output)


def test_voice_operator_genuine_command_after_tts_not_rejected() -> None:
    from grandpa.voice.operator import build_voice_operator_session

    output: list[str] = []
    mic = FakeMicrophone()
    # "open notepad" -> speaks "Opened Notepad."
    # Immediately followed by genuine command "open calculator" -> must NOT be treated as echo
    # "stop listening" -> exits
    transcriber = FakeTranscriber(
        [
            "open notepad",
            "open calculator",
            "stop listening",
        ]
    )
    speaker = FakeSpeaker()
    actions: list[dict] = []

    def mock_runner(payload: dict) -> SimpleNamespace:
        actions.append(payload)
        return SimpleNamespace(
            ok=True,
            status="completed",
            message=f"Opened {payload.get('target')}.",
            approval_required=False,
        )

    session = build_voice_operator_session(
        microphone_capture=mic,
        transcriber=transcriber,
        speaker=speaker,
        action_runner=mock_runner,
        output=output.append,
    )

    exit_code = session.run()

    assert exit_code == 0
    assert mic.calls == 3
    assert len(actions) == 2
    assert actions[0]["target"] == "notepad"
    assert actions[1]["target"] == "calculator"


def test_voice_operator_inventory_canonical_fallback_and_missing_path_safety() -> None:
    from grandpa.desktop.control.applications import ApplicationControlService
    from grandpa.pc_control import LocalActionRequest

    service = ApplicationControlService()

    # 1. Target "node pad" resolves via SAFE_APP_ALIASES -> canonical app
    assert service.app_id("node pad") == "notepad"

    # 2. Unknown app with nonexistent path does not crash with WinError 2
    req_unknown = LocalActionRequest(
        action_type="open_app",
        target="nonexistent_xyz_application_fake",
        args={},
    )
    resp = service.execute(req_unknown, "open_app")
    assert resp.ok is False
    assert resp.status in {"blocked", "failed"}


def test_voice_activity_detector_idle_silence_does_not_timeout_until_speech_starts() -> (
    None
):
    from grandpa.voice.vad import VoiceActivityConfig, VoiceActivityDetector

    config = VoiceActivityConfig(
        minimum_rms=180.0,
        minimum_speech_seconds=0.20,
        silence_seconds=0.55,
        maximum_utterance_seconds=5.0,
    )
    detector = VoiceActivityDetector(config)

    # 10 seconds of background silence/noise (RMS = 50.0) -> observe must return False
    for _ in range(100):
        done = detector.observe(50.0, 0.1)
        assert done is False
        assert detector.speech_started is False

    # Now speech starts (RMS = 400.0) for 0.3s -> speech_started becomes True
    for _ in range(3):
        detector.observe(400.0, 0.1)
    assert detector.speech_started is True

    # 0.6s trailing silence -> observe returns True with silence_timeout
    done = False
    for _ in range(6):
        if detector.observe(50.0, 0.1):
            done = True
            break
    assert done is True
    assert detector.finalization_reason == "silence_timeout"


def test_voice_session_silence_does_not_invoke_transcriber() -> None:
    from grandpa.voice.cli_session import VoiceSession
    from grandpa.voice.microphone import CapturedAudio

    class SilentMicrophone:
        def __init__(self) -> None:
            self.calls = 0

        def capture(self, stop_event=None):
            self.calls += 1
            if self.calls == 1:
                # Capture with speech_detected = False
                return CapturedAudio(b"\x00" * 3200, speech_detected=False)
            if stop_event:
                stop_event.set()
            return CapturedAudio(b"", speech_detected=False)

        def close(self) -> None:
            pass

    class SpyTranscriber:
        def __init__(self) -> None:
            self.calls = 0

        def transcribe(self, audio) -> str:
            self.calls += 1
            return "hello"

    mic = SilentMicrophone()
    stt = SpyTranscriber()
    responder = SimpleNamespace(
        handle_user_input=lambda text: SimpleNamespace(text="hi")
    )

    session = VoiceSession(
        mic,
        stt,
        responder,
        speaker=None,
        output=lambda msg: None,
    )
    code = session.run()

    assert code == 0
    assert mic.calls >= 1
    assert stt.calls == 0  # STT was never called on silent audio!


def test_faster_whisper_repetition_hallucination_filtered() -> None:
    from grandpa.speech.faster_whisper import _is_hallucinated_repetition

    # Degenerate hallucination loops must be identified
    assert (
        _is_hallucinated_repetition(
            "I'm sorry. I'm sorry. I'm sorry. I'm sorry. I'm sorry."
        )
        is True
    )
    assert (
        _is_hallucinated_repetition(
            "Thank you. Thank you. Thank you. Thank you. Thank you."
        )
        is True
    )
    assert _is_hallucinated_repetition("you you you you you you you") is True

    # Normal phrases must NOT be flagged
    assert _is_hallucinated_repetition("Open Notepad and type hello") is False
    assert _is_hallucinated_repetition("Close this window please") is False
    assert _is_hallucinated_repetition("type yes yes yes") is False


def test_voice_operator_pending_confirmation_yes_executes_action() -> None:
    from grandpa.automation.service import ScreenAutomationService
    from grandpa.automation.windows import (
        WindowCloseResult,
        WindowIdentity,
        WindowVerification,
    )
    from grandpa.voice.operator import VoiceOperatorResponder

    window = WindowIdentity(10, "Document - Notepad", 101, "notepad.exe", "notepad")
    closed_targets = []

    class MockWindowTargets:
        def focus_and_verify(self, target, *, dry_run: bool = False):
            return WindowVerification(True, "Focused.", window, window)

        def close_and_verify(self, target, *, dry_run: bool = False):
            closed_targets.append(target)
            return WindowCloseResult("closed", "Closed Notepad.", window)

    automation_service = ScreenAutomationService(window_targets=MockWindowTargets())
    responder = VoiceOperatorResponder(automation_service=automation_service)

    # Turn 1: "close notepad" -> triggers confirmation prompt
    turn1 = responder.handle_user_input("close notepad")
    assert turn1.status in {"handled", "needs_confirmation"}
    assert "Unsaved work may be lost" in turn1.text or "Yes / No" in turn1.text
    assert automation_service.has_pending_confirmation is True

    # Turn 2: "yes" -> confirms and executes exact close window
    turn2 = responder.handle_user_input("yes")
    assert turn2.status == "handled"
    assert "Closed Notepad" in turn2.text
    assert len(closed_targets) == 1
    assert automation_service.has_pending_confirmation is False


def test_voice_operator_pending_confirmation_no_cancels_action() -> None:
    from grandpa.automation.service import ScreenAutomationService
    from grandpa.automation.windows import (
        WindowCloseResult,
        WindowIdentity,
        WindowVerification,
    )
    from grandpa.voice.operator import VoiceOperatorResponder

    window = WindowIdentity(10, "Document - Notepad", 101, "notepad.exe", "notepad")
    closed_targets = []

    class MockWindowTargets:
        def focus_and_verify(self, target, *, dry_run: bool = False):
            return WindowVerification(True, "Focused.", window, window)

        def close_and_verify(self, target, *, dry_run: bool = False):
            closed_targets.append(target)
            return WindowCloseResult("closed", "Closed Notepad.", window)

    automation_service = ScreenAutomationService(window_targets=MockWindowTargets())
    responder = VoiceOperatorResponder(automation_service=automation_service)

    # Turn 1: "close notepad"
    _ = responder.handle_user_input("close notepad")
    assert automation_service.has_pending_confirmation is True

    # Turn 2: "no" -> cancels action
    turn2 = responder.handle_user_input("no")
    assert "cancelled" in turn2.text.lower() or "rejected" in turn2.text.lower()
    assert len(closed_targets) == 0
    assert automation_service.has_pending_confirmation is False


def test_voice_operator_stop_listening_with_punctuation() -> None:
    from grandpa.voice.cli_session import is_exit_phrase
    from grandpa.voice.operator import VoiceOperatorResponder

    assert is_exit_phrase("Stop listening.") is True
    assert is_exit_phrase("stop listening!") is True
    assert is_exit_phrase("stop voice.") is True
    assert is_exit_phrase("exit voice mode!") is True
    assert is_exit_phrase("Goodbye Grandpa.") is True

    responder = VoiceOperatorResponder()
    turn = responder.handle_user_input("Stop listening.")
    assert turn.status == "exit"
    assert turn.exit_requested is True


def test_voice_operator_timing_report_in_debug_mode() -> None:
    from grandpa.voice.operator import build_voice_operator_session

    output: list[str] = []
    mic = FakeMicrophone()
    transcriber = FakeTranscriber(["open notepad", "stop listening"])
    speaker = FakeSpeaker()

    def mock_runner(payload: dict) -> SimpleNamespace:
        return SimpleNamespace(
            ok=True,
            status="completed",
            message="Opened Notepad.",
            approval_required=False,
        )

    session = build_voice_operator_session(
        microphone_capture=mic,
        transcriber=transcriber,
        speaker=speaker,
        action_runner=mock_runner,
        output=output.append,
        debug=True,
    )

    exit_code = session.run()

    assert exit_code == 0
    assert any("Timing:" in line for line in output)
    assert any("STT:" in line for line in output)
    assert any("routing/action:" in line for line in output)


def test_voice_session_idle_state_printed_once_on_idle_entry() -> None:
    from grandpa.voice.cli_session import VoiceSession
    from grandpa.voice.operator import VoiceOperatorResponder

    output: list[str] = []
    mic = FakeMicrophone(count=3)
    transcriber = FakeTranscriber(["", "", "stop listening"])
    speaker = FakeSpeaker()
    responder = VoiceOperatorResponder()

    session = VoiceSession(
        mic,
        transcriber,
        responder,
        speaker,
        output=output.append,
        debug=True,
    )
    exit_code = session.run()

    assert exit_code == 0
    idle_lines = [line for line in output if "[IDLE] Listening..." in line]
    # Printed once on entering the loop, not on empty polling iterations
    assert len(idle_lines) == 1


def test_voice_session_no_repeated_listening_on_polling_loops() -> None:
    from grandpa.voice.cli_session import VoiceSession
    from grandpa.voice.operator import VoiceOperatorResponder

    output: list[str] = []
    mic = FakeMicrophone(count=5)
    transcriber = FakeTranscriber(["", "", "", "", "stop listening"])
    speaker = FakeSpeaker()
    responder = VoiceOperatorResponder()

    session = VoiceSession(
        mic,
        transcriber,
        responder,
        speaker,
        output=output.append,
        debug=False,
    )
    exit_code = session.run()

    assert exit_code == 0
    listening_lines = [line for line in output if "Listening..." in line]
    # Plain Listening... is only rendered once when starting, never spammed
    assert len(listening_lines) == 1


def test_voice_session_state_transitions_idle_to_capturing_to_processing_to_executing() -> (
    None
):
    from grandpa.voice.cli_session import VoiceSession, VoiceSessionState
    from grandpa.voice.operator import VoiceOperatorResponder

    mic = FakeMicrophone(count=1)
    transcriber = FakeTranscriber(["open notepad", "stop listening"])
    speaker = FakeSpeaker()
    responder = VoiceOperatorResponder()

    session = VoiceSession(
        mic,
        transcriber,
        responder,
        speaker,
        output=lambda msg: None,
    )
    assert session.state == VoiceSessionState.IDLE


def test_voice_session_debug_state_tags_rendered() -> None:
    from grandpa.voice.cli_session import VoiceSession
    from grandpa.voice.operator import VoiceOperatorResponder

    output: list[str] = []
    mic = FakeMicrophone(count=1)
    transcriber = FakeTranscriber(["open notepad", "stop listening"])
    speaker = FakeSpeaker()
    responder = VoiceOperatorResponder()

    session = VoiceSession(
        mic,
        transcriber,
        responder,
        speaker,
        output=output.append,
        debug=True,
    )
    exit_code = session.run()

    assert exit_code == 0
    assert any("[IDLE] Listening..." in line for line in output)
    assert any("[PROCESSING] Transcribing..." in line for line in output)
    assert any("[PROCESSING] Routing..." in line for line in output)
    assert any("[EXECUTING]" in line for line in output)


def test_vad_rejects_transient_spike_without_speech_started() -> None:
    from grandpa.voice.vad import VoiceActivityConfig, VoiceActivityDetector

    config = VoiceActivityConfig(
        minimum_rms=200.0,
        minimum_speech_seconds=0.25,
        silence_seconds=0.55,
    )
    vad = VoiceActivityDetector(config)

    # 100ms noise spike (RMS 350)
    stop = vad.observe(350.0, 0.10)
    assert stop is False
    assert vad.speech_started is False

    # 100ms silence (RMS 50)
    stop = vad.observe(50.0, 0.10)
    assert stop is False
    assert vad.speech_started is False


def test_vad_rejects_sub_minimum_voiced_duration_on_silence_timeout() -> None:
    from grandpa.voice.vad import VoiceActivityConfig, VoiceActivityDetector

    config = VoiceActivityConfig(
        minimum_rms=200.0,
        minimum_speech_seconds=0.25,
        silence_seconds=0.55,
    )
    vad = VoiceActivityDetector(config)

    # 300ms speech onset (voiced duration = 0.30s)
    vad.observe(300.0, 0.10)
    vad.observe(300.0, 0.10)
    vad.observe(300.0, 0.10)
    assert vad.speech_started is True

    # 600ms trailing silence (silence_seconds=0.55 reached)
    for _ in range(6):
        stop = vad.observe(30.0, 0.10)
        if stop:
            break

    assert stop is True
    assert vad.finalization_reason == "silence_timeout"
    assert vad.speech_active_seconds >= 0.25


def test_whisper_rejects_noisy_segments_with_high_no_speech_probability() -> None:
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from grandpa.speech.faster_whisper import FasterWhisperBackend

    backend = FasterWhisperBackend()
    mock_model = MagicMock()
    mock_seg = SimpleNamespace(
        text="hallucinated phrase",
        start=0.0,
        end=1.0,
        no_speech_prob=0.85,
        avg_logprob=-1.5,
        compression_ratio=1.0,
    )
    mock_info = SimpleNamespace(language="en", language_probability=0.9, duration=1.0)
    mock_model.transcribe.return_value = ([mock_seg], mock_info)
    backend._model = mock_model

    result = backend.transcribe_file("dummy.wav")
    assert result.text == ""
    assert len(result.segments) == 0


def test_whisper_uses_greedy_beam_size_1_for_fast_inference() -> None:
    from grandpa.speech.faster_whisper import build_transcription_options

    options = build_transcription_options()
    assert options["beam_size"] == 1
    assert options["temperature"] == 0.0
    assert options["language"] == "en"


def test_faster_whisper_speech_to_text_warm_model_reuse_without_reinstantiation() -> (
    None
):
    from grandpa.voice.speech_input import SpeechInputEngine
    from grandpa.voice.speech_to_text import FasterWhisperSpeechToText

    engine = SpeechInputEngine()
    stt = FasterWhisperSpeechToText(engine=engine)
    assert stt._engine is engine
    backend1 = engine._get_backend()
    backend2 = engine._get_backend()
    assert backend1 is backend2


def test_voice_session_discards_low_energy_audio_before_stt() -> None:
    from grandpa.voice.cli_session import VoiceSession
    from grandpa.voice.microphone import CapturedAudio
    from grandpa.voice.operator import VoiceOperatorResponder

    output: list[str] = []

    class LowEnergyMicrophone:
        def __init__(self):
            self.calls = 0

        def capture(self, stop_event=None, on_speech_start=None):
            self.calls += 1
            if self.calls == 1:
                return CapturedAudio(
                    data=b"\x00" * 3200,
                    finalization_reason="silence_timeout",
                    speech_active_seconds=0.10,
                    rms_level=50.0,
                )
            if stop_event:
                stop_event.set()
            return CapturedAudio(b"", finalization_reason="cancelled")

        def reset(self):
            pass

        def close(self):
            pass

    transcriber = FakeTranscriber(["hello"])
    responder = VoiceOperatorResponder()

    session = VoiceSession(
        LowEnergyMicrophone(),
        transcriber,
        responder,
        output=output.append,
        debug=True,
    )
    exit_code = session.run()

    assert exit_code == 0
    # STT transcriber was never invoked for the 0.10s / 50 RMS low energy audio
    assert transcriber.calls == 0
    assert any("Discarded non-speech audio" in line for line in output)


def test_voice_operator_open_calculator_end_to_end_fast_execution() -> None:
    from types import SimpleNamespace

    from grandpa.voice.operator import build_voice_operator_session

    output: list[str] = []
    actions: list[dict] = []
    mic = FakeMicrophone()
    transcriber = FakeTranscriber(["open calculator", "stop listening"])
    speaker = FakeSpeaker()

    def mock_runner(payload: dict) -> SimpleNamespace:
        actions.append(payload)
        return SimpleNamespace(
            ok=True,
            status="completed",
            message="Calculator is open.",
            approval_required=False,
        )

    session = build_voice_operator_session(
        microphone_capture=mic,
        transcriber=transcriber,
        speaker=speaker,
        action_runner=mock_runner,
        output=output.append,
    )
    exit_code = session.run()

    assert exit_code == 0
    assert len(actions) == 1
    assert actions[0]["target"] == "calculator"


def test_voice_session_fast_exit_phrase_bypass() -> None:
    from grandpa.voice.cli_session import VoiceSession
    from grandpa.voice.operator import VoiceOperatorResponder

    output: list[str] = []
    mic = FakeMicrophone()
    transcriber = FakeTranscriber(["stop listening"])
    speaker = FakeSpeaker()
    responder = VoiceOperatorResponder()

    session = VoiceSession(
        mic,
        transcriber,
        responder,
        speaker,
        output=output.append,
    )
    exit_code = session.run()

    assert exit_code == 0
    assert any("Goodbye" in line for line in output)


def test_voice_session_ctrl_c_immediate_shutdown() -> None:
    from grandpa.voice.cli_session import VoiceSession
    from grandpa.voice.operator import VoiceOperatorResponder

    output: list[str] = []

    class InterruptMicrophone:
        def capture(self, stop_event=None, on_speech_start=None):
            raise KeyboardInterrupt()

        def reset(self):
            pass

        def close(self):
            pass

    transcriber = FakeTranscriber()
    responder = VoiceOperatorResponder()

    session = VoiceSession(
        InterruptMicrophone(),
        transcriber,
        responder,
        output=output.append,
    )
    exit_code = session.run()

    assert exit_code == 0
    assert any("Goodbye" in line for line in output)
