from __future__ import annotations

import json
import subprocess
import wave
from pathlib import Path

from grandpa.voice_service.post_processing import (
    CharacterVoiceSettings,
    FFmpegCharacterVoiceProcessor,
    build_character_filters,
)


def _wav_bytes(path: Path, sample_rate: int = 24_000) -> bytes:
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(b"\x00\x00" * 240)
    return path.read_bytes()


def test_disabled_character_processing_returns_raw_audio() -> None:
    raw = b"RIFF-raw"
    processor = FFmpegCharacterVoiceProcessor(
        CharacterVoiceSettings(enabled=False),
        command_runner=lambda _command: (_ for _ in ()).throw(
            AssertionError("FFmpeg should not run")
        ),
    )

    assert processor.process(raw) is raw


def test_balanced_filters_apply_pitch_pace_compression_and_eq() -> None:
    filters = build_character_filters(
        CharacterVoiceSettings(
            pitch_semitones=-2.0,
            speed=0.92,
            eq_profile="grandpa_balanced",
        ),
        24_000,
    )

    assert filters[0].startswith("asetrate=24000*0.89089872")
    assert filters[2].startswith("atempo=1.032665")
    assert any(item.startswith("acompressor=") for item in filters)
    assert "equalizer=f=140:t=q:w=1:g=2" in filters
    assert "equalizer=f=3000:t=q:w=1:g=1" in filters


def test_balanced_clear_filters_reduce_body_and_add_broad_presence() -> None:
    filters = build_character_filters(
        CharacterVoiceSettings(
            pitch_semitones=-1.5,
            speed=0.94,
            target_lufs=-15.0,
            eq_profile="grandpa_balanced_clear",
        ),
        24_000,
    )

    assert filters[0].startswith("asetrate=24000*0.91700404")
    assert filters[2].startswith("atempo=1.025077")
    assert "equalizer=f=140:t=q:w=1:g=0.75" in filters
    assert "equalizer=f=320:t=q:w=1:g=-0.75" in filters
    assert "equalizer=f=3000:t=q:w=0.8:g=1.5" in filters


def test_deep_clear_filters_preserve_body_without_muddiness() -> None:
    filters = build_character_filters(CharacterVoiceSettings(), 24_000)

    assert filters[0].startswith("asetrate=24000*0.89089872")
    assert filters[2].startswith("atempo=1.032665")
    assert "equalizer=f=135:t=q:w=1:g=1.5" in filters
    assert "equalizer=f=320:t=q:w=1:g=-1" in filters
    assert "equalizer=f=3000:t=q:w=0.8:g=1.75" in filters


def test_approved_presence_profile_has_no_pitch_or_tempo_filters() -> None:
    filters = build_character_filters(
        CharacterVoiceSettings(
            pitch_semitones=0.0,
            speed=1.0,
            target_lufs=-14.5,
            true_peak_db=-1.0,
            compression=True,
            eq_profile="grandpa_presence",
        ),
        24_000,
    )

    assert not any("asetrate" in item for item in filters)
    assert not any("aresample" in item for item in filters)
    assert not any("atempo" in item for item in filters)
    assert filters == (
        "highpass=f=70",
        "acompressor=threshold=0.08:ratio=2.5:attack=15:release=180:"
        "makeup=1.5:knee=2.828",
        "equalizer=f=150:t=q:w=1.0:g=1.0",
        "equalizer=f=3000:t=q:w=0.8:g=2.0",
    )


def test_processor_runs_two_pass_loudness_and_returns_pcm_wav(tmp_path) -> None:
    source_bytes = _wav_bytes(tmp_path / "source.wav")
    commands: list[list[str]] = []
    measurement = {
        "input_i": "-20.0",
        "input_tp": "-5.0",
        "input_lra": "2.0",
        "input_thresh": "-30.0",
        "target_offset": "0.2",
    }

    def fake_run(command):
        command = list(command)
        commands.append(command)
        if command[-1] == "NUL":
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="",
                stderr=json.dumps(measurement),
            )
        output = Path(command[-1])
        output.write_bytes(source_bytes)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    processor = FFmpegCharacterVoiceProcessor(
        CharacterVoiceSettings(),
        ffmpeg_path="ffmpeg.exe",
        command_runner=fake_run,
    )

    processed = processor.process(source_bytes)

    assert processed == source_bytes
    assert len(commands) == 2
    assert "print_format=json" in commands[0][commands[0].index("-af") + 1]
    second_filter = commands[1][commands[1].index("-af") + 1]
    assert "measured_I=-20.0" in second_filter
    assert "alimiter=limit=0.87599172" in second_filter
    assert commands[1][-7:-1] == [
        "-ac",
        "1",
        "-ar",
        "24000",
        "-c:a",
        "pcm_s16le",
    ]
