from __future__ import annotations

from types import SimpleNamespace

import pytest

from grandpa.voice.device_manager import MicrophoneDeviceManager, MicrophoneIdentity
from grandpa.voice.errors import MicrophoneUnavailableError, VoiceRecognitionError
from grandpa.voice.microphone import CapturedAudio
from grandpa.voice.speech_input import SpeechInputResult
from grandpa.voice.speech_to_text import FasterWhisperSpeechToText
from grandpa.voice.vad import VoiceActivityConfig, VoiceActivityDetector
from grandpa.voice.wake_word import WakeWordConfig, WakeWordDetector


class FakeSoundDevice:
    def __init__(self, devices, default=(-1, -1)) -> None:
        self.devices = devices
        self.default = SimpleNamespace(device=default)

    def query_devices(self):
        return self.devices

    def query_hostapis(self):
        return [{"name": "Windows WASAPI"}]


def _input(name: str, *, channels: int = 1, hostapi: int = 0) -> dict:
    return {
        "name": name,
        "max_input_channels": channels,
        "default_samplerate": 48_000,
        "hostapi": hostapi,
        "default_low_input_latency": 0.01,
        "default_high_input_latency": 0.1,
    }


def test_device_manager_resolves_saved_name_after_index_change() -> None:
    manager = MicrophoneDeviceManager(
        FakeSoundDevice([_input("Other"), _input("USB Microphone")]),
        preference_loader=lambda: "USB Microphone",
    )

    selection = manager.select()

    assert selection.device.index == 1
    assert selection.device.name == "USB Microphone"


def test_device_manager_prefers_saved_host_api_for_duplicate_names() -> None:
    devices = [
        {**_input("Microphone Array"), "hostapi": 0},
        {**_input("Microphone Array"), "hostapi": 1},
    ]
    sounddevice = FakeSoundDevice(devices)
    sounddevice.query_hostapis = lambda: [
        {"name": "MME"},
        {"name": "Windows WASAPI"},
    ]
    manager = MicrophoneDeviceManager(
        sounddevice,
        preference_loader=lambda: MicrophoneIdentity(
            name="Microphone Array", host_api="Windows WASAPI"
        ),
    )

    selection = manager.select()

    assert selection.device.index == 1
    assert selection.device.driver == "Windows WASAPI"


def test_device_manager_prefers_wasapi_for_name_only_duplicate() -> None:
    devices = [
        {**_input("Microphone Array"), "hostapi": 0},
        {**_input("Microphone Array"), "hostapi": 1},
    ]
    sounddevice = FakeSoundDevice(devices)
    sounddevice.query_hostapis = lambda: [
        {"name": "MME"},
        {"name": "Windows WASAPI"},
    ]
    manager = MicrophoneDeviceManager(
        sounddevice, preference_loader=lambda: "Microphone Array"
    )

    assert manager.select().device.driver == "Windows WASAPI"


def test_device_manager_uses_physical_fallback_without_default() -> None:
    manager = MicrophoneDeviceManager(
        FakeSoundDevice(
            [
                _input("Primary Sound Capture Driver"),
                _input("Microphone Array (AMD Audio Device)"),
            ]
        ),
        preference_loader=lambda: None,
    )

    assert manager.select().device.index == 1


def test_device_manager_honors_and_validates_explicit_index() -> None:
    manager = MicrophoneDeviceManager(
        FakeSoundDevice([_input("Output", channels=0), _input("Headset")]),
        preference_loader=lambda: None,
    )

    assert manager.select(requested_index=1).device.name == "Headset"
    with pytest.raises(MicrophoneUnavailableError, match="no input channels"):
        manager.select(requested_index=0)


def test_device_manager_recovers_to_another_input() -> None:
    manager = MicrophoneDeviceManager(
        FakeSoundDevice([_input("USB Microphone"), _input("Microphone Array")]),
        preference_loader=lambda: None,
    )
    first = manager.select()

    recovered = manager.recover(first.device, OSError("device unplugged"))

    assert recovered.device.index != first.device.index
    assert "Switched from" in str(recovered.warning)
    assert manager.recent_errors


def test_vad_stops_after_speech_and_silence() -> None:
    detector = VoiceActivityDetector(
        VoiceActivityConfig(
            minimum_rms=100,
            minimum_speech_seconds=0.2,
            silence_seconds=0.3,
            maximum_utterance_seconds=5,
        )
    )

    assert detector.observe(10, 0.1) is False
    assert detector.observe(500, 0.1) is False
    assert detector.observe(500, 0.1) is False
    assert detector.speech_started is True
    assert detector.observe(10, 0.1) is False
    assert detector.observe(10, 0.1) is False
    assert detector.observe(10, 0.1) is True
    # The VAD reports "silence_timeout" (vad.py). "trailing_silence" is the
    # separate *duration* field, trailing_silence_seconds — these tests had
    # conflated the two. cli_session.py branches on "silence_timeout".
    assert detector.finalization_reason == "silence_timeout"
    assert detector.speech_onset_seconds == pytest.approx(0.1)
    assert detector.speech_active_seconds == pytest.approx(0.2)


def test_vad_preserves_short_pause_inside_sentence() -> None:
    detector = VoiceActivityDetector(
        VoiceActivityConfig(
            minimum_rms=100,
            minimum_speech_seconds=0.2,
            silence_seconds=1.2,
            maximum_utterance_seconds=12,
        )
    )

    assert detector.observe(500, 0.2) is False
    for _ in range(8):
        assert detector.observe(10, 0.1) is False
    assert detector.observe(500, 0.2) is False
    for _ in range(11):
        assert detector.observe(10, 0.1) is False
    assert detector.observe(10, 0.1) is True
    # The VAD reports "silence_timeout" (vad.py). "trailing_silence" is the
    # separate *duration* field, trailing_silence_seconds — these tests had
    # conflated the two. cli_session.py branches on "silence_timeout".
    assert detector.finalization_reason == "silence_timeout"


def test_vad_enforces_safe_maximum_duration() -> None:
    detector = VoiceActivityDetector(
        VoiceActivityConfig(
            minimum_rms=100,
            minimum_speech_seconds=0.1,
            silence_seconds=1.2,
            maximum_utterance_seconds=1.0,
        )
    )

    for _ in range(10):
        assert detector.observe(500, 0.1) is False
    assert detector.observe(500, 0.1) is True
    assert detector.finalization_reason == "maximum_duration"


def test_stt_retries_temporary_recognition_failure() -> None:
    class Engine:
        def __init__(self) -> None:
            self.calls = 0

        def listen(self, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                raise VoiceRecognitionError("temporary")
            return SpeechInputResult(status="completed", transcript="hello grandpa")

    engine = Engine()
    transcriber = FasterWhisperSpeechToText(
        engine=engine,
        max_attempts=2,
        retry_delay_seconds=0,
    )

    assert transcriber.transcribe(CapturedAudio(b"wav")) == "hello grandpa"
    assert engine.calls == 2
    assert transcriber.last_result is not None


def test_wake_word_variants_and_cooldown() -> None:
    now = [10.0]
    detector = WakeWordDetector(
        WakeWordConfig(enabled=True, cooldown_seconds=1.0),
        clock=lambda: now[0],
    )

    assert detector.detect("Hi Grandpa, open Chrome").command_text == "open chrome"
    assert detector.detect("Wake Grandpa").matched is False
    now[0] += 1.1
    assert detector.detect("Wake Grandpa").matched is True
