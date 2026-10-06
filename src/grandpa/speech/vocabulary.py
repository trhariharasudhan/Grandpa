"""Words Whisper will not guess, supplied by the user.

Whisper decodes what it has heard before. "Hari" is not a common English token
and the model lands on "Harry", which is a plausible English name and a wrong
one. No threshold fixes that -- the decode was confident, just wrong.

An ``initial_prompt`` biases the decoder toward spellings it would otherwise
rank lower. The prompt already carried the application names Grandpa controls
("Notepad", "Chrome", ...), which is the same mechanism applied to a different
vocabulary, and names are the case where it matters most: an application name
guessed wrongly fails visibly, a person's name guessed wrongly looks correct.

This is a setting rather than a constant because the words a model will not know
are specific to the person using it. Nobody should have to edit Python to add a
colleague, a place, or a product name.

Configure it in ``~/.grandpa/config.toml``::

    [voice]
    vocabulary = ["Hari Hara Sudhan", "Arjun", "Tiruchirappalli"]

or for one run::

    GRANDPA_VOICE_VOCABULARY="Hari Hara Sudhan,Arjun"

Both are additive to the application names, which are needed for the commands to
route at all. Set ``vocabulary_replaces_defaults = true`` to drop them.
"""

from __future__ import annotations

import os

#: Applications Grandpa can act on. Needed for routing, so these stay unless
#: explicitly replaced.
APPLICATION_VOCABULARY: tuple[str, ...] = (
    "Grandpa",
    "Notepad",
    "Chrome",
    "Calculator",
    "VS Code",
    "Explorer",
    "Settings",
    "Terminal",
)

#: Shipped so the tool works out of the box for the person it was built for.
#: "Hari" transcribed as "Harry" on this machine; the full name is included
#: because Whisper conditions on sequences, so the surname helps the given name.
DEFAULT_USER_VOCABULARY: tuple[str, ...] = ("Hari Hara Sudhan", "Hari")

ENV_VARIABLE = "GRANDPA_VOICE_VOCABULARY"


def _from_environment() -> tuple[str, ...] | None:
    raw = os.getenv(ENV_VARIABLE)
    if raw is None:
        return None
    return _clean(raw.split(","))


def _from_config() -> tuple[tuple[str, ...] | None, bool]:
    """Read ``[voice] vocabulary`` without letting a bad config break speech.

    Reads the TOML directly, the same way ``preferred_microphone`` is read:
    ``[voice]`` is not a section of the typed core ``Config``, so there is no
    dataclass field to go through. Any failure falls back to the default, because
    a malformed config must not stop speech recognition from working at all.
    """
    try:
        import tomllib

        from grandpa.core import config as core_config

        config_path = core_config.DEFAULT_CONFIG_PATH
        if not config_path.exists():
            return None, False
        data = tomllib.loads(config_path.read_text(encoding="utf-8"))
        voice_section = data.get("voice") if isinstance(data, dict) else None
        if not isinstance(voice_section, dict):
            return None, False
        replaces = bool(voice_section.get("vocabulary_replaces_defaults", False))
        words = voice_section.get("vocabulary")
        if words is None:
            return None, replaces
        if isinstance(words, str):
            words = words.split(",")
        if not isinstance(words, (list, tuple)):
            return None, replaces
        return _clean(words), replaces
    except Exception:
        return None, False


def _clean(words) -> tuple[str, ...]:
    """Trim, drop blanks, and keep first-seen order without duplicates."""
    seen: dict[str, None] = {}
    for word in words:
        text = " ".join(str(word).split())
        if text and text.casefold() not in {key.casefold() for key in seen}:
            seen[text] = None
    return tuple(seen)


def user_vocabulary() -> tuple[str, ...]:
    """The user's own words: the env var, else config, else the shipped default."""
    from_env = _from_environment()
    if from_env is not None:
        return from_env
    from_config, _ = _from_config()
    if from_config is not None:
        return from_config
    return DEFAULT_USER_VOCABULARY


def transcription_vocabulary() -> tuple[str, ...]:
    """Everything the decoder should be biased toward, applications first."""
    _, replaces = _from_config()
    words = user_vocabulary()
    if replaces:
        return words
    return _clean(APPLICATION_VOCABULARY + words)


def build_initial_prompt(vocabulary: tuple[str, ...] | None = None) -> str:
    """The ``initial_prompt`` string handed to Whisper.

    A comma-separated list ending in a full stop, which is the shape the prompt
    already had. Whisper treats it as preceding text, so it is a list of terms
    rather than an instruction -- phrasing it as a sentence would bias the
    decoder toward that sentence's words instead.
    """
    words = transcription_vocabulary() if vocabulary is None else _clean(vocabulary)
    if not words:
        return ""
    return ", ".join(words) + "."


__all__ = [
    "APPLICATION_VOCABULARY",
    "DEFAULT_USER_VOCABULARY",
    "ENV_VARIABLE",
    "build_initial_prompt",
    "transcription_vocabulary",
    "user_vocabulary",
]
