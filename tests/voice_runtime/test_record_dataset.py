from __future__ import annotations

import importlib.util
import subprocess
import sys
import wave
from pathlib import Path
from types import SimpleNamespace

import numpy as np

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "voice_runtime"
    / "datasets"
    / "hari_piper"
    / "scripts"
    / "record_dataset.py"
)
SPEC = importlib.util.spec_from_file_location("hari_piper_record_dataset", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
record_dataset = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = record_dataset
SPEC.loader.exec_module(record_dataset)


def _clean_audio(sample_rate: int = 22_050, duration: float = 3.0) -> np.ndarray:
    count = int(sample_rate * duration)
    time = np.arange(count) / sample_rate
    envelope = np.zeros(count)
    for start, end in ((0.3, 0.9), (1.2, 1.8), (2.1, 2.7)):
        envelope[int(start * sample_rate) : int(end * sample_rate)] = 1.0
    tone = envelope * 0.25 * np.sin(2 * np.pi * 180 * time)
    noise = np.random.default_rng(7).normal(0, 0.001, count)
    samples = np.asarray(
        np.clip((tone + noise) * 32767, -32768, 32767), dtype=np.int16
    )
    return samples[:, None]


def test_prompt_set_contains_40_short_coverage_items() -> None:
    assert len(record_dataset.PROMPTS) == 40
    assert len({item.stem for item in record_dataset.PROMPTS}) == 40
    combined = " ".join(item.text for item in record_dataset.PROMPTS)
    for term in (
        "Hari Hara Sudhan",
        "Grandpa",
        "Python",
        "FastAPI",
        "Docker",
        "GitHub",
        "Ollama",
        "API",
        "database",
        "network",
        "DNS",
        "router",
        "port",
        "backup",
        "system",
        "automation",
        "artificial intelligence",
    ):
        assert term in combined


def test_write_and_inspect_produces_real_pcm16_wav(tmp_path: Path) -> None:
    output = tmp_path / "test.wav"
    record_dataset.write_pcm_wav(output, _clean_audio(), 22_050)

    metrics = record_dataset.inspect_pcm_wav(output)

    assert output.read_bytes()[:4] == b"RIFF"
    assert output.read_bytes()[8:12] == b"WAVE"
    assert metrics.format == "WAV"
    assert metrics.subtype == "PCM_16"
    assert metrics.sample_rate == 22_050
    assert metrics.channels == 1
    assert metrics.duration_seconds == 3.0
    assert metrics.clipped_fraction == 0.0
    assert metrics.passed
    with wave.open(str(output), "rb") as wav_file:
        assert wav_file.getcomptype() == "NONE"
        assert wav_file.getsampwidth() == 2


def test_mislabeled_mp3_is_rejected(tmp_path: Path) -> None:
    output = tmp_path / "not-really.wav"
    output.write_bytes(b"ID3" + b"\x00" * 128)

    metrics = record_dataset.inspect_pcm_wav(output)

    assert not metrics.passed
    assert "RIFF/WAVE" in metrics.issues[0]


def test_short_phrase_trims_edges_and_preserves_internal_pause(tmp_path: Path) -> None:
    sample_rate = 22_050
    duration = 3.8
    count = int(sample_rate * duration)
    timeline = np.arange(count) / sample_rate
    rng = np.random.default_rng(11)
    audio = rng.normal(0, 0.0008, count)
    speech = ((timeline >= 0.6) & (timeline < 1.55)) | (
        (timeline >= 2.05) & (timeline < 3.2)
    )
    audio += speech * 0.18 * np.sin(2 * np.pi * 190 * timeline)
    pcm = np.asarray(np.clip(audio * 32767, -32768, 32767), dtype=np.int16)[:, None]

    trimmed, leading, trailing, threshold = record_dataset.trim_edge_silence(
        pcm, sample_rate
    )
    output = tmp_path / "short_phrase.wav"
    record_dataset.write_pcm_wav(output, trimmed, sample_rate)
    metrics = record_dataset.inspect_pcm_wav(output)

    assert 0.35 <= leading <= 0.55
    assert 0.4 <= trailing <= 0.55
    assert threshold < -45.0
    assert 2.7 <= metrics.duration_seconds <= 3.0
    assert metrics.silent_frame_fraction > 0.10
    assert metrics.passed


class FakeSoundDevice:
    def __init__(self, *, supports_target: bool = True, default_index: int = 1) -> None:
        self.supports_target = supports_target
        self.default = type("Default", (), {"device": (default_index, -1)})()
        self.devices = [
            {"name": "Output", "max_input_channels": 0, "default_samplerate": 48_000},
            {"name": "Microphone Array", "max_input_channels": 2, "default_samplerate": 44_100},
            {"name": "USB Microphone", "max_input_channels": 1, "default_samplerate": 48_000},
        ]
        self.checked: list[int] = []

    def query_devices(self):
        return self.devices

    def check_input_settings(self, **settings) -> None:
        self.checked.append(settings["samplerate"])
        if settings["samplerate"] == 22_050 and not self.supports_target:
            raise ValueError("unsupported")


def test_sample_rate_prefers_22050_when_supported() -> None:
    sd = FakeSoundDevice()
    index, device = record_dataset.select_input_device(sd)

    assert index == 1
    assert record_dataset.select_sample_rate(sd, index, device) == 22_050


def test_sample_rate_falls_back_to_native_lossless_rate() -> None:
    sd = FakeSoundDevice(supports_target=False)
    index, device = record_dataset.select_input_device(sd, requested_name="USB")

    assert index == 2
    assert record_dataset.select_sample_rate(sd, index, device) == 48_000
    assert sd.checked == [22_050, 48_000]


def test_fallback_prefers_physical_microphone_over_mapper() -> None:
    sd = FakeSoundDevice(default_index=-1)
    sd.devices.insert(
        0,
        {
            "name": "Microsoft Sound Mapper - Input",
            "max_input_channels": 2,
            "default_samplerate": 44_100,
        },
    )

    index, device = record_dataset.select_input_device(sd)

    assert index == 2
    assert device["name"] == "Microphone Array"


def test_explicit_output_device_is_rejected() -> None:
    sd = FakeSoundDevice()

    try:
        record_dataset.select_input_device(sd, requested_index=0)
    except ValueError as exc:
        assert "not a usable input device" in str(exc)
    else:
        raise AssertionError("output-only device was accepted")


def test_v2_recording_runs_through_existing_preparer(
    monkeypatch, tmp_path: Path
) -> None:
    dataset_root = tmp_path / "hari_piper"
    raw_output = dataset_root / "raw" / "original_v2"
    raw_output.mkdir(parents=True)
    item = record_dataset.PROMPTS[0]
    record_dataset.write_pcm_wav(
        raw_output / f"{item.stem}.wav",
        _clean_audio(),
        22_050,
    )
    (raw_output / f"{item.stem}.txt").write_text(
        item.text + "\n", encoding="utf-8"
    )
    monkeypatch.setattr(record_dataset, "DATASET_ROOT", dataset_root)
    monkeypatch.setattr(record_dataset, "RAW_OUTPUT", raw_output)
    monkeypatch.setattr(record_dataset, "PROMPTS", (item,))

    class FakePreparer:
        @staticmethod
        def _process_row(row, roots):
            assert roots["raw"] == raw_output
            return SimpleNamespace(
                quality_status="accepted",
                processed_duration_seconds=3.0,
                output_filename=f"{row['clip_id']}.wav",
                transcript=row["transcript"],
            )

        @staticmethod
        def _write_outputs(records, roots):
            record = records[0]
            (roots["metadata"] / "metadata.csv").write_text(
                f"{record.output_filename}|{record.transcript}\n", encoding="utf-8"
            )
            (roots["metadata"] / "extended_manifest.csv").write_text(
                "clip_id,quality_status\n001_english_intro,accepted\n",
                encoding="utf-8",
            )
            (roots["reports"] / "validation_report.json").write_text(
                '{"counts":{"accepted":1,"review":0,"rejected":0}}',
                encoding="utf-8",
            )

    monkeypatch.setattr(record_dataset, "_load_preparer", FakePreparer)

    manifest, records, issues = record_dataset.run_preparation()

    assert manifest.is_file()
    assert issues == []
    assert len(records) == 1
    assert records[0].quality_status == "accepted"
    assert (manifest.parent / "metadata.csv").read_text(encoding="utf-8").startswith(
        f"{item.stem}.wav|"
    )


def test_recording_session_launches_preparation_in_voice_runtime(
    monkeypatch, tmp_path: Path
) -> None:
    runtime_python = tmp_path / "python.exe"
    runtime_python.write_bytes(b"")
    calls: list[tuple[list[str], bool]] = []

    def fake_run(command, *, check):
        calls.append((command, check))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(record_dataset, "VOICE_RUNTIME_PYTHON", runtime_python)
    monkeypatch.setattr(record_dataset.subprocess, "run", fake_run)

    record_dataset.launch_preparation()

    assert calls == [
        (
            [
                str(runtime_python),
                str(record_dataset.Path(record_dataset.__file__).resolve()),
                "--prepare-only",
            ],
            False,
        )
    ]


def _write_valid_pair(root: Path, item=None) -> None:
    item = item or record_dataset.PROMPTS[0]
    record_dataset.write_pcm_wav(
        root / f"{item.stem}.wav", _clean_audio(), 22_050
    )
    (root / f"{item.stem}.txt").write_text(item.text + "\n", encoding="utf-8")


def test_progress_resumes_after_existing_valid_clip(monkeypatch, tmp_path: Path) -> None:
    raw = tmp_path / "original_v2"
    raw.mkdir()
    _write_valid_pair(raw)
    monkeypatch.setattr(record_dataset, "RAW_OUTPUT", raw)

    progress = record_dataset.scan_dataset_progress()

    assert [item.number for item in progress.completed] == [1]
    assert len(progress.remaining) == 39
    assert progress.next_item == record_dataset.PROMPTS[1]


def test_invalid_existing_wav_is_not_completed(monkeypatch, tmp_path: Path) -> None:
    raw = tmp_path / "original_v2"
    raw.mkdir()
    item = record_dataset.PROMPTS[0]
    (raw / f"{item.stem}.wav").write_bytes(b"ID3-not-a-wav")
    (raw / f"{item.stem}.txt").write_text(item.text + "\n", encoding="utf-8")
    monkeypatch.setattr(record_dataset, "RAW_OUTPUT", raw)

    progress = record_dataset.scan_dataset_progress()

    assert item not in progress.completed
    assert "audio validation failed" in dict(progress.invalid)[item]


def test_missing_transcript_is_not_completed(monkeypatch, tmp_path: Path) -> None:
    raw = tmp_path / "original_v2"
    raw.mkdir()
    item = record_dataset.PROMPTS[0]
    record_dataset.write_pcm_wav(raw / f"{item.stem}.wav", _clean_audio(), 22_050)
    monkeypatch.setattr(record_dataset, "RAW_OUTPUT", raw)

    progress = record_dataset.scan_dataset_progress()

    assert item not in progress.completed
    assert dict(progress.invalid)[item] == "transcript is missing"


def test_incorrect_transcript_is_not_completed(monkeypatch, tmp_path: Path) -> None:
    raw = tmp_path / "original_v2"
    raw.mkdir()
    item = record_dataset.PROMPTS[0]
    record_dataset.write_pcm_wav(raw / f"{item.stem}.wav", _clean_audio(), 22_050)
    (raw / f"{item.stem}.txt").write_text("Different text\n", encoding="utf-8")
    monkeypatch.setattr(record_dataset, "RAW_OUTPUT", raw)

    progress = record_dataset.scan_dataset_progress()

    assert item not in progress.completed
    assert "exactly match" in dict(progress.invalid)[item]


def test_existing_valid_mic_test_is_reused_by_default(
    monkeypatch, tmp_path: Path
) -> None:
    raw = tmp_path / "original_v2"
    raw.mkdir()
    record_dataset.write_pcm_wav(raw / "000_mic_test.wav", _clean_audio(), 22_050)
    monkeypatch.setattr(record_dataset, "RAW_OUTPUT", raw)
    monkeypatch.setattr(
        record_dataset,
        "record_mic_test",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("mic test unexpectedly repeated")
        ),
    )

    metrics = record_dataset.ensure_microphone_test(
        object(), 1, 22_050, input_fn=lambda _prompt: ""
    )

    assert metrics.passed


