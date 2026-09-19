"""Replace everything that sends keys, moves the mouse, or acts on a window.

A gate test that leaves the real actuator in place is not a test: when the gate
is broken, the machine running the test is what gets typed into. This session
proved it -- a probe sent a real Ctrl+C to the foreground window.

``install`` swaps every actuating primitive this codebase reaches for a recorder,
and swaps the window reads that decide *whether* to actuate for stand-ins that
find one ordinary Notepad window, so a gate is exercised all the way down
rather than stopped early by "no such window". It then checks every swap held
before returning. Anything a test drives afterwards can only be recorded.

The primitives are the bottom of the stack on purpose: a test built on them
does not care which component does the refusing today.
"""

from __future__ import annotations

import ctypes
import importlib
import sys
from dataclasses import dataclass, field
from typing import Any

# pyautogui: every function that emits input.
PYAUTOGUI_INPUT = (
    "write",
    "typewrite",
    "hotkey",
    "press",
    "keyDown",
    "keyUp",
    "click",
    "leftClick",
    "doubleClick",
    "tripleClick",
    "rightClick",
    "middleClick",
    "mouseDown",
    "mouseUp",
    "moveTo",
    "moveRel",
    "move",
    "dragTo",
    "dragRel",
    "drag",
    "scroll",
    "hscroll",
    "vscroll",
)

# user32 through ctypes: keyboard, mouse, messages and foreground changes.
USER32_ACTUATORS = (
    "keybd_event",
    "SendInput",
    "mouse_event",
    "SetCursorPos",
    "SendMessageW",
    "PostMessageW",
    "SetForegroundWindow",
    "BringWindowToTop",
    "ShowWindow",
)

# pywin32, the same operations by another door.
PYWIN32_ACTUATORS = {
    "win32api": ("keybd_event", "mouse_event", "SetCursorPos", "SendMessage"),
    "win32gui": (
        "SendMessage",
        "PostMessage",
        "SetForegroundWindow",
        "BringWindowToTop",
        "ShowWindow",
    ),
}

# Grandpa's own window actuators: focus, close, dialog buttons, UIA invoke.
GRANDPA_ACTUATORS = {
    "grandpa.windows_window_control": (
        "_apply_action",
        "_request_notepad_document_close",
        "invoke_dialog_choice",
        "_set_save_as_filename",
        "_invoke_uia_labeled_control",
        "invoke_uia_controls_by_id",
    ),
    "grandpa.automation.windows": (
        "focus_window_handle",
        "close_window_identity",
        "invoke_window_control_sequence",
        "invoke_window_dialog_choice",
        "complete_window_save_as",
    ),
}


@dataclass
class InputRecorder:
    calls: list[tuple[str, tuple, dict]] = field(default_factory=list)

    def recorder(self, name: str):
        def record(*args: Any, **kwargs: Any) -> Any:
            self.calls.append((name, args, kwargs))
            return True

        record.__input_recorder__ = name  # type: ignore[attr-defined]
        return record

    @property
    def actuated(self) -> list[str]:
        return [name for name, _args, _kwargs in self.calls]


def _fake_windows():
    from grandpa.automation.windows import WindowIdentity
    from grandpa.windows_window_control import WindowInfo

    identity = WindowIdentity(
        handle=0x5EC,
        title="Untitled - Notepad",
        process_id=0,
        process_name="notepad.exe",
        target="notepad",
    )
    info = WindowInfo(0x5EC, "Untitled - Notepad", "notepad", 0)
    return identity, info


