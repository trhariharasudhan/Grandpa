"""text_to_speech writes audio where it is supposed to, or refuses.

Tier 2: bounded rather than prompted. Generating audio is frequent enough that
a confirmation per call would be unusable -- and an unusable gate gets disabled
or clicked through, which is worse than a bound that holds silently. So the
damage is contained by *where* rather than *whether*: ``output_dir`` may name
Grandpa's own audio directory or a temporary one, and anywhere else is refused
rather than obeyed.

It is reachable unprompted from a saved manifest, which is what makes the
bound matter: without it, a step could write a file of arbitrary bytes to any
path the manifest chose.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from grandpa.tools.text_to_speech import TextToSpeechTool


def _refusal(target: Path):
    return TextToSpeechTool().execute(text="hello", output_dir=str(target))


@pytest.mark.parametrize(
    "relative,why",
    [
        (".ssh", "a credential store"),
        (".grandpa/skills", "the manifest directory"),
        ("Startup", "somewhere a file would be executed"),
    ],
)
def test_an_output_directory_outside_the_bound_is_refused(
    monkeypatch, tmp_path: Path, relative: str, why: str
) -> None:
    monkeypatch.setenv("GRANDPA_HOME", str(tmp_path / "home"))
    elsewhere = tmp_path / "elsewhere" / relative

    result = _refusal(elsewhere)

    assert result.success is False, f"still writes into {why}"
    assert "Refused" in result.content
    assert not elsewhere.exists()


def test_the_audio_directory_is_accepted(monkeypatch, tmp_path: Path) -> None:
    """The bound has to let the intended destination through."""
    home = tmp_path / "home"
    audio = home / "audio"
    audio.mkdir(parents=True)
    monkeypatch.setenv("GRANDPA_HOME", str(home))

    result = _refusal(audio)

    # It gets past the bound. What happens after depends on a TTS backend
    # being available, which is not what this test is about.
    assert "Refused" not in result.content


def test_the_system_temp_tree_is_not_a_permission(monkeypatch, tmp_path: Path) -> None:
    """An earlier version allowed "or a temporary directory", which allowed
    everything: pytest's own tmp_path lives under the system temp tree, and so
    does any scratch directory a caller would name. Not giving output_dir at
    all still uses the tool's own mkdtemp, which never reaches this check."""
    import tempfile

    monkeypatch.setenv("GRANDPA_HOME", str(tmp_path / "home"))

    result = _refusal(Path(tempfile.gettempdir()) / "grandpa-tts-probe")

    assert result.success is False
    assert "Refused" in result.content


def test_the_refusal_names_where_it_would_have_written(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("GRANDPA_HOME", str(tmp_path / "home"))

    result = _refusal(tmp_path / "elsewhere")

    assert "elsewhere" in result.content
    assert "audio" in result.content
