"""What a surface knows about a request before any handler sees it.

One object rather than a text argument plus a context argument, because a
handler that receives both can be handed two things that disagree -- and the
disagreement would be invisible, since nothing downstream can tell which one
the caller meant. ``text`` lives here so there is exactly one answer.

``origin`` is required and has no default. That is the whole point of the
field: ``DEFAULT_ACTION_ORIGIN`` already exists in two places and means a
request whose provenance nobody recorded is indistinguishable from one a person
typed. AD-022 exists because that silence is what lets model-chosen parameters
arrive looking like direct user input. A surface that cannot say where a
request came from should fail to construct a context, loudly, rather than be
handed ``"direct"`` on its behalf.

The type comes from ``grandpa.policy.models`` rather than being restated here.
``pc_control`` declares its own identical ``ActionOrigin``, so the vocabulary
already exists twice; adding a third copy in ``dispatch`` would make the
eventual reconciliation harder, not easier.
"""

from __future__ import annotations

from dataclasses import dataclass

from grandpa.policy.models import ActionOrigin


@dataclass(frozen=True)
class RequestContext:
    """One request, as presented to the handler chain.

    Frozen for the same reason ``PolicyRequest`` and ``LocalActionRequest`` are:
    a context that could be edited between the handler that claimed it and the
    handler that ran it is a context whose provenance means nothing.

    ``dry_run`` carries the caller's intent to preview rather than act. It
    defaults to ``False`` because acting is the ordinary case and previewing is
    the deliberate one -- the opposite of ``origin``, where there is no
    ordinary case and every caller must say.

    **There is deliberately no ``surface`` field.** One was carried here from
    the first sketch and removed in 4.5G, having never been read or written by
    anything: the audit that preceded the removal found zero production
    consumers, no ``.surface`` read, no ``surface=`` write, and -- decisively --
    no vocabulary it could hold. ``ActionOrigin`` could not supply one, since
    two of its six values are already surface-shaped and four are
    initiator-shaped; the ``source`` label used elsewhere in the package is
    overloaded across roughly thirty-five unrelated meanings; and the
    architecture documents name entry surfaces in prose without ever agreeing
    on a set. The first consumer would therefore have had to invent the
    contract, which is the one thing a provenance-adjacent field must not be
    left to do.

    Modality still belongs beside provenance eventually -- that direction is
    recorded under P1a in ``TARGET_ARCHITECTURE.md``. It should return as a
    named vocabulary when something needs it, not as an empty string every
    caller fills in differently.
    """

    text: str
    origin: ActionOrigin
    dry_run: bool = False


__all__ = ["RequestContext"]
