"""A4: lip-sync -- the mouth track, its timing, and the page that plays it.

No real voice is used: a fake synthesiser writes a WAV with known loud and
silent stretches, and a fake player records when playback began. The drift
check uses the real clock, because drift is a property of real timing.
"""

from __future__ import annotations

import json
import math
import re
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from grandpa.ui import lipsync
from grandpa.ui.avatar_controller import AvatarController
from grandpa.ui.avatar_states import AvatarState, StateMessage, encode
from grandpa.ui.avatar_window import WEB_DIR
from grandpa.ui.lipsync import (
    MAX_TRACK,
    VISEMES,
    LipSyncSpeaker,
    build_track,
    envelope,
    read_wav,
    split_sentences,
    text_to_tokens,
)

pytestmark = pytest.mark.core

RATE = 16_000


def _tone(ms: int, loud: bool = True) -> list[float]:
    n = int(RATE * ms / 1000)
    amp = 0.6 if loud else 0.0
    return [amp * math.sin(2 * math.pi * 220 * i / RATE) for i in range(n)]


def _write_wav(path: Path, samples: list[float], channels: int = 1) -> None:
    import struct

    frames = b"".join(
        struct.pack("<" + "h" * channels, *([int(s * 32767)] * channels))
        for s in samples
    )
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(RATE)
        wav.writeframes(frames)


# --- the phoneme pass ---------------------------------------------------------


def _visemes(text: str) -> list[str]:
    return [t.viseme for t in text_to_tokens(text) if t.viseme != "rest"]


def test_lips_close_on_m_b_p_and_bite_on_f_v() -> None:
    assert _visemes("map") == ["MBP", "AA", "MBP"]
    assert _visemes("five") == ["FV", "I", "FV"]  # the silent final e is dropped


def test_vowel_pairs_are_one_shape() -> None:
    assert _visemes("see") == ["E", "I"]
    assert _visemes("moon") == ["MBP", "U", "E"]


def test_punctuation_is_a_pause() -> None:
    tokens = text_to_tokens("Yes. No")
    pauses = [t for t in tokens if t.viseme == "rest"]
    assert any(t.length >= 2 for t in pauses)


def test_other_scripts_give_no_letter_shapes() -> None:
    assert _visemes("வணக்கம் 30") == []


# --- the amplitude pass -------------------------------------------------------


def test_the_envelope_is_loud_where_the_voice_is(tmp_path) -> None:
    path = tmp_path / "a.wav"
    _write_wav(path, _tone(200, loud=False) + _tone(400) + _tone(200, loud=False))
    samples, rate = read_wav(path)
    assert rate == RATE
    levels = envelope(samples, rate)
    assert len(levels) == 40  # 800 ms / 20 ms
    assert max(levels[:10]) == 0
    assert min(levels[11:29]) > 0.9
    assert max(levels[31:]) == 0


def test_stereo_is_read_as_mono(tmp_path) -> None:
    path = tmp_path / "s.wav"
    _write_wav(path, _tone(100), channels=2)
    samples, rate = read_wav(path)
    assert len(samples) == RATE // 10


# --- the track ----------------------------------------------------------------


def _check(track, duration_ms: int) -> None:
    times = [e["t"] for e in track]
    assert times == sorted(times)
    assert times[0] == 0 and times[-1] == duration_ms
    assert track[-1]["v"] == "rest"
    assert {e["v"] for e in track} <= set(VISEMES)
    assert all(0 <= e["w"] <= 1 for e in track)
    assert len(track) <= MAX_TRACK


def test_the_mouth_moves_only_while_the_audio_is_loud() -> None:
    levels = [0.0] * 10 + [1.0] * 30 + [0.0] * 10  # 200 ms quiet, 600 loud, 200 quiet
    track = build_track("Hello, my friend", 1000, levels)
    _check(track, 1000)
    open_times = [e["t"] for e in track if e["v"] != "rest" and e["w"] > 0]
    assert open_times
    assert min(open_times) >= 200 and max(open_times) < 800


def test_a_silence_mid_reply_closes_the_mouth() -> None:
    levels = [1.0] * 20 + [0.0] * 10 + [1.0] * 20
    track = build_track("open wide and say aah", 1000, levels)
    _check(track, 1000)
    during_gap = [e for e in track if 400 <= e["t"] < 600]
    assert during_gap and all(e["v"] == "rest" for e in during_gap)


