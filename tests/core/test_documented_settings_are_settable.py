"""Every setting the documentation tells you to put in config.toml must be
settable by ``grandpa config set``.

Reported: ``grandpa config set voice.vocabulary "..."`` answered "Unknown
config key", while an earlier round had reported the setting as
``[voice] vocabulary`` in config.toml. Both halves were true at once -- that is
the fault this file exists to catch.

``config set`` validates against ``_SETTABLE_SECTIONS``, which is
``GrandpaConfig``'s dataclass fields. ``[voice]`` was read by parsing the raw
TOML, so the reader found the value and nothing could write it. Three settings
shared that: ``voice.vocabulary``, ``voice.vocabulary_replaces_defaults`` and
``voice.preferred_microphone``.

The sweep below found three more of the same shape, each for a different
reason:

    security.enforce_tool_confirmation   a REMOVED_CONFIG_KEYS entry still
    security.ssrf_protection             advertised by the sample config in the
                                         very file that removes it
    scheduler.default_agent              documented under the wrong section;
                                         the real key is agent.default_agent

A removed key failing this test is the point, not an inconvenience: a security
option that looks configurable and does nothing is worse than no option, which
is why it was removed -- so it must not survive in a sample either.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import grandpa
from grandpa.core.config import REMOVED_CONFIG_KEYS, validate_config_key

pytestmark = pytest.mark.core

_ROOT = Path(grandpa.__file__).parents[2]

#: A ``[section]`` line on its own.
_SECTION = re.compile(r"^\s*\[([a-z_][a-z0-9_]*)\]\s*$")
#: A ``key = value`` line under one.
_ASSIGN = re.compile(r"^\s*([a-z_][a-z0-9_]*)\s*=\s*\S")


def _documented_settings() -> dict[str, set[str]]:
    """Every ``[section] key`` shown by a file that promises ``config.toml``.

    Scoped to files mentioning config.toml on purpose. Without that scope the
    sweep also matches skill manifests, workflow schemas and page-reader
    dictionaries -- TOML-shaped blocks that are not configuration, which made
    the first version of this unusable.
    """
    targets = (
        [_ROOT / "README.md"]
        + [p for p in (_ROOT / "docs").rglob("*.md") if "__pycache__" not in str(p)]
        + [p for p in (_ROOT / "src").rglob("*.py") if "__pycache__" not in str(p)]
    )
    found: dict[str, set[str]] = {}
    for path in sorted(targets):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "config.toml" not in text:
            continue
        section: str | None = None
        for line in text.splitlines():
            heading = _SECTION.match(line)
            if heading:
                section = heading.group(1)
                continue
            if section is None:
                continue
            assignment = _ASSIGN.match(line)
            if assignment:
                key = f"{section}.{assignment.group(1)}"
                found.setdefault(key, set()).add(
                    path.relative_to(_ROOT).as_posix()
                )
            elif line.strip() and not line.startswith((" ", "\t", "#")):
                section = None
    return found


# --- the sweep -------------------------------------------------------------------


def test_the_sweep_finds_something_to_check() -> None:
    """Guards the guard: a broken scan would pass everything silently."""
    found = _documented_settings()

    assert len(found) > 20, f"only found {len(found)} documented settings"
    assert "speech.model" in found, "a known documented setting was missed"


def test_every_documented_setting_is_settable() -> None:
    """The test the reported bug asked for."""
    unsettable: list[str] = []
    for key, where in sorted(_documented_settings().items()):
        try:
            validate_config_key(key)
        except ValueError:
            unsettable.append(f"{key} (in {', '.join(sorted(where))})")

    assert not unsettable, "documented for config.toml but `config set` refuses:\n  " + (
        "\n  ".join(unsettable)
    )


def test_no_removed_key_is_still_advertised() -> None:
    """Two security options that do nothing were still in the sample config.

    They were removed *because* they do nothing, so a sample that teaches them
    undoes the removal: a user copying it gets a warning about a key the sample
    told them to set.
    """
    documented = _documented_settings()
    resurrected = sorted(set(documented) & set(REMOVED_CONFIG_KEYS))

    assert not resurrected, (
        "removed config keys are still shown as settings: "
        + ", ".join(f"{key} (in {', '.join(sorted(documented[key]))})" for key in resurrected)
    )


# --- the reported setting, directly ----------------------------------------------


@pytest.mark.parametrize(
    "key",
    [
        "voice.vocabulary",
        "voice.vocabulary_replaces_defaults",
        "voice.preferred_microphone",
    ],
)
def test_the_voice_section_is_settable(key: str) -> None:
    """All three, not just the reported one. They shared one cause."""
    validate_config_key(key)


def _set_and_point_reader(monkeypatch, tmp_path, pairs) -> None:
    """Run `config set` for each pair, then aim the reader at the same file.

    The path is read from ``_get_config_path``, the helper the command itself
    uses, rather than guessed: conftest rebinds ``DEFAULT_CONFIG_PATH`` at
    import and guessing made the test fail for reasons unrelated to the fix.
    """
    from click.testing import CliRunner

    from grandpa.cli import cli
    from grandpa.cli.config_cmd import _get_config_path
    from grandpa.core import config as core_config

    # Both: _get_config_path resolves the read path from DEFAULT_CONFIG_PATH
    # while the writer builds its own from DEFAULT_CONFIG_DIR, so patching one
    # made config set report success and write somewhere else entirely.
    monkeypatch.setattr(core_config, "DEFAULT_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(core_config, "DEFAULT_CONFIG_PATH", tmp_path / "config.toml")
    written = _get_config_path(None)

    runner = CliRunner()
    for key, value in pairs:
        result = runner.invoke(cli, ["config", "set", key, value])
        assert result.exit_code == 0, result.output

    assert written.exists(), f"config set wrote nothing to {written}"
    monkeypatch.setattr(core_config, "DEFAULT_CONFIG_PATH", written)


def test_setting_the_vocabulary_reaches_the_decoder(tmp_path, monkeypatch) -> None:
    """The round trip, which is the only thing that proves the fix.

    The config half always worked -- hand-writing the section reached the
    decoder prompt. What failed was writing it with the obvious command.
    """
    monkeypatch.setenv("GRANDPA_HOME", str(tmp_path))
    monkeypatch.delenv("GRANDPA_VOICE_VOCABULARY", raising=False)

    _set_and_point_reader(
        monkeypatch, tmp_path,
        [("voice.vocabulary", "Grandpa, Notepad, Arjun")],
    )

    from grandpa.speech import vocabulary

    assert vocabulary.user_vocabulary() == ("Grandpa", "Notepad", "Arjun")
    prompt = vocabulary.build_initial_prompt()
    assert "Grandpa" in prompt and "Arjun" in prompt


def test_the_replaces_flag_drops_the_shipped_names(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GRANDPA_HOME", str(tmp_path))
    monkeypatch.delenv("GRANDPA_VOICE_VOCABULARY", raising=False)

    _set_and_point_reader(
        monkeypatch, tmp_path,
        [
            ("voice.vocabulary", "Grandpa, Arjun"),
            ("voice.vocabulary_replaces_defaults", "true"),
        ],
    )

    from grandpa.speech import vocabulary

    assert vocabulary.build_initial_prompt() == "Grandpa, Arjun."


def test_the_env_var_still_wins(tmp_path, monkeypatch) -> None:
    """Documented precedence, and the only route that worked before."""
    monkeypatch.setenv("GRANDPA_HOME", str(tmp_path))
    monkeypatch.setenv("GRANDPA_VOICE_VOCABULARY", "FromEnv,Only")

    from grandpa.speech import vocabulary

    assert vocabulary.user_vocabulary() == ("FromEnv", "Only")
