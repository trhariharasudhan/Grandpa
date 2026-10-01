"""An expected failure must print a sentence, not a stack trace.

A live run of ``grandpa voice push-to-talk`` ended in this:

    Traceback (most recent call last):
      ...
    speech_input.py:220   raise VoiceRecognitionError(
                            "No speech was detected in the audio.")

Auditing all eleven voice entry points by patching the helper each one calls to
raise, seven let a ``VoiceError`` escape and two reported success on a failure:

    voice doctor              TRACEBACK
    voice diagnose            TRACEBACK
    voice test                TRACEBACK
    voice set-device          TRACEBACK
    voice microphone-test     TRACEBACK
    voice push-to-talk        TRACEBACK
    voice --list-voices       TRACEBACK
    voice --diagnose          TRACEBACK
    voice devices             message printed, exit 0
    voice --list-microphones  message printed, exit 0
    voice (group)             handled

``set-device`` and ``microphone-test`` each *have* an ``except VoiceError``;
they call ``import_sounddevice()`` on the line before the ``try``, outside it.
That is why the fix is one decorator rather than more try blocks: the placement
is what went wrong, and a decorator cannot be placed wrongly.

Exit 0 on a failure is the quieter half of the same bug -- a script cannot tell
that nothing was listed because the dependency is missing.
"""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from grandpa.cli import voice_cmd
from grandpa.voice.errors import (
    VoiceDependencyError,
    VoiceOutputUnavailableError,
    VoiceRecognitionError,
)

pytestmark = pytest.mark.core


def _dependency(*_args, **_kwargs):
    raise VoiceDependencyError()


def _recognition(*_args, **_kwargs):
    raise VoiceRecognitionError()


def _output(*_args, **_kwargs):
    raise VoiceOutputUnavailableError()


#: (label, argv, attribute to break, replacement)
ENTRY_POINTS = [
    ("doctor", ["doctor"], "run_voice_doctor", _dependency),
    ("diagnose", ["diagnose"], "run_voice_doctor", _dependency),
    ("devices", ["devices"], "list_input_devices", _dependency),
    ("test", ["test", "--dry-run"], "SpeechOutputEngine", _output),
    ("set-device", ["set-device", "x"], "import_sounddevice", _dependency),
    (
        "microphone-test",
        ["microphone-test", "--no-playback"],
        "import_sounddevice",
        _dependency,
    ),
    (
        "push-to-talk",
        ["push-to-talk", "--once"],
        "FasterWhisperSpeechToText",
        _recognition,
    ),
    ("group", [], "build_voice_session", _dependency),
    ("--list-microphones", ["--list-microphones"], "list_input_devices", _dependency),
    ("--list-voices", ["--list-voices"], "list_system_voices", _dependency),
    ("--diagnose", ["--diagnose"], "run_voice_doctor", _dependency),
]


def _invoke(monkeypatch, argv, attribute, replacement):
    assert hasattr(voice_cmd, attribute), attribute
    monkeypatch.setattr(voice_cmd, attribute, replacement)
    return CliRunner().invoke(voice_cmd.voice, argv, catch_exceptions=True)


@pytest.mark.parametrize(
    ("label", "argv", "attribute", "replacement"),
    ENTRY_POINTS,
    ids=[case[0] for case in ENTRY_POINTS],
)
def test_no_voice_command_lets_a_domain_error_reach_a_traceback(
    monkeypatch, label, argv, attribute, replacement
) -> None:
    result = _invoke(monkeypatch, argv, attribute, replacement)

    leaked = result.exception is not None and not isinstance(
        result.exception, SystemExit
    )
    assert not leaked, (
        f"{label} leaked {type(result.exception).__name__} to the top level, "
        f"which click prints as a stack trace"
    )


@pytest.mark.parametrize(
    ("label", "argv", "attribute", "replacement"),
    ENTRY_POINTS,
    ids=[case[0] for case in ENTRY_POINTS],
)
def test_every_voice_command_reports_failure_in_its_exit_code(
    monkeypatch, label, argv, attribute, replacement
) -> None:
    """Two of these used to print the message and exit 0."""
    result = _invoke(monkeypatch, argv, attribute, replacement)

    assert result.exit_code != 0, f"{label} reported success on a failure"


@pytest.mark.parametrize(
    ("label", "argv", "attribute", "replacement"),
    ENTRY_POINTS,
    ids=[case[0] for case in ENTRY_POINTS],
)
def test_every_voice_command_says_something_the_user_can_act_on(
    monkeypatch, label, argv, attribute, replacement
) -> None:
    result = _invoke(monkeypatch, argv, attribute, replacement)

    text = (result.output or "") + (result.stderr or "" if result.stderr_bytes else "")
    assert text.strip(), f"{label} failed silently"
    assert "Traceback" not in text, f"{label} printed a traceback into its output"


def test_the_guard_is_on_every_command_in_the_group() -> None:
    """A command added later must not reintroduce this.

    Checked by name on the wrapped callback rather than by behaviour, so a new
    command missing the decorator fails here instead of in a live run.
    """
    undecorated = [
        name
        for name, command in voice_cmd.voice.commands.items()
        if getattr(command.callback, "__wrapped__", None) is None
    ]

    assert undecorated == [], (
        f"these voice commands lack @handles_voice_errors: {undecorated}"
    )


def test_the_group_itself_is_guarded_too() -> None:
    assert getattr(voice_cmd.voice.callback, "__wrapped__", None) is not None
