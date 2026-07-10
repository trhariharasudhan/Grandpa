"""Voice Operator Mode for command-first desktop control."""

from __future__ import annotations

import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from grandpa.pc_control import run_local_action
from grandpa.voice.errors import (
    MicrophoneUnavailableError,
    VoiceDependencyError,
    VoiceError,
    VoiceOutputUnavailableError,
    VoiceRecognitionError,
)
from grandpa.voice.speech_output import SpeechOutputEngine

OperatorStatus = Literal["handled", "blocked", "unsupported", "exit", "error"]


@dataclass(frozen=True)
class VoiceOperatorIntent:
    kind: str
    action: str = ""
    target: str = ""
    args: dict[str, Any] | None = None
    status: OperatorStatus = "handled"
    message: str = ""


@dataclass(frozen=True)
class VoiceOperatorResult:
    status: OperatorStatus
    message: str
    spoken_text: str
    action: dict[str, Any] | None = None
    requires_confirmation: bool = False


APP_ALIASES = {
    "chrome": "chrome",
    "google chrome": "chrome",
    "edge": "edge",
    "microsoft edge": "edge",
    "vscode": "vscode",
    "vs code": "vscode",
    "visual studio code": "vscode",
    "notepad": "notepad",
    "calculator": "calculator",
    "calc": "calculator",
    "file explorer": "file explorer",
    "explorer": "file explorer",
}
KEY_ALIASES = {
    "enter": "enter",
    "return": "enter",
    "escape": "esc",
    "esc": "esc",
    "tab": "tab",
}
DANGEROUS_PATTERNS = (
    r"\bdelete all\b",
    r"\bformat\b",
    r"\bshutdown\b",
    r"\brestart\b",
    r"\bpowershell\b",
    r"\bcmd\b",
    r"\bshell\b",
    r"\brun command\b",
)
LAUNCH_WORDS = {"start", "launch", "run"}
APP_PHRASE_ALIASES = {
    "google chrome browser": "chrome",
    "chrome browser": "chrome",
    "visual studio code": "vscode",
    "vs code": "vscode",
    "note bad": "notepad",
    "note pad": "notepad",
}


def parse_voice_operator_command(text: str) -> VoiceOperatorIntent:
    command = normalize_voice_operator_transcript(text)
    if not command:
        return VoiceOperatorIntent("none", status="unsupported", message="I did not hear a command.")
    if command in {"stop listening", "exit", "quit"}:
        return VoiceOperatorIntent("exit", status="exit", message="Voice Operator Mode stopped.")
    if any(re.search(pattern, command) for pattern in DANGEROUS_PATTERNS):
        return VoiceOperatorIntent("blocked", status="blocked", message="I blocked that command for safety.")

    if command in {"scan my apps", "scan apps", "scan installed apps"}:
        return VoiceOperatorIntent("app_inventory", "scan", message="Scanning installed apps.")
    if command in {"what apps do i have", "list apps", "show apps", "list my apps"}:
        return VoiceOperatorIntent("app_inventory", "list", message="Listing installed apps.")
    if command.startswith("find app "):
        name = command[len("find app ") :].strip()
        return VoiceOperatorIntent("app_inventory", "find", name, message=f"Finding {name}.")

    app = _match_app(command, prefixes=("open ",))
    if app:
        return VoiceOperatorIntent("local_action", "open_app", app, message=f"Opening {app}.")

    app = _match_app(command, prefixes=("switch to ", "focus "))
    if app:
        return VoiceOperatorIntent("local_action", "focus_window", app, message=f"Focusing {app}.")

    window_action = _parse_window_action(command)
    if window_action:
        return VoiceOperatorIntent("local_action", window_action, "active", message=_window_message(window_action))

    if command in {"screenshot", "take screenshot", "capture screen", "capture screenshot"}:
        return VoiceOperatorIntent("screen", "screenshot", message="Capturing the screen.")
    if command in {"what is on my screen", "what's on my screen", "read my screen", "describe my screen"}:
        return VoiceOperatorIntent("screen", "read", message="Reading the screen.")

    if command.startswith("type "):
        value = text.strip()[len("type ") :].strip()
        if not value:
            return VoiceOperatorIntent("none", status="unsupported", message="Tell me what text to type.")
        return VoiceOperatorIntent(
            "local_action",
            "keyboard_type",
            "focused app",
            {"text": value},
            message="Typing text.",
        )

    key_match = re.fullmatch(r"press (enter|return|escape|esc|tab)", command)
    if key_match:
        key = KEY_ALIASES[key_match.group(1)]
        return VoiceOperatorIntent(
            "local_action",
            "keyboard_hotkey",
            key,
            {"keys": [key]},
            message=f"Pressing {key}.",
        )

    return VoiceOperatorIntent(
        "none",
        status="unsupported",
        message="I don't know that operator command yet.",
    )


