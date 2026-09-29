"""A test may not open the microphone or make the machine talk.

The default-deny guard enumerates the action catalogue, which is what makes it
cover an action nobody thought of. Voice is the hole in that argument: nothing
in the catalogue says "open the microphone" or "speak", so the enumeration
covered none of it, and until this landed a voice test could record from a real
microphone and play audio out loud on the machine running the suite.

The three TTS backends converge on ``sounddevice.play`` for the audible part
(``speech_output._play_audio_bytes``), so denying play covers grandpa_voice and
kokoro as well. pyttsx3 drives SAPI in-process and never reaches sounddevice, so
its engine is denied separately, at ``Engine.say`` and ``Engine.runAndWait``.

Half of these tests exist because the first draft of this guard denied things
that do not actuate, twice:

* ``sounddevice.stop`` and ``sounddevice.wait`` -- stop halts playback and wait
  blocks until it ends. ``SpeechOutputEngine.stop()`` calls ``sd.stop()``
  unconditionally, so ten voice tests failed, including a dry run that had never
  made a sound. A guard that blocks the off switch is not stricter.
* ``pyttsx3.init`` -- it builds the SAPI driver, makes no sound, and is the only
  route to ``getProperty("voices")``. Denying it broke ``grandpa voice diagnose``
  and ``SpeechOutputEngine.diagnostics()``, which is exactly the read path this
  file's own docstring promised to keep working.

So the allowed list is tested as deliberately as the denied one, and the rule
those mistakes produced is written down in ``actuation_guard`` beside the
primitive list: before denying a call, say what it actuates; if the answer is
"it leads to something that actuates", deny that instead, one level down.
"""

from __future__ import annotations

import importlib

import pytest

from tests.actuation_guard import (
    AUDIO_CLASS_NAMES,
    AUDIO_MODULE_NAMES,
    ActuationDenied,
    is_denied,
)

pytestmark = pytest.mark.core


def _module(name: str):
    try:
        return importlib.import_module(name)
    except BaseException:  # noqa: BLE001 - PortAudio failures are not ImportError
        pytest.skip(f"{name} is not importable in this environment")


def test_playing_audio_is_denied() -> None:
    """The speaker: every TTS backend's audible step goes through here."""
    sounddevice = _module("sounddevice")

    with pytest.raises(ActuationDenied) as denied:
        sounddevice.play([0.0] * 16, 16000)

    assert "sounddevice.play" in str(denied.value)


def test_recording_from_the_microphone_is_denied() -> None:
    """The microphone, via the one-shot API jarvis/voice_input.py uses."""
    sounddevice = _module("sounddevice")

    with pytest.raises(ActuationDenied):
        sounddevice.rec(16000, samplerate=16000, channels=1)


def test_opening_an_input_stream_is_denied() -> None:
    """The microphone, via the streaming API voice/microphone.py uses.

    A separate test from ``rec`` on purpose: they are different entry points and
    denying one has never implied the other.
    """
    sounddevice = _module("sounddevice")

    with pytest.raises(ActuationDenied):
        sounddevice.InputStream(samplerate=16000, channels=1)


def test_speaking_with_pyttsx3_is_denied() -> None:
    """Denied at the engine's methods, not at init.

    init() makes no sound and is the only route to getProperty("voices"), which
    `voice diagnose` needs -- so the denial sits on say() and runAndWait().
    """
    engine_module = _module("pyttsx3.engine")

    for method in ("say", "runAndWait"):
        assert is_denied(engine_module.Engine, method), method


def test_initialising_pyttsx3_is_still_allowed() -> None:
    """Reading the installed voices must keep working under the guard.

    Denying ``pyttsx3.init`` looked stricter and broke ``voice diagnose`` and
    ``SpeechOutputEngine.diagnostics()``, both of which enumerate voices through
    an engine instance. A guard that blocks reading is a guard people turn off.
    """
    pyttsx3 = _module("pyttsx3")

    assert not is_denied(pyttsx3, "init")


def test_the_product_speech_path_is_denied() -> None:
    """Not just the library: the function Grandpa actually calls to speak.

    Patching a library is only worth something if the product's own path reaches
    it. This calls ``_speak_with_pyttsx3`` the way ``SpeechOutputEngine`` does.
    """
    from grandpa.voice.speech_output import _speak_with_pyttsx3

    with pytest.raises(ActuationDenied):
        _speak_with_pyttsx3("this must never be audible", voice="", rate=0)


def test_reading_the_device_list_is_still_allowed() -> None:
    """`voice diagnose` enumerates devices, and must keep working under the guard."""
    sounddevice = _module("sounddevice")

    assert not is_denied(sounddevice, "query_devices")


def test_stopping_and_waiting_are_still_allowed() -> None:
    """The off switch is not actuation, and denying it is not strictness.

    ``sd.stop()`` halts playback and ``sd.wait()`` blocks until it ends. Neither
    opens a device or emits a sound. Both were in the deny list for one run, and
    it cost the interrupt path its tests: ``SpeechOutputEngine.stop()`` calls
    ``sd.stop()`` unconditionally, so ten voice tests failed -- including a dry
    run that had never made a sound.

    The rule this encodes: before denying a primitive, say what it actuates. If
    the answer is "it leads to something that actuates", deny that instead.
    """
    sounddevice = _module("sounddevice")

    assert not is_denied(sounddevice, "stop")
    assert not is_denied(sounddevice, "wait")


def test_the_engine_can_still_be_built_and_asked_what_voices_exist() -> None:
    """The product's own read path, end to end, the way diagnostics uses it.

    Asserting on is_denied() only checks the patching. This builds a real engine
    and reads a property from it, which is what `voice diagnose` does to print
    "TTS selected voice" -- and what denying pyttsx3.init broke.
    """
    pyttsx3 = _module("pyttsx3")

    engine = pyttsx3.init()
    try:
        voices = engine.getProperty("voices")
    finally:
        del engine

    assert voices is not None


@pytest.mark.parametrize(
    ("module_name", "class_name"), sorted(AUDIO_CLASS_NAMES), ids=lambda v: str(v)
)
def test_every_declared_audio_class_method_is_denied(
    module_name: str, class_name: str
) -> None:
    """Same drift check as below, for the class-level targets."""
    owner = getattr(_module(module_name), class_name)

    for name in AUDIO_CLASS_NAMES[(module_name, class_name)]:
        assert hasattr(owner, name), (
            f"{class_name} has no {name}; the guard lists it but patches nothing"
        )
        assert is_denied(owner, name), f"{class_name}.{name} is not denied"


@pytest.mark.parametrize("module_name", sorted(AUDIO_MODULE_NAMES))
def test_every_declared_audio_primitive_is_actually_denied(module_name: str) -> None:
    """The declaration and the patching must not drift apart.

    A name added to AUDIO_MODULE_NAMES that the module does not have would be
    skipped silently by ``hasattr``, leaving a primitive listed as covered and
    in fact untouched.
    """
    module = _module(module_name)

    missing = [
        name for name in AUDIO_MODULE_NAMES[module_name] if not hasattr(module, name)
    ]
    assert not missing, (
        f"{module_name} has no {missing}; the guard lists them but patches "
        f"nothing, so they read as covered while they are not"
    )
    for name in AUDIO_MODULE_NAMES[module_name]:
        assert is_denied(module, name), f"{module_name}.{name} is not denied"
