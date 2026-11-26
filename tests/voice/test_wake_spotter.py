""""Hey Grandpa" without a trained model: segments, matching, the worker."""

from __future__ import annotations

import io
import wave

import pytest

np = pytest.importorskip("numpy")

from grandpa.voice.wake_spotter import (  # noqa: E402
    FRAME_SAMPLES,
    SpotterConfig,
    TranscriptWakeEngine,
    match_wake,
    pcm_to_wav,
)


@pytest.mark.parametrize(
    "text,rest",
    [
        ("Hey Grandpa.", 0),
        ("Hey, Grandpa!", 0),
        ("hi grandpa open notepad", 2),
        ("Grandpa, what time is it?", 4),
        ("Hey grand pa", 0),
        ("Hey Granpa, volume up", 2),
        ("Okay grandpa", 0),
    ],
)
def test_the_phrase_at_the_start_wakes(text: str, rest: int) -> None:
    match = match_wake(text)
    assert match.matched and match.rest == rest


@pytest.mark.parametrize(
    "text",
    [
        "",
        "I called my grandpa yesterday",
        "my grandpa is 80",
        "hey there",
        "grandfather",
        "hey you grandpa",
        "Thank you.",
    ],
)
def test_other_speech_does_not_wake(text: str) -> None:
    assert not match_wake(text).matched


def frame(level: int) -> "np.ndarray":
    rng = np.random.default_rng(level)
    return (rng.standard_normal(FRAME_SAMPLES) * level).astype(np.int16)


def quiet(n: int) -> list:
    return [frame(20) for _ in range(n)]


def loud(n: int) -> list:
    return [frame(3000) for _ in range(n)]


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def engine(said: str, *, gate=lambda: True, clock=None, run=None):
    woke: list = []
    heard: list = []

    def spotter(samples):
        heard.append(len(samples))
        return said

    eng = TranscriptWakeEngine(
        lambda samples, match: woke.append(match),
        spotter=spotter,
        gate=gate,
        clock=clock or Clock(),
        run=run or (lambda job: job()),
    )
    return eng, woke, heard


def test_silence_never_reaches_whisper() -> None:
    eng, woke, heard = engine("Hey Grandpa")
    for f in quiet(200):
        eng.process(f)
    assert heard == [] and woke == []


def test_a_spoken_phrase_is_read_once_and_wakes() -> None:
    eng, woke, heard = engine("Hey Grandpa")
    for f in quiet(20) + loud(10) + quiet(12):
        eng.process(f)
    assert len(heard) == 1 and len(woke) == 1
    # pre-roll + the speech + the quiet that ended it
    assert heard[0] >= 10 * FRAME_SAMPLES


def test_a_click_is_too_short_to_read() -> None:
    eng, woke, heard = engine("Hey Grandpa")
    for f in quiet(20) + loud(2) + quiet(12):
        eng.process(f)
    assert heard == []


def test_other_words_are_read_but_do_not_wake() -> None:
    eng, woke, heard = engine("what a nice day")
    for f in quiet(20) + loud(10) + quiet(12):
        eng.process(f)
    assert len(heard) == 1 and woke == []


def test_nothing_is_read_while_grandpa_is_busy() -> None:
    busy = {"on": True}
    eng, woke, heard = engine("Hey Grandpa", gate=lambda: not busy["on"])
    for f in quiet(20) + loud(10) + quiet(12):
        eng.process(f)
    assert heard == []


def test_long_talk_is_cut_and_the_rest_ignored() -> None:
    eng, woke, heard = engine("blah")
    cap = int(SpotterConfig().maximum_seconds / (FRAME_SAMPLES / 16000))
    for f in quiet(20) + loud(cap * 3) + quiet(12):
        eng.process(f)
    assert len(heard) == 1  # one capped segment; the rest of the talk is skipped


def test_a_segment_is_dropped_while_the_last_is_still_read() -> None:
    jobs: list = []
    eng, woke, heard = engine("Hey Grandpa", run=jobs.append)
    for f in quiet(20) + loud(10) + quiet(12) + loud(10) + quiet(12):
        eng.process(f)
    assert len(jobs) == 1 and eng.segments_dropped == 1
    jobs[0]()
    assert len(woke) == 1


def test_no_second_wake_during_the_cooldown() -> None:
    clock = Clock()
    eng, woke, heard = engine("Hey Grandpa", clock=clock)
    for f in quiet(20) + loud(10) + quiet(12) + loud(10) + quiet(12):
        eng.process(f)
    assert len(woke) == 1
    clock.now = 10.0
    for f in loud(10) + quiet(12):
        eng.process(f)
    assert len(woke) == 2


def test_the_segment_becomes_a_16k_wav() -> None:
    data = pcm_to_wav(np.zeros(1600, dtype=np.int16))
    with wave.open(io.BytesIO(data)) as wav:
        assert (wav.getframerate(), wav.getnchannels(), wav.getnframes()) == (16000, 1, 1600)
