"""The rendered tool definitions have to be the shape the APIs actually accept.

Nothing consumes this output yet, so nothing else would notice if it drifted
out of the OpenAI/Ollama function-calling format.
"""

from __future__ import annotations

import json
import re
from typing import Any

import pytest

from grandpa.action_layer.catalogue import CATALOGUE, EXCLUSIONS
from grandpa.action_layer.tool_schema import as_tool_definition, as_tool_definitions

# OpenAI's constraint on a function name, which Ollama inherits.
_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

DEFINITIONS = as_tool_definitions()


def test_one_definition_per_catalogue_entry_in_order() -> None:
    rendered = [definition["function"]["name"] for definition in DEFINITIONS]

    assert rendered == [spec.name for spec in CATALOGUE]


@pytest.mark.parametrize("definition", DEFINITIONS, ids=lambda d: d["function"]["name"])
def test_every_definition_matches_the_function_calling_format(
    definition: dict[str, Any],
) -> None:
    assert set(definition) == {"type", "function"}, definition
    assert definition["type"] == "function"

    function = definition["function"]
    assert set(function) == {"name", "description", "parameters"}, function
    assert _NAME.match(function["name"]), f"illegal tool name: {function['name']!r}"
    assert function["description"].strip(), f"{function['name']}: empty description"

    parameters = function["parameters"]
    assert parameters["type"] == "object", function["name"]
    assert isinstance(parameters["properties"], dict), function["name"]
    assert isinstance(parameters["required"], list), function["name"]
    assert set(parameters["required"]) <= set(parameters["properties"]), function[
        "name"
    ]


def test_the_whole_payload_serialises_as_json() -> None:
    """This is handed to an HTTP API, so anything unserialisable is a bug."""
    assert json.loads(json.dumps(DEFINITIONS)) == DEFINITIONS


def test_an_action_that_will_stop_and_ask_says_so() -> None:
    """The format has no risk field, so the warning has to be in the words."""
    for spec in CATALOGUE:
        description = as_tool_definition(spec)["function"]["description"]
        asks = "confirmation" in description.lower()
        assert asks is spec.requires_confirmation, spec.name


def test_nothing_excluded_is_offered_to_a_model() -> None:
    offered = {definition["function"]["name"] for definition in DEFINITIONS}

    assert not offered & set(EXCLUSIONS), sorted(offered & set(EXCLUSIONS))


def test_a_subset_can_be_rendered() -> None:
    subset = as_tool_definitions(spec for spec in CATALOGUE if spec.name == "volume_up")

    assert [definition["function"]["name"] for definition in subset] == ["volume_up"]