def test_empty_menu_input_reprompts_instead_of_exiting() -> None:
    answers = iter(("", "a"))

    choice = record_dataset.prompt_choice(
        "choice: ", {"a", "q"}, input_fn=lambda _prompt: next(answers)
    )

    assert choice == "a"


def test_fast_mode_auto_accepts_valid_clip(monkeypatch, tmp_path: Path) -> None:
    raw = tmp_path / "original_v2"
    raw.mkdir()
    item = record_dataset.PROMPTS[0]
    monkeypatch.setattr(record_dataset, "RAW_OUTPUT", raw)
    monkeypatch.setattr(record_dataset, "countdown", lambda: None)
    monkeypatch.setattr(record_dataset, "capture_audio", lambda *_args, **_kwargs: _clean_audio())

    result = record_dataset.record_item(
        object(),
        item,
        device_index=1,
        sample_rate=22_050,
        mode="fast",
        input_fn=lambda _prompt: "",
    )

    assert result == "accepted"
    assert record_dataset.validate_recording_pair(item)[0]


def test_quit_preserves_previously_accepted_clip(monkeypatch, tmp_path: Path) -> None:
    raw = tmp_path / "original_v2"
    raw.mkdir()
    accepted = record_dataset.PROMPTS[0]
    current = record_dataset.PROMPTS[1]
    _write_valid_pair(raw, accepted)
    monkeypatch.setattr(record_dataset, "RAW_OUTPUT", raw)
    monkeypatch.setattr(record_dataset, "countdown", lambda: None)
    monkeypatch.setattr(record_dataset, "capture_audio", lambda *_args, **_kwargs: _clean_audio())
    answers = iter(("", "q"))

    result = record_dataset.record_item(
        object(),
        current,
        device_index=1,
        sample_rate=22_050,
        input_fn=lambda _prompt: next(answers),
    )

    assert result == "quit"
    assert record_dataset.validate_recording_pair(accepted)[0]
    assert not (raw / f"{current.stem}.wav").exists()


