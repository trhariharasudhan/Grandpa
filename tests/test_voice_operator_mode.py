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
    assert normalize_voice_operator_transcript("open open open notepad") == "open notepad"
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
        action_runner=lambda _payload: SimpleNamespace(ok=True, status="completed", message="done", approval_required=False),
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

    window = WindowIdentity(
        10, "Untitled - Notepad", 101, "notepad.exe", "notepad"
    )
    dialog = DialogIdentity(
        20, "Notepad", 101, 10, "notepad_unsaved"
    )

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
        return SimpleNamespace(ok=True, status="completed", message="Opened Chrome.", approval_required=False)

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
        listen_func=lambda: (_ for _ in ()).throw(VoiceRecognitionError("I did not hear anything. Check microphone or speak louder.")),
        prefer_voice=True,
    )

    assert code == 0
    assert any("I did not hear anything" in line for line in output)
    assert any("try again" in line for line in output)
