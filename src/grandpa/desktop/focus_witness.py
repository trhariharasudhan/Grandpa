"""What a staged keystroke was approved against, so it can be checked again.

A keystroke lands on whatever holds focus at the instant it is sent, not when the
approval arrived. That is why synthetic input was never staged for a later yes:
consent given a turn ago is consent for a screen that may no longer be there.

A witness turns "consent a turn ago" into "consent for *this* screen". It records
what the foreground window was when the action was staged, and the same reading is
taken again before the action runs. If the hard fields differ, the approval is not
for what is in front of the user now.

Tiered on purpose, because a window title changes constantly -- clocks tick,
unsaved markers appear, tab counts change, "(2) Inbox" becomes "(3) Inbox":

* **Identity** (hard): ``hwnd``, ``pid``, ``exe_path``, ``class_name``. A
  relaunched application is a mismatch even though its path is the same: a new
  process is a new session with different content.
* **Geometry** (hard, only for coordinate-bearing actions): ``rect``. A window
  that moved five pixels invalidates approved coordinates. Actions that follow
  focus rather than pixels -- typing, hotkeys, arrow keys -- do not compare it.
* **Control** (hard, when the action named one): ``control_id``. Resolved by
  looking the control up again, so a control that vanished or changed type is a
  mismatch rather than a string that trivially equals itself.
* **Title** (soft, never decisive): ``title_digest``, over a *normalised* title.
  A normalised-title change alone is not a mismatch. It is recorded, and it is
  what the spoken read-back names.

A witness that cannot be captured -- at staging or at redemption -- is a
mismatch, not a pass, for the same reason the commit guard records an
unobtainable digest as "unavailable" rather than as a blank that matches.
"""

from __future__ import annotations

import hashlib
import os
import re
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Callable

#: Catalogued actions whose parameters carry screen coordinates. Only these
#: compare geometry: a moved window invalidates an approved (x, y), while a
#: keystroke follows focus and does not care where the window sits.
GEOMETRY_ACTIONS = frozenset({"mouse_click", "mouse_drag", "mouse_move"})

#: The only origins that may stage synthetic input against a witness.
#:
#: A witness is one of three preconditions, not the whole mechanism. The other
#: two are that the approval is redeemable on the *next* turn only, and that a
#: spoken read-back names the window before anything is sent. Both of those need
#: a loop with turns and a voice; a witness handed to a caller that has neither
#: is a keystroke approved by something nobody heard describe it.
#:
#: So this is an allowlist, not a capability check, and it is deliberately not
#: "any origin that can produce a witness":
#:
#: * ``voice`` is here because it *cannot* ask inline -- its only question is the
#:   next utterance -- and because it has turns and speaks. Deferred consent with
#:   a witness is the only shape of consent available to it.
#: * ``chat`` is not, and not because it is less trusted. Chat *can* ask inline
#:   and does: Screen Automation V2 prompts in the same turn and refuses on "n",
#:   which verify_confirmation_enforcement's P5b probe pins. An inline question
#:   answered now is strictly better evidence than a witness re-checked later, so
#:   giving chat the deferred path would replace a stronger mechanism with a
#:   weaker one.
#: * ``http`` is not, because it has no turns and no user in the loop. "The next
#:   turn" is meaningless when the next request may come from anywhere, and there
#:   is nobody to read a read-back to.
#:
#: Widening this set means arguing that the new origin has all three, not just
#: the witness.
WITNESS_ORIGINS = frozenset({"voice"})


def may_carry_a_witness(origin: str | None) -> bool:
    """Whether ``origin`` may stage synthetic input against a witness."""
    return bool(origin) and origin in WITNESS_ORIGINS


_MISSING = "<no-witness>"


def geometry_matters(action: str) -> bool:
    """Whether ``action``'s approval is tied to where the window is."""
    return action in GEOMETRY_ACTIONS


# --- the title, normalised ----------------------------------------------------

_UNSAVED_MARKERS = ("*", "●", "•", "▪")
_COUNTER = re.compile(r"\(\s*\d+\s*\)")
_CLOCK = re.compile(r"\b\d{1,2}:\d{2}(:\d{2})?\s*(am|pm)?\b", re.IGNORECASE)
_ELAPSED = re.compile(r"\b\d+\s*(ms|s|sec|secs|seconds|min|mins|minutes)\b", re.I)


def normalise_title(title: str) -> str:
    """Strip what changes on its own, so only a real change registers.

    Raw title equality is unusable as a signal: an unsaved marker appears, a
    clock ticks, an unread counter increments. What is left after this is stable
    while the user is looking at the same thing.
    """
    text = str(title or "")
    for marker in _UNSAVED_MARKERS:
        text = text.replace(marker, " ")
    text = _COUNTER.sub(" ", text)
    text = _CLOCK.sub(" ", text)
    text = _ELAPSED.sub(" ", text)
    return " ".join(text.split()).casefold()


