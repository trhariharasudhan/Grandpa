from __future__ import annotations

import io
import threading
import wave
from array import array

import pytest

from grandpa.voice.device_manager import MicrophoneDevice
from grandpa.voice.errors import MicrophoneUnavailableError
from grandpa.voice.microphone import CapturedAudio, MicrophoneCapture
from grandpa.voice.vad import VoiceActivityConfig


class FakeRecording:
    def __init__(self, frames: bytes, frame_count: int) -> None:
        self._frames = frames
        self._frame_count = frame_count

    def tobytes(self) -> bytes:
        return self._frames

    def __len__(self) -> int:
        return self._frame_count


class FakeStream:
    def __init__(self, *, channels: int, sample: tuple[int, ...]) -> None:
        self.channels = channels
        self.sample = sample
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.closed = True

    def read(self, frame_count: int):
        values = self.sample[: self.channels] * frame_count
        return FakeRecording(array("h", values).tobytes(), frame_count), False

    def stop(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True


class FakeSoundDevice:
    def __init__(self, supported: set[tuple[int, int]]) -> None:
        self.supported = supported
        self.checks: list[tuple[int, int]] = []
        self.opened: list[dict] = []

    def check_input_settings(self, **settings) -> None:
        candidate = (int(settings["samplerate"]), int(settings["channels"]))
        self.checks.append(candidate)
        if candidate not in self.supported:
            raise RuntimeError("Invalid sample rate")

    def InputStream(self, **settings):
        self.opened.append(settings)
        channels = int(settings["channels"])
        sample = (1_000, 3_000) if channels == 2 else (2_000,)
        return FakeStream(channels=channels, sample=sample)


def _device(rate: int, channels: int = 2) -> MicrophoneDevice:
    return MicrophoneDevice(
        index=15,
        name="Microphone Array",
        input_channels=channels,
        default_sample_rate=rate,
        driver="Windows WASAPI",
    )


def _capture(native_rate: int, *, channels: int = 2):
    supported_channels = 1 if native_rate == 16_000 else channels
    sounddevice = FakeSoundDevice({(native_rate, supported_channels)})
    capture = MicrophoneCapture(
        duration_seconds=1.0,
        sample_rate=16_000,
        chunk_seconds=1.0,
        recovery_attempts=0,
        vad_config=VoiceActivityConfig(maximum_utterance_seconds=1.0),
    )
    result = capture._capture_from_device(
        sounddevice,
        _device(native_rate, channels),
        threading.Event(),
    )
    return sounddevice, result


@pytest.mark.parametrize("native_rate", [16_000, 44_100, 48_000])
def test_capture_negotiates_native_rate_and_preserves_canonical_duration(
    native_rate: int,
) -> None:
    sounddevice, result = _capture(native_rate)

    assert sounddevice.opened[0]["samplerate"] == native_rate
    assert result.capture_sample_rate == native_rate
    assert result.captured_frame_count in {15_999, 16_000}
    with wave.open(io.BytesIO(result.data), "rb") as wav_file:
        assert wav_file.getframerate() == 16_000
        assert wav_file.getnchannels() == 1
        assert wav_file.getsampwidth() == 2
        assert wav_file.getnframes() in {15_999, 16_000}
        assert wav_file.getnframes() / wav_file.getframerate() == pytest.approx(
            1.0, abs=1 / 16_000
        )


def test_unsupported_configured_rate_falls_back_to_device_default() -> None:
    sounddevice, result = _capture(48_000)

    assert sounddevice.checks[:2] == [(16_000, 1), (48_000, 2)]
    assert result.capture_sample_rate == 48_000
    assert result.capture_channels == 2


def test_stereo_capture_is_downmixed_before_stt() -> None:
    _sounddevice, result = _capture(48_000)

    with wave.open(io.BytesIO(result.data), "rb") as wav_file:
        samples = array("h")
        samples.frombytes(wav_file.readframes(wav_file.getnframes()))
    assert samples
    assert min(samples) >= 1_999
    assert max(samples) <= 2_001


def test_phase_opposed_stereo_uses_strongest_channel() -> None:
    sounddevice = FakeSoundDevice({(48_000, 2)})
    capture = MicrophoneCapture(
        duration_seconds=1.0,
        sample_rate=16_000,
        chunk_seconds=1.0,
        recovery_attempts=0,
        vad_config=VoiceActivityConfig(maximum_utterance_seconds=1.0),
    )

    class PhaseOpposedSoundDevice(FakeSoundDevice):
        def InputStream(self, **settings):
            self.opened.append(settings)
            return FakeStream(channels=2, sample=(4_000, -4_000))

    sounddevice = PhaseOpposedSoundDevice({(48_000, 2)})
    result = capture._capture_from_device(
        sounddevice, _device(48_000), threading.Event()
    )

    assert result.rms_level > 3_900


def test_negotiation_failure_names_device_and_rates() -> None:
    capture = MicrophoneCapture(recovery_attempts=0)

    with pytest.raises(MicrophoneUnavailableError) as exc_info:
        capture._capture_from_device(
            FakeSoundDevice(set()),
            _device(48_000),
            threading.Event(),
        )

    message = str(exc_info.value)
    assert "Microphone Array" in message
    assert "16000 Hz" in message
    assert "48000 Hz" in message


def test_microphone_capture_injects_sounddevice_into_device_manager(
    monkeypatch,
) -> None:
    from unittest.mock import MagicMock

    from grandpa.voice.device_manager import MicrophoneDeviceManager

    mock_sd = FakeSoundDevice({(16_000, 1)})
    mock_sd.query_devices = MagicMock(
        return_value=[
            {
                "name": "Default Mic",
                "max_input_channels": 1,
                "default_samplerate": 16000,
                "hostapi": 0,
            }
        ]
    )
    mock_sd.query_hostapis = MagicMock(return_value=[{"name": "MME"}])
    mock_sd.default = MagicMock()
    mock_sd.default.device = (0, 0)

    capture = MicrophoneCapture(
        sounddevice=mock_sd,
        duration_seconds=0.1,
        vad_config=VoiceActivityConfig(maximum_utterance_seconds=0.1),
    )
    stop = threading.Event()
    stop.set()  # Stop immediately so capture doesn't block

    # Prior to stop, verify calling capture creates device_manager with injected sounddevice
    capture.device_manager = None
    stop_event = threading.Event()
    monkeypatch.setattr(
        capture, "_capture_from_device", lambda sd, dev, st, **kw: CapturedAudio(b"")
    )

    capture.capture(stop_event=stop_event)

    assert capture.device_manager is not None
    assert isinstance(capture.device_manager, MicrophoneDeviceManager)
    assert capture.device_manager.sounddevice is mock_sd


def test_microphone_capture_uses_injected_device_manager(monkeypatch) -> None:
    from unittest.mock import MagicMock

    from grandpa.voice.device_manager import MicrophoneDeviceManager

    mock_sd = FakeSoundDevice({(16_000, 1)})
    mock_manager = MicrophoneDeviceManager(mock_sd)
    mock_manager.select = MagicMock(
        return_value=MagicMock(device=_device(16_000, 1), warning=None)
    )

    capture = MicrophoneCapture(
        device_manager=mock_manager,
        duration_seconds=0.1,
    )
    monkeypatch.setattr(
        capture, "_capture_from_device", lambda sd, dev, st, **kw: CapturedAudio(b"")
    )

    capture.capture(stop_event=threading.Event())

    assert capture.device_manager is mock_manager
    assert mock_manager.select.called
