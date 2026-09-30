"""A capture that hears nothing must give up, and say why.

`grandpa voice` printed "Listening..." and then produced nothing for five to ten
minutes. Every ``return True`` in VoiceActivityDetector.observe was gated on
``_speech_started``, and the caller's utterance cap was only checked after speech
began -- so if nothing crossed the threshold the loop read frames forever.
Demonstrated with synthetic audio before the fix: at amplitudes 0, 50 and 179
against a threshold of 180 the call never returned.

Whatever the underlying cause -- a silent device, a threshold above the speech
level, the wrong input of four duplicates -- the user-visible failure was the
same and was its own bug. So there are two properties here:

  1. the capture gives up within a bounded time when no speech arrives;
  2. it says what it heard, naming the device and the level, and at a log level
     that reaches a normal run rather than requiring --verbose.

Levels throughout are the ones this machine actually measured, not ideal ones:

    overall RMS 308.3   speech-active RMS 496.2   SNR 12.4 dB
    implied non-speech floor 119.7  ->  threshold max(180, 299.2) = 299.2

No microphone is opened: frames come from a fake sounddevice.
"""

from __future__ import annotations

import threading
from array import array

import pytest

from grandpa.voice.microphone import CapturedAudio
from grandpa.voice.vad import VoiceActivityConfig, VoiceActivityDetector

pytestmark = pytest.mark.core

# --- measured on this machine ----------------------------------------------------
MEASURED_FLOOR = 119.7
MEASURED_SPEECH = 496.2
MEASURED_THRESHOLD = 299.2

CONFIG = VoiceActivityConfig(
    minimum_rms=180.0,
    minimum_speech_seconds=0.25,
    silence_seconds=0.55,
    maximum_utterance_seconds=12.0,
    silence_before_speech_seconds=8.0,
)


# --- 1. the capture gives up ------------------------------------------------------


@pytest.mark.parametrize(
    ("level", "label"),
    [
        (0.0, "digital silence"),
        (50.0, "quiet room"),
        (MEASURED_FLOOR, "this mic's measured noise floor"),
        (179.0, "just under the 180 minimum"),
    ],
)
def test_a_capture_that_hears_nothing_finishes(level: float, label: str) -> None:
    """The unbounded loop, bounded. Each of these ran forever before the fix."""
    detector = VoiceActivityDetector(CONFIG)

    elapsed = 0.0
    finished = False
    # Twice the timeout: if it has not stopped by then it never will.
    while elapsed < CONFIG.silence_before_speech_seconds * 2:
        finished = detector.observe(level, 0.1)
        elapsed += 0.1
        if finished:
            break

    assert finished, f"{label}: capture never gave up"
    assert detector.finalization_reason == "no_speech_timeout"
    assert elapsed == pytest.approx(CONFIG.silence_before_speech_seconds, abs=0.2)
    assert detector.speech_started is False


def test_speech_at_this_mic_s_level_still_fires_well_inside_the_timeout() -> None:
    """The timeout must not clip real speech from the machine that reported this."""
    detector = VoiceActivityDetector(CONFIG)

    # A second of the measured floor, then the measured speech level.
    for _ in range(10):
        detector.observe(MEASURED_FLOOR, 0.1)
    assert detector.speech_started is False
    assert detector.current_threshold == pytest.approx(MEASURED_THRESHOLD, abs=1.0)

    for _ in range(5):
        detector.observe(MEASURED_SPEECH, 0.1)

    assert detector.speech_started is True, (
        f"speech at {MEASURED_SPEECH} did not cross a threshold of "
        f"{detector.current_threshold:.1f}"
    )
    assert detector.finalization_reason != "no_speech_timeout"


def test_repeated_false_starts_cannot_hold_the_capture_open() -> None:
    """The no-speech clock survives reset(), on purpose.

    A burst too short to keep calls reset(), which clears the per-attempt
    elapsed time. If the timeout were measured on that, a stream of clicks or
    door slams would restart it forever -- the same unbounded wait wearing a
    different hat.
    """
    detector = VoiceActivityDetector(CONFIG)

    elapsed = 0.0
    finished = False
    while elapsed < CONFIG.silence_before_speech_seconds * 2:
        # 0.1s of loud, then 0.6s of quiet: enough to trip a start and then be
        # discarded as too short, over and over.
        for level in (MEASURED_SPEECH,) + (MEASURED_FLOOR,) * 6:
            finished = detector.observe(level, 0.1)
            elapsed += 0.1
            if finished:
                break
        if finished:
            break

    assert finished, "false starts held the capture open past the timeout"