def test_tamil_follows_the_voice_alone() -> None:
    levels = [0.0, 1.0, 1.0, 0.0, 0.5]
    track = build_track("வணக்கம்", 100, levels)
    _check(track, 100)
    assert any(e["v"] == "AA" for e in track)


def test_silence_is_a_closed_mouth() -> None:
    track = build_track("hello", 500, [0.0] * 25)
    assert all(e["v"] == "rest" for e in track)


def test_a_long_reply_stays_within_the_track_limit() -> None:
    text = "the quick brown fox jumps over the lazy dog " * 40
    levels = [1.0, 0.0] * 1500  # 60 s of rapid on/off
    track = build_track(text, 60_000, levels)
    _check(track, 60_000)


def test_a_track_rides_in_the_speaking_state() -> None:
    track = build_track("hi", 200, [1.0] * 10)
    data = json.loads(
        encode(StateMessage(AvatarState.SPEAKING, visemes=track, speech_start_ms=123.0))
    )
    assert data["state"] == "speaking"
    assert data["visemes"] == list(track)
    assert data["speech_start_ms"] == 123.0


# --- saying it: timing ----------------------------------------------------------


@dataclass
class FakeVoice:
    ms: int = 600
    played_at: float = 0.0
    fail: bool = False

    def synthesize(self, text: str, path: Path) -> None:
        if self.fail:
            raise RuntimeError("no SAPI voice")
        _write_wav(path, _tone(100, loud=False) + _tone(self.ms - 100))

    def play(self, path: Path) -> None:
        self.played_at = time.time() * 1000
        assert path.exists()


def test_playback_starts_when_the_track_says_within_100ms() -> None:
    voice = FakeVoice()
    started: list = []
    speaker = LipSyncSpeaker(synthesize=voice.synthesize, play=voice.play)
    assert speaker.speak(
        "Volume is thirty.", lambda track, at: started.append((track, at))
    )
    ((track, start_ms),) = started
    assert abs(voice.played_at - start_ms) < 100  # the A4 drift budget
    assert voice.played_at >= start_ms - 5  # never before the page has the track
    assert abs(track[-1]["t"] - voice.ms) < 100  # the track is as long as the audio
    assert track[0]["v"] == "rest"  # the first 100 ms are silent


def test_the_track_is_published_before_any_sound() -> None:
    order: list[str] = []
    speaker = LipSyncSpeaker(
        synthesize=FakeVoice().synthesize,
        play=lambda _p: order.append("play"),
        sleep=lambda _s: None,
    )
    speaker.speak("hello", lambda *_a: order.append("track"))
    assert order == ["track", "play"]


def test_no_voice_means_no_mouth_and_no_crash() -> None:
    started: list = []
    speaker = LipSyncSpeaker(
        synthesize=FakeVoice(fail=True).synthesize, play=FakeVoice().play
    )
    assert speaker.speak("hello", lambda *a: started.append(a)) is False
    assert started == []


def test_nothing_to_say_is_silent() -> None:
    speaker = LipSyncSpeaker(synthesize=FakeVoice().synthesize, play=FakeVoice().play)
    assert speaker.speak("```code only```", lambda *_a: None) is False


# --- saying it: one sentence at a time ------------------------------------------


def test_a_reply_is_cut_into_sentences() -> None:
    assert split_sentences(
        "The time is ten o'clock. Volume is now thirty percent! Anything else?"
    ) == [
        "The time is ten o'clock.",
        "Volume is now thirty percent! Anything else?",
    ]


def test_short_sentences_ride_with_the_next() -> None:
    assert split_sentences("Okay. Sure. I opened Notepad for you just now.") == [
        "Okay. Sure. I opened Notepad for you just now."
    ]


def test_numbers_and_tamil_are_not_cut_mid_sentence() -> None:
    assert split_sentences("Python 3.12 is installed on this computer already.") == [
        "Python 3.12 is installed on this computer already."
    ]
    tamil = "வணக்கம் கேப்டன், எப்படி இருக்கீங்க? இன்னைக்கு என்ன வேலை பண்ணலாம்?"
    assert split_sentences(tamil) == [
        "வணக்கம் கேப்டன், எப்படி இருக்கீங்க?",
        "இன்னைக்கு என்ன வேலை பண்ணலாம்?",
    ]


