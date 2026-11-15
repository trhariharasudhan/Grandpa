"""ElevenLabs TTS backend: Grandpa speaks in Captain's own cloned voice.

This is the one *cloud* voice in Grandpa, so it is strictly opt-in and never
the only voice:

* it is used only when an API key is set (``ELEVENLABS_API_KEY`` or
  ``GRANDPA_ELEVENLABS_API_KEY``) -- the key lives in the environment, never in
  the repo or the config file;
* every reply it speaks is sent to ElevenLabs as text, so a user who wants
  everything on the PC simply leaves the key unset (or sets
  ``GRANDPA_AVATAR_VOICE=piper``);
* when the network or the account fails, the avatar falls back to the local
  voices (Piper / MMS Tamil) for that sentence and stops trying the cloud for
  :data:`COOLDOWN_S`, so a dead Wi-Fi costs one timeout, not one per sentence.

Audio is asked for as raw 16-bit PCM (available on every plan) and wrapped into
a WAV here, so the lip-sync code reads it like any other voice.

Settings (all optional except the key):

``GRANDPA_ELEVENLABS_VOICE``        voice id for English / Thanglish replies
``GRANDPA_ELEVENLABS_TAMIL_VOICE``  voice id for Tamil-script replies
                                    (defaults to the English voice)
``GRANDPA_ELEVENLABS_MODEL``        model id, default ``eleven_flash_v2_5``
"""

from __future__ import annotations

import io
import logging
import os
import threading
import time
import wave
from pathlib import Path
from typing import Any, List

from grandpa.core.registry import TTSRegistry
from grandpa.speech.tts import TTSBackend, TTSResult

logger = logging.getLogger(__name__)

API_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
ENV_KEYS = ("GRANDPA_ELEVENLABS_API_KEY", "ELEVENLABS_API_KEY")
ENV_VOICE = "GRANDPA_ELEVENLABS_VOICE"
ENV_TAMIL_VOICE = "GRANDPA_ELEVENLABS_TAMIL_VOICE"
ENV_MODEL = "GRANDPA_ELEVENLABS_MODEL"

DEFAULT_VOICE_ID = "iJwttXBNy3RzWJrkRD97"
""""Achchuu", Captain's instant voice clone. Not a secret: it only works with
his own API key."""
DEFAULT_MODEL = "eleven_flash_v2_5"
"""Lowest latency (~75 ms), half the credits of Multilingual v2, and it speaks
Tamil. ``eleven_multilingual_v2`` sounds a little richer but is slower."""
SAMPLE_RATE = 24_000
OUTPUT_FORMAT = f"pcm_{SAMPLE_RATE}"
TIMEOUT_S = 10.0
COOLDOWN_S = 60.0
"""After a failure, skip the cloud this long and use the local voice."""

VOICE_SETTINGS: dict[str, Any] = {
    "stability": 0.5,
    "similarity_boost": 0.8,
    "style": 0.0,
    "use_speaker_boost": True,
    "speed": 1.0,
}
"""Close to the clone (high similarity), steady but not flat (mid stability)."""

_down_until = 0.0
_down_lock = threading.Lock()


def api_key() -> str:
    for name in ENV_KEYS:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


def voice_id(tamil: bool = False) -> str:
    english = os.environ.get(ENV_VOICE, "").strip() or DEFAULT_VOICE_ID
    if tamil:
        return os.environ.get(ENV_TAMIL_VOICE, "").strip() or english
    return english


_default_voice = voice_id


def model_id() -> str:
    return os.environ.get(ENV_MODEL, "").strip() or DEFAULT_MODEL


def ready() -> bool:
    """True when a key is set and the cloud is not in its cool-down."""
    return bool(api_key()) and time.monotonic() >= _down_until


def mark_down(seconds: float = COOLDOWN_S) -> None:
    global _down_until
    with _down_lock:
        _down_until = time.monotonic() + seconds


def mark_up() -> None:
    global _down_until
    with _down_lock:
        _down_until = 0.0