def test_the_timeout_can_be_switched_off_explicitly() -> None:
    """Zero disables it, for a caller that wants the old unbounded behaviour."""
    detector = VoiceActivityDetector(
        VoiceActivityConfig(minimum_rms=180.0, silence_before_speech_seconds=0.0)
    )

    for _ in range(200):
        assert detector.observe(0.0, 0.1) is False

    assert detector.finalization_reason is None


# --- 2. it says what it heard -----------------------------------------------------


class _Presenter:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.statuses: list[str] = []
        self.debug = False
        self.output = lambda text: None

    def print_error(self, content: str) -> None:
        self.errors.append(content)

    def print_status(self, content: str) -> None:
        self.statuses.append(content)

    def stop_listening(self) -> None:
        pass


def _session(presenter: _Presenter):
    """A VoiceSession with only what _report_quiet_capture touches."""
    from grandpa.voice.cli_session import VoiceSession

    session = VoiceSession.__new__(VoiceSession)
    session.presenter = presenter
    session.debug = False
    return session


def _report(audio: CapturedAudio) -> list[str]:
    presenter = _Presenter()
    _session(presenter)._report_quiet_capture(audio)
    return presenter.errors


def test_no_frames_at_all_names_the_device() -> None:
    """The device is chosen automatically from four duplicates; name it."""
    messages = _report(
        CapturedAudio(
            b"",
            speech_detected=False,
            finalization_reason="no_speech_timeout",
            device_name="Microphone Array (AMD Audio Device)",
            device_index=9,
            chunks_read=0,
        )
    )

    assert len(messages) == 1
    assert "Microphone Array (AMD Audio Device)" in messages[0]
    assert "device 9" in messages[0]
    assert "no audio" in messages[0]


def test_frames_of_silence_say_so_and_mention_the_permission() -> None:
    """Windows delivers zeros rather than an error when mic access is denied."""
    messages = _report(
        CapturedAudio(
            b"",
            speech_detected=False,
            finalization_reason="no_speech_timeout",
            device_name="Microphone Array (AMD Audio Device)",
            device_index=9,
            chunks_read=80,
            max_chunk_rms=0.0,
            speech_threshold=180.0,
        )
    )

    assert len(messages) == 1
    assert "silence" in messages[0]
    assert "80 audio chunks" in messages[0]
    assert "privacy" in messages[0]


def test_audio_below_the_threshold_reports_the_measured_level() -> None:
    """The message a person can act on, at this machine's real numbers."""
    messages = _report(
        CapturedAudio(
            b"",
            speech_detected=False,
            finalization_reason="no_speech_timeout",
            device_name="Microphone Array (AMD Audio Device)",
            device_index=9,
            chunks_read=80,
            max_chunk_rms=MEASURED_FLOOR,
            speech_threshold=MEASURED_THRESHOLD,
        )
    )

    assert len(messages) == 1
    assert "120" in messages[0], messages[0]
    assert "299" in messages[0], messages[0]
    assert "--list-microphones" in messages[0]


def test_a_successful_capture_says_nothing_extra() -> None:
    """No new noise on the path that works."""
    assert (
        _report(
            CapturedAudio(
                b"RIFF....",
                speech_detected=True,
                finalization_reason="silence_timeout",
                device_name="Microphone Array (AMD Audio Device)",
                device_index=9,
                chunks_read=40,
                max_chunk_rms=MEASURED_SPEECH,
                speech_threshold=MEASURED_THRESHOLD,
            )
        )
        == []
    )


