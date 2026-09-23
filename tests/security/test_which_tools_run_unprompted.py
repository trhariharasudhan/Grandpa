"""Which tools a saved manifest can run without anyone being asked.

There are two kinds of "saved skill" in this codebase and they reach different
things, which matters for what this pins:

* a **user skill** (``skill_builder``, the SQLite store, the HTTP API) has steps
  that name *runtime skills*. ``run_user_skill`` dispatches through
  ``skills.registry.execute_skill``, so a user-skill step **cannot name a tool
  at all**; and
* an **agent-authored manifest** (``~/.grandpa/skills/*.toml``, written by
  ``skill_manage``) has steps that name *tools*. ``SkillExecutor.run`` sends
  each one through ``ToolExecutor.execute``
  (skills/executor.py -> tools/_stubs.py), which is the one mandatory
  confirmation boundary for tools.

So the answer to "what runs unprompted from a saved skill" is: the tools below,
reachable from a manifest, not from a user skill. ``ToolExecutor`` refuses a
tool whose spec sets ``requires_confirmation`` when it has no callback -- that
is what makes ``shell_exec`` safe in a manifest -- and runs everything else.

This file pins the flags, hand-audited, so that adding an acting tool without
the flag fails here and names it. The reason strings are the audit: each says
what that tool does, not what its name suggests.
"""

from __future__ import annotations

import pytest

# requires_confirmation=True: refused in a manifest with no callback.
GATED = {
    "shell_exec": "runs an arbitrary shell command",
    "git_commit": "writes a commit to the repository",
    "skill_manage": "creates and deletes skill manifests, which are themselves "
    "deferred execution",
    # Tier 1: irreversible, or reaching arbitrary code.
    "apply_patch": "applies a diff to files in the working tree",
    "code_interpreter": "runs a subprocess",
    "repl": "executes Python in-process behind a denylist, not a sandbox",
}

# requires_confirmation=False and able to change something. Every one of these
# runs unprompted as a manifest step.
UNGATED_BUT_ACTS = {
    # Tier 2: bounded rather than prompted, because a prompt per call would be
    # unusable and the damage is containable by *where* rather than *whether*.
    "file_write": "writes files, confined to the file domain's own roots and "
    "carve-outs",
    "db_query": "executes SQL; read_only defaults True, and a stored skill "
    "step may no longer turn it off",
    "text_to_speech": "writes audio, confined to GRANDPA_HOME/audio or a "
    "temporary directory",
    "http_request": "sends network requests; SSRF-guarded, not confirmation-gated",
    "web_search": "sends network requests; SSRF-guarded",
    "memory_manage": "writes the memory store",
    "memory_store": "writes the memory store",
    "memory_index": "indexes a file or directory into the memory backend",
    "kg_add_entity": "writes the knowledge graph",
    "kg_add_relation": "writes the knowledge graph",
    "user_profile_manage": "writes the user profile store",
}

# Tier 3: left ungated on the argument that they write only inside Grandpa's
# own home. That argument has to be true, so it is checked below rather than
# asserted -- two of these used a hardcoded "~/.grandpa/..." literal and
# ignored GRANDPA_HOME entirely until it was.
TIER_3 = (
    "memory_manage",
    "memory_store",
    "memory_index",
    "kg_add_entity",
    "kg_add_relation",
    "user_profile_manage",
)


def _snapshot() -> dict[str, bool]:
    """Read every registered tool's confirmation flag.

    Taken once, at import time, deliberately. conftest's autouse
    ``_clean_registries`` fixture empties the tool registry before every test,
    and it cannot be refilled: ``load_builtin_tools`` works by importing
    modules, so the ``@ToolRegistry.register`` decorators do not run a second
    time. Collection happens before the fixtures, so this is the one point
    where the real registry is populated.
    """
    from grandpa.core.registry import ToolRegistry
    from grandpa.tools import load_builtin_tools

    load_builtin_tools()
    flags: dict[str, bool] = {}
    for name in ToolRegistry.keys():
        try:
            flags[name] = bool(ToolRegistry.create(name).spec.requires_confirmation)
        except Exception:  # noqa: BLE001 - a tool that cannot be built cannot run
            continue
    return flags