def synthesize_pcm(
    text: str,
    *,
    voice: str | None = None,
    language: str | None = None,
    model: str | None = None,
    client: Any = None,
) -> bytes:
    """Raw 16-bit mono PCM at :data:`SAMPLE_RATE` for ``text``."""
    key = api_key()
    if not key:
        raise RuntimeError("No ElevenLabs API key (set ELEVENLABS_API_KEY).")
    body: dict[str, Any] = {
        "text": text,
        "model_id": model or model_id(),
        "voice_settings": VOICE_SETTINGS,
    }
    if language:
        body["language_code"] = language
    import httpx

    post = client.post if client is not None else httpx.post
    response = post(
        API_URL.format(voice_id=voice or voice_id()),
        params={"output_format": OUTPUT_FORMAT},
        headers={"xi-api-key": key, "Content-Type": "application/json"},
        json=body,
        timeout=TIMEOUT_S,
    )
    if response.status_code != 200:
        detail = response.text[:200] if hasattr(response, "text") else ""
        raise RuntimeError(f"ElevenLabs said {response.status_code}: {detail}")
    data = response.content
    if not data:
        raise RuntimeError("ElevenLabs returned no audio.")
    return data[: len(data) // 2 * 2]


def pcm_to_wav(pcm: bytes, path: Path | io.BytesIO, rate: int = SAMPLE_RATE) -> None:
    with wave.open(path if isinstance(path, io.BytesIO) else str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(pcm)


def synthesize_wav(
    text: str, path: Path, *, tamil: bool = False, client: Any = None
) -> None:
    """Write ``text`` in the cloned voice to the WAV file ``path``."""
    pcm = synthesize_pcm(
        text,
        voice=voice_id(tamil),
        language="ta" if tamil else None,
        client=client,
    )
    pcm_to_wav(pcm, path)


@TTSRegistry.register("elevenlabs")
class ElevenLabsTTSBackend(TTSBackend):
    """ElevenLabs: cloud TTS in a cloned voice (opt-in, needs an API key)."""

    backend_id = "elevenlabs"

    def synthesize(
        self,
        text: str,
        *,
        voice_id: str = "",
        speed: float = 1.0,
        output_format: str = "wav",
    ) -> TTSResult:
        voice = voice_id or _default_voice()
        pcm = synthesize_pcm(text, voice=voice)
        buf = io.BytesIO()
        pcm_to_wav(pcm, buf)
        frames = len(pcm) // 2
        return TTSResult(
            audio=buf.getvalue(),
            format="wav",
            voice_id=voice,
            sample_rate=SAMPLE_RATE,
            duration_seconds=frames / SAMPLE_RATE,
            metadata={"backend": "elevenlabs", "model": model_id()},
        )

    def available_voices(self) -> List[str]:
        return [_default_voice()]

    def health(self) -> bool:
        return ready()


__all__ = [
    "DEFAULT_MODEL",
    "DEFAULT_VOICE_ID",
    "ElevenLabsTTSBackend",
    "api_key",
    "mark_down",
    "mark_up",
    "model_id",
    "pcm_to_wav",
    "ready",
    "synthesize_pcm",
    "synthesize_wav",
    "voice_id",
]


def main(argv: list[str] | None = None) -> int:
    """``python -m grandpa.speech.elevenlabs_tts "text" [out.wav]``: say one line."""
    import sys

    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print('usage: python -m grandpa.speech.elevenlabs_tts "text" [out.wav]')
        return 2
    if not api_key():
        print("Set ELEVENLABS_API_KEY first (see assets/avatar/README or docs).")
        return 1
    from grandpa.speech.tamil_tts import is_tamil

    out = Path(args[1] if len(args) > 1 else "elevenlabs_sample.wav")
    started = time.perf_counter()
    synthesize_wav(args[0], out, tamil=is_tamil(args[0]))
    print(
        f"saved {out} in {time.perf_counter() - started:.2f}s (voice {voice_id()}, {model_id()})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