def test_the_message_is_logged_at_warning_not_info(caplog) -> None:
    """A normal run has to show this.

    Every existing diagnostic in the capture path is at INFO, and the file
    handler only exists with --verbose, so a ten-minute failure left no trace
    anywhere. The user should not have to know to re-run with a flag.
    """
    import logging

    with caplog.at_level(logging.WARNING, logger="grandpa.voice.cli_session"):
        _report(
            CapturedAudio(
                b"",
                speech_detected=False,
                finalization_reason="no_speech_timeout",
                device_name="Microphone Array (AMD Audio Device)",
                device_index=9,
                chunks_read=80,
                max_chunk_rms=MEASURED_FLOOR,
                speech_threshold=MEASURED_THRESHOLD,
            )
        )

    assert any(
        record.levelno >= logging.WARNING and "heard no speech" in record.message
        for record in caplog.records
    ), caplog.records


# --- 3. a marginal capture is not a command ---------------------------------------
#
# The replacement for refusing single-word exit phrases. A spurious "Goodbye."
# needs a spurious transcript, which needs a capture too marginal to be speech --
# so refuse the capture, which protects every command rather than only exits.
#
# The gate existed but only fired when the VAD finalised on silence_timeout, so a
# capture ending on maximum_duration or stream_ended skipped it entirely.


@pytest.mark.parametrize(
    "reason",
    ["silence_timeout", "maximum_duration", "stream_ended", "cancelled"],
)
def test_a_marginal_capture_is_discarded_whatever_ended_it(reason: str) -> None:
    """A click that crossed the threshold for a tenth of a second is not speech."""
    from grandpa.voice.cli_session import VoiceSession

    presenter = _Presenter()
    session = VoiceSession.__new__(VoiceSession)
    session.presenter = presenter
    session.debug = False
    session.stop_event = None
    session.transcriber = None  # must not be reached

    audio = CapturedAudio(
        b"RIFF....",
        speech_detected=True,
        finalization_reason=reason,
        device_name="Microphone Array (AMD Audio Device)",
        device_index=9,
        chunks_read=8,
        speech_active_seconds=0.1,
        rms_level=MEASURED_FLOOR,
        max_chunk_rms=MEASURED_FLOOR,
        speech_threshold=MEASURED_THRESHOLD,
    )

    assert _marginal(audio) is True, (
        f"a 0.1s burst at RMS {MEASURED_FLOOR} was accepted after {reason}"
    )


def test_real_speech_at_this_mic_s_level_is_not_discarded() -> None:
    """The gate must not eat the speech this machine actually produces."""
    from grandpa.voice.cli_session import VoiceSession

    session = VoiceSession.__new__(VoiceSession)
    session.presenter = _Presenter()
    session.debug = False

    audio = CapturedAudio(
        b"RIFF....",
        speech_detected=True,
        finalization_reason="silence_timeout",
        device_name="Microphone Array (AMD Audio Device)",
        device_index=9,
        chunks_read=40,
        # Six seconds of speech, as the microphone test recorded.
        speech_active_seconds=2.1,
        rms_level=MEASURED_SPEECH,
        max_chunk_rms=MEASURED_SPEECH,
        speech_threshold=MEASURED_THRESHOLD,
    )

    assert _marginal(audio) is False


def test_a_capture_with_no_vad_metadata_is_not_judged() -> None:
    """Absent is not zero, and a gate that confuses them eats real audio.

    ``speech_active_seconds`` defaults to 0.0, so a first version of this gate --
    keyed only on the field -- silently discarded every hand-built CapturedAudio
    that left the metadata unset. One existing test constructs
    ``CapturedAudio(b"hello", 16000)`` positionally and expects the transcript to
    reach the responder; it broke, and it was right to.

    So the gate applies only when a reason is set, meaning a VAD actually judged
    the capture. "unknown" is the dataclass default and means nothing measured it.
    """
    audio = CapturedAudio(b"hello", "wav")

    assert audio.finalization_reason == "unknown"
    assert audio.speech_active_seconds == 0.0
    assert _marginal(audio) is False, (
        "a capture with no VAD metadata was judged marginal on default values"
    )


