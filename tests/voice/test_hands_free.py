"""B2: always listening for "Hey Grandpa", VAD command capture, barge-in.

No microphone, no wake model, no Whisper: the gate's listener, the
microphone, the transcriber and the speaker are fakes, so these run on Linux CI.
"""

from __future__ import annotations

import threading
import time

import pytest
from click.testing import CliRunner

from grandpa.voice.cli_session import VoiceSession, _spoken_label
from grandpa.voice.errors import MicrophoneUnavailableError
from grandpa.voice.hands_free import MicrophoneStopped, WakeGate
from grandpa.voice.wake_engine import WakeEvent


def _event(at: float = 1.0) -> WakeEvent:
    return WakeEvent(model="hey_grandpa", score=0.9, at_seconds=at)


# --------------------------------------------------------------------- gate


class FakeListener:
    def __init__(self, engine, on_wake, *, device=None, sounddevice_module=None):
        self.engine = engine
        self.on_wake = on_wake
        self.device = device
        self.started = 0
        self.stopped = 0
        self.error = ""

    def start(self):
        self.started += 1

    def stop(self):
        self.stopped += 1


class FakeEngine:
    label = "hey_grandpa"


def _gate() -> tuple[WakeGate, FakeListener]:
    gate = WakeGate(FakeEngine(), device=3, listener_factory=FakeListener)
    return gate, gate._listener


def test_gate_hands_over_wakes_from_the_audio_thread():
    gate, listener = _gate()
    assert listener.device == 3
    with gate:
        assert listener.started == 1
        gate.start()  # idempotent
        assert listener.started == 1
        listener.on_wake(_event(2.0))
        got = gate.wait_for_wake(threading.Event(), timeout=1.0)
        assert got is not None and got.at_seconds == 2.0
        assert gate.wait_for_wake(threading.Event(), timeout=0.05) is None
    assert listener.stopped == 1


def test_gate_clear_forgets_wakes_heard_while_busy():
    gate, listener = _gate()
    listener.on_wake(_event())
    listener.on_wake(_event())
    gate.clear()
    assert gate.wait_for_wake(None, timeout=0.05) is None


def test_gate_never_blocks_the_audio_thread_when_full():
    gate, listener = _gate()
    for i in range(20):
        listener.on_wake(_event(float(i)))  # must not raise or block


def test_gate_returns_on_stop_and_reports_a_dead_microphone():
    gate, listener = _gate()
    stop = threading.Event()
    stop.set()
    assert gate.wait_for_wake(stop) is None
    listener.error = "device unplugged"
    with pytest.raises(MicrophoneStopped) as info:
        gate.wait_for_wake(threading.Event(), timeout=1.0)
    assert isinstance(info.value, MicrophoneUnavailableError)
    assert "device unplugged" in str(info.value)


# ------------------------------------------------------------------ session


class ScriptedGate:
    """Each idle ``wait_for_wake`` takes the next scripted answer.

    Calls from the barge-in watch (its own thread) take from ``during_speech``
    instead, so the two never race for the same answer.
    """

    label = "hey_grandpa"

    def __init__(
        self,
        script: list[WakeEvent | None],
        during_speech: list[WakeEvent | None] | None = None,
    ) -> None:
        self.script = list(script)
        self.during_speech = list(during_speech or [])
        self.waits = 0
        self.started = False
        self.stopped = False
        self.cleared = 0

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def clear(self):
        self.cleared += 1

    def wait_for_wake(self, stop=None, timeout=None):
        self.waits += 1
        barge = threading.current_thread().name == "grandpa-barge-in"
        script = self.during_speech if barge else self.script
        if script:
            return script.pop(0)
        time.sleep(min(timeout or 0.01, 0.01))
        return None


class Audio:
    pass


class Microphone:
    def __init__(self) -> None:
        self.captures = 0

    def capture(self, stop_event=None):
        self.captures += 1
        return Audio()

    def reset(self):
        pass

    def close(self):
        pass


class Transcriber:
    def __init__(self, transcripts: list[str]) -> None:
        self.transcripts = list(transcripts)
        self.calls = 0

    def transcribe(self, _audio) -> str:
        self.calls += 1
        return self.transcripts.pop(0) if self.transcripts else "stop listening"


class Responder:
    def __init__(self) -> None:
        self.received: list[str] = []

    def handle_user_input(self, text: str):
        self.received.append(text)
        return type("R", (), {"text": f"Handled {text}"})()


class SlowSpeaker:
    """Replies starting with "Handled" play for up to ``seconds`` unless stopped."""

    def __init__(self, seconds: float = 2.0) -> None:
        self.seconds = seconds
        self.spoken: list[str] = []
        self.interrupted: list[bool] = []
        self.stop_calls = 0
        self.is_speaking = False

    def speak(self, text, stop_event=None):
        self.spoken.append(text)
        if not text.startswith("Handled"):
            return
        interrupted = bool(stop_event and stop_event.wait(self.seconds))
        self.interrupted.append(interrupted)

    def stop(self):
        self.stop_calls += 1

    def wait_until_finished(self, stop_event=None):
        return stop_event is None or not stop_event.is_set()


def _run(session: VoiceSession, seconds: float = 5.0) -> int:
    result: list[int] = []
    thread = threading.Thread(target=lambda: result.append(session.run()))
    thread.start()
    thread.join(seconds)
    if thread.is_alive():
        session.stop_event.set()
        thread.join(2)
        pytest.fail("voice session did not finish")
    return result[0]


