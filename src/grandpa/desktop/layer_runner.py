"""A parsed desktop payload, performed by the action layer.

Voice Operator Mode and the desktop runtime skills both parsed or stored a
``pc_action_type`` and handed it to ``pc_control.run_local_action``. Those were
doors to a catalogued capability that did not go through the layer: pc_control
decided the tier, the approval and the audit, while chat's identical phrase was
decided by the catalogue. They agreed, action for action, when they were
compared -- but two policies agreeing today is a coincidence maintained by hand,
and every hole this phase has found was two routes to one capability.

The answer keeps ``pc_control``'s shape (``ok``, ``status``, ``message``,
``evidence``), because that is what the callers read.

No confirmation callback is handed over. Neither caller can be asked at the
moment of action -- voice's only question is the next utterance, and a stored
workflow step has nobody present at all -- so an action the catalogue asks about
is refused here rather than performed, and synthetic input is refused by the
layer itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from grandpa.action_layer.catalogue import get

INVENTORY_TARGETS = frozenset({"apps_search", "apps_is_running", "apps_restart"})
"""Inventory actions that take what the user named; the rest take nothing."""


def parameters_for(spec_name: str, target: str, args: dict[str, Any]) -> dict[str, Any]:
    """The catalogued parameters for a parsed desktop action.

    One translation, shared by chat's desktop route, voice operator mode and
    the desktop runtime skills: they all read the same parser's output, and
    two translations of it is the shape of bug this phase keeps finding.
    """
    parameters = {
        key: value for key, value in (args or {}).items() if value not in (None, "")
    }

    if spec_name in INVENTORY_TARGETS:
        return {"query": target} if target else {}
    if spec_name.startswith("apps_"):
        return {}
    if spec_name == "open_app":
        parameters["app"] = target
        return parameters
    if spec_name == "volume_set":
        # The parser puts the level in args; the catalogue names it "level".
        if "level" not in parameters and target:
            parameters["level"] = target
        return parameters
    # Only where the catalogue actually declares one. The parser fills target
    # for its own convenience -- system_lock carries "lock", empty_recycle_bin
    # carries "recycle_bin" -- and passing that to an action that takes no
    # parameters would be rejected as an unknown one.
    key = get(spec_name).target_parameter
    if target and key:
        parameters.setdefault(key, target)
    return parameters


@dataclass(frozen=True)
class DesktopActionResponse:
    """``pc_control.LocalActionResponse``'s shape, filled from an ActionResult."""

    ok: bool
    action_id: str | None
    status: str
    message: str
    approval_required: bool
    risk_level: str
    evidence: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "action_id": self.action_id,
            "status": self.status,
            "message": self.message,
            "approval_required": self.approval_required,
            "risk_level": self.risk_level,
            "evidence": dict(self.evidence),
            "error": self.error,
        }


_STATUS_BY_ERROR = {
    "confirmation_required": "approval_required",
    "confirmation_declined": "rejected",
    "blocked": "blocked",
    "blocked_by_policy": "blocked",
    "protected_path": "blocked",
    "protected_window": "blocked",
    "inline_consent_required": "blocked",
    "unsupported": "unsupported",
}


def run_through_the_layer(payload: dict[str, Any]) -> Any:
    """Perform one parsed desktop action through the action layer."""
    from grandpa.action_layer.catalogue import get
    from grandpa.action_layer.executor import execute
    from grandpa.action_layer.model import ActionRequest, Origin

    action = str(payload.get("action_type") or "")
    try:
        spec = get(action)
    except KeyError:
        # Not in the catalogue, which for this door means refused. The names
        # that land here are the ones the catalogue excludes on purpose: the
        # blocked capabilities (script_run, shell_run, file_permanent_delete,
        # the purchase and credential browser actions) and the browser stubs
        # that never completed anything. Falling back to pc_control would be
        # reopening the second door this module exists to close.
        return DesktopActionResponse(
            ok=False,
            action_id=None,
            status="unsupported",
            message=f"I can't do {action.replace('_', ' ')} from here.",
            approval_required=False,
            risk_level="BLOCKED",
            evidence={"action_type": action},
            error="unsupported",
        )

    # One translation of the parser's output, shared with chat's desktop route:
    # the parser puts a volume level in target, names an app there too, and
    # fills target for actions that take no parameter at all.
    parameters = parameters_for(
        action, str(payload.get("target") or ""), dict(payload.get("args") or {})
    )

    if payload.get("dry_run"):
        return DesktopActionResponse(
            ok=True,
            action_id=None,
            status="dry_run",
            message=f"Would run {action}.",
            approval_required=False,
            risk_level=spec.risk.value,
            evidence={"would_execute": True, "action_type": action},
        )

    result = execute(
        ActionRequest(
            action,
            parameters,
            origin=Origin.USER_VOICE,
            risk=spec.risk,
            requires_confirmation=spec.requires_confirmation
            or bool(payload.get("require_approval")),
        ),
        # No callback: a spoken turn cannot answer a question asked mid-action.
        None,
    )
    status = (
        "completed"
        if result.success
        else _STATUS_BY_ERROR.get(str(result.error or ""), "failed")
    )
    return DesktopActionResponse(
        ok=result.success,
        action_id=None,
        status=status,
        message=result.message,
        approval_required=status == "approval_required",
        risk_level=spec.risk.value,
        evidence=dict(result.data),
        error=result.error,
    )


__all__ = ["DesktopActionResponse", "parameters_for", "run_through_the_layer"]
