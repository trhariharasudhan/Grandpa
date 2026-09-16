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
    CORE_DOMAINS,
    DOMAINS,
    domain_of,
    extended_actions,
    get,
    loadable_domains,
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
    """Roughly ten is the budget. The point is lost if it creeps."""
    assert len(CORE_ACTIONS) <= 12, "core has crept; every action is paid for cold"
    assert len(set(CORE_ACTIONS)) == len(CORE_ACTIONS), "a core action is listed twice"


# --- no domain may be split ---------------------------------------------------


def test_core_holds_whole_domains_only() -> None:
    """A split domain must fail the build. This is that assertion.

    Measured on grandpa-brain: the model calls load_tools for a subject wholly
    absent from its list and does not when part of that subject is already in
    front of it -- "I cannot directly pin a note to the top", with four notes
    tools in hand. Splitting a domain hides its other actions rather than
    deferring them, so the shape is enforced here rather than trusted.
    """
    for domain in CORE_DOMAINS:
        missing = [name for name in DOMAINS[domain] if name not in CORE_ACTIONS]
        assert missing == [], f"{domain} is split: core is missing {missing}"


def test_no_domain_is_partly_in_core() -> None:
    """The same rule read from the other end: every domain is all in, or all out."""
    core = set(CORE_ACTIONS)
    for domain, names in DOMAINS.items():
        inside = [name for name in names if name in core]
        outside = [name for name in names if name not in core]
        assert not (inside and outside), (
            f"{domain} is split: {inside} in core, {outside} deferred"
        )


def test_core_actions_are_exactly_the_core_domains() -> None:
    expected = [action for domain in CORE_DOMAINS for action in DOMAINS[domain]]

    assert list(CORE_ACTIONS) == expected


def test_a_core_domain_is_not_offered_for_loading() -> None:
    """Loading one would buy no tools, so it is not in the offer."""
    for domain in CORE_DOMAINS:
        assert domain not in loadable_domains()
    assert set(loadable_domains()) | set(CORE_DOMAINS) == set(DOMAINS)


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


def test_a_deferred_domain_offers_all_of_itself() -> None:
    """Nothing is held back, because nothing of it was sent."""
    notes = {entry["function"]["name"] for entry in domain_tool_definitions("notes")}

    assert notes == set(DOMAINS["notes"])
    assert "notes_create" in notes and "notes_pin" in notes


def test_a_core_domain_adds_nothing_when_loaded() -> None:
    for domain in CORE_DOMAINS:
        assert domain_tool_definitions(domain) == []


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
    offered = meta["function"]["parameters"]["properties"]["domain"]["enum"]
    assert offered == list(loadable_domains())
    assert not set(offered) & set(CORE_DOMAINS), (
        "a core domain is sent whole; offering it buys a round trip and no tools"
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
