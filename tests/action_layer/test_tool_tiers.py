"""Two tiers of tools, and the prefix stability the whole idea rests on.

Sending all 108 actions costs ~9,400 tokens, which on a machine without a GPU
is about sixteen minutes of prompt evaluation before the model can answer. The
fix is to send twenty and let the model fetch the rest -- but only if the
twenty are byte-identical every time, because a prefix that changes is a prefix
Ollama cannot reuse. That is what most of this file checks.
"""

from __future__ import annotations

import json

import pytest

from grandpa.action_layer.catalogue import (
    CATALOGUE,
    CORE_ACTIONS,
    DOMAINS,
    domain_of,
    extended_actions,
    get,
)
from grandpa.action_layer.tool_schema import (
    LOAD_TOOLS,
    as_tool_definitions,
    core_tool_definitions,
    domain_tool_definitions,
    tool_definitions_for,
)


def tokens(definitions) -> int:
    """Rough token count. Four characters a token is close enough to compare."""
    return len(json.dumps(definitions)) // 4


# --- the grouping is complete and disjoint -----------------------------------


def test_every_action_is_in_exactly_one_domain() -> None:
    grouped = [action for actions in DOMAINS.values() for action in actions]

    assert sorted(grouped) == sorted(spec.name for spec in CATALOGUE)
    assert len(grouped) == len(set(grouped)), "an action is in two domains"


def test_every_core_action_exists_and_has_a_domain() -> None:
    for action in CORE_ACTIONS:
        assert get(action), action
        assert domain_of(action) is not None, action


def test_core_is_small_enough_to_be_worth_having() -> None:
    """Twenty is the budget. The point is lost if it creeps."""
    assert len(CORE_ACTIONS) == 20
    assert len(set(CORE_ACTIONS)) == 20, "a core action is listed twice"


# --- nothing became unreachable ----------------------------------------------


def test_every_action_is_reachable_through_core_or_one_domain() -> None:
    """Deferred, never removed. This is the promise the tiering makes."""
    reachable = set(CORE_ACTIONS)
    for domain in DOMAINS:
        reachable.update(
            entry["function"]["name"] for entry in domain_tool_definitions(domain)
        )

    assert reachable == {spec.name for spec in CATALOGUE}


def test_loading_every_domain_offers_the_whole_catalogue() -> None:
    everything = tool_definitions_for(sorted(DOMAINS))
    offered = {entry["function"]["name"] for entry in everything}

    assert offered == {spec.name for spec in CATALOGUE} | {LOAD_TOOLS}


def test_a_domain_does_not_repeat_what_core_already_sent() -> None:
    notes = {entry["function"]["name"] for entry in domain_tool_definitions("notes")}

    assert "notes_create" in CORE_ACTIONS
    assert "notes_create" not in notes
    assert "notes_delete" in notes


# --- the prefix is the product ------------------------------------------------


def test_the_core_block_is_byte_identical_whatever_is_loaded() -> None:
    """Measured, not assumed: this is what makes the cached prefix work."""
    core = json.dumps(core_tool_definitions())
    # A JSON array's opening bracket plus every core element, without the
    # closing bracket, is the literal prefix of any longer array.
    prefix = core[:-1]

    for loaded in ([], ["notes"], ["notes", "browser"], sorted(DOMAINS)):
        rendered = json.dumps(tool_definitions_for(loaded))
        assert rendered.startswith(prefix), loaded


def test_core_is_identical_across_repeated_calls() -> None:
    assert json.dumps(core_tool_definitions()) == json.dumps(core_tool_definitions())


def test_core_order_is_the_declared_order() -> None:
    """Reordering core would throw the cache away as surely as changing it."""
    names = [entry["function"]["name"] for entry in core_tool_definitions()]

    assert names == [*CORE_ACTIONS, LOAD_TOOLS]