def execute_voice_operator_intent(
    intent: VoiceOperatorIntent,
    *,
    dry_run: bool = False,
    action_runner: Callable[[dict[str, Any]], Any] = run_local_action,
    screen_reader: Callable[..., Any] | None = None,
) -> VoiceOperatorResult:
    if intent.status in {"blocked", "unsupported", "exit"}:
        return VoiceOperatorResult(intent.status, intent.message, intent.message)
    if intent.kind == "app_inventory":
        return _execute_app_inventory_intent(intent)
    if intent.kind == "screen":
        return _execute_screen_intent(intent, screen_reader=screen_reader)
    if intent.kind != "local_action":
        return VoiceOperatorResult("unsupported", intent.message, intent.message)

    payload = {
        "action_type": intent.action,
        "target": intent.target,
        "args": intent.args or {},
        "dry_run": dry_run,
    }
    response = action_runner(payload)
    status: OperatorStatus = "handled" if getattr(response, "ok", False) else _coerce_status(getattr(response, "status", "error"))
    message = str(getattr(response, "message", intent.message))
    return VoiceOperatorResult(
        status=status,
        message=message,
        spoken_text=message,
        action=payload,
        requires_confirmation=bool(getattr(response, "approval_required", False)),
    )


def run_voice_operator_loop(
    *,
    input_func: Callable[[str], str] = input,
    output_func: Callable[[str], None] = print,
    listen_func: Callable[[], str] | None = None,
    action_runner: Callable[[dict[str, Any]], Any] | None = None,
    speech_output: SpeechOutputEngine | None = None,
    dry_run: bool = False,
    prefer_voice: bool | None = None,
    duration_seconds: float = 4.0,
    device: int | None = None,
    device_name: str | None = None,
    debug: bool = False,
) -> int:
    output_func("Voice Operator Mode started")
    output_func("Press Enter to record, or type a command. Say 'stop listening' to exit.")
    use_voice = sys.stdin.isatty() if prefer_voice is None else prefer_voice
    listener = listen_func or (
        lambda: _listen_once(
            duration_seconds=duration_seconds,
            device=device,
            device_name=device_name,
            debug_output=output_func if debug else None,
            warning_output=output_func,
        )
    )
    runner = action_runner or run_local_action
    speaker = speech_output or SpeechOutputEngine()

    while True:
        try:
            if use_voice:
                trigger = input_func("Press Enter to record, or type command: ")
                if trigger is None:
                    raise EOFError
                if trigger.strip():
                    text = trigger
                else:
                    output_func(f"Recording for {duration_seconds:g} seconds...")
                    try:
                        text = listener()
                    except VoiceRecognitionError as exc:
                        output_func(str(exc))
                        output_func("You can press Enter to try again, or type a command.")
                        continue
                    except (VoiceDependencyError, MicrophoneUnavailableError) as exc:
                        output_func(str(exc))
                        output_func("Falling back to typed input.")
                        use_voice = False
                        text = input_func("> ")
                    except VoiceError as exc:
                        output_func(str(exc))
                        output_func("Falling back to typed input.")
                        use_voice = False
                        text = input_func("> ")
                if not text.strip():
                    output_func("No command heard. Press Enter to record, or type a command.")
                    continue
            else:
                text = input_func("> ")
                if text is None:
                    raise EOFError
                if not text.strip():
                    continue
        except (EOFError, KeyboardInterrupt):
            output_func("Voice Operator Mode stopped")
            return 0

        normalized_text = normalize_voice_operator_transcript(text)
        if debug:
            output_func(f"Raw transcript: {text}")
            output_func(f"Normalized transcript: {normalized_text}")
        output_func(f"Understood: {normalized_text}")
        intent = parse_voice_operator_command(normalized_text)
        result = execute_voice_operator_intent(intent, dry_run=dry_run, action_runner=runner)
        output_func(result.message)
        _speak_best_effort(speaker, result.spoken_text, dry_run=dry_run)
        if result.status == "exit":
            return 0


def _execute_screen_intent(
    intent: VoiceOperatorIntent,
    *,
    screen_reader: Callable[..., Any] | None,
) -> VoiceOperatorResult:
    if screen_reader is None:
        from grandpa.screen_awareness import describe_screen

        screen_reader = describe_screen
    context = screen_reader(include_ocr=intent.action == "read")
    message = str(getattr(context, "message", "") or "I could not inspect the screen.")
    return VoiceOperatorResult("handled", message, message)


