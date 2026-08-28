from __future__ import annotations

import threading

import pytest

from grandpa.cli.theme import FAREWELL_TEXT
from grandpa.voice.cli_session import (
    VoiceSession,
    is_exit_phrase,
    is_probable_speaker_echo,
)
from grandpa.voice.config import load_voice_assistant_config
from grandpa.voice.errors import (
    MicrophoneUnavailableError,
    VoiceDependencyError,
    VoiceRecognitionError,
)
from grandpa.voice.microphone import CapturedAudio
from grandpa.voice.text_to_speech import GrandpaTextToSpeech, clean_text_for_speech
from grandpa.voice.wake_word import WakeWordDetector


class FakeAudio:
    pass


class FakeMicrophone:
    def __init__(
        self,
        count: int = 1,
        error: Exception | None = None,
        *,
        error_on_calls: dict[int, Exception] | None = None,
        set_stop_on_capture: bool = False,
    ) -> None:
        self.count = count
        self.error = error
        self.error_on_calls = error_on_calls or {}
        self.calls = 0
        self.closed = False
        self.reset_calls = 0
        self.stop_events: list[threading.Event | None] = []
        self.set_stop_on_capture = set_stop_on_capture

    def capture(self, stop_event: threading.Event | None = None):
        self.calls += 1
        self.stop_events.append(stop_event)
        if self.calls in self.error_on_calls:
            raise self.error_on_calls[self.calls]
        if self.error is not None:
            raise self.error
        if self.set_stop_on_capture and stop_event is not None:
            stop_event.set()
        return FakeAudio()

    def close(self) -> None:
        self.closed = True

    def reset(self) -> None:
        self.reset_calls += 1


class FakeTranscriber:
    def __init__(
        self, transcripts: list[str] | None = None, error: Exception | None = None
    ) -> None:
        self.transcripts = transcripts or []
        self.error = error
        self.calls = 0

    def transcribe(self, _audio) -> str:
        self.calls += 1
        if self.error is not None:
            raise self.error
        if not self.transcripts:
            return "stop listening"
        return self.transcripts.pop(0)


class FakeResponder:
    def __init__(self) -> None:
        self.received: list[str] = []

    def handle_user_input(self, text: str):
        self.received.append(text)
        return type("Response", (), {"text": f"Handled {text}"})()


class FakeSpeaker:
    def __init__(self, error: Exception | None = None) -> None:
        self.spoken: list[str] = []
        self.stop_events: list[threading.Event | None] = []
        self.error = error
        self.stopped = False
        self.is_speaking = False
        self.wait_calls = 0

    def speak(self, text: str, stop_event: threading.Event | None = None) -> None:
        self.spoken.append(text)
        self.stop_events.append(stop_event)
        if self.error is not None:
            raise self.error

    def stop(self) -> None:
        self.stopped = True

    def wait_until_finished(self, stop_event: threading.Event | None = None) -> bool:
        self.wait_calls += 1
        return stop_event is None or not stop_event.is_set()


def test_voice_session_successful_transcription_flow() -> None:
    output: list[str] = []
    responder = FakeResponder()
    speaker = FakeSpeaker()
    session = VoiceSession(
        FakeMicrophone(),
        FakeTranscriber(["open notepad", "stop listening"]),
        responder,
        speaker,
        output=output.append,
    )

    assert session.run() == 0
    assert any("Voice Assistant" in line for line in output)
    assert "You: open notepad" in output
    assert "Grandpa: Handled open notepad" in output
    assert responder.received == ["open notepad"]
    assert speaker.spoken == [
        "Handled open notepad",
        "Goodbye! I’ll be here when you need me.",
    ]


