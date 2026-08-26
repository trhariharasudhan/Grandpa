import sys
from unittest.mock import MagicMock

from grandpa.local_actions import handle_local_action, run_chrome_profile_selection
from grandpa.voice.assistant import VoiceCommandProcessor
from grandpa.voice.microphone import MicrophoneCapture
from grandpa.windows_app_resolver import AppResolution, launch_app


def test_notepad_verified_launch_success(monkeypatch):
    monkeypatch.setattr(
        "grandpa.windows_app_resolver.verify_app_launched",
        lambda a, d, launched_pid=None: "ok",
    )
    monkeypatch.setattr(sys, "platform", "win32")

    mock_proc = MagicMock()
    mock_proc.pid = 1234
    monkeypatch.setattr("subprocess.Popen", lambda *args, **kwargs: mock_proc)

    monkeypatch.setattr(
        "grandpa.windows_app_resolver.resolve_app",
        lambda name: AppResolution(
            "notepad", "Notepad", "found", "path", "notepad.exe", "test", "found"
        ),
    )

    result = launch_app("notepad")
    assert result.status == "found"
    assert "is open" in result.message


def test_notepad_verified_launch_no_visible_window(monkeypatch):
    monkeypatch.setattr(
        "grandpa.windows_app_resolver.verify_app_launched",
        lambda a, d, launched_pid=None: "no_visible_window",
    )
    monkeypatch.setattr(sys, "platform", "win32")

    mock_proc = MagicMock()
    mock_proc.pid = 1234
    monkeypatch.setattr("subprocess.Popen", lambda *args, **kwargs: mock_proc)
    monkeypatch.setattr(
        "grandpa.windows_app_resolver.resolve_app",
        lambda name: AppResolution(
            "notepad", "Notepad", "found", "path", "notepad.exe", "test", "found"
        ),
    )

    result = launch_app("notepad")
    assert result.status == "error"
    assert "no visible Notepad window appeared" in result.message


def test_calculator_verified_launch(monkeypatch):
    monkeypatch.setattr(
        "grandpa.windows_app_resolver.verify_app_launched",
        lambda a, d, launched_pid=None: "ok",
    )
    monkeypatch.setattr(sys, "platform", "win32")

    mock_proc = MagicMock()
    mock_proc.pid = 5678
    monkeypatch.setattr("subprocess.Popen", lambda *args, **kwargs: mock_proc)
    monkeypatch.setattr(
        "grandpa.windows_app_resolver.resolve_app",
        lambda name: AppResolution(
            "calculator", "Calculator", "found", "path", "calc.exe", "test", "found"
        ),
    )

    result = launch_app("calculator")
    assert result.status == "found"
    assert "is open" in result.message


def test_chrome_chooser_detection(monkeypatch):
    monkeypatch.setattr(
        "grandpa.windows_app_resolver.verify_app_launched",
        lambda a, d, launched_pid=None: "chrome_profile_chooser",
    )
    monkeypatch.setattr(sys, "platform", "win32")

    mock_proc = MagicMock()
    mock_proc.pid = 9999
    monkeypatch.setattr("subprocess.Popen", lambda *args, **kwargs: mock_proc)
    monkeypatch.setattr(
        "grandpa.windows_app_resolver.resolve_app",
        lambda name: AppResolution(
            "chrome", "Chrome", "found", "path", "chrome.exe", "test", "found"
        ),
    )

    result = launch_app("chrome")
    assert result.status == "found"
    assert "profile chooser" in result.message


