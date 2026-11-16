"""B5: hands-free end to end -- "Hey Grandpa, set volume to 30".

The whole voice path runs for real except the edges: the wake model's events,
the microphone, Whisper and the speaker are fakes, and the volume actuator is
mocked (no Windows audio endpoint on Linux CI). In between, the real
``VoiceSession`` audio-wake loop and the real ``VoiceCommandProcessor`` decide
what happens, with no Ollama: every phrase here must be handled without the
model, so the engine is made to fail loudly if anything reaches it.
"""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock

import pytest

from grandpa.action_layer.catalogue import get
from grandpa.desktop.automation import DesktopParser
from grandpa.pc_control import LocalActionResponse
from grandpa.voice.assistant import VoiceCommandProcessor
from grandpa.voice.cli_session import VoiceSession
from grandpa.voice.wake_engine import WakeEvent
from grandpa.voice.wake_word import strip_leading_wake_phrase


@pytest.fixture(autouse=True)
def _action_log(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GRANDPA_LOCAL_ACTION_LOG", str(tmp_path / "actions.jsonl"))


@pytest.fixture(autouse=True)
def _no_model(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(self, *args, **kwargs):
        raise AssertionError("this phrase must not need the model")

    monkeypatch.setattr(VoiceCommandProcessor, "_generate_response", refuse)
    # The session's start-up Ollama check: no Ollama on CI, and none needed.
    monkeypatch.setattr(VoiceCommandProcessor, "_ensure_engine", lambda self: None)


def _actuator(monkeypatch: pytest.MonkeyPatch, action: str, message: str) -> MagicMock:
    mock = MagicMock(
        return_value=LocalActionResponse(
            True, None, "completed", message, False, "LOW", {}
        )
    )
    monkeypatch.setattr(get(action).implementation, mock, raising=True)
    return mock


class Gate:
    """The openWakeWord gate: one "Hey Grandpa" per scripted entry."""

    label = "hey_grandpa"

    def __init__(self, wakes: int) -> None:
        self.wakes = wakes
        self.started = self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def clear(self):
        pass

    def wait_for_wake(self, stop=None, timeout=None):
        if threading.current_thread().name == "grandpa-barge-in":
            time.sleep(0.01)
            return None
        if self.wakes > 0:
            self.wakes -= 1
            return WakeEvent(model="hey_grandpa", score=0.9, at_seconds=1.0)
        time.sleep(0.01)
        return None


class Microphone:
    def __init__(self) -> None:
        self.captures = 0

    def capture(self, stop_event=None):
        self.captures += 1
        return object()

    def reset(self):
        pass

    def close(self):
        pass


class Whisper:
    def __init__(self, heard: list[str]) -> None:
        self.heard = list(heard)

    def transcribe(self, _audio) -> str:
        return self.heard.pop(0) if self.heard else "stop listening"


class Speaker:
    def __init__(self) -> None:
        self.spoken: list[str] = []
        self.is_speaking = False

    def speak(self, text, stop_event=None):
        self.spoken.append(text)

    def stop(self):
        pass

    def wait_until_finished(self, stop_event=None):
        return True


def _hands_free(heard: list[str], wakes: int):
    speaker = Speaker()
    mic = Microphone()
    output: list[str] = []
    session = VoiceSession(
        mic,
        Whisper(heard),
        VoiceCommandProcessor(model_name=None),
        speaker,
        output=output.append,
        stop_event=threading.Event(),
        wake_response_enabled=False,
        post_tts_cooldown_ms=0,
        audio_wake=Gate(wakes),
        barge_in_enabled=True,
    )
    done: list[int] = []
    thread = threading.Thread(target=lambda: done.append(session.run()))
    thread.start()
    thread.join(10)
    if thread.is_alive():
        session.stop_event.set()
        thread.join(2)
        pytest.fail("hands-free session did not finish")
    return done[0], speaker, mic, "\n".join(output)


@pytest.mark.parametrize(
    "heard",
    [
        "set volume to 30",
        # What Whisper writes when the capture opens on the wake phrase's tail.
        "Grandpa, set volume to 30.",
        "Hey Grandpa, set the volume to 30 percent.",
        "Set the volume to 30%.",
    ],
)
def test_hey_grandpa_set_volume_to_30(heard: str, monkeypatch) -> None:
    volume = _actuator(monkeypatch, "volume_set", "Volume set to 30%.")

    code, speaker, _mic, text = _hands_free([heard, "stop listening"], wakes=2)

    assert code == 0
    volume.assert_called_once()
    request = volume.call_args.args[0]
    assert request.args == {"level": 30}
    assert "Volume set to 30%." in speaker.spoken
    assert "Wake word detected." in text


def test_a_capture_that_was_only_the_wake_phrase_listens_again(monkeypatch) -> None:
    volume = _actuator(monkeypatch, "volume_set", "Volume set to 30%.")

    # One wake: "Grandpa." alone, then the command, then the goodbye after a
    # second wake. No extra "Hey Grandpa" is needed between the first two.
    code, speaker, mic, _text = _hands_free(
        ["Grandpa.", "set volume to 30", "stop listening"], wakes=2
    )

    assert code == 0
    volume.assert_called_once()
    assert mic.captures == 3
    assert "Volume set to 30%." in speaker.spoken


@pytest.mark.parametrize("answer", ["no", "yes"])
def test_shutdown_by_voice_needs_approval_and_never_runs(answer, monkeypatch) -> None:
    # Today a spoken answer cannot approve a shutdown at all: it is refused
    # with "approval required", and neither "no" nor "yes" runs it.
    shutdown = _actuator(monkeypatch, "system_shutdown", "Shutting down.")

    code, speaker, _mic, _text = _hands_free(
        ["Hey Grandpa, shut down the computer", answer, "stop listening"], wakes=3
    )

    assert code == 0
    shutdown.assert_not_called()
    assert "approval required" in speaker.spoken[0].lower(), speaker.spoken


@pytest.mark.parametrize(
    "transcript,command",
    [
        ("Hey Grandpa, set volume to 30.", "set volume to 30."),
        ("grandpa set volume to 30", "set volume to 30"),
        ("Hi Grandpa! Open Chrome", "Open Chrome"),
        ("Grandpa.", ""),
        ("set volume to 30", "set volume to 30"),
        # Only a leading phrase goes: the rest is the user's own sentence.
        ("call grandpa tomorrow", "call grandpa tomorrow"),
        ("Grandpas are wise", "Grandpas are wise"),
    ],
)
def test_strip_leading_wake_phrase(transcript: str, command: str) -> None:
    assert strip_leading_wake_phrase(transcript) == command


@pytest.mark.parametrize(
    "phrase",
    [
        "set volume to 30",
        "volume 30",
        "Set the volume to 30.",
        "set the volume to 30 percent",
        "Set the volume to 30%.",
        "change the volume to 30",
        "turn my volume to 30",
    ],
)
def test_spoken_volume_phrasings_parse(phrase: str) -> None:
    action = DesktopParser().parse(phrase)
    assert action is not None
    assert action.pc_action_type == "volume_set"
    assert action.args == {"level": 30}