def test_microphone_capture_waits_until_speaker_is_idle() -> None:
    events: list[str] = []

    class WaitingSpeaker(FakeSpeaker):
        def __init__(self) -> None:
            super().__init__()
            self.is_speaking = True

        def wait_until_finished(self, stop_event=None) -> bool:
            events.append("speaker-finished")
            self.is_speaking = False
            return True

    class OrderedMicrophone(FakeMicrophone):
        def capture(self, stop_event=None):
            events.append("capture")
            return super().capture(stop_event)

    session = VoiceSession(
        OrderedMicrophone(),
        FakeTranscriber(["stop listening"]),
        FakeResponder(),
        WaitingSpeaker(),
        post_tts_cooldown_ms=0,
    )
    assert session.run() == 0
    assert events[:2] == ["speaker-finished", "capture"]


def test_voice_session_waits_for_async_tts_before_next_capture() -> None:
    events: list[str] = []

    class AsyncSpeaker(FakeSpeaker):
        def speak(self, text, stop_event=None) -> None:
            super().speak(text, stop_event)
            self.is_speaking = True
            events.append("speak")

        def wait_until_finished(self, stop_event=None) -> bool:
            events.append("tts-finished")
            self.is_speaking = False
            return True

    class OrderedMicrophone(FakeMicrophone):
        def capture(self, stop_event=None):
            events.append("capture")
            return super().capture(stop_event)

    session = VoiceSession(
        OrderedMicrophone(),
        FakeTranscriber(["hello", "stop listening"]),
        FakeResponder(),
        AsyncSpeaker(),
        post_tts_cooldown_ms=0,
    )
    assert session.run() == 0
    first_speak = events.index("speak")
    assert events[first_speak : first_speak + 3] == ["speak", "tts-finished", "capture"]


def test_post_tts_cooldown_is_stop_aware_and_configured() -> None:
    waits: list[float] = []
    stop = threading.Event()
    session = VoiceSession(
        FakeMicrophone(),
        FakeTranscriber(),
        FakeResponder(),
        FakeSpeaker(),
        stop_event=stop,
        post_tts_cooldown_ms=400,
        cooldown_wait=lambda _stop, seconds: waits.append(seconds) or False,
    )
    session._speak("Hello.")
    assert waits == [0.4]


def test_microphone_buffers_are_reset_around_tts_and_each_capture() -> None:
    microphone = FakeMicrophone()
    session = VoiceSession(
        microphone,
        FakeTranscriber(["hello", "stop listening"]),
        FakeResponder(),
        FakeSpeaker(),
        post_tts_cooldown_ms=0,
    )
    assert session.run() == 0
    assert microphone.calls == 2
    assert microphone.reset_calls >= 4


def test_exact_spoken_response_echo_is_ignored() -> None:
    output: list[str] = []
    responder = FakeResponder()
    session = VoiceSession(
        FakeMicrophone(),
        FakeTranscriber(["hello", "Handled hello", "stop listening"]),
        responder,
        FakeSpeaker(),
        output=output.append,
        post_tts_cooldown_ms=0,
    )
    assert session.run() == 0
    assert responder.received == ["hello"]
    assert "Ignoring probable speaker echo." in output


def test_short_you_echo_is_ignored_inside_echo_window() -> None:
    output: list[str] = []
    responder = FakeResponder()
    session = VoiceSession(
        FakeMicrophone(),
        FakeTranscriber(["hello", "you", "stop listening"]),
        responder,
        FakeSpeaker(),
        output=output.append,
        post_tts_cooldown_ms=0,
    )
    assert session.run() == 0
    assert responder.received == ["hello"]
    assert output.count("Ignoring probable speaker echo.") == 1


def test_similar_user_command_outside_echo_window_is_accepted() -> None:
    assert not is_probable_speaker_echo(
        "Opening Notepad",
        "Opening Notepad.",
        age_seconds=3.1,
        window_seconds=3.0,
    )


def test_normal_next_user_command_is_processed() -> None:
    responder = FakeResponder()
    session = VoiceSession(
        FakeMicrophone(),
        FakeTranscriber(["hello", "open notepad", "stop listening"]),
        responder,
        FakeSpeaker(),
        post_tts_cooldown_ms=0,
    )
    assert session.run() == 0
    assert responder.received == ["hello", "open notepad"]


