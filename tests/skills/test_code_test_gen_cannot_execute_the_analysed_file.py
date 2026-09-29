"""Pointing code-test-gen at a file must not run that file.

The shipped manifest built ``code_interpreter``'s ``code`` argument by
interpolating ``{analysis}`` -- which carries the whole contents of the file
under analysis -- after a single ``#``. A ``#`` comments out one line. The file
arrives with real newlines, so from its second line onward its own code sat at
top level in the payload, as code to execute.

It never actually ran, because of a second defect in the same line: ``\\n`` in a
TOML literal string is a backslash followed by an n, and JSON decoding leaves it
that way, so the payload's final line began with a literal backslash and every
run died with "unexpected character after line continuation character" before
reaching the interpolated lines. The syntax error was load-bearing. Fixing it
alone would have turned a skill that always failed into one that executed
whatever file it was given.

Both were fixed together, and these tests describe the property rather than the
implementation: whatever the manifest does, a marker in the analysed file must
not reach the interpreter, and the skill must succeed on ordinary input.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import tomllib

pytestmark = pytest.mark.core

MANIFEST = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "grandpa"
    / "skills"
    / "data"
    / "code-test-gen.toml"
)
PLACEHOLDER = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")

MARKER = "MARKER_THE_FILE_EXECUTED"
FILE_WITH_EXECUTABLE_LINES = (
    "def add(a, b):\n"
    "    return a + b\n"
    "\n"
    f'print("{MARKER}")\n'
    "import os\n"
    f'os.environ["{MARKER}"] = "1"\n'
)


def steps() -> list[dict]:
    return tomllib.loads(MANIFEST.read_text(encoding="utf-8"))["skill"]["steps"]


def code_step() -> dict:
    found = [step for step in steps() if step.get("tool_name") == "code_interpreter"]
    assert len(found) == 1, f"expected exactly one code_interpreter step, got {found}"
    return found[0]


def render(template: str, values: dict[str, str]) -> str:
    """Substitute the way the skill engine does: plain textual replacement."""
    rendered = template
    for name, value in values.items():
        rendered = rendered.replace("{" + name + "}", value)
    return rendered


def test_the_code_payload_interpolates_nothing_from_the_analysed_file() -> None:
    """The property, stated against the manifest: no placeholder in the payload.

    Asserted on the parsed `code` argument rather than the raw template, so a
    placeholder smuggled in through a different quoting style is still caught.
    """
    template = code_step()["arguments_template"]
    # The template is JSON once its placeholders are filled; fill them with a
    # value that is a legal JSON string body so the structure can be parsed.
    filled = PLACEHOLDER.sub("X", template)
    code = json.loads(filled)["code"]

    assert not PLACEHOLDER.search(code), (
        f"code-test-gen builds its interpreter payload from {PLACEHOLDER.findall(code)}, "
        f"and a step output interpolated into executable code is executable code. "
        f"The payload must be static."
    )


def test_a_file_full_of_executable_lines_never_reaches_the_payload() -> None:
    """The same property, driven end to end through the template."""
    template = code_step()["arguments_template"]
    # Whatever the earlier steps are named, feed every one of them the hostile
    # file, so this does not depend on the analysis step keeping its name.
    hostile = {
        name: FILE_WITH_EXECUTABLE_LINES for name in PLACEHOLDER.findall(template)
    }
    code = json.loads(render(template, hostile) if hostile else template)["code"]

    assert MARKER not in code, (
        "the analysed file's own lines reached the interpreter payload"
    )
    assert "os.environ" not in code


def test_the_payload_is_syntactically_valid_python() -> None:
    """The defect that masked the other one: it failed on every input.

    A literal backslash-n at the start of a line is
    "unexpected character after line continuation character".
    """
    template = code_step()["arguments_template"]
    code = json.loads(PLACEHOLDER.sub("X", template))["code"]

    compile(code, "<code-test-gen>", "exec")


def test_the_payload_has_no_literal_backslash_escapes_left() -> None:
    """States the cause, so a reintroduced `\\\\n` is named rather than just failing."""
    template = code_step()["arguments_template"]
    code = json.loads(PLACEHOLDER.sub("X", template))["code"]

    assert "\\n" not in code, (
        "the payload contains a literal backslash followed by n where a newline "
        "was meant. In a TOML literal string write a single backslash-n: JSON "
        "decoding turns that into a real newline."
    )


def test_the_analysis_is_still_carried_to_the_review_step() -> None:
    """Removing the injection must not silently drop the skill's own content.

    The analysis belongs in the review step's prompt, where it is read. The
    point of the fix is that it is not *executed*, not that it disappears.
    """
    thinking = [step for step in steps() if step.get("tool_name") == "think"]
    templates = " ".join(step.get("arguments_template", "") for step in thinking)

    assert "{analysis}" in templates
