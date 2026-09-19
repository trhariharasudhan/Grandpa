"""The natural-language front end to the action layer.

``local_actions`` parsed a phrase and then performed it itself, through its own
``_execute`` dispatch and its own approval store. This module is where that
second half goes instead: a parsed phrase is mapped to a catalogued action and
performed by the layer, so the risk tier, whether to ask, and the audit record
are the layer's -- the same for chat, voice, the scheduler and the server.

It is being filled in a tranche at a time. ``MIGRATED`` names the parsed shapes
that have moved; anything not in it still falls through to the legacy dispatch,
which is how each tranche can land, be tested end to end, and be committed on
its own.

What does **not** move here, deliberately, is the order of the guards in front
of a phrase. ``local_actions`` refuses a phrase containing "delete", "registry",
"password" and similar before any parser sees it. The catalogue has no such
text-level check, so a phrase routed around it would lose it. Mapping happens
*after* that guard, in the same place the legacy dispatch ran, so no tranche
reopens it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

__all__ = [
    "MIGRATED",
    "PhraseResult",
    "request_for",
    "run_parsed",
]

ConfirmCallback = Callable[[str, str], bool]
"""A caller's prompt: (what will happen, tier) -> approved."""


@dataclass(frozen=True)
class PhraseResult:
    """What a caller reads back, in the shape ``local_actions`` always returned."""

    status: str
    kind: str | None = None
    target: str = ""
    message: str = ""
    tts_text: str = ""
    permission: str | None = None
    pending_action: dict[str, Any] | None = None

    @property
    def should_fallback(self) -> bool:
        return self.status == "no_match"


# --- which parsed shapes have moved -------------------------------------------
#
# Keyed on the (kind, target) a local_actions parser produced. A value is the
# catalogued action and the parameters to send it. A callable value builds them
# from the target, for shapes whose target carries an argument.

MappedRequest = tuple[str, dict[str, Any]]

MIGRATED: dict[tuple[str, str], MappedRequest | Callable[[str], MappedRequest]] = {
    # --- tranche 1: reads that change nothing and ask nothing ----------------
    #
    # Cheapest and safest first. For every one of these both routes reached
    # the same underlying service, and none is in pc_control's approval set,
    # so there was no guard on one side missing from the other. Two answers do
    # change: "show installed apps" listed the resolver's ten-app allowlist,
    # not what is installed, and now reads the real inventory; and the page
    # reads answer from the browser_awareness analyzer, which owns page reading
    # since Phase 1.5.
    ("time", "local_time"): ("datetime_now", {"kind": "time"}),
    ("system_info", "system_info"): ("system_info", {}),
    ("app_lookup", "installed_apps"): ("apps_list", {}),
    ("window", "list|windows"): ("list_windows", {}),
    ("browser", "context|active"): ("browser_context", {}),
    ("browser", "tabs|recent"): ("browser_tabs", {}),
    ("browser", "diagnostics|browser"): ("browser_diagnostics", {}),
    ("browser", "summary|visible"): ("browser_summary", {}),
    ("browser", "headings|visible"): ("browser_headings", {}),
    ("browser", "links|visible"): ("browser_links", {}),
    ("browser", "buttons|visible"): ("browser_buttons", {}),
    ("pc_control", "list_monitors|monitors"): ("list_monitors", {}),
    ("pc_control", "active_process|active"): ("active_process", {}),
    ("pc_control", "list_processes|processes"): ("list_processes", {}),
    ("pc_control", "desktop_summary|desktop"): ("desktop_summary", {}),
    ("pc_control", "pc_diagnostics|diagnostics"): ("pc_diagnostics", {}),
    ("pc_control", "clipboard_inspect|clipboard"): ("clipboard_inspect", {}),
    ("pc_control", "clipboard_history|clipboard"): ("clipboard_history", {}),
    # --- tranche 2: the screen, by OCR -----------------------------------
    #
    # Reads, but the most sensitive ones in the product: a screenshot is
    # whatever is on the display. Guard compared, and one was missing on
    # both routes -- see capture_screenshot.
    ("screenshot", "screen"): ("screen_capture", {}),
    ("screen", "screen_context"): ("screen_describe", {}),
    ("screen", "active_window"): ("screen_active_window", {}),
    ("screen", "screen_diagnostics"): ("screen_diagnostics", {}),
}
"""Filled a tranche at a time; see the phase report for the order."""