def test_ctrl_c_during_tts_stops_speech_without_resuming_capture() -> None:
    class InterruptingSpeaker(FakeSpeaker):
        def speak(self, text, stop_event=None) -> None:
            self.spoken.append(text)
            raise KeyboardInterrupt

    output: list[str] = []
    microphone = FakeMicrophone()
    speaker = InterruptingSpeaker()
    session = VoiceSession(
        microphone,
        FakeTranscriber(["hello"]),
        FakeResponder(),
        speaker,
        output=output.append,
        post_tts_cooldown_ms=0,
    )
    assert session.run() == 0
    assert microphone.calls == 1
    assert speaker.stopped is True
    assert FAREWELL_TEXT in output
    assert f"Grandpa: {FAREWELL_TEXT}" not in output


def test_grandpa_tts_exposes_reliable_speaking_state(monkeypatch) -> None:
    started = threading.Event()
    release = threading.Event()
    tts = GrandpaTextToSpeech()

    def blocking_speak(*_args, **_kwargs) -> None:
        started.set()
        release.wait(timeout=2)

    monkeypatch.setattr(tts._engine, "speak", blocking_speak)
    stop = threading.Event()
    worker = threading.Thread(target=tts.speak, args=("Hello", stop))
    worker.start()
    assert started.wait(timeout=1)
    assert tts.is_speaking is True
    release.set()
    worker.join(timeout=2)
    assert not worker.is_alive()
    assert tts.wait_until_finished(stop) is True
    assert tts.is_speaking is False


def test_voice_session_empty_transcription_is_ignored() -> None:
    output: list[str] = []
    responder = FakeResponder()
    session = VoiceSession(
        FakeMicrophone(),
        FakeTranscriber([" ", "exit"]),
        responder,
        None,
        output=output.append,
    )

    assert session.run() == 0
    assert "I did not catch that." in output
    assert responder.received == []


def test_voice_session_exit_phrase_stops_loop() -> None:
    output: list[str] = []
    session = VoiceSession(
        FakeMicrophone(),
        FakeTranscriber(["goodbye grandpa"]),
        FakeResponder(),
        None,
        output=output.append,
    )

    assert session.run() == 0
    assert FAREWELL_TEXT in output
    assert f"Grandpa: {FAREWELL_TEXT}" not in output


def test_voice_session_ctrl_c_shuts_down_cleanly() -> None:
    output: list[str] = []
    microphone = FakeMicrophone(error=KeyboardInterrupt())
    speaker = FakeSpeaker()
    session = VoiceSession(
        microphone,
        FakeTranscriber(),
        FakeResponder(),
        speaker,
        output=output.append,
    )

    assert session.run() == 0
    assert FAREWELL_TEXT in output
    assert f"Grandpa: {FAREWELL_TEXT}" not in output
    assert "Voice assistant stopped." not in output
    assert not any("Traceback" in line for line in output)
    assert microphone.closed is True
    assert speaker.stopped is True


def test_voice_session_stop_event_interrupts_capture_without_transcribing() -> None:
    output: list[str] = []
    microphone = FakeMicrophone(set_stop_on_capture=True)
    transcriber = FakeTranscriber(["hello"])
    session = VoiceSession(
        microphone,
        transcriber,
        FakeResponder(),
        None,
        output=output.append,
    )

    assert session.run() == 0
    assert microphone.calls == 1
    assert microphone.stop_events[0] is not None
    assert microphone.stop_events[0].is_set()
    assert transcriber.calls == 0
    assert output.count("Listening...") == 1
    assert "Goodbye! I’ll be here when you need me." not in output