@dataclass
class TimedVoice:
    """Synthesis takes ``synth_s`` per sentence, playback ``play_s``."""

    synth_s: float = 0.05
    play_s: float = 0.05
    events: list = field(default_factory=list)

    def synthesize(self, text: str, path: Path) -> None:
        time.sleep(self.synth_s)
        self.events.append(("synth", text, time.time()))
        _write_wav(path, _tone(200))

    def play(self, path: Path) -> None:
        self.events.append(("play", path.name, time.time()))
        time.sleep(self.play_s)


REPLY = (
    "The weather in Bengaluru is pleasant today. "
    "It will be around twenty six degrees this evening. "
    "Carry an umbrella just in case it rains later."
)


def test_each_sentence_gets_its_own_track() -> None:
    voice = TimedVoice()
    started: list = []
    speaker = LipSyncSpeaker(synthesize=voice.synthesize, play=voice.play)
    assert speaker.speak(REPLY, lambda track, at: started.append((track, at)))
    assert len(started) == 3
    starts = [at for _track, at in started]
    assert starts == sorted(starts)
    plays = [e for e in voice.events if e[0] == "play"]
    assert len(plays) == 3
    assert len({name for _k, name, _t in plays}) == 3  # one WAV per sentence


def test_the_first_sound_waits_for_one_sentence_not_the_whole_reply() -> None:
    voice = TimedVoice(synth_s=0.15, play_s=0.2)
    speaker = LipSyncSpeaker(synthesize=voice.synthesize, play=voice.play)
    speaker.speak(REPLY, lambda *_a: None)
    kinds = [kind for kind, _x, _t in voice.events]
    # The first sound comes after one synthesis, before the last one is made.
    # Order, not seconds: a slow CI machine stretches every sleep alike.
    assert kinds[0] == "synth"
    assert kinds.index("play") < len(kinds) - 1 - kinds[::-1].index("synth")


def test_the_next_sentence_is_made_while_this_one_plays() -> None:
    voice = TimedVoice(synth_s=0.05, play_s=0.3)
    speaker = LipSyncSpeaker(synthesize=voice.synthesize, play=voice.play)
    speaker.speak(REPLY, lambda *_a: None)
    kinds = [kind for kind, *_ in voice.events]
    assert kinds[:3] == ["synth", "play", "synth"]


def test_a_sentence_never_starts_before_the_last_one_ends() -> None:
    voice = TimedVoice(synth_s=0.01, play_s=0.15)
    speaker = LipSyncSpeaker(synthesize=voice.synthesize, play=voice.play)
    speaker.speak(REPLY, lambda *_a: None)
    plays = [t for kind, _x, t in voice.events if kind == "play"]
    assert all(b - a >= 0.14 for a, b in zip(plays, plays[1:], strict=False))


def test_a_voice_that_breaks_mid_reply_stops_cleanly(tmp_path) -> None:
    calls: list[str] = []

    def synth(text: str, path: Path) -> None:
        calls.append(text)
        if len(calls) > 1:
            raise RuntimeError("voice crashed")
        _write_wav(path, _tone(200))

    started: list = []
    speaker = LipSyncSpeaker(synthesize=synth, play=lambda _p: None)
    assert speaker.speak(REPLY, lambda *a: started.append(a)) is True
    assert len(started) == 1  # the first sentence was said, the rest skipped


def test_streaming_can_be_switched_off() -> None:
    voice = TimedVoice(synth_s=0.0, play_s=0.0)
    started: list = []
    speaker = LipSyncSpeaker(synthesize=voice.synthesize, play=voice.play, stream=False)
    speaker.speak(REPLY, lambda *a: started.append(a))
    assert len(started) == 1


def test_no_wav_is_left_behind() -> None:
    import tempfile as tf

    before = set(Path(tf.gettempdir()).glob("grandpa-say-*.wav"))
    voice = TimedVoice(synth_s=0.0, play_s=0.0)
    LipSyncSpeaker(synthesize=voice.synthesize, play=voice.play).speak(
        REPLY, lambda *_a: None
    )
    assert set(Path(tf.gettempdir()).glob("grandpa-say-*.wav")) == before