def _execute_app_inventory_intent(intent: VoiceOperatorIntent) -> VoiceOperatorResult:
    from grandpa.apps.inventory import find_app, list_apps, scan_app_inventory

    if intent.action == "scan":
        apps = scan_app_inventory()
        message = f"Scanned {len(apps)} apps."
        return VoiceOperatorResult("handled", message, message)
    if intent.action == "list":
        apps = list_apps()
        if not apps:
            message = "No app inventory found. Run scan my apps first."
        else:
            names = ", ".join(app.display_name for app in apps[:20])
            suffix = f" and {len(apps) - 20} more" if len(apps) > 20 else ""
            message = f"Installed apps: {names}{suffix}."
        return VoiceOperatorResult("handled", message, message)
    if intent.action == "find":
        result = find_app(intent.target)
        return VoiceOperatorResult("handled" if result.status == "found" else "unsupported", result.message, result.message)
    return VoiceOperatorResult("unsupported", "I don't know that app inventory command yet.", "I don't know that app inventory command yet.")


def _listen_once(
    *,
    duration_seconds: float = 4.0,
    device: int | None = None,
    device_name: str | None = None,
    debug_output: Callable[[str], None] | None = None,
    warning_output: Callable[[str], None] | None = None,
) -> str:
    from grandpa.jarvis.voice_input import (
        SoundDeviceMicrophoneRecorder,
        listen_for_jarvis_command,
    )

    recorder = SoundDeviceMicrophoneRecorder(duration_seconds=duration_seconds, device=device, device_name=device_name)
    try:
        return listen_for_jarvis_command(recorder=recorder).transcript
    finally:
        if warning_output and recorder.last_diagnostics and recorder.last_diagnostics.warning:
            warning_output(f"Audio warning: {recorder.last_diagnostics.warning}")
        if debug_output and recorder.last_diagnostics:
            diagnostics = recorder.last_diagnostics
            debug_output(f"Requested device: {diagnostics.requested_device_id}")
            debug_output(f"Requested device name: {diagnostics.requested_device_name}")
            debug_output(f"Actual device: {diagnostics.selected_device_id}")
            debug_output(f"Audio device name: {diagnostics.device_name}")
            debug_output(f"Audio channels: {diagnostics.channels}")
            debug_output(f"Audio sample rate: {diagnostics.sample_rate}")
            debug_output(f"Audio RMS level: {diagnostics.rms_level:.1f}")
            debug_output(f"Audio captured frames: {diagnostics.captured_frame_count}")


def _speak_best_effort(speech_output: SpeechOutputEngine, text: str, *, dry_run: bool) -> None:
    try:
        speech_output.speak(text, interrupt=True, dry_run=dry_run)
    except VoiceOutputUnavailableError:
        return


def _match_app(command: str, *, prefixes: tuple[str, ...]) -> str | None:
    for prefix in prefixes:
        if command.startswith(prefix):
            raw = command[len(prefix) :].strip()
            return APP_ALIASES.get(raw, raw)
    return None


def _parse_window_action(command: str) -> str | None:
    target_words = ("this window", "active window", "current window", "window")
    mapping = {
        "close": "close_window",
        "minimize": "minimize_window",
        "maximise": "maximize_window",
        "maximize": "maximize_window",
        "restore": "restore_window",
    }
    for verb, action in mapping.items():
        if any(command == f"{verb} {target}" for target in target_words):
            return action
    return None


def _window_message(action: str) -> str:
    labels = {
        "close_window": "Closing the active window.",
        "minimize_window": "Minimizing the active window.",
        "maximize_window": "Maximizing the active window.",
        "restore_window": "Restoring the active window.",
    }
    return labels[action]


def _coerce_status(status: str) -> OperatorStatus:
    if status in {"blocked", "unsupported"}:
        return status
    if status == "approval_required":
        return "handled"
    return "error"


def _normalise(text: str) -> str:
    value = text.strip().lower()
    value = re.sub(r"[?!.,;:]+", " ", value)
    return re.sub(r"\s+", " ", value)


def normalize_voice_operator_transcript(text: str) -> str:
    command = _normalise(text)
    if not command:
        return ""
    if command.startswith("type "):
        return command

    words = command.split()
    deduped_words: list[str] = []
    for word in words:
        if not deduped_words or deduped_words[-1] != word:
            deduped_words.append(word)
    command = " ".join(deduped_words)

    words = command.split()
    if words and words[0] in LAUNCH_WORDS:
        words[0] = "open"
        command = " ".join(words)

    if command.startswith("open "):
        target = command[len("open ") :].strip()
        target_words = target.split()
        while target_words and target_words[0] == "open":
            target_words.pop(0)
        target = _normalize_app_phrase(" ".join(target_words))
        return f"open {target}".strip()

    return _normalize_app_phrase(command)


def _normalize_app_phrase(value: str) -> str:
    result = value
    for phrase, replacement in sorted(APP_PHRASE_ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
        result = re.sub(rf"\b{re.escape(phrase)}\b", replacement, result)
    return re.sub(r"\s+", " ", result).strip()


__all__ = [
    "VoiceOperatorIntent",
    "VoiceOperatorResult",
    "execute_voice_operator_intent",
    "normalize_voice_operator_transcript",
    "parse_voice_operator_command",
    "run_voice_operator_loop",
]