def test_voice_session_microphone_failure_is_actionable() -> None:
    output: list[str] = []
    microphone = FakeMicrophone(error=MicrophoneUnavailableError())
    session = VoiceSession(
        microphone,
        FakeTranscriber(),
        FakeResponder(),
        None,
        output=output.append,
    )

    assert session.run() == 1
    assert any("No usable microphone was detected" in line for line in output)
    assert microphone.closed is True


def test_voice_session_stt_initialization_failure_is_actionable() -> None:
    output: list[str] = []
    session = VoiceSession(
        FakeMicrophone(),
        FakeTranscriber(
            error=VoiceDependencyError("The Whisper model could not be loaded.")
        ),
        FakeResponder(),
        None,
        output=output.append,
    )

    assert session.run() == 1
    assert any("The Whisper model could not be loaded." in line for line in output)


def test_voice_session_recoverable_recognition_failure_continues() -> None:
    class OnceFailingTranscriber(FakeTranscriber):
        def transcribe(self, audio) -> str:
            self.calls += 1
            if self.calls == 1:
                raise VoiceRecognitionError()
            return "quit"

    output: list[str] = []
    session = VoiceSession(
        FakeMicrophone(),
        OnceFailingTranscriber(),
        FakeResponder(),
        None,
        output=output.append,
    )

    assert session.run() == 0
    assert any("I could not understand the audio" in line for line in output)


def test_voice_session_tts_failure_does_not_crash() -> None:
    output: list[str] = []
    session = VoiceSession(
        FakeMicrophone(),
        FakeTranscriber(["hello", "quit"]),
        FakeResponder(),
        FakeSpeaker(error=VoiceDependencyError("TTS failed")),
        output=output.append,
    )

    assert session.run() == 0
    assert any("Text-to-speech is unavailable" in line for line in output)


def test_voice_session_passes_stop_event_to_tts_and_stops_on_cleanup() -> None:
    output: list[str] = []
    speaker = FakeSpeaker()
    session = VoiceSession(
        FakeMicrophone(),
        FakeTranscriber(["hello", "quit"]),
        FakeResponder(),
        speaker,
        output=output.append,
    )

    assert session.run() == 0
    assert speaker.stop_events
    assert all(event is not None for event in speaker.stop_events)
    assert speaker.stopped is True


def test_wake_word_detector_matches_default_phrases() -> None:
    detector = WakeWordDetector()

    assert detector.matches("Grandpa")
    assert detector.matches("  Hey Grandpa!  ")
    assert detector.matches("HEY, GRANDPA?")


def test_wake_word_detector_does_not_match_unrelated_words() -> None:
    detector = WakeWordDetector()

    assert not detector.matches("my grandparent is visiting")
    assert not detector.matches("hello there")


def test_wake_word_detector_extracts_inline_command() -> None:
    match = WakeWordDetector().detect("Hey Grandpa, open calculator please")

    assert match.matched is True
    assert match.phrase == "hey grandpa"
    assert match.command_text == "open calculator please"


def test_wake_word_detector_returns_empty_command_for_wake_only() -> None:
    match = WakeWordDetector().detect("Hey Grandpa!")

    assert match.matched is True
    assert match.command_text == ""


def test_wake_word_mode_uses_second_utterance_as_command() -> None:
    output: list[str] = []
    responder = FakeResponder()
    speaker = FakeSpeaker()
    session = VoiceSession(
        FakeMicrophone(),
        FakeTranscriber(["hey grandpa", "open chrome", "quit"]),
        responder,
        speaker,
        output=output.append,
        wake_word_enabled=True,
        wake_detector=WakeWordDetector(),
    )

    assert session.run() == 0
    assert "Waiting for wake word..." in output
    assert "Wake word detected." in output
    assert "Listening for command..." in output
    assert responder.received == ["open chrome"]
    assert "hey grandpa" not in responder.received
    assert speaker.spoken[0] == "Yes?"