def _app_lookup(name: str) -> MappedRequest:
    # "where is chrome installed". detect_app asks the same resolver and gives
    # the same sentence, word for word.
    return ("detect_app", {"app": name})


def _window(action: str) -> Callable[[str], MappedRequest]:
    def build(target: str) -> MappedRequest:
        return (action, {"window": target or "active"})

    return build


_PREFIXED: dict[tuple[str, str], Callable[[str], MappedRequest]] = {
    # --- tranche 3: windows ---------------------------------------------------
    #
    # Both routes called the same control_window, which already refuses to
    # close Task Manager, Windows Security, Registry Editor, an administrator
    # shell or a terminal -- local_actions blocked "close task manager" a step
    # earlier as well, but the function below it would have refused anyway. No
    # hole. Closing asks on both routes since the tier decisions in this phase.
    ("window", "focus|"): _window("focus_window"),
    ("window", "minimize|"): _window("minimize_window"),
    ("window", "maximize|"): _window("maximize_window"),
    ("window", "restore|"): _window("restore_window"),
    ("window", "close|"): _window("close_window"),
}
"""Shapes matched by kind and target *prefix*, e.g. ("window", "focus|")."""


def _open_app(name: str) -> MappedRequest:
    # "open chrome". local_actions called launch_app itself, around the
    # application service's rule that starting a browser asks first -- so
    # "open chrome" from voice, the scheduler or the HTTP API just started it.
    return ("open_app", {"app": name})


def _open_folder(path: str) -> MappedRequest:
    # "open C:\Users\...\.ssh". local_actions called os.startfile after a yes,
    # with no protected-path check; open_folder refuses .ssh, the browser
    # profile store, and the rest of pc_control's protected set.
    return ("open_folder", {"path": path})


_BY_KIND: dict[str, Callable[[str], MappedRequest]] = {
    # tranche 1
    "app_lookup": _app_lookup,
    # tranche 4: launching
    "app": _open_app,
    "folder": _open_folder,
}
"""Shapes matched by kind alone, when the target is the argument itself.

Checked last, so an exact entry above -- ("app_lookup", "installed_apps") --
wins over the kind-wide one.
"""


def request_for(kind: str | None, target: str) -> MappedRequest | None:
    """The catalogued action for a parsed shape, or None if it has not moved."""
    if not kind:
        return None
    exact = MIGRATED.get((kind, target))
    if exact is not None:
        return exact(target) if callable(exact) else exact
    for (prefix_kind, prefix), build in _PREFIXED.items():
        if kind == prefix_kind and target.startswith(prefix):
            return build(target[len(prefix) :])
    by_kind = _BY_KIND.get(kind)
    if by_kind is not None and target:
        return by_kind(target)
    return None


def _layer_confirm(confirm: ConfirmCallback | None):
    """Adapt a caller's (spec, tier) prompt to the layer's callback."""
    if confirm is None:
        return None

    def ask(action: str, parameters: Any, risk: Any) -> bool:
        plan = parameters.get("_plan") if hasattr(parameters, "get") else None
        if not plan:
            detail = ", ".join(
                f"{key}={value!r}"
                for key, value in sorted(dict(parameters).items())
                if not str(key).startswith("_")
            )
            plan = action + (f" ({detail})" if detail else "")
        tier = getattr(risk, "value", str(risk))
        return bool(confirm(str(plan), f"{tier} risk"))

    return ask


