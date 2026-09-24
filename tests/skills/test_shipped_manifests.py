"""Every manifest the package ships must name tools that exist, in every family.

The eighteen bundled skills had five bugs, and three of them were invisible to
any test that only *loaded* a manifest: a step named ``llm_call``, which has
never existed; a step sent ``path`` where the parameter is ``file_path``; and
every template broke on any value containing a backslash, which on Windows is
every file path.

The skills family is covered by ``test_bundled_skills.py``. Two more families
ship the same shape of data and had the same bugs:

* ``agents/templates/`` -- four agent templates, whose ``tools`` list and
  ``system_prompt_template`` are read at ``create_from_template``;
* ``operators/data/`` -- four operators, whose ``tools`` list reaches an agent.

Between them they named eight tools that do not resolve, and one of those names
was pinned by an assertion in ``tests/operators/test_operators.py`` -- a test
agreeing with the manifest it was checking, both of them wrong.

The parametrisation walks each directory, so a manifest added later is covered
the day the file lands rather than when somebody remembers to add it here.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import tomllib

SRC = Path(__file__).resolve().parents[2] / "src" / "grandpa"

FAMILIES = {
    "skills": (SRC / "skills" / "data", "skill"),
    "agent-templates": (SRC / "agents" / "templates", "template"),
    "operators": (SRC / "operators" / "data", "operator"),
}

# A path shaped like the ones this product is given on the machine it runs on.
# The backslashes are the point: they are what broke every file-taking skill.
WINDOWS_PATH = r"C:\Users\ASUS\Documents\quarterly report.pdf"


def _registered_tools() -> frozenset[str]:
    """Tool names, snapshotted at import.

    conftest's autouse ``_clean_registries`` empties the tool registry before
    every test, and ``load_builtin_tools`` cannot refill it: it works by
    importing modules, so the ``@ToolRegistry.register`` decorators do not run a
    second time. Collection happens before the fixtures, so this is the one point
    where the real registry is populated.
    """
    from grandpa.core.registry import ToolRegistry
    from grandpa.tools import load_builtin_tools

    load_builtin_tools()
    return frozenset(ToolRegistry.keys())


REGISTERED_TOOLS = _registered_tools()


def _manifests() -> list[tuple[str, Path, str]]:
    found: list[tuple[str, Path, str]] = []
    for family, (directory, section) in FAMILIES.items():
        for path in sorted(directory.glob("*.toml")):
            found.append((family, path, section))
    return found


MANIFESTS = _manifests()
IDS = [f"{family}:{path.stem}" for family, path, _ in MANIFESTS]


def _table(path: Path, section: str) -> dict:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    table = data.get(section, {})
    return table if isinstance(table, dict) else {}


def _declared_tools(table: dict) -> list[str]:
    """The tool names a manifest asks for, wherever that family keeps them."""
    if isinstance(table.get("tools"), list):
        return [str(name) for name in table["tools"]]
    agent = table.get("agent")
    if isinstance(agent, dict) and isinstance(agent.get("tools"), list):
        return [str(name) for name in agent["tools"]]
    # A skill names one tool per step rather than keeping a list.
    steps = table.get("steps")
    if isinstance(steps, list):
        return [
            str(step["tool_name"])
            for step in steps
            if isinstance(step, dict) and step.get("tool_name")
        ]
    return []


def _prompt_templates(table: dict) -> list[tuple[str, str]]:
    """Only the fields the product actually runs ``str.format`` over.

    ``system_prompt_template`` and nothing else. ``AgentManager.create_from_template``
    pops that key and calls ``.format(instruction=...)`` on it, so a stray brace
    there raises at run time. An operator's ``system_prompt`` is handed to the
    model verbatim -- the operators package calls ``.format`` nowhere -- so a
    ``{timestamp}`` in one is literal text a prompt author meant to write. An
    earlier version of this checked those too and reported three operators as
    broken, which would have been a requirement invented by the test.
    """
    found: list[tuple[str, str]] = []
    value = table.get("system_prompt_template")
    if isinstance(value, str) and value:
        found.append(("system_prompt_template", value))
    agent = table.get("agent")
    if isinstance(agent, dict):
        nested = agent.get("system_prompt_template")
        if isinstance(nested, str) and nested:
            found.append(("agent.system_prompt_template", nested))
    return found


# ---------------------------------------------------------------------------
# The checks
# ---------------------------------------------------------------------------


def test_there_are_manifests_in_every_family() -> None:
    """An empty directory would make every assertion below vacuously true."""
    by_family: dict[str, int] = {}
    for family, _, _ in MANIFESTS:
        by_family[family] = by_family.get(family, 0) + 1
    assert by_family.get("skills", 0) >= 18, by_family
    assert by_family.get("agent-templates", 0) >= 1, by_family
    assert by_family.get("operators", 0) >= 4, by_family


def test_the_registry_snapshot_is_not_empty() -> None:
    """Otherwise every tool name would 'resolve' against an empty set."""
    assert len(REGISTERED_TOOLS) > 20, sorted(REGISTERED_TOOLS)


@pytest.mark.parametrize(("family", "path", "section"), MANIFESTS, ids=IDS)
def test_every_declared_tool_resolves(family: str, path: Path, section: str) -> None:
    """A name that does not resolve is a step that fails at run time.

    ``knowledge_curator`` named knowledge_add_entity, knowledge_add_relation and
    knowledge_query; the registry has kg_add_entity, kg_add_relation and
    kg_query. ``inbox_triager`` named channel_send and channel_list, which exist
    nowhere in the product. Nothing failed, because nothing ran them.
    """
    declared = _declared_tools(_table(path, section))
    assert declared, f"{path.name} declares no tools; is the section name right?"
    missing = sorted(set(declared) - REGISTERED_TOOLS)
    assert not missing, (
        f"{path.name} names {missing}, which the tool registry does not have. "
        f"Either the name is wrong, or the tool exists but is not registered in "
        f"grandpa.tools._BUILTINS."
    )


@pytest.mark.parametrize(("family", "path", "section"), MANIFESTS, ids=IDS)
def test_every_prompt_template_survives_a_windows_path(
    family: str, path: Path, section: str
) -> None:
    """``str.format`` on a prompt raises on any brace it was not given.

    The skills' version of this bug was JSON escaping; here it is ``KeyError``
    from a stray brace, or ``IndexError`` from a bare ``{}``. Either way the
    template is filled in at run time with values a user supplies, and a path is
    the commonest of them.
    """
    for key, template in _prompt_templates(_table(path, section)):
        try:
            filled = template.format(instruction=WINDOWS_PATH)
        except (KeyError, IndexError, ValueError) as exc:
            pytest.fail(
                f"{path.name}: {key} does not survive expansion "
                f"({type(exc).__name__}: {exc}). A literal brace in a prompt must "
                f"be doubled."
            )
        assert WINDOWS_PATH in filled or "{instruction}" not in template


def _prompt_text(table: dict) -> str:
    """Everything a manifest says to the model, as one body of text."""
    chunks: list[str] = []
    for key in ("system_prompt_template", "system_prompt", "instructions"):
        value = table.get(key)
        if isinstance(value, str):
            chunks.append(value)
    agent = table.get("agent")
    if isinstance(agent, dict):
        for key in ("system_prompt_template", "system_prompt", "instructions"):
            value = agent.get(key)
            if isinstance(value, str):
                chunks.append(value)
    return "\n".join(chunks)


@pytest.mark.parametrize(("family", "path", "section"), MANIFESTS, ids=IDS)
def test_no_prompt_names_a_tool_the_manifest_did_not_grant(
    family: str, path: Path, section: str
) -> None:
    """A prompt telling the model to use a tool it does not have.

    ``knowledge_curator`` instructed the agent to "Store your updated state with
    memory_store", and memory_store was not in its tools list. The model is told
    to do something it cannot; what happens next is a wasted turn at best.

    This does not parse the prose. It takes the set of names the registry knows,
    which is a closed set of identifiers, and looks for each one verbatim. Exact
    matching against a known set, so a sentence about "thinking" is not mistaken
    for the ``think`` tool -- though a prompt that happens to contain a real tool
    name as an ordinary word would be a false positive worth fixing in the prompt
    anyway, since the model reads it the same way.
    """
    table = _table(path, section)
    prompt = _prompt_text(table)
    if not prompt:
        pytest.skip("no prompt in this manifest")
    granted = set(_declared_tools(table))
    named = {
        tool
        for tool in REGISTERED_TOOLS
        if re.search(rf"\b{re.escape(tool)}\b", prompt)
    }
    ungranted = sorted(named - granted)
    assert not ungranted, (
        f"{path.name}'s prompt tells the model to use {ungranted}, which its "
        f"tools list does not grant. Either add them to tools, or stop naming "
        f"them: it has {sorted(granted)}."
    )


@pytest.mark.parametrize(("family", "path", "section"), MANIFESTS, ids=IDS)
def test_every_manifest_has_an_id_matching_its_filename(
    family: str, path: Path, section: str
) -> None:
    """Cheap, and the thing a loader keyed by name relies on."""
    table = _table(path, section)
    declared = str(table.get("id") or table.get("name") or "")
    assert declared, f"{path.name} declares neither id nor name"
    normalised = declared.replace("_", "-").lower()
    assert normalised == path.stem.replace("_", "-").lower(), (
        f"{path.name} declares id {declared!r}"
    )