def test_wake_word_mode_executes_inline_command_without_second_capture() -> None:
    output: list[str] = []
    responder = FakeResponder()
    microphone = FakeMicrophone()
    session = VoiceSession(
        microphone,
        FakeTranscriber(["hey grandpa open chrome", "quit"]),
        responder,
        None,
        output=output.append,
        wake_word_enabled=True,
        wake_detector=WakeWordDetector(),
    )

    assert session.run() == 0
    assert responder.received == ["open chrome"]
    assert microphone.calls == 2
    assert "Listening for command..." not in output
    assert output.count("Waiting for wake word...") == 2


def test_wake_word_mode_command_timeout_returns_to_waiting() -> None:
    output: list[str] = []
    responder = FakeResponder()
    session = VoiceSession(
        FakeMicrophone(),
        FakeTranscriber(["grandpa", "", "quit"]),
        responder,
        None,
        output=output.append,
        wake_word_enabled=True,
        wake_detector=WakeWordDetector(),
    )

    assert session.run() == 0
    assert "No command heard. Returning to wake-word mode." in output
    assert output.count("Waiting for wake word...") == 2
    assert responder.received == []


def test_wake_word_mode_exit_phrase_stops_while_waiting() -> None:
    output: list[str] = []
    responder = FakeResponder()
    session = VoiceSession(
        FakeMicrophone(),
        FakeTranscriber(["stop listening"]),
        responder,
        None,
        output=output.append,
        wake_word_enabled=True,
        wake_detector=WakeWordDetector(),
    )

    assert session.run() == 0
    assert FAREWELL_TEXT in output
    assert f"Grandpa: {FAREWELL_TEXT}" not in output
    assert responder.received == []


def test_wake_word_mode_ctrl_c_during_wake_capture() -> None:
    output: list[str] = []
    microphone = FakeMicrophone(error_on_calls={1: KeyboardInterrupt()})
    session = VoiceSession(
        microphone,
        FakeTranscriber(),
        FakeResponder(),
        None,
        output=output.append,
        wake_word_enabled=True,
        wake_detector=WakeWordDetector(),
    )

    assert session.run() == 0
    assert microphone.calls == 1
    assert FAREWELL_TEXT in output
    assert f"Grandpa: {FAREWELL_TEXT}" not in output
    assert "Voice assistant stopped." not in output
    assert not any("Traceback" in line for line in output)
    assert microphone.closed is True


def test_wake_word_mode_ctrl_c_during_command_capture() -> None:
    output: list[str] = []
    microphone = FakeMicrophone(error_on_calls={2: KeyboardInterrupt()})
    responder = FakeResponder()
    session = VoiceSession(
        microphone,
        FakeTranscriber(["hey grandpa"]),
        responder,
        None,
        output=output.append,
        wake_word_enabled=True,
        wake_detector=WakeWordDetector(),
    )

    assert session.run() == 0
    assert microphone.calls == 2
    assert FAREWELL_TEXT in output
    assert f"Grandpa: {FAREWELL_TEXT}" not in output
    assert responder.received == []


def test_wake_word_mode_can_disable_spoken_acknowledgement() -> None:
    output: list[str] = []
    speaker = FakeSpeaker()
    session = VoiceSession(
        FakeMicrophone(),
        FakeTranscriber(["hey grandpa", "quit"]),
        FakeResponder(),
        speaker,
        output=output.append,
        wake_word_enabled=True,
        wake_detector=WakeWordDetector(),
        wake_response_enabled=False,
    )

    assert session.run() == 0
    assert "Grandpa: Yes?" not in output
    assert speaker.spoken == ["Goodbye! I’ll be here when you need me."]


def test_clean_text_for_speech_removes_markdown_and_truncates() -> None:
    text = "Open **Chrome** at https://example.com\n```python\nprint('x')\n```"

    spoken = clean_text_for_speech(text, max_chars=40)

    assert "Chrome" in spoken
    assert "https://" not in spoken
    assert "print" not in spoken
    assert len(spoken) <= 40


