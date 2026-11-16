"""B1: the audio wake word decides on frames, not on single loud blips.

A fake openWakeWord model returns scripted scores, so these tests check
Grandpa's own logic (threshold, patience, cooldown, reset, model lookup, the
false-triggers-per-hour arithmetic, the CLI) without the microphone or the
4 MB feature models. One test runs the real openWakeWord on noise when its
models happen to be installed, and is skipped otherwise.
"""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np
import pytest
from click.testing import CliRunner

from grandpa.voice import wake_engine as we

pytestmark = pytest.mark.core


class FakeModel:
    """Scores come from a script, one per predict() call."""

    def __init__(self, scores: list[float], name: str = "hey_grandpa") -> None:
        self.scores = list(scores)
        self.name = name
        self.calls = 0
        self.resets = 0
        self.frame_sizes: list[int] = []

    def predict(self, frame):
        self.frame_sizes.append(len(frame))
        score = self.scores[self.calls] if self.calls < len(self.scores) else 0.0
        self.calls += 1
        return {self.name: score}

    def reset(self) -> None:
        self.resets += 1


def _frame() -> np.ndarray:
    return np.zeros(we.FRAME_SAMPLES, dtype=np.int16)


def _engine(scores, **config) -> tuple[we.WakeWordEngine, FakeModel]:
    model = FakeModel(scores)
    engine = we.WakeWordEngine(
        we.WakeEngineConfig(**config),
        model=model,
        resolved=we.ResolvedModel("fake", "hey_grandpa", "file"),
    )
    return engine, model


def _feed(engine, count):
    return [e for e in (engine.process(_frame()) for _ in range(count)) if e]


def test_one_loud_frame_is_not_a_wake():
    engine, _ = _engine([0.0, 0.95, 0.0, 0.0], patience=2)
    assert _feed(engine, 4) == []


def test_two_frames_in_a_row_wake_once_and_reset_the_model():
    engine, model = _engine([0.1, 0.7, 0.8, 0.9, 0.9], patience=2)
    events = _feed(engine, 5)
    assert len(events) == 1
    assert events[0].model == "hey_grandpa"
    assert events[0].score == pytest.approx(0.8)
    assert events[0].at_seconds == pytest.approx(3 * we.FRAME_SECONDS)
    assert model.resets == 1


def test_cooldown_blocks_a_second_wake_then_allows_one():
    # 2 s cooldown = 25 frames of 80 ms.
    scores = [0.9, 0.9] + [0.9] * 25 + [0.9, 0.9]
    engine, _ = _engine(scores, patience=2, cooldown_seconds=2.0)
    events = _feed(engine, len(scores))
    assert len(events) == 2
    assert events[1].at_seconds - events[0].at_seconds >= 2.0


def test_threshold_is_inclusive_and_configurable():
    engine, _ = _engine([0.3, 0.3], patience=2, threshold=0.3)
    assert len(_feed(engine, 2)) == 1
    engine, _ = _engine([0.29, 0.29], patience=2, threshold=0.3)
    assert _feed(engine, 2) == []


def test_bytes_frames_are_int16_and_a_recording_is_cut_into_80ms_frames():
    engine, model = _engine([0.0] * 10)
    engine.process(_frame().tobytes())
    engine.process_audio(np.zeros(we.FRAME_SAMPLES * 3 + 100, dtype=np.int16))
    assert model.frame_sizes == [we.FRAME_SAMPLES] * 4
    assert engine.seconds_heard == pytest.approx(4 * we.FRAME_SECONDS)


@pytest.mark.parametrize(
    "overrides",
    [{"threshold": 0.0}, {"threshold": 1.0}, {"patience": 0}, {"cooldown_seconds": -1}],
)
def test_bad_settings_are_refused(overrides):
    with pytest.raises(ValueError):
        we.WakeEngineConfig(**overrides).validated()


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("GRANDPA_WAKE_THRESHOLD", "0.65")
    monkeypatch.setenv("GRANDPA_WAKE_PATIENCE", "3")
    monkeypatch.setenv("GRANDPA_WAKE_MODEL", "hey_mycroft")
    config = we.WakeEngineConfig.from_env()
    assert (config.threshold, config.patience, config.model) == (0.65, 3, "hey_mycroft")
    assert we.WakeEngineConfig.from_env(threshold=0.4).threshold == 0.4


def test_model_lookup_prefers_the_hey_grandpa_file(tmp_path: Path):
    empty, chosen = tmp_path / "a", tmp_path / "b"
    empty.mkdir()
    chosen.mkdir()
    (chosen / "hey_grandpa.onnx").write_bytes(b"onnx")
    resolved = we.resolve_wake_model("", search_dirs=[empty, chosen])
    assert resolved.source == "file"
    assert resolved.reference == str(chosen / "hey_grandpa.onnx")


def test_missing_model_says_how_to_get_one(tmp_path: Path):
    with pytest.raises(we.WakeEngineUnavailable) as missing:
        we.resolve_wake_model("", search_dirs=[tmp_path])
    assert "wake-word.md" in str(missing.value)
    assert "hey_mycroft" in str(missing.value)


def test_builtin_names_and_paths(tmp_path: Path):
    builtin = we.resolve_wake_model("hey_mycroft", builtin_names=["hey_mycroft"])
    assert builtin == we.ResolvedModel("hey_mycroft", "hey_mycroft", "builtin")
    with pytest.raises(we.WakeEngineUnavailable, match="Unknown wake model"):
        we.resolve_wake_model("hey_nobody", builtin_names=["hey_mycroft"])
    with pytest.raises(we.WakeEngineUnavailable, match="not found"):
        we.resolve_wake_model(str(tmp_path / "missing.onnx"), builtin_names=[])


