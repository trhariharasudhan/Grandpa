"""What a tool needs handed to it, declared by the tool and supplied in one place.

A tool that needs an inference engine or a memory backend cannot invent one. Until
now the wiring was a chain of name tests inside ``SystemBuilder._inject_tool_deps``
-- ``if name == "llm" ... elif name.startswith("memory_")`` -- which is a list of
the tools somebody remembered, and so covers exactly the tools somebody
remembered. Anything built outside that method got nothing:
``skills.manager.builtin_tool_executor``, which is what ``grandpa skill run``
uses, built every tool from the registry and injected nothing at all. Three of
the eighteen bundled skills failed because of it, each with a message that named
the symptom rather than the cause: "No memory backend configured.", "No
inference engine configured."

So the tool declares what it needs and this supplies it:

    class LLMTool(BaseTool):
        requires = ("engine", "model")

Two properties follow, and both are the point:

* a tool added next month is wired the day it declares a dependency, by nobody's
  diligence, which is the same argument as taking the actuation list from the
  catalogue rather than from a list of categories that have already gone wrong;
* what cannot be supplied is known at *build* time and named there, rather than
  surfacing as a puzzling refusal in the middle of step three of a skill.

Providers are callables, so nothing is resolved unless a tool actually asks for
it. Resolving an inference engine means talking to Ollama; a CLI command whose
skill only reads a file should not pay for that.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

ATTRIBUTE = {
    "engine": "_engine",
    "model": "_model",
    "memory_backend": "_backend",
    "knowledge_store": "_store",
}
"""Dependency name -> the attribute the tool keeps it in.

Held here rather than guessed from the name, because the attributes predate this
and renaming them across every tool would be a bigger change than the bug.
"""

Provider = Callable[[], Any]


def declared_dependencies(tool: Any) -> tuple[str, ...]:
    """What this tool says it needs. Empty for a tool that needs nothing."""
    declared = getattr(tool, "requires", ())
    if isinstance(declared, str):  # a single name, written without the comma
        return (declared,)
    return tuple(declared)


def inject(tool: Any, providers: Mapping[str, Provider]) -> list[str]:
    """Fill in what ``tool`` declares, and return the names that could not be.

    A provider that returns ``None`` or raises counts as unavailable: the
    difference between "no engine is running" and "resolving the engine blew up"
    matters to a person reading a log, not to a tool that cannot work either way.
    The exception is logged by the caller that owns the provider.
    """
    missing: list[str] = []
    for need in declared_dependencies(tool):
        attribute = ATTRIBUTE.get(need)
        if attribute is None:
            missing.append(need)
            continue
        provider = providers.get(need)
        if provider is None:
            missing.append(need)
            continue
        try:
            value = provider()
        except Exception:  # noqa: BLE001 - an unavailable dependency is not a crash
            value = None
        if value is None or (need == "model" and not str(value).strip()):
            missing.append(need)
            continue
        setattr(tool, attribute, value)
    return missing


def describe_unavailable(unavailable: Mapping[str, list[str]]) -> str:
    """One line per tool that could not be wired, for a build to print."""
    if not unavailable:
        return ""
    parts = [
        f"{name} (needs {', '.join(needs)})"
        for name, needs in sorted(unavailable.items())
    ]
    return "Unavailable: " + "; ".join(parts)


def memoized(provider: Provider) -> Provider:
    """Resolve at most once, however many tools ask for it."""
    cache: list[Any] = []

    def resolve() -> Any:
        if not cache:
            cache.append(provider())
        return cache[0]

    return resolve


__all__ = [
    "ATTRIBUTE",
    "declared_dependencies",
    "describe_unavailable",
    "inject",
    "memoized",
]
