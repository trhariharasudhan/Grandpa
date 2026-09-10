"""Risk classification and approval policy for PC-control actions."""

from __future__ import annotations

from typing import Any


def classify(request: Any) -> str:
    from grandpa import pc_control

    return pc_control._classify_risk_impl(request)


def requires_approval(request: Any) -> bool:
    """Whether the boundary would stage this request for approval.

    A *view* of the policy, not a second implementation of it. Enforcement
    stays inline in ``pc_control._run_local_action_impl``; this reports what
    that gate would decide, and every clause here mirrors one of its.

    The sensitive-launch clause is what keeps them in step. Without it this
    answered ``False`` for ``open_app terminal`` while the gate staged it --
    the HIGH tier was covered, the MEDIUM half of ``SENSITIVE_APP_RISK`` was
    not. A predicate that looks authoritative and is more permissive than
    enforcement is worse than no predicate at all.

    Delegates to ``grandpa.policy.engine``, on the same terms as ``classify``
    above: the rule moved, the policy did not. The tables still travel as an
    argument because ``policy`` imports nothing from ``pc_control``, so this
    keeps holding the data while ``policy`` states what to do with it.
    """
    from grandpa import pc_control
    from grandpa.policy.engine import requires_approval as _policy_requires_approval

    return _policy_requires_approval(request, pc_control._risk_tables())


def readiness() -> dict[str, Any]:
    from grandpa import pc_control

    return {
        "status": "ready",
        "low_risk_actions": len(pc_control.LOW_RISK_ACTIONS),
        "medium_risk_actions": len(pc_control.MEDIUM_RISK_ACTIONS),
        "high_risk_actions": len(pc_control.HIGH_RISK_ACTIONS),
        "blocked_actions": len(pc_control.BLOCKED_ACTIONS),
    }
