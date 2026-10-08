"""A PortAudio index is positional, so nothing may persist one.

Across three live runs the same microphone was index 9, then 15, then 9 again,
because a Bluetooth device connected and disconnected in between. An index is a
position in an enumeration, not an identity.

What is stored is a name plus a host API, which is why this was tolerable:

    [voice]
    preferred_microphone = "Microphone Array (AMD Audio Device)"
    preferred_microphone_host_api = "Windows WASAPI"

An index reaches the code from exactly two transient places -- ``--microphone N``
and ``GRANDPA_VOICE_MICROPHONE`` -- and neither is written anywhere. But when one
*was* supplied it was taken entirely on trust: ``select(requested_index=...)``
returned whatever sat at that position with no identity check at all, so a
shifted index recorded silently from the wrong device. That is the gap this file
closes.
"""

from __future__ import annotations

import inspect

import pytest

from grandpa.voice.device_manager import (
    MicrophoneDeviceManager,
    MicrophoneIdentity,
)

pytestmark = pytest.mark.core

ARRAY = "Microphone Array (AMD Audio Device)"
HEADSET = "Headset (Bluetooth Hands-Free)"


class FakeSounddevice:
    """Enough of sounddevice for selection, with a shiftable device list."""

    def __init__(self, names: list[str]) -> None:
        self._names = names
        self.default = type("D", (), {"device": [0, 1]})()

    def query_devices(self):
        return [
            {
                "name": name,
                "max_input_channels": 2,
                "max_output_channels": 0,
                "default_samplerate": 48_000.0,
                "hostapi": 0,
            }
            for name in self._names
        ]

    def query_hostapis(self, index=None):
        api = {"name": "Windows WASAPI", "devices": list(range(len(self._names)))}
        return api if index is not None else [api]


def _manager(names: list[str], preference) -> MicrophoneDeviceManager:
    manager = MicrophoneDeviceManager(FakeSounddevice(names))
    manager.preference_loader = lambda: preference
    return manager


# --- 1. nothing persists an index -------------------------------------------------


def test_the_preference_writer_stores_a_name_and_never_an_index() -> None:
    from grandpa.jarvis import voice_input

    signature = inspect.signature(voice_input.save_preferred_microphone_name)
    assert "index" not in signature.parameters
    source = inspect.getsource(voice_input.save_preferred_microphone_name)
    for key in (
        "preferred_microphone",
        "preferred_microphone_host_api",
        "preferred_microphone_input_channels",
        "preferred_microphone_sample_rate",
    ):
        assert key in source
    assert "preferred_microphone_index" not in source


def test_the_index_is_only_ever_transient() -> None:
    """Config never reads an index from disk -- only the flag and the env var."""
    from grandpa.voice import config as voice_config

    source = inspect.getsource(voice_config.load_voice_assistant_config)
    assert "_env_int(\"GRANDPA_VOICE_MICROPHONE\")" in source
    # If this ever reads the stored document, a stale index could be persisted.
    assert "preferred_microphone_index" not in inspect.getsource(voice_config)


def test_no_module_writes_a_microphone_index_to_the_config_document() -> None:
    """A guard against the obvious future mistake, across the whole package."""
    from pathlib import Path

    import grandpa

    root = Path(grandpa.__file__).parent
    offenders = []
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "preferred_microphone_index" in text:
            offenders.append(str(path.relative_to(root)))
    assert offenders == [], offenders


# --- 2. and a supplied index is checked against the stored name -------------------


def test_a_requested_index_pointing_elsewhere_warns() -> None:
    """The headset connected, so index 0 is no longer the array."""
    manager = _manager([HEADSET, ARRAY], MicrophoneIdentity(name=ARRAY))

    selection = manager.select(requested_index=0)

    assert selection.device.name == HEADSET, "the explicit request is still honoured"
    assert selection.warning is not None
    assert HEADSET in selection.warning
    assert ARRAY in selection.warning
    assert "shift" in selection.warning


def test_a_requested_index_that_matches_the_preference_is_quiet() -> None:
    manager = _manager([HEADSET, ARRAY], MicrophoneIdentity(name=ARRAY))

    selection = manager.select(requested_index=1)

    assert selection.device.name == ARRAY
    assert selection.warning is None


def test_the_request_is_honoured_not_overridden() -> None:
    """A warning, not a substitution. The user asked for an index."""
    manager = _manager([HEADSET, ARRAY], MicrophoneIdentity(name=ARRAY))

    assert manager.select(requested_index=0).device.index == 0


def test_no_stored_preference_means_no_warning() -> None:
    manager = _manager([HEADSET, ARRAY], None)

    assert manager.select(requested_index=0).warning is None


def test_a_preference_that_cannot_be_read_does_not_break_the_request() -> None:
    manager = MicrophoneDeviceManager(FakeSounddevice([HEADSET, ARRAY]))

    def explode():
        raise RuntimeError("config is unreadable")

    manager.preference_loader = explode

    selection = manager.select(requested_index=0)

    assert selection.device.name == HEADSET
    assert selection.warning is None


def test_the_name_comparison_ignores_case_and_spacing() -> None:
    manager = _manager(
        ["  microphone   array (AMD Audio Device) "], MicrophoneIdentity(name=ARRAY)
    )

    assert manager.select(requested_index=0).warning is None


def test_selecting_by_name_still_follows_the_index_that_name_is_at_now() -> None:
    """The whole reason a name is stored rather than an index."""
    for names, expected_index in (([HEADSET, ARRAY], 1), ([ARRAY, HEADSET], 0)):
        manager = _manager(names, MicrophoneIdentity(name=ARRAY))

        selection = manager.select()

        assert selection.device.name == ARRAY
        assert selection.device.index == expected_index


# --- 3. the warning has somewhere to be seen --------------------------------------


def test_push_to_talk_prints_the_warning_once() -> None:
    from grandpa.voice.push_to_talk import PushToTalkSession

    class Capture:
        last_warning = "Device 9 is 'Headset', not the saved preference 'Array'."
        device = 9

        def capture(self, stop_event=None, on_speech_start=None):
            if stop_event is not None:
                stop_event.wait(timeout=5.0)
            return type(
                "A", (), {"captured_frame_count": 0, "rms_level": 0.0}
            )()

        def close(self) -> None:
            pass

    class Probe:
        def __init__(self) -> None:
            self.script = [True, False, True, False]

        def is_down(self, key: str) -> bool:
            return self.script.pop(0) if self.script else False

    lines: list[str] = []
    calls: list[int] = []

    def clock() -> float:
        calls.append(1)
        return 0.0 if len(calls) == 1 else 3.6

    session = PushToTalkSession(
        capture=Capture(),
        transcriber=type("T", (), {"transcribe": lambda self, a: ""})(),
        probe=Probe(),
        echo=lines.append,
        sleep=lambda _s: None,
        clock=clock,
    )

    session.run_once()

    assert sum(1 for line in lines if "saved preference" in line) == 1, lines
