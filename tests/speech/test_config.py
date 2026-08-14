"""Tests for speech configuration."""

from grandpa.core.config import GrandpaConfig, SpeechConfig, load_config


def test_speech_config_defaults():
    cfg = SpeechConfig()
    assert cfg.backend == "auto"
    assert cfg.model == "base"
    assert cfg.language == ""
    assert cfg.device == "auto"
    assert cfg.compute_type == "auto"


def test_Grandpa_config_has_speech():
    cfg = GrandpaConfig()
    assert hasattr(cfg, "speech")
    assert isinstance(cfg.speech, SpeechConfig)
    assert cfg.speech.backend == "auto"


def test_Grandpa_system_has_speech_backend():
    """GrandpaSystem has a speech_backend attribute."""
    from grandpa.system import GrandpaSystem

    assert "speech_backend" in GrandpaSystem.__dataclass_fields__


def test_tts_config_defaults():
    cfg = GrandpaConfig()
    assert hasattr(cfg, "tts")
    assert cfg.tts.backend == "kokoro"


def test_grandpa_voice_config_defaults():
    cfg = GrandpaConfig()
    assert hasattr(cfg, "grandpa_voice")
    assert cfg.grandpa_voice.engine == "f5"
    assert cfg.grandpa_voice.device == "cpu"
    assert cfg.grandpa_voice.voice_id == "grandpa"
    assert cfg.grandpa_voice.service_url == "http://127.0.0.1:8765"
    assert cfg.grandpa_voice.synthesis_timeout_seconds == 600.0
    assert cfg.grandpa_voice.nfe_step == 8
    assert cfg.grandpa_voice.cpu_threads == 4
    assert cfg.grandpa_voice.cfg_strength == 0.0
    assert cfg.grandpa_voice.character_voice is True
    assert cfg.grandpa_voice.pitch_semitones == -2.0
    assert cfg.grandpa_voice.character_speed == 0.92
    assert cfg.grandpa_voice.target_lufs == -14.5
    assert cfg.grandpa_voice.true_peak_db == -1.0
    assert cfg.grandpa_voice.compression is True
    assert cfg.grandpa_voice.eq_profile == "grandpa_deep_clear"
    assert cfg.grandpa_voice.runtime_python == ""
    assert cfg.grandpa_voice.model_cache == ""


def test_voice_configuration_loads_from_toml(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[tts]
backend = "grandpa_voice"
enabled = false

[grandpa_voice]
engine = "f5"
device = "cpu"
voice_id = "grandpa"
reference_audio = ""
reference_text = "Local reference"
service_url = "http://127.0.0.1:9876"
synthesis_timeout_seconds = 720.0
nfe_step = 12
cpu_threads = 2
cfg_strength = 1.5
character_voice = false
pitch_semitones = -3.0
character_speed = 0.88
target_lufs = -14.0
true_peak_db = -1.5
compression = false
eq_profile = "grandpa_deep"
runtime_python = "D:/Grandpa/voice_runtime/.venv/Scripts/python.exe"
model_cache = "D:/Grandpa/voice_runtime/models_or_cache/huggingface/hub"
""".strip(),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.tts.backend == "grandpa_voice"
    assert config.tts.enabled is False
    assert config.grandpa_voice.engine == "f5"
    assert config.grandpa_voice.device == "cpu"
    assert config.grandpa_voice.voice_id == "grandpa"
    assert config.grandpa_voice.reference_audio == ""
    assert config.grandpa_voice.reference_text == "Local reference"
    assert config.grandpa_voice.service_url == "http://127.0.0.1:9876"
    assert config.grandpa_voice.synthesis_timeout_seconds == 720.0
    assert config.grandpa_voice.nfe_step == 12
    assert config.grandpa_voice.cpu_threads == 2
    assert config.grandpa_voice.cfg_strength == 1.5
    assert config.grandpa_voice.character_voice is False
    assert config.grandpa_voice.pitch_semitones == -3.0
    assert config.grandpa_voice.character_speed == 0.88
    assert config.grandpa_voice.target_lufs == -14.0
    assert config.grandpa_voice.true_peak_db == -1.5
    assert config.grandpa_voice.compression is False
    assert config.grandpa_voice.eq_profile == "grandpa_deep"
    assert config.grandpa_voice.runtime_python.endswith("Scripts/python.exe")
    assert config.grandpa_voice.model_cache.endswith("huggingface/hub")


def test_old_config_without_voice_sections_remains_compatible(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text('[engine]\ndefault = "ollama"\n', encoding="utf-8")

    config = load_config(config_path)

    assert config.tts.backend == "kokoro"
    assert config.tts.enabled is True
    assert config.grandpa_voice.service_url == "http://127.0.0.1:8765"
    assert config.grandpa_voice.synthesis_timeout_seconds == 600.0
    assert config.grandpa_voice.nfe_step == 8
    assert config.grandpa_voice.cpu_threads == 4
    assert config.grandpa_voice.cfg_strength == 0.0
    assert config.grandpa_voice.character_voice is True
    assert config.grandpa_voice.eq_profile == "grandpa_deep_clear"


def test_presence_profile_loads_from_toml(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "[grandpa_voice]\n"
        'eq_profile = "grandpa_presence"\n'
        "pitch_semitones = 0.0\n"
        "character_speed = 1.0\n",
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.grandpa_voice.eq_profile == "grandpa_presence"
    assert config.grandpa_voice.pitch_semitones == 0.0
    assert config.grandpa_voice.character_speed == 1.0
