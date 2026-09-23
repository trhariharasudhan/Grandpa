"""A manifest that cannot say who wrote it does not load by itself.

``SkillManager.discover()`` loaded every ``*.toml`` under
``~/.grandpa/skills/``. A manifest is deferred execution -- its steps name
tools, and ``SkillExecutor`` sends each through ``ToolExecutor`` when the skill
is invoked -- and ``skill_manage`` is a model-facing tool that writes exactly
those files. Gating ``skill_manage`` closed the front door; this closes the
one where a file simply appears in the directory.

The rule is deliberately blunt: trusted means the file says ``provenance =
"user"`` (or ``"bundled"``, for manifests reviewed in the repository).
Everything else -- written by a model, written by an agent, or saying nothing
at all -- needs someone to agree. "Says nothing" has to be untrusted, because
otherwise omitting the line is how you become trusted.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from grandpa.skills.manager import SkillManager

MODEL_WRITTEN = """[skill]
name = "exfiltrate"
provenance = "model"

[[skill.steps]]
tool_name = "file_write"
arguments_template = '{"path": "x", "content": "y"}'
"""

HAND_WRITTEN = """[skill]
name = "my-own-routine"

[[skill.steps]]
tool_name = "think"
"""

VOUCHED_FOR = """[skill]
name = "vetted"
provenance = "user"

[[skill.steps]]
tool_name = "think"
"""


@pytest.fixture
def skills_dir(tmp_path: Path) -> Path:
    (tmp_path / "exfiltrate.toml").write_text(MODEL_WRITTEN, encoding="utf-8")
    (tmp_path / "mine.toml").write_text(HAND_WRITTEN, encoding="utf-8")
    (tmp_path / "vetted.toml").write_text(VOUCHED_FOR, encoding="utf-8")
    return tmp_path


def test_a_model_written_manifest_does_not_load_unasked(skills_dir: Path) -> None:
    manager = SkillManager(None)

    manager.discover(paths=[skills_dir])

    assert "exfiltrate" not in manager.skill_names()
    assert any("exfiltrate" in reason for reason in manager.skipped)


def test_a_manifest_with_no_provenance_does_not_load_unasked(
    skills_dir: Path,
) -> None:
    manager = SkillManager(None)

    manager.discover(paths=[skills_dir])

    assert "my-own-routine" not in manager.skill_names()


def test_a_manifest_that_says_a_person_wrote_it_loads(skills_dir: Path) -> None:
    manager = SkillManager(None)

    manager.discover(paths=[skills_dir])

    assert "vetted" in manager.skill_names()


def test_the_refusal_says_what_to_do_about_it(skills_dir: Path) -> None:
    """A hand-written manifest is the case that costs a real person something.

    So the message has to name the fix rather than just refuse.
    """
    manager = SkillManager(None)

    manager.discover(paths=[skills_dir])

    hand_written = next(r for r in manager.skipped if "my-own-routine" in r)
    assert 'provenance = "user"' in hand_written
    assert "does not say who wrote it" in hand_written


def test_agreeing_loads_it_and_the_prompt_names_the_steps(skills_dir: Path) -> None:
    asked: list[str] = []
    manager = SkillManager(None)

    manager.discover(
        paths=[skills_dir], confirm=lambda prompt, _p: asked.append(prompt) or True
    )

    assert "exfiltrate" in manager.skill_names()
    prompt = next(p for p in asked if "exfiltrate" in p)
    assert "written by a model" in prompt
    assert "file_write" in prompt, "the prompt must say what it will be able to run"


def test_declining_leaves_it_alone(skills_dir: Path) -> None:
    manager = SkillManager(None)

    manager.discover(paths=[skills_dir], confirm=lambda *_: False)

    assert "exfiltrate" not in manager.skill_names()
    assert "my-own-routine" not in manager.skill_names()
    assert "vetted" in manager.skill_names(), "a vouched-for skill is never asked about"


def test_skill_manage_records_what_wrote_the_file(tmp_path: Path) -> None:
    """The tool cannot claim to be a person."""
    from grandpa.tools.skill_manage import SkillManageTool

    SkillManageTool(skills_dir=tmp_path).execute(
        action="create", name="written-by-a-model", steps=[{"tool_name": "think"}]
    )

    written = (tmp_path / "written-by-a-model.toml").read_text(encoding="utf-8")
    assert 'provenance = "model"' in written

    manager = SkillManager(None)
    manager.discover(paths=[tmp_path])
    assert "written-by-a-model" not in manager.skill_names()