def test_false_triggers_per_hour_and_budget():
    events = [we.WakeEvent("x", 0.9, 1.0)]
    over = we.WakeReport(seconds=1800, events=events * 1)
    assert over.per_hour == pytest.approx(2.0)
    assert "OVER" in over.summary(negative=True)
    within = we.WakeReport(seconds=7200, events=events)
    assert within.per_hour == pytest.approx(0.5)
    text = within.summary(negative=True)
    assert "within" in text and "rough estimate" not in text
    assert "per hour" not in we.WakeReport(seconds=10, events=[]).summary(
        negative=False
    )


def _write_wav(path: Path, samples: np.ndarray, rate: int, channels: int = 1):
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(samples.astype("<i2").tobytes())


def test_wav_is_resampled_to_16k_mono(tmp_path: Path):
    stereo = np.zeros(48_000 * 2, dtype=np.int16)  # 1 s at 48 kHz, 2 channels
    path = tmp_path / "stereo.wav"
    _write_wav(path, stereo, 48_000, channels=2)
    samples = we.read_wav_16k_mono(path)
    assert samples.dtype == np.int16
    assert len(samples) == we.SAMPLE_RATE


def test_cli_test_reports_false_triggers(tmp_path: Path, monkeypatch):
    from grandpa.cli.wake_cmd import wake

    path = tmp_path / "tv.wav"
    _write_wav(path, np.zeros(we.SAMPLE_RATE * 6, dtype=np.int16), we.SAMPLE_RATE)
    model = FakeModel([0.0] * 10 + [0.9, 0.9])
    real_engine = we.WakeWordEngine

    def fake_engine(config):
        return real_engine(
            config, model=model, resolved=we.ResolvedModel("f", "hey_grandpa", "file")
        )

    monkeypatch.setattr(we, "WakeWordEngine", fake_engine)
    result = CliRunner().invoke(wake, ["test", str(path), "--negative"])
    assert result.exit_code == 0, result.output
    assert "heard hey_grandpa (score 0.90)" in result.output
    assert "1 trigger(s) in 0.1 min" in result.output
    assert "False triggers: 600.00 per hour, OVER" in result.output


def test_cli_explains_a_missing_model(monkeypatch, tmp_path):
    from grandpa.cli.wake_cmd import wake

    monkeypatch.setattr(we, "DEFAULT_MODEL_DIR", tmp_path)
    monkeypatch.setattr(we, "REPO_MODEL_DIR", tmp_path)
    monkeypatch.delenv("GRANDPA_WAKE_MODEL", raising=False)
    path = tmp_path / "x.wav"
    _write_wav(path, np.zeros(1600, dtype=np.int16), we.SAMPLE_RATE)
    result = CliRunner().invoke(wake, ["test", str(path)])
    assert result.exit_code != 0
    assert "No 'Hey Grandpa' model yet" in result.output


class FakeStream:
    def __init__(self, frames: int) -> None:
        self.frames = frames
        self.started = self.closed = False

    def start(self):
        self.started = True

    def read(self, n):
        if self.frames <= 0:
            raise RuntimeError("device gone")
        self.frames -= 1
        return np.zeros((n, 1), dtype=np.int16), False

    def stop(self):
        pass

    def close(self):
        self.closed = True


class FakeSoundDevice:
    def __init__(self, frames: int) -> None:
        self.kwargs: dict = {}
        self.stream = FakeStream(frames)

    def InputStream(self, **kwargs):  # noqa: N802 - mirrors sounddevice
        self.kwargs = kwargs
        return self.stream


def test_listener_opens_16k_mono_80ms_and_reports_wakes_and_a_dead_device():
    engine, _ = _engine([0.0, 0.9, 0.9, 0.0])
    sd = FakeSoundDevice(frames=4)
    heard: list[we.WakeEvent] = []
    listener = we.WakeWordListener(engine, heard.append, sounddevice_module=sd)
    listener.start()
    listener._thread.join(timeout=2)
    listener.stop()
    assert sd.kwargs == {
        "samplerate": 16_000,
        "channels": 1,
        "dtype": "int16",
        "blocksize": 1280,
        "device": None,
    }
    assert len(heard) == 1
    assert listener.error == "device gone"
    assert sd.stream.closed


def test_nothing_in_the_engine_writes_audio_to_disk():
    import ast

    source = Path(we.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    writes = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"write", "writeframes", "write_bytes", "save"}
    ]
    assert writes == []
    assert '"wb"' not in source


def test_real_openwakeword_stays_quiet_on_noise():
    """With the real model (if its files are installed): 60 s of noise, no wake."""
    oww = pytest.importorskip("openwakeword")
    models = Path(oww.__file__).parent / "resources" / "models"
    needed = ["melspectrogram.onnx", "embedding_model.onnx", "hey_mycroft_v0.1.onnx"]
    if not all((models / name).is_file() for name in needed):
        pytest.skip("openWakeWord feature models not downloaded (grandpa wake setup)")
    engine = we.WakeWordEngine(
        we.WakeEngineConfig(model="hey_mycroft"),
        resolved=we.ResolvedModel(
            str(models / "hey_mycroft_v0.1.onnx"), "hey_mycroft", "file"
        ),
    )
    rng = np.random.default_rng(7)
    noise = (rng.normal(0, 800, we.SAMPLE_RATE * 60)).astype(np.int16)
    assert engine.process_audio(noise) == []
