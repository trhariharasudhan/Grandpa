import grandpa.windows_window_control as wwc
from grandpa.local_actions import handle_local_action, resolve_fuzzy_app
from grandpa.voice.assistant import VoiceCommandProcessor
from grandpa.voice.cli_session import is_prompt_echo
from grandpa.windows_window_control import WindowInfo, _resolve_window


def test_voice_actions_routing():
    # Basic open actions (without execution to prevent popups, execute=False)
    calc_act = handle_local_action("open calculator", execute=False)
    assert calc_act.status == "handled"
    assert calc_act.kind == "app"
    assert calc_act.target == "calculator"

    notepad_act = handle_local_action("launch notepad", execute=False)
    assert notepad_act.status == "handled"
    assert notepad_act.kind == "app"
    assert notepad_act.target == "notepad"

    chrome_act = handle_local_action("please launch Chrome", execute=False)
    assert chrome_act.status == "handled"
    assert chrome_act.kind == "app"
    assert chrome_act.target == "chrome"

    vscode_act = handle_local_action("can you open VS Code?", execute=False)
    assert vscode_act.status == "handled"
    assert vscode_act.kind == "app"
    assert vscode_act.target == "vscode"


def test_voice_window_actions_routing():
    focus_chrome = handle_local_action("focus chrome", execute=False)
    assert focus_chrome.status == "handled"
    assert focus_chrome.kind == "window"
    assert "focus" in focus_chrome.target
    assert "chrome" in focus_chrome.target

    switch_notepad = handle_local_action("Switch to Notepad", execute=False)
    assert switch_notepad.status == "handled"
    assert switch_notepad.kind == "window"
    assert "focus" in switch_notepad.target
    assert "notepad" in switch_notepad.target


def test_downloads_folder_routing():
    downloads_act = handle_local_action("Show my Downloads", execute=False)
    assert downloads_act.status == "handled"
    assert downloads_act.kind == "folder"
    assert "Downloads" in downloads_act.target


def test_conversational_distinction_does_not_execute():
    # Conversational inquiries should return no_match (which falls back to conversational LLM)
    assert (
        handle_local_action("What is a calculator?", execute=False).status == "no_match"
    )
    assert (
        handle_local_action("How does a calculator work?", execute=False).status
        == "no_match"
    )
    assert (
        handle_local_action("Tell me about Google Chrome.", execute=False).status
        == "no_match"
    )
    assert (
        handle_local_action("Why is VS Code useful?", execute=False).status
        == "no_match"
    )


def test_safety_and_destructive_blocks():
    # Danger/blocked commands
    blocked_act = handle_local_action("delete all files", execute=False)
    assert blocked_act.status == "blocked"
    assert blocked_act.permission == "blocked"


def test_fuzzy_app_name_resolution():
    # Exact and corrections
    app_id, conf, label = resolve_fuzzy_app("calc")
    assert app_id == "calculator"
    assert conf == 1.0

    app_id, conf, label = resolve_fuzzy_app("calc-you-later")
    assert app_id == "calculator"
    assert conf == 1.0

    app_id, conf, label = resolve_fuzzy_app("Calcumator")
    assert app_id == "calculator"
    assert 0.8 <= conf < 1.0
    assert label == "Calculator"

    # Weak match (Calcium) should have low confidence
    app_id, conf, label = resolve_fuzzy_app("Calcium")
    assert conf < 0.8


def test_fuzzy_open_and_focus_routing():
    # Uncertain name Calcumator should trigger pending_confirmation
    calcumator_open = handle_local_action("open calcumator", execute=False)
    assert calcumator_open.status == "pending_confirmation"
    assert calcumator_open.message == "Did you mean Calculator?"
    assert calcumator_open.pending_action["command"] == "open calculator"

    # Calcium should fall back to conversation (no_match)
    calcium_open = handle_local_action("open calcium", execute=False)
    assert calcium_open.status == "no_match"


def test_voice_command_processor_confirmation_flow(monkeypatch):
    proc = VoiceCommandProcessor(model_name=None)

    # Trigger a pending confirmation
    resp = proc.handle_user_input("open calcumator")
    assert resp.status == "pending_confirmation"
    assert resp.text == "Did you mean Calculator?"
    assert proc._pending_action is not None

    # Cancel confirmation
    resp_no = proc.handle_user_input("no")
    assert resp_no.status == "cancelled"
    assert resp_no.text == "Okay, cancelled."
    assert proc._pending_action is None

    # Confirm (Yes)
    proc.handle_user_input("open calcumator")
    # Mock launch_app to avoid actual process launch
    import grandpa.windows_app_resolver as war
    from grandpa.windows_app_resolver import AppResolution

    mock_resolution = AppResolution(
        "calculator",
        "Calculator",
        "found",
        "command",
        "calc.exe",
        "allowlist",
        "Success",
    )
    monkeypatch.setattr(war, "launch_app", lambda x: mock_resolution)

    resp_yes = proc.handle_user_input("yes")
    assert resp_yes.status == "handled"
    assert "Calculator opened" in resp_yes.text


def test_window_resolution_priority(monkeypatch):
    # Mock _list_windows to return multiple candidates
    mock_windows = [
        WindowInfo(1001, "Google Chrome - New Tab", "chrome", 5000),
        WindowInfo(1002, "Calculator", "calculator", 6000),
    ]
    monkeypatch.setattr(wwc, "_list_windows", lambda: mock_windows)

    # 1. Previously launched PID match
    wwc.record_launched_pid("chrome", 5000)
    res = _resolve_window("chrome")
    assert res.handle == 1001

    # 2. Canonical executable name match
    monkeypatch.setattr(
        wwc, "_get_window_executable_name", lambda h: "calc.exe" if h == 1002 else ""
    )
    res_calc = _resolve_window("calculator")
    assert res_calc.handle == 1002


def test_minimized_window_restoration_and_verification(monkeypatch):
    mock_applied = []

    def fake_apply(action, hwnd):
        mock_applied.append((action, hwnd))

    monkeypatch.setattr(wwc, "_apply_action", fake_apply)
    monkeypatch.setattr(wwc, "_get_foreground_window", lambda: 1002)

    window = WindowInfo(1002, "Calculator", "calculator", 6000)

    # Test focus verification succeeds when foreground matches
    res = wwc.control_window_info("focus", window, target="calculator")
    assert res.status == "handled"
    assert res.message == "Calculator focused."


def test_whisper_prompt_echo_filtering():
    # Prompt echoes or subsets should be rejected
    assert is_prompt_echo("Grandpa, Ollama") is True
    assert is_prompt_echo("current year may be 3026") is True
    assert is_prompt_echo("The current year may be 2026") is True

    # Legitimate questions should not be rejected
    assert is_prompt_echo("What year is it?") is False
    assert is_prompt_echo("stop listening") is False
