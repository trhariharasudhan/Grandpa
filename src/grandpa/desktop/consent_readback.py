"""What Grandpa says out loud before sending a keystroke, and after refusing one.

With no screen, the read-back *is* the confirmation interface. Three rules, and
each is here because leaving it out loses something a person needs:

* **The application is always named.** The witness exists because the window can
  change between the ask and the yes; a prompt that does not say which window is
  a prompt the user cannot check.
* **Present continuous.** "Typing X into Y" is plainly about to happen. "Shall I
  type X" invites a yes to a hypothetical.
* **A mismatch says what did NOT happen first.** "I did not type anything" is the
  part the user most needs, before any offer to do it against the new window.

The wordings are asserted verbatim by tests, because the exact sentence is the
product here.
"""

from __future__ import annotations

from typing import Any

from grandpa.desktop.focus_witness import Witness

#: Human phrasing per catalogued synthetic action, in the present continuous.
#: ``{what}`` is filled from the action's own parameters.
_PHRASING = {
    "keyboard_type": "Typing {what}",
    "keyboard_hotkey": "Pressing {what}",
    "mouse_click": "Clicking {what}",
    "mouse_drag": "Dragging {what}",
    "mouse_move": "Moving the pointer {what}",
    "mouse_scroll": "Scrolling {what}",
    "desktop_navigate": "Moving the selection {what}",
}


def _what(action: str, parameters: dict[str, Any]) -> str:
    """The part of the sentence that describes the action's own payload."""
    if action == "keyboard_type":
        return str(parameters.get("text") or parameters.get("target") or "").strip()
    if action == "keyboard_hotkey":
        return str(parameters.get("keys") or parameters.get("target") or "").strip()
    if action in {"mouse_click", "mouse_move"}:
        name = str(parameters.get("control") or "").strip()
        x, y = parameters.get("x"), parameters.get("y")
        where = f"at {x} across and {y} down" if x is not None and y is not None else ""
        if name and where:
            return f"the {name} {where}".strip()
        return (name or where).strip()
    if action == "mouse_drag":
        return (
            f"from {parameters.get('start_x')}, {parameters.get('start_y')} "
            f"to {parameters.get('end_x')}, {parameters.get('end_y')}"
        )
    if action == "mouse_scroll":
        amount = parameters.get("amount")
        try:
            notches = int(amount)
        except (TypeError, ValueError):
            return ""
        return "up" if notches > 0 else "down"
    if action == "desktop_navigate":
        return str(parameters.get("direction") or "").strip()
    return str(parameters.get("target") or "").strip()


def _verb_phrase(action: str, parameters: dict[str, Any]) -> str:
    template = _PHRASING.get(action, "Running {what}")
    what = _what(action, parameters)
    phrase = template.format(what=what).strip()
    # "Typing  into Notepad" reads as a bug; drop the empty slot instead.
    return " ".join(phrase.split())


def _window_clause(witness: Witness) -> str:
    """ "into Notepad, the window titled Untitled" -- or just the app if untitled."""
    title = " ".join(str(witness.title or "").split())
    if title:
        return f"{witness.app_name}, the window titled {title}"
    return witness.app_name


def _consent_sentence(action: str) -> str:
    if action in {"keyboard_type", "keyboard_hotkey", "desktop_navigate"}:
        return "Say yes to send those keystrokes, or cancel."
    if action == "mouse_click":
        return "Say yes to click, or cancel."
    if action == "mouse_drag":
        return "Say yes to drag, or cancel."
    if action == "mouse_scroll":
        return "Say yes to scroll, or cancel."
    return "Say yes to go ahead, or cancel."


def ask(action: str, parameters: dict[str, Any], witness: Witness) -> str:
    """The read-back spoken when a synthetic action is staged.

    Example, for ``keyboard_type`` with text "transfer approved" in Outlook::

        Typing transfer approved into Outlook, the window titled Untitled
        Message. Say yes to send those keystrokes, or cancel.
    """
    preposition = "in" if action.startswith("mouse") else "into"
    return (
        f"{_verb_phrase(action, parameters)} {preposition} "
        f"{_window_clause(witness)}. {_consent_sentence(action)}"
    )


def reask(
    action: str,
    parameters: dict[str, Any],
    staged: Witness,
    current: Witness,
) -> str:
    """The read-back when the window changed and the action is offered again.

    Takes no ``reason``: the spoken sentence says which application it is now and
    which it was, which is the only form of "why" a listener can act on. The
    field-level reason from ``focus_witness.compare`` goes in the written message
    and the audit record, where it can be read.

    Leads with what did not happen. Example::

        The window changed since you asked -- it is Chrome now, not Notepad. I
        did not type anything. Say yes to type hello into Chrome instead, or
        cancel.
    """
    # The application is named twice already -- once as what it is now, once as
    # what it was -- so the offer names it without the title clause the staging
    # read-back carries. A third repetition of the same window reads as padding,
    # and padding is what stops people listening to the part that matters.
    return (
        f"The window changed since you asked - it is {current.app_name} now, "
        f"not {staged.app_name}. {_did_not_happen(action)} "
        f"Say yes to {_offer(action, parameters)} {current.app_name} "
        f"instead, or cancel."
    )


def _did_not_happen(action: str) -> str:
    if action == "keyboard_type":
        return "I did not type anything."
    if action in {"keyboard_hotkey", "desktop_navigate"}:
        return "I did not send any keys."
    if action == "mouse_click":
        return "I did not click."
    if action == "mouse_drag":
        return "I did not drag anything."
    if action == "mouse_scroll":
        return "I did not scroll."
    if action == "mouse_move":
        return "I did not move the pointer."
    return "I did not do it."


def _offer(action: str, parameters: dict[str, Any]) -> str:
    """ "type hello into" / "click the Delete button in" -- lower case, mid-sentence."""
    phrase = _verb_phrase(action, parameters)
    lowered = phrase[:1].lower() + phrase[1:] if phrase else phrase
    verbs = {
        "Typing": "type",
        "Pressing": "press",
        "Clicking": "click",
        "Dragging": "drag",
        "Scrolling": "scroll",
    }
    for gerund, plain in verbs.items():
        if phrase.startswith(gerund):
            lowered = plain + phrase[len(gerund) :]
            break
    preposition = "in" if action.startswith("mouse") else "into"
    return f"{lowered} {preposition}"


def refuse(action: str) -> str:
    """The read-back when a second mismatch drops the action for good.

    One re-ask per intent. A window changing every turn must not become an
    endless prompt, because that is exactly how "yes" becomes a reflex.

    Names no window deliberately: by this point two different ones have been in
    front, so naming either would be misleading. What the user needs is that
    nothing happened and that the next move is theirs.
    """
    said = _did_not_happen(action)
    return (
        f"The window changed again, so I have stopped asking. {said} "
        f"Tell me once more when the right window is in front."
    )


def cannot_witness(action: str) -> str:
    """The read-back when no witness could be taken at all."""
    return (
        f"I could not tell which window is in front, so I will not send that. "
        f"{_did_not_happen(action)}"
    )


__all__ = ["ask", "cannot_witness", "reask", "refuse"]