def test_chrome_profile_text_matching(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")

    mock_window = MagicMock()
    mock_window.title = "Who's using Chrome?"

    call_idx = 0

    def mock_list_windows():
        nonlocal call_idx
        call_idx += 1
        if call_idx <= 2:
            return [mock_window]
        return []

    monkeypatch.setattr(
        "grandpa.windows_window_control._list_windows", mock_list_windows
    )
    monkeypatch.setattr(
        "grandpa.windows_window_control.control_window", lambda act, tgt: True
    )

    mock_node = MagicMock()
    mock_node.visible = True
    mock_node.label = "Hari Hara Sudhan"
    mock_node.bounds.center = (400, 300)

    mock_graph = MagicMock()
    mock_graph.nodes = [mock_node]

    mock_inspect = MagicMock()
    mock_inspect.graph = mock_graph

    mock_engine = MagicMock()
    mock_engine.inspect.return_value = mock_inspect

    monkeypatch.setattr("grandpa.vision.service.VisionEngine", lambda: mock_engine)

    mock_service = MagicMock()
    monkeypatch.setattr(
        "grandpa.automation.service.get_automation_service", lambda: mock_service
    )

    msg = run_chrome_profile_selection("Hari Hara Sudhan")
    assert "selected" in msg or "opened" in msg
    mock_service.handle.assert_called_with(
        "click at 400 300", target_window="Who's using Chrome?"
    )


def test_ambiguous_profile_clarification(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")

    mock_window = MagicMock()
    mock_window.title = "Who's using Chrome?"
    monkeypatch.setattr(
        "grandpa.windows_window_control._list_windows", lambda: [mock_window]
    )
    monkeypatch.setattr(
        "grandpa.windows_window_control.control_window", lambda act, tgt: True
    )

    node1 = MagicMock()
    node1.visible = True
    node1.label = "Hari 1"

    node2 = MagicMock()
    node2.visible = True
    node2.label = "Hari 2"

    mock_graph = MagicMock()
    mock_graph.nodes = [node1, node2]

    mock_inspect = MagicMock()
    mock_inspect.graph = mock_graph

    mock_engine = MagicMock()
    mock_engine.inspect.return_value = mock_inspect

    monkeypatch.setattr("grandpa.vision.service.VisionEngine", lambda: mock_engine)

    msg = run_chrome_profile_selection("Hari")
    assert "Which Chrome profile do you mean" in msg


def test_window_focus_suffixes():
    calc_act = handle_local_action("Switch to calculator screen", execute=False)
    assert calc_act.status == "handled"
    assert calc_act.kind == "window"
    assert calc_act.target == "focus|calculator"

    chrome_act = handle_local_action("Bring Chrome app to front", execute=False)
    assert chrome_act.status == "handled"
    assert chrome_act.kind == "window"
    assert chrome_act.target == "focus|chrome"


def test_minimized_window_restore(monkeypatch):
    res = handle_local_action("restore Notepad", execute=False)
    assert res.status == "handled"
    assert res.kind == "window"
    assert res.target == "restore|notepad"


def test_background_listening_after_app_launch(monkeypatch):
    mock_sd = MagicMock()
    mock_stream = MagicMock()
    mock_sd.InputStream.return_value = mock_stream
    mock_sd.query_devices.return_value = [
        {
            "name": "mock_mic",
            "max_input_channels": 1,
            "default_samplerate": 44100.0,
            "hostapi": 0,
        }
    ]
    mock_sd.default.device = [0, 1]

    monkeypatch.setattr("grandpa.voice.microphone.import_sounddevice", lambda: mock_sd)
    monkeypatch.setattr(
        "grandpa.voice.device_manager.import_sounddevice", lambda: mock_sd
    )

    cap = MicrophoneCapture()
    cap.recovery_attempts = 2

    call_count = 0

    # Mirrors MicrophoneCapture._capture_from_device, which gained the
    # on_speech_start VAD-onset callback the presenter uses. The fake had not
    # been updated, so the real signature raised TypeError, which the retry
    # loop then reported as a microphone failure.
    def fake_capture(sd, dev, stop, on_speech_start=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("Device busy")
        return b"fake audio"

    cap._capture_from_device = fake_capture

    audio = cap.capture()
    assert audio == b"fake audio"
    assert call_count == 2


def test_grandpa_self_description():
    proc = VoiceCommandProcessor(model_name=None)
    res = proc.handle_user_input("tell me about yourself")
    assert res.status == "handled"
    assert res.kind == "local"
    assert "privacy-focused" in res.text
    assert "ISO" not in res.text


def test_stop_reasoning_and_cancel_intent_routing():
    act1 = handle_local_action("stop reasoning")
    assert act1.status == "handled"
    assert act1.kind == "session_control"
    assert "cancelled" in act1.message

    proc = VoiceCommandProcessor(model_name=None)
    res1 = proc.handle_user_input("stop reasoning")
    assert res1.kind == "session_control"
    assert "cancelled" in res1.text

    from grandpa.projects.commands import handle_project_command

    res2 = handle_project_command("stop reasoning")
    assert res2.status == "no_match"


def test_datetime_regression():
    from grandpa.core.runtime_context import handle_datetime_intent

    resp = handle_datetime_intent("what is today's date")
    assert resp is not None
    assert "today is" in resp.lower()


def test_tts_regression():
    from grandpa.voice.speech_output import SpeechOutputEngine

    engine = SpeechOutputEngine()
    assert hasattr(engine, "speak")


def test_stop_listening_regression():
    from grandpa.voice.cli_session import is_exit_phrase

    assert is_exit_phrase("stop listening") is True
    assert is_exit_phrase("exit") is True