def run_parsed(
    kind: str | None,
    target: str,
    *,
    confirm: ConfirmCallback | None = None,
    execute: bool = True,
    deferred_origin: str | None = None,
    confirmed: bool = False,
    summary: str | None = None,
    require_consent: bool = False,
) -> PhraseResult | None:
    """Perform a parsed phrase through the layer, or return None if not migrated.

    How an action that needs consent gets it -- three cases, and only three:

    * ``confirm`` given: the caller asks inline. Chat and the tool loop.
    * no ``confirm``, ``deferred_origin`` given: the caller has opted into
      deferred consent. The action is staged in the kernel's approval store,
      bound to that origin, and runs only when that origin says yes on a later
      turn. Voice opts in; nothing else does by default.
    * neither: refused, and nothing is staged. Absence of a callback never
      means "stage it and let something approve it later" -- that is the
      property verify_confirmation_enforcement's P1 probe proves for the tool
      path, and it holds here too.

    ``confirmed=True`` is for running an action whose consent was already given
    by an approval; ``execute=False`` describes what would happen and does
    nothing, as ``local_actions`` callers have always used it.

    ``require_consent`` asks even where the catalogue would not. local_actions
    passes it when its own rule was stricter -- an unknown folder asks there,
    and open_folder does not -- so moving a phrase onto the layer never makes
    it ask less than it did.
    """
    mapped = request_for(kind, target)
    if mapped is None:
        return None

    from grandpa.action_layer.catalogue import get
    from grandpa.action_layer.executor import execute as execute_action
    from grandpa.action_layer.model import ActionRequest, Origin

    name, parameters = mapped
    spec = get(name)
    needs_consent = spec.requires_confirmation or require_consent
    permission = "requires_confirmation" if needs_consent else "allowed"

    if not execute:
        # A dry run says what *would* happen, and for an action that asks, what
        # would happen first is the question. local_actions has always answered
        # "requires_confirmation" here; reporting "handled" for everything made a
        # confirmation-gated action look as if it would simply run.
        return PhraseResult(
            status="requires_confirmation" if needs_consent else "handled",
            kind=kind,
            target=target,
            message=f"Would run {name}.",
            tts_text=f"Would run {name}.",
            permission=permission,
        )

    wording = summary or f"Confirmation required before running {name}."

    if needs_consent and not confirmed and confirm is None:
        if not deferred_origin:
            # No one to ask and no opt-in: refuse, and stage nothing.
            return PhraseResult(
                status="blocked",
                kind=kind,
                target=target,
                message=f"{wording} There is no way to ask for that here, so "
                "nothing was run.",
                tts_text="I need your confirmation for that, and cannot ask here.",
                permission=permission,
            )
        from grandpa.desktop.kernel import approvals

        staged = approvals.stage_deferred(
            origin=deferred_origin,
            action=name,
            target=target,
            parameters=dict(parameters),
            payload={"kind": kind, "target": target},
            risk_level=spec.risk.value,
        )
        return PhraseResult(
            status="requires_confirmation",
            kind=kind,
            target=target,
            message=f"{wording}\n\nReply with yes/confirm to approve, or cancel to "
            f"deny.\nAction ID: {staged['id']}",
            tts_text=wording,
            permission=permission,
            pending_action=staged,
        )

    request = ActionRequest(
        name,
        dict(parameters),
        origin=Origin.USER_CHAT,
        risk=spec.risk,
        requires_confirmation=needs_consent,
    )
    if confirmed:
        # Consent was given by an approval of exactly this action; passing it
        # through rather than asking a second time.
        result = execute_action(request, lambda *_a, **_k: True)
    else:
        result = execute_action(request, _layer_confirm(confirm))

    if result.success:
        status = "handled"
    elif result.error in {"confirmation_declined"}:
        status = "cancelled"
    elif result.error in {"confirmation_required"}:
        status = "requires_confirmation"
    elif (
        result.error in {"unsupported"}
        or str(result.data.get("status")) == "unsupported"
    ):
        status = "unsupported"
    elif result.error in {
        "blocked",
        "blocked_by_policy",
        "protected_path",
        "protected_window",
        "browser_not_in_front",
    }:
        status = "blocked"
    else:
        status = "error"

    return PhraseResult(
        status=status,
        kind=kind,
        target=target,
        message=result.message,
        tts_text=result.message,
        permission=permission,
    )