def title_digest(title: str) -> str:
    normalised = normalise_title(title)
    return hashlib.sha256(normalised.encode("utf-8", "replace")).hexdigest()


# --- the witness --------------------------------------------------------------


@dataclass(frozen=True)
class Witness:
    """One reading of the foreground window."""

    hwnd: int
    pid: int
    exe_path: str
    class_name: str
    rect: tuple[int, int, int, int]
    title_digest: str
    control_id: str
    #: Wall clock, not a monotonic reading, and not compared by anything.
    #:
    #: It was meant to feed the expiry. It does not: a row expires on the store's
    #: single TTL and on the turn counter, both of which live on the row rather
    #: than in here, so comparing this would be a second expiry policy wearing a
    #: different hat. It is recorded because the audit trail should be able to say
    #: when the screen was read, and it is wall clock because the witness is
    #: persisted to sqlite and read back in another process, where a monotonic
    #: value means nothing.
    captured_at: float
    #: Kept for the spoken read-back, which has to name the window a person can
    #: see. Never compared -- the digest above is the comparison.
    title: str = ""

    @property
    def app_name(self) -> str:
        """What to call the application out loud.

        ``exe_path`` is normcased, because Windows paths compare
        case-insensitively and the comparison is the field's real job. That makes
        it lower case, which reads wrong in a sentence, so the stem is
        recapitalised here: "notepad" and "OUTLOOK" both become the form a person
        would write. A name that is already mixed case is left alone, since
        ``capitalize`` would turn "VSCode" into "Vscode".
        """
        stem = os.path.splitext(os.path.basename(self.exe_path))[0]
        if not stem:
            return "an unknown application"
        if stem.islower() or stem.isupper():
            return stem.capitalize()
        return stem

    def to_dict(self) -> dict[str, Any]:
        return {
            "hwnd": self.hwnd,
            "pid": self.pid,
            "exe_path": self.exe_path,
            "class_name": self.class_name,
            "rect": list(self.rect),
            "title_digest": self.title_digest,
            "control_id": self.control_id,
            "captured_at": self.captured_at,
            "title": self.title,
        }

    @classmethod
    def from_dict(cls, data: Any) -> "Witness | None":
        if not isinstance(data, dict) or not data:
            return None
        try:
            rect = tuple(int(value) for value in (data.get("rect") or (0, 0, 0, 0)))
            if len(rect) != 4:
                return None
            return cls(
                hwnd=int(data["hwnd"]),
                pid=int(data["pid"]),
                exe_path=str(data["exe_path"]),
                class_name=str(data["class_name"]),
                rect=rect,  # type: ignore[arg-type]
                title_digest=str(data["title_digest"]),
                control_id=str(data.get("control_id") or ""),
                captured_at=float(data["captured_at"]),
                title=str(data.get("title") or ""),
            )
        except (KeyError, TypeError, ValueError):
            # A stored witness we cannot read is not a witness. Returning None
            # makes it a mismatch rather than something that compares equal to
            # whatever comes next.
            return None


# --- capture ------------------------------------------------------------------


