"""A marginal capture must not become a command, and the system default must be used.

Two fixes, and a record of one I made and withdrew.

**Exit phrases: unchanged, deliberately.** A bare "Goodbye." ended the session,
and Whisper's stock output on silence includes exactly that, so the obvious guard
was to refuse single-word exits. I implemented it, and the suite refused it: three
tests assert "goodbye", "exit" and "quit" work as written, and eight more end a
session loop with a bare "quit". That is documented, conventional behaviour --
"quit" is what people say -- so blocking it is a usability regression dressed as a
hardening.

The hazard was never in the vocabulary. A spurious exit needs a spurious
*transcript*, which needs a capture too marginal to be speech. That is worth
refusing for every command, not only for exits, and the gate for it already
existed in ``_listen_for_transcript`` -- applied only when the VAD finalised on
``silence_timeout``, so a capture ending any other way skipped it. Widening it
protects "delete that file" on the same evidence, which a vocabulary change never
would have. Tests for that live in test_capture_never_sits_silent.py.

**The default device.** ``sounddevice.default.device`` reprs as ``[1, 3]`` but is
a ``_InputOutputPair``, which inherits straight from ``object``. The old code
tested ``isinstance(default, (list, tuple))``, fell through to ``int(pair)``,
raised TypeError, and a bare ``except`` returned None. Every device came back
``is_default=False``, so selection could never honour the system default and fell
through to a name heuristic that prefers WASAPI -- choosing index 9 while Windows
had nominated index 1. ``voice diagnose`` reported "No default index reported",
which was the bug describing itself.
"""

from __future__ import annotations

import pytest

from grandpa.voice.cli_session import EXIT_PHRASES, is_exit_phrase
from grandpa.voice.device_manager import _default_input_device

pytestmark = pytest.mark.core


# --- exit phrases -----------------------------------------------------------------


@pytest.mark.parametrize(
    "spoken",
    [
        "stop listening",
        "please stop listening",
        "exit voice mode",
        "exit voice",
        "goodbye grandpa",
        "goodbye now",
        "quit voice",
        "quit voice mode",
        "stop voice",
        "stop voice mode",
        "stop grandpa",
        "grandpa stop",
        "hey grandpa stop",
        "Goodbye, Grandpa!",
        "stop-listening",
        # The bare words, kept on purpose. Withdrawing them broke three
        # documented expectations and eight session-loop tests.
        "goodbye",
        "exit",
        "quit",
        "Goodbye.",
        "Quit!",
    ],
)
def test_the_exit_vocabulary_is_unchanged(spoken: str) -> None:
    """Including the bare words. "quit" is what people say.

    Pinned so the change I withdrew is not quietly reapplied: the protection
    against a hallucinated exit belongs in the marginal-capture gate, not here.
    """
    assert is_exit_phrase(spoken) is True, spoken


def test_the_added_multi_word_forms_work_too() -> None:
    """Added while the vocabulary change was in flight, and worth keeping.

    "quit" had no two-word form at all, which is what made blocking it so
    obviously wrong once the suite said so.
    """
    for spoken in ("quit voice", "quit voice mode", "goodbye now"):
        assert is_exit_phrase(spoken) is True, spoken
        assert spoken in EXIT_PHRASES


def test_empty_and_whitespace_are_not_commands() -> None:
    """Checked explicitly: an empty transcription must mean nothing at all."""
    for text in ("", "   ", "\n", "\t ", ".", "  ...  "):
        assert is_exit_phrase(text) is False, repr(text)


def test_ordinary_speech_is_not_an_exit() -> None:
    for text in (
        "what is the time",
        "stop the music",
        "exit the building",
        "type goodbye into notepad",
        "say goodbye to the cat",
    ):
        assert is_exit_phrase(text) is False, text


# --- the default input device ------------------------------------------------------


class _InputOutputPair:
    """Mimics sounddevice._InputOutputPair: subscriptable, not a sequence type."""

    def __init__(self, value_in, value_out) -> None:
        self._values = [value_in, value_out]

    def __getitem__(self, index):
        return self._values[index]

    def __repr__(self) -> str:
        return repr(self._values)


class _FakeSoundDevice:
    def __init__(self, default) -> None:
        self.default = type("_Default", (), {"device": default})()


def test_the_input_output_pair_is_read_rather_than_swallowed() -> None:
    """The exact shape sounddevice returns on this machine."""
    fake = _FakeSoundDevice(_InputOutputPair(1, 3))

    assert _default_input_device(fake) == 1


def test_a_plain_integer_default_still_works() -> None:
    """Some backends expose a scalar; do not regress them."""
    assert _default_input_device(_FakeSoundDevice(4)) == 4


def test_a_list_or_tuple_default_still_works() -> None:
    assert _default_input_device(_FakeSoundDevice([2, 5])) == 2
    assert _default_input_device(_FakeSoundDevice((7, 8))) == 7


def test_no_default_is_reported_as_none() -> None:
    """-1 is PortAudio's "no device", and must not be offered as index -1."""
    assert _default_input_device(_FakeSoundDevice(_InputOutputPair(-1, -1))) is None
    assert _default_input_device(_FakeSoundDevice(-1)) is None


def test_an_unreadable_default_is_none_not_a_crash() -> None:
    class _Raising:
        @property
        def default(self):
            raise RuntimeError("PortAudio not initialised")

    assert _default_input_device(_Raising()) is None
    assert _default_input_device(_FakeSoundDevice("not a number")) is None
    assert _default_input_device(_FakeSoundDevice(None)) is None


def test_the_system_default_now_wins_over_the_wasapi_heuristic() -> None:
    """The behaviour the type bug was costing.

    Four duplicates of one microphone across host APIs, plus a default that is
    not the WASAPI one. Before the fix every device came back is_default=False
    and the name heuristic picked WASAPI; now the nominated device wins.
    """
    from grandpa.voice.device_manager import MicrophoneDevice, _best_device

    def device(index: int, driver: str, *, is_default: bool) -> MicrophoneDevice:
        return MicrophoneDevice(
            index=index,
            name="Microphone Array (AMD Audio Device)",
            input_channels=2,
            default_sample_rate=48_000,
            host_api=0,
            driver=driver,
            low_input_latency=None,
            high_input_latency=None,
            is_default=is_default,
            is_default_communications=None,
            is_virtual=False,
            transport="built-in",
        )

    devices = [
        device(1, "MME", is_default=True),
        device(5, "Windows DirectSound", is_default=False),
        device(9, "Windows WASAPI", is_default=False),
        device(12, "Windows WDM-KS", is_default=False),
    ]

    chosen = _best_device(devices)

    assert chosen is not None
    assert chosen.index == 1, (
        f"picked device {chosen.index} ({chosen.driver}) instead of the system default"
    )