def install(monkeypatch) -> InputRecorder:
    """Swap every actuator for a recorder and prove each swap held."""
    rec = InputRecorder()
    swapped: list[tuple[object, str]] = []

    def swap(owner: object, name: str, label: str) -> None:
        monkeypatch.setattr(owner, name, rec.recorder(label), raising=False)
        swapped.append((owner, name))

    import pyautogui

    for name in PYAUTOGUI_INPUT:
        swap(pyautogui, name, f"pyautogui.{name}")
    # Reads pyautogui answers for the input code; never the real screen.
    monkeypatch.setattr(pyautogui, "size", lambda: (1920, 1080))
    monkeypatch.setattr(pyautogui, "position", lambda: (960, 540))

    def _no_screen(*_a, **_k):
        raise RuntimeError("screen reads are mocked in input-gate tests")

    monkeypatch.setattr(pyautogui, "screenshot", _no_screen)

    if sys.platform == "win32":
        user32 = ctypes.windll.user32
        for name in USER32_ACTUATORS:
            swap(user32, name, f"user32.{name}")

    for module_name, names in PYWIN32_ACTUATORS.items():
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            continue
        for name in names:
            swap(module, name, f"{module_name}.{name}")

    for module_name, names in GRANDPA_ACTUATORS.items():
        module = importlib.import_module(module_name)
        for name in names:
            assert hasattr(module, name), (
                f"{module_name}.{name} moved; update the recorder"
            )
            swap(module, name, f"{module_name}.{name}")

    # Launching. Not input, but a voice phrase can reach it ("go to notepad"
    # launched a real Notepad from a probe that recorded only input), so a
    # test using this recorder must not be able to start anything either.
    import os
    import subprocess
    import webbrowser

    def _refuse_launch(label: str):
        record = rec.recorder(label)

        def launch(*args: Any, **kwargs: Any) -> Any:
            record(*args, **kwargs)
            raise OSError(f"input-gate test: {label} recorded, not started")

        launch.__input_recorder__ = label  # type: ignore[attr-defined]
        return launch

    for owner, name, label in (
        (subprocess, "Popen", "subprocess.Popen"),
        (os, "startfile", "os.startfile"),
        (webbrowser, "open", "webbrowser.open"),
        (webbrowser, "open_new", "webbrowser.open"),
        (webbrowser, "open_new_tab", "webbrowser.open"),
    ):
        monkeypatch.setattr(owner, name, _refuse_launch(label), raising=False)
        swapped.append((owner, name))
    if sys.platform == "win32":
        shell32 = ctypes.windll.shell32
        monkeypatch.setattr(shell32, "ShellExecuteW", _refuse_launch("ShellExecuteW"))
        swapped.append((shell32, "ShellExecuteW"))
    try:
        import win32api

        monkeypatch.setattr(win32api, "ShellExecute", _refuse_launch("ShellExecute"))
        swapped.append((win32api, "ShellExecute"))
    except ImportError:
        pass
    import grandpa.windows_app_resolver as resolver

    monkeypatch.setattr(resolver, "launch_app", _refuse_launch("launch_app"))
    swapped.append((resolver, "launch_app"))

    # The reads that decide whether there is anything to act on: one Notepad.
    import grandpa.automation.windows as targets
    import grandpa.windows_window_control as wc

    identity, info = _fake_windows()
    monkeypatch.setattr(targets, "resolve_window", lambda _target: identity)
    monkeypatch.setattr(targets, "foreground_window", lambda: identity)
    monkeypatch.setattr(targets, "window_handle_exists", lambda _h: True)
    monkeypatch.setattr(targets, "window_identity_ready", lambda _w: True)
    monkeypatch.setattr(wc, "_resolve_window", lambda _target: info)
    monkeypatch.setattr(wc, "_get_foreground_window", lambda: info.handle)
    monkeypatch.setattr(wc, "_list_windows", lambda: [info])

    # A browser in front, so browser hotkeys (back, reload, new tab) get past
    # "the foreground window is not a browser" and reach the input they send.
    # Its page comes from this payload; the real browser is never read.
    import json

    import grandpa.browser_control as browser_control

    monkeypatch.setenv(
        "GRANDPA_BROWSER_CONTEXT_JSON",
        json.dumps(
            {
                "title": "Example Page",
                "url": "https://example.test",
                "headings": ["Example"],
                "visible_text": "An example page.",
            }
        ),
    )
    monkeypatch.setattr(
        browser_control, "_active_window_title", lambda: "Example Page - Google Chrome"
    )
    if sys.platform == "win32":
        assert browser_control._find_visible_browser_window() is not None

    # Held: every name now resolves to a recorder, and a recorder records.
    for owner, name in swapped:
        current = getattr(owner, name)
        assert getattr(current, "__input_recorder__", None), (
            f"{owner!r}.{name} is still the real actuator"
        )
    pyautogui.press("recorder-probe")
    try:
        subprocess.Popen(["recorder-probe"])
    except OSError:
        pass
    else:  # pragma: no cover - the swap failed
        raise AssertionError("subprocess.Popen started a process")
    assert rec.actuated == ["pyautogui.press", "subprocess.Popen"], (
        f"a recorder did not hold: {rec.actuated}"
    )
    rec.calls.clear()
    return rec