def _marginal(audio: CapturedAudio) -> bool:
    """Whether _listen_for_transcript's marginal gate would drop this capture.

    Mirrors the conditions rather than calling the method, which would need a
    microphone, a transcriber and a presenter animation. The conditions are
    asserted against the source in the test below so this cannot drift.
    """
    reason = str(getattr(audio, "finalization_reason", "") or "")
    if reason in {"", "unknown"}:
        return False
    voiced = float(getattr(audio, "speech_active_seconds", 0.0) or 0.0)
    rms = float(getattr(audio, "rms_level", 0.0) or 0.0)
    return voiced < 0.25 or (rms < 120.0 and voiced < 0.5)


def test_the_gate_is_no_longer_conditional_on_the_finalisation_reason() -> None:
    """Asserted against the source, because that condition was the whole bug.

    A mirrored predicate in a test can agree with itself forever while the
    product drifts, so this checks the real thing: the marginal-capture branch
    must not be nested inside a finalization_reason comparison.
    """
    import inspect

    from grandpa.voice.cli_session import VoiceSession

    source = inspect.getsource(VoiceSession._listen_for_transcript)
    marker = "voiced_duration < 0.25"
    assert marker in source, "the marginal-capture gate moved or was renamed"
    before = source[: source.index(marker)]
    # The last conditional before the gate must not be a reason check.
    tail = before[-400:]
    assert 'finalization_reason", None) == "silence_timeout"' not in tail, (
        "the marginal-capture gate is conditional on silence_timeout again, so a "
        "capture that ends any other way skips it"
    )


# --- the capture loop itself, with a fake device ----------------------------------


class _Frames:
    def __init__(self, samples: array) -> None:
        self._samples = samples

    def tobytes(self) -> bytes:
        return self._samples.tobytes()

    def __len__(self) -> int:
        return len(self._samples)


class _Stream:
    def __init__(self, amplitude: int, frames: int) -> None:
        self.amplitude = amplitude
        self.frames = frames
        self.reads = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, count: int):
        self.reads += 1
        return _Frames(array("h", [self.amplitude] * count)), False

    def close(self):
        pass

    def stop(self):
        pass


class _FakeSoundDevice:
    def __init__(self, amplitude: int) -> None:
        self.amplitude = amplitude

    def InputStream(self, **kwargs):  # noqa: N802 - mirrors sounddevice
        return _Stream(self.amplitude, 1600)

    def check_input_settings(self, **kwargs):
        return None


class _FixedManager:
    def __init__(self, sounddevice) -> None:
        from grandpa.voice.device_manager import MicrophoneDevice

        self.sounddevice = sounddevice
        self.device = MicrophoneDevice(
            index=9,
            name="Microphone Array (AMD Audio Device)",
            input_channels=1,
            default_sample_rate=16_000,
            host_api=0,
            driver="Windows WASAPI",
            low_input_latency=None,
            high_input_latency=None,
            is_default=False,
            is_default_communications=None,
            is_virtual=False,
            transport="built-in",
        )

    def select(self, **kwargs):
        from grandpa.voice.device_manager import MicrophoneSelection

        return MicrophoneSelection(self.device)


@pytest.mark.parametrize("amplitude", [0, 50, 120, 179])
def test_the_real_capture_loop_returns_on_silence(amplitude: int) -> None:
    """End to end through MicrophoneCapture, with frames from a fake device.

    Bounded by a thread join rather than trusted: before the fix this did not
    return, so a test that simply called it would hang the suite.
    """
    from grandpa.voice.microphone import MicrophoneCapture

    fake = _FakeSoundDevice(amplitude)
    capture = MicrophoneCapture(
        duration_seconds=3.0,
        sample_rate=16_000,
        chunk_seconds=0.1,
        vad_config=CONFIG,
        device_manager=_FixedManager(fake),
        sounddevice=fake,
    )
    captured: dict = {}

    def worker():
        captured["audio"] = capture.capture(stop_event=threading.Event())

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join(20.0)

    assert not thread.is_alive(), (
        f"capture() did not return for amplitude {amplitude} -- the unbounded "
        f"pre-speech loop is back"
    )
    audio = captured["audio"]
    assert audio.finalization_reason == "no_speech_timeout"
    assert audio.speech_detected is False
    assert audio.chunks_read > 0
    assert audio.device_name == "Microphone Array (AMD Audio Device)"
    assert audio.device_index == 9