# --- the controller -------------------------------------------------------------


@dataclass
class Reply:
    text: str = "ok"
    status: str = "ok"
    failed: bool = False
    kind: str | None = None


class Bridge:
    def __init__(self, reply: Reply):
        self.reply = reply

    def send(self, _text: str) -> Reply:
        return self.reply


class Speaker:
    def __init__(self):
        self.said: list[str] = []

    def speak(self, text, on_start):
        self.said.append(text)
        on_start(
            ({"t": 0, "v": "AA", "w": 1.0}, {"t": 300, "v": "rest", "w": 0.0}), 42.0
        )
        return True


def _states(published) -> list[StateMessage]:
    return [m for m in published if isinstance(m, StateMessage)]


def test_a_spoken_reply_shows_speaking_with_its_track_then_rests() -> None:
    published: list = []
    speaker = Speaker()
    controller = AvatarController(
        bridge=Bridge(Reply("It is ten o'clock.")),
        publish=published.append,
        speaker=speaker,
    )
    controller.submit("what time is it")
    states = _states(published)
    assert [str(s.state) for s in states] == ["thinking", "speaking", "idle"]
    assert states[1].visemes[0]["v"] == "AA" and states[1].speech_start_ms == 42.0
    assert speaker.said == ["It is ten o'clock."]


def test_a_question_is_said_and_then_the_yes_no_shows() -> None:
    published: list = []
    controller = AvatarController(
        bridge=Bridge(Reply("Lock the screen?", status="requires_confirmation")),
        publish=published.append,
        speaker=Speaker(),
    )
    controller.submit("lock the screen")
    assert [str(s.state) for s in _states(published)] == [
        "thinking",
        "speaking",
        "confirm",
    ]


def test_without_a_speaker_the_avatar_stays_silent() -> None:
    published: list = []
    controller = AvatarController(bridge=Bridge(Reply("Hi.")), publish=published.append)
    controller.submit("hello")
    assert "speaking" not in [str(s.state) for s in _states(published)]


def test_a_speaker_that_raises_does_not_break_the_reply() -> None:
    class Broken:
        def speak(self, *_a):
            raise RuntimeError("audio device gone")

    published: list = []
    controller = AvatarController(
        bridge=Bridge(Reply("Hi.")), publish=published.append, speaker=Broken()
    )
    assert controller.submit("hello")
    assert str(_states(published)[-1].state) == "idle"


# --- the page -------------------------------------------------------------------


def _js(name: str) -> str:
    return (WEB_DIR / name).read_text(encoding="utf-8")


def test_the_page_knows_the_same_visemes() -> None:
    js = _js("character.js")
    listed = re.search(r"const VISEMES = \[([^\]]+)\]", js).group(1)
    assert {v.strip().strip('"') for v in listed.split(",")} == set(VISEMES) - {"rest"}
    shapes = re.search(r"const MOUTH = \{(.+?)\};", js, re.S).group(1)
    assert set(re.findall(r"(\w+):", shapes)) == set(VISEMES)


def test_the_page_plays_the_track_by_this_pcs_clock() -> None:
    js = _js("character.js")
    assert "msg.speech_start_ms" in js
    assert "Date.now() - speech.start" in js
    assert "cleanTrack(msg.visemes)" in js  # Python's track is checked, not trusted
    assert "const MAX_TRACK = " in js


def test_both_characters_move_their_mouth() -> None:
    js = _js("character.js")
    assert js.count("setMouth(weights)") == 2  # the placeholder and a .glb
    assert "v.toLowerCase() === name.toLowerCase()" in js  # .glb shape keys by name


def test_the_command_can_be_quiet() -> None:
    from click.testing import CliRunner

    from grandpa.cli import cli

    result = CliRunner().invoke(cli, ["avatar", "--help"])
    assert result.exit_code == 0, result.output
    assert "--quiet" in result.output


def test_the_default_speaker_follows_the_tts_switch(monkeypatch) -> None:
    from types import SimpleNamespace

    import grandpa.core.config as config

    monkeypatch.setattr(
        config,
        "load_config",
        lambda: SimpleNamespace(tts=SimpleNamespace(enabled=False)),
    )
    speaker, line = lipsync.default_speaker()
    assert speaker is None and "tts.enabled" in line