def _session(gate, transcripts, speaker, *, barge_in=True, wake_response=False):
    output: list[str] = []
    mic = Microphone()
    transcriber = Transcriber(transcripts)
    responder = Responder()
    session = VoiceSession(
        mic,
        transcriber,
        responder,
        speaker,
        output=output.append,
        stop_event=threading.Event(),
        wake_response_enabled=wake_response,
        post_tts_cooldown_ms=0,
        audio_wake=gate,
        barge_in_enabled=barge_in,
    )
    return session, mic, transcriber, responder, output


def test_nothing_is_transcribed_until_hey_grandpa():
    gate = ScriptedGate([None, None, None, _event(), _event()])
    session, mic, transcriber, responder, output = _session(
        gate, ["set volume to 30", "stop listening"], SlowSpeaker(0.01)
    )
    assert _run(session) == 0
    # Three idle polls heard nothing: no capture, no Whisper.
    assert mic.captures == 2 and transcriber.calls == 2
    assert responder.received == ["set volume to 30"]
    assert gate.started and gate.stopped
    text = "\n".join(output)
    assert "Say 'Hey Grandpa'" in text
    assert "Wake word detected." in text


def test_wake_response_is_spoken_before_listening():
    gate = ScriptedGate([_event(), None, _event()])
    speaker = SlowSpeaker(0.01)
    session, *_ = _session(
        gate, ["what time is it", "stop listening"], speaker, wake_response=True
    )
    assert _run(session) == 0
    assert speaker.spoken[0] == "Yes?"


def test_hey_grandpa_while_he_speaks_stops_him_and_listens_at_once():
    # Idle -> wake; then "Hey Grandpa" again while the reply plays.
    gate = ScriptedGate([_event(1.0)], during_speech=[_event(5.0)])
    speaker = SlowSpeaker(seconds=3.0)
    session, mic, _t, responder, output = _session(
        gate, ["tell me a long story", "stop listening"], speaker
    )
    started = time.monotonic()
    assert _run(session) == 0
    assert time.monotonic() - started < 2.5  # the 3 s reply was cut short
    assert speaker.interrupted == [True]
    assert speaker.stop_calls >= 1
    # Second command came straight after the barge-in, with no third wake.
    assert responder.received == ["tell me a long story"]
    assert mic.captures == 2
    assert "Stopped. Listening..." in "\n".join(output)


def test_no_barge_in_lets_the_reply_finish():
    gate = ScriptedGate([_event(), _event()])
    speaker = SlowSpeaker(seconds=0.3)
    session, mic, _t, responder, _o = _session(
        gate, ["tell me a story", "stop listening"], speaker, barge_in=False
    )
    assert _run(session) == 0
    assert speaker.interrupted == [False]
    assert responder.received == ["tell me a story"]


def test_dead_wake_microphone_ends_the_session_with_a_message():
    class DeadGate(ScriptedGate):
        def wait_for_wake(self, stop=None, timeout=None):
            raise MicrophoneStopped("device unplugged")

    gate = DeadGate([])
    session, *_rest, output = _session(gate, [], SlowSpeaker(0.01))
    assert _run(session) == 1
    assert any("device unplugged" in line for line in output)
    assert gate.stopped


def test_without_audio_wake_the_speaker_still_obeys_the_session_stop():
    speaker = SlowSpeaker(0.01)
    session, *_ = _session(None, ["hello", "stop listening"], speaker)
    stop = session.stop_event
    session._speak("Handled hi")
    assert speaker.interrupted == [False]
    assert not stop.is_set()


@pytest.mark.parametrize(
    "label,spoken",
    [
        ("hey_grandpa", "Hey Grandpa"),
        ("/home/x/.Grandpa/wakeword/hey_grandpa.onnx", "Hey Grandpa"),
        ("hey_mycroft", "Hey Mycroft"),
        ("", "Hey Grandpa"),
    ],
)
def test_spoken_label(label, spoken):
    assert _spoken_label(label) == spoken


# ---------------------------------------------------------------------- CLI


def test_cli_hey_grandpa_without_a_model_says_what_to_do(monkeypatch):
    from grandpa.cli import voice_cmd
    from grandpa.voice import wake_engine as we

    def no_model(config):
        raise we.WakeEngineUnavailable(we.SETUP_HINT)

    monkeypatch.setattr(we, "WakeWordEngine", no_model)
    built: list[dict] = []
    monkeypatch.setattr(voice_cmd, "build_voice_session", lambda **kw: built.append(kw))
    result = CliRunner().invoke(voice_cmd.voice, ["--hey-grandpa"])
    assert result.exit_code == 1
    assert "push-to-talk" in result.output
    assert built == []


def test_cli_hey_grandpa_wires_the_gate_and_barge_in(monkeypatch):
    from grandpa.cli import voice_cmd
    from grandpa.voice import hands_free
    from grandpa.voice import wake_engine as we

    monkeypatch.setattr(we, "WakeWordEngine", lambda config: FakeEngine())
    monkeypatch.setattr(
        hands_free,
        "WakeWordListener",
        FakeListener,
    )
    built: list[dict] = []

    class Done:
        def run(self):
            return 0

    def fake_build(**kwargs):
        built.append(kwargs)
        return Done()

    monkeypatch.setattr(voice_cmd, "build_voice_session", fake_build)
    result = CliRunner().invoke(
        voice_cmd.voice, ["--hey-grandpa", "--no-barge-in", "--no-tts"]
    )
    assert result.exit_code == 0, result.output
    kwargs = built[0]
    assert isinstance(kwargs["audio_wake"], WakeGate)
    assert kwargs["barge_in"] is False
    assert kwargs["wake_word"] is True