FLAGS = _snapshot()


def _specs() -> dict[str, bool]:
    assert FLAGS, "the tool registry was empty at import time"
    return FLAGS


@pytest.mark.parametrize("name,why", sorted(GATED.items()))
def test_the_gated_tools_stay_gated(name: str, why: str) -> None:
    flags = _specs()

    assert name in flags, f"{name} is no longer registered"
    assert flags[name] is True, f"{name} lost its confirmation gate -- it {why}"


@pytest.mark.parametrize("name,why", sorted(UNGATED_BUT_ACTS.items()))
def test_the_ungated_acting_tools_are_the_ones_we_know_about(
    name: str, why: str
) -> None:
    """Recorded, not endorsed.

    This asserts the audit is still accurate, so that a change in either
    direction is visible: if one of these gains a gate, update the list and say
    so in the CHANGELOG.
    """
    flags = _specs()

    assert name in flags, f"{name} is no longer registered ({why})"
    assert flags[name] is False, (
        f"{name} now requires confirmation. That is an improvement -- move it "
        f"to GATED and record it."
    )


def test_no_unaudited_tool_is_registered() -> None:
    """A new tool must be classified here before it ships.

    Without this the list above ages silently: a tool added next month would
    run unprompted from a manifest and nothing would say so.
    """
    read_only = {
        "calculator",
        "think",
        "retrieval",
        "llm",
        "file_read",
        "pdf_extract",
        "git_diff",
        "git_log",
        "git_status",
        "kg_query",
        "kg_neighbors",
        "memory_retrieve",
        "memory_search",
    }
    known = set(GATED) | set(UNGATED_BUT_ACTS) | read_only

    unaudited = set(_specs()) - known

    assert unaudited == set(), (
        f"these tools are registered but not classified: {sorted(unaudited)}. "
        "Add each to GATED, UNGATED_BUT_ACTS, or the read-only set, with a "
        "reason saying what it does."
    )


def test_a_user_skill_step_cannot_name_a_tool() -> None:
    """The boundary the two kinds of saved skill do not share.

    A user-skill step's ``skill`` field is looked up in the runtime registry.
    Tool names are not in it, so a step naming ``shell_exec`` resolves to
    nothing -- and is treated as acting, so it cannot even be saved silently.
    """
    from grandpa.skill_builder.validator import validate_workflow_steps
    from grandpa.skills.registry import ensure_default_skills_registered, get_skill

    ensure_default_skills_registered()
    for tool_name in ("file_write", "http_request", "apply_patch"):
        with pytest.raises(KeyError):
            get_skill(tool_name)

    steps = validate_workflow_steps([{"skill": "file_write", "params": {}}])

    assert steps[0]["risk_level"] == "HIGH"
    assert steps[0]["approval_required"] is True


def test_tier_three_writes_only_under_grandpa_home(monkeypatch, tmp_path) -> None:
    """The claim that justifies leaving these ungated, checked.

    A tool that takes a backend writes wherever that backend does -- which is
    the caller's choice, not the tool's -- and without one it does nothing. The
    two that own a path have to honour GRANDPA_HOME.
    """
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("GRANDPA_HOME", str(home))

    from grandpa.tools.memory_manage import MemoryManageTool
    from grandpa.tools.user_profile_manage import UserProfileManageTool

    owned = {
        "memory_manage": MemoryManageTool()._memory_path,
        "user_profile_manage": UserProfileManageTool()._user_path,
    }
    outside = {
        name: path
        for name, path in owned.items()
        if not path.resolve().is_relative_to(home.resolve())
    }

    assert outside == {}, (
        f"these are in Tier 3 on the grounds that they write under "
        f"GRANDPA_HOME, and they do not: {outside}"
    )


def test_the_tier_three_backend_tools_do_nothing_without_one() -> None:
    """The other four own no path: unconfigured, they write nowhere at all."""
    # Built directly: conftest empties the registry before every test.
    from grandpa.tools.knowledge_tools import KGAddEntityTool, KGAddRelationTool

    for tool in (KGAddEntityTool(), KGAddRelationTool()):
        result = tool.execute(entity_id="x", name="x", source="a", target="b")

        assert result.success is False
        assert "backend" in result.content.lower()