def test_loading_the_same_domain_twice_changes_nothing() -> None:
    once = json.dumps(tool_definitions_for(["notes"]))

    assert json.dumps(tool_definitions_for(["notes", "notes"])) == once


def test_an_unknown_domain_is_ignored_rather_than_breaking_the_prefix() -> None:
    assert tool_definitions_for(["nonsense"]) == core_tool_definitions()


# --- the meta-tool ------------------------------------------------------------


def test_load_tools_is_offered_and_lists_the_real_domains() -> None:
    meta = core_tool_definitions()[-1]

    assert meta["function"]["name"] == LOAD_TOOLS
    assert meta["function"]["parameters"]["properties"]["domain"]["enum"] == sorted(
        DOMAINS
    )


def test_load_tools_is_not_a_catalogued_action() -> None:
    """It changes the menu; it does not touch the machine, so it has no tier."""
    assert LOAD_TOOLS not in {spec.name for spec in CATALOGUE}


# --- what it costs ------------------------------------------------------------


def test_core_is_a_large_fraction_cheaper_than_everything() -> None:
    core = tokens(core_tool_definitions())
    everything = tokens(as_tool_definitions(CATALOGUE))

    assert core < everything / 4, f"core {core} vs all {everything}"


def test_one_domain_costs_far_less_than_the_rest_of_the_catalogue() -> None:
    core = tokens(core_tool_definitions())
    with_notes = tokens(tool_definitions_for(["notes"]))
    everything = tokens(as_tool_definitions(CATALOGUE))

    assert with_notes - core < (everything - core) / 4


# --- risk and confirmation are untouched --------------------------------------


@pytest.mark.parametrize("spec", CATALOGUE, ids=lambda spec: spec.name)
def test_tiering_changes_no_action_s_behaviour(spec) -> None:
    """A deferred action is the same action when it arrives."""
    from grandpa.action_layer.tool_schema import as_tool_definition

    rendered = as_tool_definition(spec)
    domain = domain_of(spec.name)
    if spec.name in CORE_ACTIONS:
        source = core_tool_definitions()
    else:
        source = domain_tool_definitions(domain)

    (found,) = [e for e in source if e["function"]["name"] == spec.name]
    assert found == rendered, "an action is described differently by tier"


def test_a_confirmable_action_still_says_so_wherever_it_is_sent() -> None:
    (delete,) = [
        entry
        for entry in domain_tool_definitions("notes")
        if entry["function"]["name"] == "notes_delete"
    ]

    assert "confirmation" in delete["function"]["description"].lower()


# --- the lean rendering -------------------------------------------------------


def test_executor_only_schema_keys_are_not_sent_to_the_model() -> None:
    """additionalProperties and an empty required cost tokens and say nothing.

    The executor still enforces both -- from the catalogue, not from what the
    model was shown.
    """
    for entry in core_tool_definitions():
        parameters = entry["function"]["parameters"]
        assert "additionalProperties" not in parameters
        assert parameters.get("required") != []


def test_the_executor_still_rejects_an_unknown_parameter() -> None:
    """Proof that dropping additionalProperties changed no behaviour."""
    from grandpa.action_layer.executor import execute
    from grandpa.action_layer.model import ActionRequest

    result = execute(
        ActionRequest("volume_up", {"nonsense": 1}, requires_confirmation=False)
    )

    assert result.error == "invalid_parameters"
    assert "unknown parameter" in result.message


def test_a_required_parameter_is_still_required() -> None:
    from grandpa.action_layer.executor import execute
    from grandpa.action_layer.model import ActionRequest

    result = execute(ActionRequest("open_app", {}, requires_confirmation=False))

    assert result.error == "invalid_parameters"
    assert "app" in result.message


# --- the domains a person would name -----------------------------------------


def test_extended_actions_is_the_domain_minus_core() -> None:
    for domain, actions in DOMAINS.items():
        expected = set(actions) - set(CORE_ACTIONS)
        assert {spec.name for spec in extended_actions(domain)} == expected, domain