def test_voice_config_defaults_and_environment_overrides(monkeypatch) -> None:
    monkeypatch.setenv("GRANDPA_VOICE_STT_MODEL", "tiny.en")
    monkeypatch.setenv("GRANDPA_VOICE_LANGUAGE", "en")
    monkeypatch.setenv("GRANDPA_VOICE_DEVICE", "cpu")
    monkeypatch.setenv("GRANDPA_VOICE_COMPUTE_TYPE", "int8")
    monkeypatch.setenv("GRANDPA_VOICE_RATE", "160")
    monkeypatch.setenv("GRANDPA_VOICE_VOLUME", "0.8")
    monkeypatch.setenv("GRANDPA_VOICE_POST_TTS_COOLDOWN_MS", "650")
    monkeypatch.setenv("GRANDPA_VOICE_ECHO_WINDOW_SECONDS", "4.5")
    monkeypatch.setenv("GRANDPA_VOICE_ECHO_SIMILARITY_THRESHOLD", "0.9")

    config = load_voice_assistant_config()

    assert config.stt_model == "tiny.en"
    assert config.language == "en"
    assert config.device == "cpu"
    assert config.compute_type == "int8"
    assert config.tts_rate == 160
    assert config.tts_volume == 0.8
    assert config.post_tts_cooldown_ms == 650
    assert config.echo_window_seconds == 4.5
    assert config.echo_similarity_threshold == 0.9


@pytest.mark.parametrize(
    "phrase", ["stop listening", "Exit Voice Mode", " goodbye   grandpa "]
)
def test_exit_phrase_matching(phrase: str) -> None:
    assert is_exit_phrase(phrase)


@pytest.mark.parametrize(
    "phrase",
    [
        "I will give you an example today.",
        "Please don't stop listening.",
        "We should discuss the exit voice mode behavior.",
        "This is quite useful.",
    ],
)
def test_similar_words_do_not_stop_voice_session(phrase: str) -> None:
    assert not is_exit_phrase(phrase)


def test_normal_transcript_continues_and_invokes_responder_and_tts() -> None:
    output: list[str] = []
    responder = FakeResponder()
    speaker = FakeSpeaker()
    stop = threading.Event()
    session = VoiceSession(
        FakeMicrophone(),
        FakeTranscriber([]),
        responder,
        speaker,
        output=output.append,
        stop_event=stop,
    )

    session._handle_transcript("I will give you an example today.", stop)

    assert not stop.is_set()
    assert responder.received == ["I will give you an example today."]
    assert speaker.spoken
    assert not any("Goodbye" in line for line in output)


def test_shutdown_farewell_has_no_assistant_prefix() -> None:
    output: list[str] = []
    stop = threading.Event()
    session = VoiceSession(
        FakeMicrophone(),
        FakeTranscriber([]),
        FakeResponder(),
        FakeSpeaker(),
        output=output.append,
        stop_event=stop,
    )

    session._handle_transcript("stop listening", stop)

    assert stop.is_set()
    assert FAREWELL_TEXT in output
    assert f"Grandpa: {FAREWELL_TEXT}" not in output


def test_voice_session_normal_startup_stays_alive() -> None:
    output = []

    class StoppingMicrophone(FakeMicrophone):
        def capture(self, stop_event=None):
            self.calls += 1
            if self.calls == 1:
                return CapturedAudio(b"", 16000)
            else:
                if stop_event:
                    stop_event.set()
                return CapturedAudio(b"", 16000)

    microphone = StoppingMicrophone()
    transcriber = FakeTranscriber(["hello"])
    responder = FakeResponder()

    session = VoiceSession(
        microphone,
        transcriber,
        responder,
        None,
        output=output.append,
    )

    assert session.run() == 0
    assert "Voice assistant stopped." not in output
    assert "Stopping Grandpa Voice Assistant..." not in output


