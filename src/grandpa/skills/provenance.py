"""Who wrote a skill manifest, and whether that is enough to load it.

A manifest under ``~/.grandpa/skills/`` is deferred execution: its steps name
tools, and ``SkillExecutor`` sends each one through ``ToolExecutor``, so
anything in it that is not confirmation-gated runs unprompted when the skill is
next invoked. ``SkillManager.discover()`` used to load every ``*.toml`` it
found, with no record of where the file came from -- and ``skill_manage`` is a
model-facing tool that writes exactly such files.

So a manifest now says who wrote it, and the ones that cannot vouch for
themselves do not load unless someone is there to be asked:

``provenance = "user"``
    A person wrote or reviewed this file. Loads.

``provenance = "model"`` / ``"agent"``
    Written by ``skill_manage``, or by an agent. Needs confirmation.

missing
    Unknown. Needs confirmation -- because the alternative is that omitting the
    line is the way to be trusted, which is not a check at all.

A manifest a person wrote by hand has no provenance line, so it is in the last
group: it will not load until they either add ``provenance = "user"`` to its
``[skill]`` table or answer the prompt. That is a real cost, and it is the
deliberate side of the trade -- "unmarked" has to be the untrusted state, or
the marking means nothing.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from grandpa.skills.types import SkillManifest

TRUSTED_PROVENANCE = frozenset({"user", "bundled"})
"""Provenance values that load without being asked about.

``bundled`` is for manifests that ship inside the package, which are reviewed
in the repository like any other code.
"""

MODEL_PROVENANCE = frozenset({"model", "agent", "assistant"})
"""Written by something that is not a person. Always needs confirmation."""


def needs_confirmation(manifest: SkillManifest) -> bool:
    """Whether loading this manifest has to be agreed to first."""
    return normalise(manifest.provenance) not in TRUSTED_PROVENANCE


def normalise(value: str | None) -> str:
    return " ".join(str(value or "").strip().lower().split())


def describe(manifest: SkillManifest) -> str:
    """The sentence a person is shown before a manifest loads."""
    provenance = normalise(manifest.provenance)
    steps = ", ".join(
        step.tool_name or step.skill_name for step in manifest.steps if step
    )
    if provenance in MODEL_PROVENANCE:
        written_by = f"was written by a {provenance}"
    elif not provenance:
        written_by = "does not say who wrote it"
    else:
        written_by = f"records its author as {provenance!r}, which is not recognised"
    return (
        f'The skill "{manifest.name}" {written_by}. Loading it means its steps '
        f"run whenever it is invoked, without being asked again"
        + (f": {steps}" if steps else "")
        + ".\nLoad it?"
    )


def admit(
    manifest: SkillManifest,
    confirm: Callable[[str, str], bool] | None,
) -> tuple[bool, str]:
    """Decide whether ``manifest`` may load. Returns (allowed, reason)."""
    if not needs_confirmation(manifest):
        return True, ""
    if confirm is None:
        return False, (
            f"{manifest.name}: not loaded. "
            + describe(manifest).split("\n")[0]
            + " There is no way to ask here, so it was left alone. Add "
            'provenance = "user" to its [skill] table if you wrote it.'
        )
    if confirm(describe(manifest), "requires_confirmation"):
        return True, ""
    return False, f"{manifest.name}: not loaded (declined)."


__all__ = [
    "MODEL_PROVENANCE",
    "TRUSTED_PROVENANCE",
    "admit",
    "describe",
    "needs_confirmation",
    "normalise",
]
