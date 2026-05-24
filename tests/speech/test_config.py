"""Tests for speech configuration."""

from grandpa.core.config import GrandpaConfig, SpeechConfig


def test_speech_config_defaults():
    cfg = SpeechConfig()
    assert cfg.backend == "auto"
    assert cfg.model == "base"
    assert cfg.language == ""
    assert cfg.device == "auto"
    assert cfg.compute_type == "float16"


def test_Grandpa_config_has_speech():
    cfg = GrandpaConfig()
    assert hasattr(cfg, "speech")
    assert isinstance(cfg.speech, SpeechConfig)
    assert cfg.speech.backend == "auto"


def test_Grandpa_system_has_speech_backend():
    """GrandpaSystem has a speech_backend attribute."""
    from grandpa.system import GrandpaSystem

    assert "speech_backend" in GrandpaSystem.__dataclass_fields__
