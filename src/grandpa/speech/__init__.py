"""Speech subsystem — speech-to-text and text-to-speech backends."""

import importlib

# Local STT backend.
for _mod in ("faster_whisper",):
    try:
        importlib.import_module(f".{_mod}", __name__)
    except ImportError:
        pass

# Optional local TTS backend.
for _mod in ("kokoro_tts", "grandpa_voice_tts"):
    try:
        importlib.import_module(f".{_mod}", __name__)
    except ImportError:
        pass
