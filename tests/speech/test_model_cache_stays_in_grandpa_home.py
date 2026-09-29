"""A downloaded model lands inside GRANDPA_HOME, not in the user's home cache.

``WhisperModel(...)`` built without ``download_root`` falls back to the
huggingface_hub default under ``~/.cache/huggingface``. That is outside
``GRANDPA_HOME``, so a first transcription puts a several-hundred-megabyte
download in a real user directory -- and in the suite it left the write guard as
the only thing in the way, which is exactly the guard a ``real_writes`` marker
exists to lift.

``voice_service._load_f5_model`` had the same shape: ``hf_cache_dir=cache_dir or
None``, so an unset ``GRANDPA_VOICE_MODEL_CACHE`` meant the same fallback for a
model of the same order of size.

Both now derive a default from ``GRANDPA_HOME``, read at call time rather than at
import -- see the note on ``config._in_config_dir`` for why that distinction
matters. These tests pin the location and the lateness of the read.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from grandpa.speech.faster_whisper import model_cache_dir

pytestmark = pytest.mark.core


def test_the_whisper_cache_is_inside_grandpa_home(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("GRANDPA_HOME", str(tmp_path / "home"))

    cache = Path(model_cache_dir())

    assert cache.is_relative_to(tmp_path / "home"), cache


def test_the_whisper_cache_follows_a_later_grandpa_home(monkeypatch, tmp_path) -> None:
    """The value must be read when it is used, not captured at import.

    An import-time constant is evaluated before anything has set GRANDPA_HOME,
    which is how six config defaults once wrote into a real home directory.
    """
    monkeypatch.setenv("GRANDPA_HOME", str(tmp_path / "first"))
    first = Path(model_cache_dir())
    monkeypatch.setenv("GRANDPA_HOME", str(tmp_path / "second"))
    second = Path(model_cache_dir())

    assert first != second
    assert second.is_relative_to(tmp_path / "second")


def test_the_whisper_cache_is_never_the_huggingface_default(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("GRANDPA_HOME", str(tmp_path / "home"))

    cache = Path(model_cache_dir())

    assert ".cache" not in cache.parts
    assert "huggingface" not in cache.parts


def test_whisper_is_built_with_a_download_root(monkeypatch, tmp_path) -> None:
    """The product path, not just the helper.

    A helper nobody passes to WhisperModel would still leave the download in the
    user's cache, so this asserts on the call the backend actually makes.
    """
    monkeypatch.setenv("GRANDPA_HOME", str(tmp_path / "home"))
    from grandpa.speech import faster_whisper as backend_module

    captured: dict[str, object] = {}

    class _FakeModel:
        def __init__(self, model_size, **kwargs):
            captured["model_size"] = model_size
            captured.update(kwargs)

    monkeypatch.setattr(backend_module, "WhisperModel", _FakeModel)
    backend = backend_module.FasterWhisperBackend(model_size="base")

    backend._ensure_model()

    assert "download_root" in captured, (
        "WhisperModel was built without download_root, so the weights go to the "
        "huggingface_hub default under the user's home cache"
    )
    assert Path(str(captured["download_root"])).is_relative_to(tmp_path / "home")


def test_the_f5_cache_default_is_inside_grandpa_home(monkeypatch, tmp_path) -> None:
    """The voice sidecar's model cache, which had the identical defect."""
    monkeypatch.setenv("GRANDPA_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("GRANDPA_VOICE_MODEL_CACHE", raising=False)
    from grandpa.voice_service import service

    captured: dict[str, object] = {}

    class _FakeF5:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    fake_api = type("_Module", (), {"F5TTS": _FakeF5})
    monkeypatch.setitem(
        __import__("sys").modules, "f5_tts", type("_Pkg", (), {"api": fake_api})
    )
    monkeypatch.setitem(__import__("sys").modules, "f5_tts.api", fake_api)

    service._load_f5_model()

    assert captured["hf_cache_dir"] is not None, (
        "hf_cache_dir=None sends the download to the huggingface_hub default"
    )
    assert Path(str(captured["hf_cache_dir"])).is_relative_to(tmp_path / "home")


def test_an_explicit_f5_cache_still_wins(monkeypatch, tmp_path) -> None:
    """Someone who set the variable chose that location; the default must not override it."""
    monkeypatch.setenv("GRANDPA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("GRANDPA_VOICE_MODEL_CACHE", str(tmp_path / "chosen"))
    from grandpa.voice_service import service

    captured: dict[str, object] = {}

    class _FakeF5:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    fake_api = type("_Module", (), {"F5TTS": _FakeF5})
    monkeypatch.setitem(
        __import__("sys").modules, "f5_tts", type("_Pkg", (), {"api": fake_api})
    )
    monkeypatch.setitem(__import__("sys").modules, "f5_tts.api", fake_api)

    service._load_f5_model()

    assert captured["hf_cache_dir"] == str(tmp_path / "chosen")