def _foreground_reading() -> dict[str, Any] | None:
    """hwnd, pid, class name, rect and title of the foreground window."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        hwnd = int(user32.GetForegroundWindow())
        if not hwnd:
            return None
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

        class_buffer = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, class_buffer, 256)

        rect = wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return None

        length = int(user32.GetWindowTextLengthW(hwnd))
        title_buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, title_buffer, length + 1)

        return {
            "hwnd": hwnd,
            "pid": int(pid.value),
            "class_name": class_buffer.value,
            "rect": (int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)),
            "title": title_buffer.value,
        }
    except Exception:  # noqa: BLE001 - an unreadable window is a failed capture
        return None


def _executable_for(pid: int) -> str:
    try:
        import psutil  # type: ignore

        return os.path.normcase(str(psutil.Process(pid).exe() or ""))
    except Exception:  # noqa: BLE001 - no path means no identity
        return ""


def _resolve_control_uia(hwnd: int, control_target: str) -> str:
    """Identity of ``control_target`` inside ``hwnd`` right now, or "" if absent.

    Looked up rather than carried, so the control tier can fail. A control_id
    copied from the staged action would compare equal to itself and prove
    nothing.
    """
    try:
        from grandpa.vision.uia import UiAutomationExtractor
    except Exception:  # noqa: BLE001 - UIA unavailable
        return ""
    try:
        wanted = normalise_title(control_target)
        for node in UiAutomationExtractor().extract(hwnd) or ():
            element = getattr(node, "element", node)
            candidates = {
                normalise_title(str(getattr(element, "automation_id", "") or "")),
                normalise_title(str(getattr(element, "name", "") or "")),
                normalise_title(str(getattr(element, "text", "") or "")),
            }
            if wanted and wanted in candidates:
                return (
                    f"{getattr(element, 'automation_id', '')}"
                    f"|{getattr(element, 'type', '')}"
                    f"|{normalise_title(str(getattr(element, 'name', '') or ''))}"
                )
    except Exception:  # noqa: BLE001 - a lookup that errored found nothing
        return ""
    return ""


#: Replaceable so the control tier is testable without a live desktop. Production
#: resolves through UIA; a test supplies its own.
CONTROL_RESOLVER: Callable[[int, str], str] = _resolve_control_uia


def capture(*, control_target: str = "") -> Witness | None:
    """Read the foreground window, or None if it cannot be read.

    ``control_target`` is the control the action names, if it names one. When it
    is given and cannot be resolved, capture fails: an action aimed at a control
    that is not there has nothing to be approved against.
    """
    reading = _foreground_reading()
    if reading is None:
        return None
    executable = _executable_for(int(reading["pid"]))
    if not executable:
        # No identity, no witness. exe_path is the field that actually says which
        # application this is; hwnd and pid are reused by the OS.
        return None
    control_id = ""
    if control_target:
        control_id = CONTROL_RESOLVER(int(reading["hwnd"]), control_target)
        if not control_id:
            return None
    return Witness(
        hwnd=int(reading["hwnd"]),
        pid=int(reading["pid"]),
        exe_path=executable,
        class_name=str(reading["class_name"]),
        rect=tuple(reading["rect"]),  # type: ignore[arg-type]
        title_digest=title_digest(str(reading["title"])),
        control_id=control_id,
        captured_at=time.time(),
        title=str(reading["title"]),
    )


# --- comparison ---------------------------------------------------------------


@dataclass(frozen=True)
class Comparison:
    """Whether a staged witness still describes what is in front of the user."""

    matched: bool
    #: Hard fields that differ, in the order they were checked.
    differences: tuple[str, ...] = ()
    #: True when the normalised title moved but nothing hard did. Not a mismatch;
    #: carried so the read-back and the audit record can mention it.
    title_drifted: bool = False
    reason: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


def compare(
    staged: Witness | None,
    current: Witness | None,
    *,
    action: str,
) -> Comparison:
    """Compare two readings for ``action``.

    A missing witness on either side is a mismatch. That is the whole point of
    treating a failed capture as a refusal: the alternative is a blank that
    matches anything.
    """
    if staged is None and current is None:
        return Comparison(
            False,
            (_MISSING,),
            reason="neither the staged nor the current window could be read",
        )
    if staged is None:
        return Comparison(
            False,
            (_MISSING,),
            reason="nothing recorded what this was approved against",
        )
    if current is None:
        return Comparison(
            False,
            (_MISSING,),
            reason="the foreground window could not be read now",
        )

    differences: list[str] = []
    if staged.hwnd != current.hwnd:
        differences.append("hwnd")
    if staged.pid != current.pid:
        differences.append("pid")
    if staged.exe_path != current.exe_path:
        differences.append("exe_path")
    if staged.class_name != current.class_name:
        differences.append("class_name")
    if geometry_matters(action) and staged.rect != current.rect:
        differences.append("rect")
    # Control is hard only when the action named one. When it did, the staged
    # value was resolved from the live tree, and so is this one.
    if staged.control_id or current.control_id:
        if staged.control_id != current.control_id:
            differences.append("control_id")

    drifted = staged.title_digest != current.title_digest
    if differences:
        return Comparison(
            False,
            tuple(differences),
            title_drifted=drifted,
            reason=_describe(differences, staged, current),
            extra={"staged_title": staged.title, "current_title": current.title},
        )
    return Comparison(
        True,
        (),
        title_drifted=drifted,
        reason="",
        extra={"staged_title": staged.title, "current_title": current.title},
    )


def _describe(differences: list[str], staged: Witness, current: Witness) -> str:
    """A reason a person can act on, naming the application rather than a field."""
    if "exe_path" in differences:
        return f"the window changed from {staged.app_name} to {current.app_name}"
    if "pid" in differences:
        return f"{staged.app_name} was restarted since you asked"
    if "hwnd" in differences or "class_name" in differences:
        return f"a different {staged.app_name} window is in front now"
    if "rect" in differences:
        return f"the {staged.app_name} window moved or was resized"
    if "control_id" in differences:
        return "the control that was approved is no longer there"
    return "the foreground window changed"


__all__ = [
    "CONTROL_RESOLVER",
    "GEOMETRY_ACTIONS",
    "Comparison",
    "Witness",
    "capture",
    "compare",
    "geometry_matters",
    "normalise_title",
    "title_digest",
]
