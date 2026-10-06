"""The words a model will not guess belong to the user, not to the source.

"Hari" transcribed as "Harry". That is not a threshold failure -- the decode was
confident and wrong -- and the only mechanism that addresses it is biasing the
decoder with an ``initial_prompt``. The prompt already carried the application
names Grandpa controls, so this is the same mechanism pointed at a second
vocabulary.

It is a setting because the words vary by person. Nobody should edit Python to
add a colleague's name.
"""

from __future__ import annotations

import pytest

from grandpa.speech.faster_whisper import build_transcription_options
from grandpa.speech.vocabulary import (
    APPLICATION_VOCABULARY,
    DEFAULT_USER_VOCABULARY,
    ENV_VARIABLE,
    build_initial_prompt,
    transcription_vocabulary,
    user_vocabulary,
)

pytestmark = pytest.mark.core


@pytest.fixture(autouse=True)
def _no_inherited_vocabulary(monkeypatch):
    monkeypatch.delenv(ENV_VARIABLE, raising=False)


def _write_config(tmp_path, monkeypatch, body: str):
    from grandpa.core import config as core_config

    path = tmp_path / "config.toml"
    path.write_text(body, encoding="utf-8")
    monkeypatch.setattr(core_config, "DEFAULT_CONFIG_PATH", path)
    return path


# --- 1. the name is in the shipped default ----------------------------------------


def test_the_reported_name_is_in_the_prompt() -> None:
    assert "Hari Hara Sudhan" in build_initial_prompt()
    assert "Hari" in DEFAULT_USER_VOCABULARY


def test_the_application_names_are_still_there() -> None:
    """They are needed for routing, so a vocabulary addition must not lose them."""
    prompt = build_initial_prompt()
    for application in APPLICATION_VOCABULARY:
        assert application in prompt, application


def test_the_prompt_is_a_term_list_not_an_instruction() -> None:
    """Whisper treats initial_prompt as preceding text, not a directive.

    Phrasing it as a sentence would bias the decode toward that sentence's
    words, which is the opposite of what is wanted.
    """
    prompt = build_initial_prompt()

    assert prompt.endswith(".")
    assert ", " in prompt
    for instruction_word in ("please", "transcribe", "should", "must"):
        assert instruction_word not in prompt.lower()


def test_it_reaches_the_real_decoding_options() -> None:
    assert build_transcription_options("en")["initial_prompt"] == (
        build_initial_prompt()
    )


# --- 2. the user can extend it -----------------------------------------------------


def test_an_environment_variable_extends_it(monkeypatch) -> None:
    monkeypatch.setenv(ENV_VARIABLE, "Arjun,Tiruchirappalli")

    assert user_vocabulary() == ("Arjun", "Tiruchirappalli")
    prompt = build_initial_prompt()
    assert "Arjun" in prompt and "Tiruchirappalli" in prompt
    assert "Notepad" in prompt, "applications are additive"


def test_config_extends_it(tmp_path, monkeypatch) -> None:
    _write_config(
        tmp_path, monkeypatch, '[voice]\nvocabulary = ["Arjun", "Meenakshi"]\n'
    )

    assert user_vocabulary() == ("Arjun", "Meenakshi")
    assert "Meenakshi" in build_initial_prompt()


def test_the_environment_wins_over_config(tmp_path, monkeypatch) -> None:
    _write_config(tmp_path, monkeypatch, '[voice]\nvocabulary = ["FromConfig"]\n')
    monkeypatch.setenv(ENV_VARIABLE, "FromEnv")

    assert user_vocabulary() == ("FromEnv",)


def test_config_can_replace_the_defaults_outright(tmp_path, monkeypatch) -> None:
    _write_config(
        tmp_path,
        monkeypatch,
        '[voice]\nvocabulary = ["Only", "These"]\n'
        "vocabulary_replaces_defaults = true\n",
    )

    assert transcription_vocabulary() == ("Only", "These")
    assert "Notepad" not in build_initial_prompt()


def test_a_comma_string_in_config_works_too(tmp_path, monkeypatch) -> None:
    """TOML allows a bare string, and a user will write one."""
    _write_config(tmp_path, monkeypatch, '[voice]\nvocabulary = "Arjun, Meenakshi"\n')

    assert user_vocabulary() == ("Arjun", "Meenakshi")


# --- 3. and cannot break speech recognition ----------------------------------------


def test_a_malformed_config_falls_back_rather_than_raising(
    tmp_path, monkeypatch
) -> None:
    """Speech must keep working whatever is in the file."""
    _write_config(tmp_path, monkeypatch, "[voice\nvocabulary = broken")

    assert user_vocabulary() == DEFAULT_USER_VOCABULARY
    assert build_initial_prompt()


def test_a_wrongly_typed_setting_falls_back(tmp_path, monkeypatch) -> None:
    _write_config(tmp_path, monkeypatch, "[voice]\nvocabulary = 42\n")

    assert user_vocabulary() == DEFAULT_USER_VOCABULARY


def test_a_missing_config_file_falls_back(tmp_path, monkeypatch) -> None:
    from grandpa.core import config as core_config

    monkeypatch.setattr(
        core_config, "DEFAULT_CONFIG_PATH", tmp_path / "nothing-here.toml"
    )

    assert user_vocabulary() == DEFAULT_USER_VOCABULARY


def test_an_empty_vocabulary_setting_is_respected(tmp_path, monkeypatch) -> None:
    """Explicitly empty is a choice, distinct from unset."""
    _write_config(tmp_path, monkeypatch, "[voice]\nvocabulary = []\n")

    assert user_vocabulary() == ()
    assert "Hari" not in build_initial_prompt()
    assert "Notepad" in build_initial_prompt()


def test_blanks_and_duplicates_are_cleaned(monkeypatch) -> None:
    monkeypatch.setenv(ENV_VARIABLE, " Arjun , , Arjun ,  arjun ,Meenakshi")

    assert user_vocabulary() == ("Arjun", "Meenakshi")


def test_internal_whitespace_is_normalised(monkeypatch) -> None:
    monkeypatch.setenv(ENV_VARIABLE, "Hari   Hara    Sudhan")

    assert user_vocabulary() == ("Hari Hara Sudhan",)


def test_an_empty_total_vocabulary_gives_an_empty_prompt(
    tmp_path, monkeypatch
) -> None:
    """Not the string 'None', which Whisper would try to transcribe toward."""
    _write_config(
        tmp_path,
        monkeypatch,
        "[voice]\nvocabulary = []\nvocabulary_replaces_defaults = true\n",
    )

    assert build_initial_prompt() == ""
