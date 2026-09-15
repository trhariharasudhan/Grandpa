"""Render the catalogue as tool definitions a model can be handed.

The shape is the one OpenAI's chat completions API defines and Ollama copies::

    {"type": "function",
     "function": {"name": ..., "description": ..., "parameters": {...schema}}}

**Tiering.** The whole catalogue is ~9,400 tokens. On a machine without a GPU
Ollama evaluates a cold prompt at roughly ten tokens a second, so sending all
108 actions costs about sixteen minutes before the model can say a word. So
:func:`core_tool_definitions` sends twenty, plus one meta-tool the model calls
to fetch a domain it needs. Nothing is unreachable; the rest is one round trip
away.

The core block is emitted first and never varies, which is the whole point:
Ollama caches the evaluated prefix, and a prefix that changes between requests
is a prefix that is never reused. ``tests/action_layer/test_tool_tiers.py``
asserts the bytes are identical whatever has been loaded since.

Risk does not appear as a field, because the format has nowhere to put one and
inventing a key a model will ignore would be worse than useless. What a model
does need to know is said in the description instead: an action that will stop
and ask says so in words.
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

from grandpa.action_layer.catalogue import (
    CATALOGUE,
    CORE_ACTIONS,
    DOMAINS,
    ActionSpec,
    extended_actions,
    get,
)

__all__ = [
    "LOAD_TOOLS",
    "as_tool_definition",
    "as_tool_definitions",
    "core_tool_definitions",
    "domain_tool_definitions",
    "tool_definitions_for",
]

_CONFIRMATION_NOTICE = "Requires the user's explicit confirmation before it runs."

LOAD_TOOLS = "load_tools"
"""The meta-tool's name. Not a catalogued action: it changes what the model can
see rather than doing anything to the machine, so it never reaches the
executor and has no risk tier."""


def _description_for(spec: ActionSpec) -> str:
    parts = [spec.description.strip()]
    if spec.notes.strip():
        parts.append(spec.notes.strip())
    if spec.requires_confirmation:
        parts.append(_CONFIRMATION_NOTICE)
    return " ".join(parts)


def _lean(parameters: dict[str, Any]) -> dict[str, Any]:
    """Drop the schema keys only the executor needs.

    ``additionalProperties: false`` and an empty ``required`` are there so the
    executor can reject a bad call, and it does that from the catalogue, not
    from what the model was shown. Sending them costs about a thousand tokens
    across the catalogue and tells the model nothing.
    """
    schema = dict(parameters)
    schema.pop("additionalProperties", None)
    if not schema.get("required"):
        schema.pop("required", None)
    if not schema.get("properties"):
        schema.pop("properties", None)
    return schema


def as_tool_definition(spec: ActionSpec) -> dict[str, Any]:
    """Render one catalogue entry as a single tool definition."""
    return {
        "type": "function",
        "function": {
            "name": spec.name,
            "description": _description_for(spec),
            "parameters": _lean(dict(spec.parameters)),
        },
    }


def as_tool_definitions(
    specs: Iterable[ActionSpec] | None = None,
) -> list[dict[str, Any]]:
    """Render the catalogue as tool definitions, in catalogue order.

    Pass ``specs`` to render a subset. The default is every catalogued action,
    which is what a caller wants when it is not paying a cold-start cost --
    a cloud model, or a test.
    """
    return [
        as_tool_definition(spec) for spec in (CATALOGUE if specs is None else specs)
    ]


def _load_tools_definition() -> dict[str, Any]:
    """The meta-tool, listing the domains by name so the model can pick one."""
    return {
        "type": "function",
        "function": {
            "name": LOAD_TOOLS,
            "description": (
                "Load the tools for one subject when you need an action that is "
                "not in your current list. Call this first, then call the action "
                "it gives you. Use it whenever the user asks for something you "
                "cannot already do -- do not say you are unable until you have "
                "looked."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "description": "Which subject's tools to load.",
                        "enum": sorted(DOMAINS),
                    }
                },
                "required": ["domain"],
            },
        },
    }


def core_tool_definitions() -> list[dict[str, Any]]:
    """The always-sent block: the core actions, then the meta-tool.

    Fixed order, fixed content. This is the prefix Ollama caches.
    """
    return [as_tool_definition(get(name)) for name in CORE_ACTIONS] + [
        _load_tools_definition()
    ]


def domain_tool_definitions(domain: str) -> list[dict[str, Any]]:
    """What a domain adds beyond core. Empty for an unknown domain."""
    return [as_tool_definition(spec) for spec in extended_actions(domain)]


def tool_definitions_for(loaded: Sequence[str] = ()) -> list[dict[str, Any]]:
    """Core, then each loaded domain in the order it was asked for.

    Appending rather than reordering is what keeps the core block byte-identical
    across a conversation -- and therefore what keeps the cached prefix.
    """
    definitions = core_tool_definitions()
    seen: set[str] = set()
    for domain in loaded:
        if domain in seen or domain not in DOMAINS:
            continue
        seen.add(domain)
        definitions.extend(domain_tool_definitions(domain))
    return definitions
