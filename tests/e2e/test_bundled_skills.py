"""The skills that ship with Grandpa, through the real CLI.

`skill list` reported "No skills installed" on a clean install while eighteen
manifests sat inside the package. Three separate bugs produced that, and each
hid the next, so the only evidence worth having is the CLI's own output.

The unit tests in tests/skills/test_bundled_skills.py pin the mechanics. These
pin what a person sees.
"""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.e2e]


@pytest.mark.real_actions(reason="reaches the real subprocess.Popen")
def test_skill_list_shows_the_bundled_skills(cli) -> None:
    listed = cli("skill", "list")

    assert listed.returncode == 0, listed.text
    assert "No skills installed" not in listed.text
    # Two of the eighteen, named rather than counted: a count would pass on any
    # eighteen skills, including the wrong ones.
    assert "email-draft" in listed.text
    assert "web-summarize" in listed.text


@pytest.mark.real_actions(reason="reaches the real subprocess.Popen")
def test_skill_info_reads_one(cli) -> None:
    info = cli("skill", "info", "email-draft")

    assert info.returncode == 0, info.text
    assert "email-draft" in info.text


@pytest.mark.real_actions(reason="reaches the real subprocess.Popen")
def test_skill_run_executes_one(cli) -> None:
    """email-draft is three `think` steps, so it needs no model and no network.

    A skill that loads but cannot run is not fixed, which is why this asserts
    on the run rather than on the listing.
    """
    ran = cli(
        "skill",
        "run",
        "email-draft",
        "-a",
        "recipient=Ana",
        "-a",
        "intent=thank her for the review",
        "-a",
        "context=the audit",
    )

    assert ran.returncode == 0, ran.text
    assert "Success" in ran.text
    # The last step's output carries the arguments through, which is the
    # evidence that the template was filled rather than passed through raw.
    assert "Ana" in ran.text


@pytest.mark.real_actions(reason="reaches the real subprocess.Popen")
def test_a_skill_that_reads_a_file_gets_a_usable_path(cli) -> None:
    """The bug that made every file-taking skill fail on Windows.

    Templates put the value inside a JSON string, and a raw backslash is an
    invalid JSON escape -- so a path like C:\\Users\\... produced "Invalid
    arguments JSON" and the step failed.
    """
    source = cli.home / "example.py"
    source.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")

    ran = cli("skill", "run", "code-lint", "-a", f"file_path={source}")

    assert ran.returncode == 0, ran.text
    assert "Invalid arguments JSON" not in ran.text
    assert "Success" in ran.text


@pytest.mark.real_actions(reason="reaches the real subprocess.Popen")
def test_a_bundled_skill_cannot_be_deleted(cli) -> None:
    removed = cli("skill", "remove", "email-draft", "--yes")

    assert removed.returncode != 0, removed.text
    assert "ships with Grandpa" in removed.text

    # Still listed afterwards, which is the point.
    listed = cli("skill", "list")
    assert "email-draft" in listed.text
