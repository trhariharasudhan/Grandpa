"""Render the catalogue as tool definitions a model can be handed.

The shape is the one OpenAI's chat completions API defines and Ollama copies::

    {"type": "function",
     "function": {"name": ..., "description": ..., "parameters": {...schema}}}

Nothing consumes this yet. It exists so Phase 1 can prove the catalogue is
already expressible as tools -- the wiring comes later.

Risk does not appear as a field, because the format has nowhere to put one and
inventing a key a model will ignore would be worse than useless. What a model
does need to know is said in the description instead: an action that will stop
and ask says so in words.
"""

from __future__ import annotations

from typing import Any, Iterable

from grandpa.action_layer.catalogue import CATALOGUE, ActionSpec

__all__ = ["as_tool_definition", "as_tool_definitions"]

_CONFIRMATION_NOTICE = "Requires the user's explicit confirmation before it runs."


def _description_for(spec: ActionSpec) -> str:
    parts = [spec.description.strip()]
    if spec.notes.strip():
        parts.append(spec.notes.strip())
    if spec.requires_confirmation:
        parts.append(_CONFIRMATION_NOTICE)
    return " ".join(parts)


def as_tool_definition(spec: ActionSpec) -> dict[str, Any]:
    """Render one catalogue entry as a single tool definition."""
    return {
        "type": "function",
        "function": {
            "name": spec.name,
            "description": _description_for(spec),
            "parameters": dict(spec.parameters),
        },
    }


def as_tool_definitions(
    specs: Iterable[ActionSpec] | None = None,
) -> list[dict[str, Any]]:
    """Render the catalogue as tool definitions, in catalogue order.

    Pass ``specs`` to render a subset -- a caller that only wants the actions
    below a risk tier, say. The default is the whole catalogue, which by
    construction contains nothing BLOCKED and nothing stubbed.
    """
    return [
        as_tool_definition(spec) for spec in (CATALOGUE if specs is None else specs)
    ]