def test_voice_session_ollama_unavailable_at_startup() -> None:
    from unittest.mock import MagicMock

    from grandpa.engine import EngineConnectionError

    output = []
    responder = MagicMock()
    responder._ensure_engine = MagicMock(
        side_effect=EngineConnectionError("Ollama not reachable")
    )

    session = VoiceSession(
        FakeMicrophone(),
        FakeTranscriber(["hello"]),
        responder,
        None,
        output=output.append,
    )

    exit_code = session.run()
    assert exit_code == 1
    assert any(
        "Ollama is not available" in str(line) or "Ollama not reachable" in str(line)
        for line in output
    )


def test_voice_session_ollama_healthy_at_startup() -> None:
    from unittest.mock import MagicMock

    output = []

    class StoppingMicrophone(FakeMicrophone):
        def capture(self, stop_event=None):
            if stop_event:
                stop_event.set()
            return CapturedAudio(b"", 16000)

    responder = MagicMock()
    responder._ensure_engine = MagicMock()

    session = VoiceSession(
        StoppingMicrophone(),
        FakeTranscriber(["hello"]),
        responder,
        None,
        output=output.append,
    )

    exit_code = session.run()
    assert exit_code == 0


def test_voice_session_handle_transcript_inference_error() -> None:
    from unittest.mock import MagicMock

    from grandpa.engine import EngineConnectionError

    output = []
    responder = MagicMock()
    responder._ensure_engine = MagicMock()
    responder.handle_user_input = MagicMock(
        side_effect=EngineConnectionError("Ollama not reachable")
    )

    class StoppingMicrophone(FakeMicrophone):
        def __init__(self) -> None:
            super().__init__()
            self.calls = 0

        def capture(self, stop_event=None):
            self.calls += 1
            if self.calls == 1:
                return CapturedAudio(b"hello", 16000)
            else:
                if stop_event:
                    stop_event.set()
                return CapturedAudio(b"", 16000)

    speaker = MagicMock()

    session = VoiceSession(
        StoppingMicrophone(),
        FakeTranscriber(["hello"]),
        responder,
        speaker,
        output=output.append,
    )

    exit_code = session.run()
    assert exit_code == 0
    assert speaker.speak.call_count == 0
    assert any(
        "Ollama is not available" in str(line) or "Ollama not reachable" in str(line)
        for line in output
    )


def test_build_voice_session_routes_output_to_the_caller_sink(monkeypatch):
    """A caller-supplied ``output`` sink must actually receive messages.

    ``build_voice_session`` used to construct ``VoicePresenter`` without
    passing ``output``, so the presenter decided its rendering mode against
    the default ``print`` and sent everything to a Rich console on stderr.
    ``VoiceSession.__post_init__`` then assigned ``presenter.output``, but the
    mode was already fixed — so errors, status and assistant text never
    reached the sink. Embedders and screen-reader users saw nothing.
    """
    from grandpa.voice.cli_session import build_voice_session

    captured: list[str] = []

    session = build_voice_session(
        output=captured.append,
        microphone_capture=FakeMicrophone(error=MicrophoneUnavailableError("boom")),
        transcriber=FakeTranscriber(),
        speaker=FakeSpeaker(),
    )

    presenter = session.presenter
    # ``==`` not ``is``: each attribute access builds a fresh bound method.
    assert presenter.output == captured.append
    # The mode must reflect the real sink, not the default print.
    assert presenter.no_color is True

    presenter.print_error("Device disconnected.")
    assert any("Device disconnected." in line for line in captured)


def test_voice_session_surfaces_setup_errors_through_the_output_sink():
    """End-to-end: an unrecoverable mic error reaches the caller's sink."""
    from grandpa.voice.operator import build_voice_operator_session

    captured: list[str] = []
    session = build_voice_operator_session(
        microphone_capture=FakeMicrophone(
            error=MicrophoneUnavailableError("Device disconnected.")
        ),
        transcriber=FakeTranscriber(),
        speaker=FakeSpeaker(),
        output=captured.append,
    )

    assert session.run() == 1
    assert any("Device disconnected." in line for line in captured)