def test_ctrl_c_returns_cleanly_and_preserves_files(
    monkeypatch, tmp_path: Path
) -> None:
    raw = tmp_path / "original_v2"
    raw.mkdir()
    item = record_dataset.PROMPTS[0]
    _write_valid_pair(raw, item)
    monkeypatch.setattr(record_dataset, "RAW_OUTPUT", raw)
    monkeypatch.setattr(
        record_dataset,
        "main",
        lambda _argv=None: (_ for _ in ()).throw(KeyboardInterrupt()),
    )

    assert record_dataset.cli([]) == 130
    assert (raw / f"{item.stem}.wav").is_file()
    assert (raw / f"{item.stem}.txt").is_file()


def test_ten_clip_checkpoint_defaults_to_saved_quit() -> None:
    state = record_dataset.SessionState()

    should_continue, updated = record_dataset.checkpoint_decision(
        10, state, input_fn=lambda _prompt: ""
    )

    assert not should_continue
    assert updated.checkpoints_shown == (10,)


def test_completed_recording_is_never_overwritten(
    monkeypatch, tmp_path: Path
) -> None:
    raw = tmp_path / "original_v2"
    raw.mkdir()
    item = record_dataset.PROMPTS[0]
    _write_valid_pair(raw, item)
    original = (raw / f"{item.stem}.wav").read_bytes()
    monkeypatch.setattr(record_dataset, "RAW_OUTPUT", raw)
    monkeypatch.setattr(
        record_dataset,
        "capture_audio",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("completed clip was recorded again")
        ),
    )

    result = record_dataset.record_item(
        object(), item, device_index=1, sample_rate=22_050
    )

    assert result == "accepted"
    assert (raw / f"{item.stem}.wav").read_bytes() == original


def test_preparation_is_not_triggered_with_only_ten_clips(
    monkeypatch, tmp_path: Path
) -> None:
    raw = tmp_path / "original_v2"
    raw.mkdir()
    prompts = record_dataset.PROMPTS[:10]
    for item in prompts:
        _write_valid_pair(raw, item)
    monkeypatch.setattr(record_dataset, "RAW_OUTPUT", raw)
    monkeypatch.setattr(
        record_dataset,
        "launch_preparation",
        lambda: (_ for _ in ()).throw(
            AssertionError("preparation ran before 40 clips")
        ),
    )

    assert not record_dataset.maybe_prepare_complete_dataset(
        input_fn=lambda _prompt: "y"
    )
