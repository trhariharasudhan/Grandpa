"""Map a chat phrase to a catalogued desktop action.

This branch is the one that deletes a path rather than adding one. ``DesktopParser``
already produced a ``pc_action_type`` -- ``open_app``, ``minimize_window``,
``volume_set`` -- and ``DesktopExecutor`` turned that into a ``pc_control``
payload and ran it. Every one of those names is in the catalogue, pointing at
the same implementation, so the payload-building, the status coercion and the
message formatting were a second way of doing what the layer already does.

The parser stays. What goes is the executor path behind it.

**The guard that came with it.** ``desktop/automation.py`` asked before starting
a browser and refused when there was nobody to ask. Nothing else did: ``open_app``
was catalogued LOW with no confirmation, so a model could start a browser without
a word. The rule now lives in ``desktop.control.applications``, the implementation
every route calls, and pc_control gates it through its own approval flow -- so the
migration carries the guard rather than dropping it.
"""

from __future__ import annotations

from typing import Any

from grandpa.action_layer.catalogue import get
from grandpa.action_layer.model import ActionRequest, Origin

__all__ = ["INVENTORY_TARGETS", "build_desktop_request"]

INVENTORY_TARGETS = frozenset({"apps_search", "apps_is_running", "apps_restart"})
"""Inventory actions that take what the user named; the rest take nothing."""


def _parameters(spec_name: str, target: str, args: dict[str, Any]) -> dict[str, Any]:
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


def build_desktop_request(text: str) -> tuple[ActionRequest | None, Any]:
    """The request for ``text``, or ``(None, None)`` when this is not for us."""
    from grandpa.desktop.automation import DesktopParser

    parsed = DesktopParser().parse(text)
    if parsed is None:
        return None, None

    name = parsed.pc_action_type
    try:
        spec = get(name)
    except KeyError:
        # The parser produced something the catalogue has not been told about.
        # Falling through leaves the phrase to the handlers below rather than
        # answering it with a guess.
        return None, None

    return (
        ActionRequest(
            name,
            _parameters(name, str(parsed.target or ""), dict(parsed.args or {})),
            origin=Origin.USER_CHAT,
            risk=spec.risk,
            requires_confirmation=spec.requires_confirmation,
        ),
        parsed,
    )
