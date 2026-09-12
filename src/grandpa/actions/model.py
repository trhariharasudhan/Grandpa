"""The data contract for the single action layer.

Pure data. This module executes nothing, touches no I/O, and imports nothing
from ``pc_control``, ``local_actions``, ``desktop_automation`` or any handler --
that direction of dependency is what the layer exists to remove. Everything
downstream (the catalogue, the tool-schema export, and later the dispatcher)
depends only on the four types defined here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

__all__ = ["ActionRequest", "ActionResult", "Origin", "RiskLevel"]

_EMPTY: Mapping[str, Any] = MappingProxyType({})


class Origin(str, Enum):
    """Who asked for an action.

    Origin says *where the request came from*, never how dangerous it is --
    risk is a property of the action (see :class:`RiskLevel`). The same
    ``file_delete`` is equally destructive whether a person typed it or a model
    chose it. Origin exists so a caller can apply its own policy on top (for
    example, requiring confirmation for anything a model initiated) and so the
    audit trail can say who was responsible.
    """

    USER_CLI = "user_cli"
    """Typed at the command line (``python -m grandpa.cli ...``)."""

    USER_CHAT = "user_chat"
    """Typed into an interactive chat session."""

    USER_VOICE = "user_voice"
    """Spoken, and transcribed by the voice stack."""

    MODEL = "model"
    """Chosen by the language model as a tool call."""

    AGENT = "agent"
    """Issued by a managed agent running on the user's behalf."""

    SKILL = "skill"
    """Issued from inside a skill or workflow definition."""

    HTTP = "http"
    """Arrived over the local HTTP/API surface."""

    PLAN = "plan"
    """A step of a previously approved multi-step plan."""

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


class RiskLevel(str, Enum):
    """How dangerous an action is.

    These are exactly the four tiers ``grandpa.pc_control`` already defines --
    ``RiskLevel = Literal["LOW", "MEDIUM", "HIGH", "BLOCKED"]``
    (``src/grandpa/pc_control.py``), backed there by ``LOW_RISK_ACTIONS``,
    ``MEDIUM_RISK_ACTIONS``, ``HIGH_RISK_ACTIONS`` and ``BLOCKED_ACTIONS``.
    This is a mirror, not a new scale: the names and the values match, and
    ``tests/actions/test_catalogue_coverage.py`` fails if the two ever disagree
    about a given action.

    It is mirrored rather than imported because importing ``pc_control`` would
    pull the approval store, the audit log and the whole desktop import cycle
    into every consumer of this contract.
    """

    LOW = "LOW"
    """Reads state or makes an easily reversed change. No confirmation."""

    MEDIUM = "MEDIUM"
    """Changes something the user would notice. Reversible with effort."""

    HIGH = "HIGH"
    """Destroys data or ends the session. Confirmation always required."""

    BLOCKED = "BLOCKED"
    """Never performed, whoever asks. Present so refusals are explicit."""

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


@dataclass(frozen=True, slots=True)
class ActionRequest:
    """One action someone wants performed, with everything needed to judge it.

    Immutable on purpose: a request that has been risk-rated and shown to a
    user for confirmation must be the same request that later executes.
    """

    action: str
    """Catalogue name of the action, e.g. ``"volume_set"``."""

    parameters: Mapping[str, Any] = field(default_factory=lambda: _EMPTY)
    """Arguments, matching the catalogue entry's JSON schema."""

    origin: Origin = Origin.USER_CLI
    """Who asked."""

    risk: RiskLevel = RiskLevel.BLOCKED
    """The action's tier. Defaults to ``BLOCKED`` for the same reason
    ``pc_control._classify_risk_impl`` returns ``BLOCKED`` for an unknown
    action: an unrated request is not a safe request."""

    requires_confirmation: bool = True
    """Whether a human must approve before this runs. Defaults to ``True`` so
    a request built without consulting the catalogue errs towards asking."""

    def __post_init__(self) -> None:
        object.__setattr__(self, "origin", Origin(self.origin))
        object.__setattr__(self, "risk", RiskLevel(self.risk))
        object.__setattr__(self, "parameters", MappingProxyType(dict(self.parameters)))


@dataclass(frozen=True, slots=True)
class ActionResult:
    """What happened when an action was attempted."""

    success: bool
    """``True`` only if the action actually took effect."""

    message: str = ""
    """One line a person can read."""

    data: Mapping[str, Any] = field(default_factory=lambda: _EMPTY)
    """Structured detail for a caller or a model to act on."""

    error: str | None = None
    """Why it failed. ``None`` on success."""

    def __post_init__(self) -> None:
        object.__setattr__(self, "data", MappingProxyType(dict(self.data)))

    @classmethod
    def ok(cls, message: str = "", /, **data: Any) -> ActionResult:
        """A result that succeeded."""
        return cls(success=True, message=message, data=data)

    @classmethod
    def failed(cls, error: str, /, message: str = "", **data: Any) -> ActionResult:
        """A result that did not take effect."""
        return cls(success=False, message=message or error, data=data, error=error)
