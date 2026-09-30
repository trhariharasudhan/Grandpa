"""Building and stubbing focus witnesses, without a live desktop.

A witness is a reading of the foreground window. Tests need to control what that
reading says -- including "it could not be read" -- and to make the second reading
differ from the first in exactly one field, so a tier can be shown to be the thing
doing the refusing.

Nothing here touches the real desktop: ``stub_capture`` replaces
``focus_witness.capture`` entirely, so no test depends on which window happens to
be in front of whoever is running the suite.
"""

from __future__ import annotations

from typing import Any, Iterable

from grandpa.desktop import focus_witness
from grandpa.desktop.focus_witness import Witness

#: A plausible Notepad reading. Every field is named so a test can change one.
NOTEPAD: dict[str, Any] = {
    "hwnd": 0x1234,
    "pid": 4242,
    "exe_path": r"c:\windows\system32\notepad.exe",
    "class_name": "Notepad",
    "rect": (100, 100, 900, 700),
    "control_id": "",
    "captured_at": 1_000_000.0,
    "title": "Untitled - Notepad",
}


def make_witness(**overrides: Any) -> Witness:
    """A witness built from NOTEPAD, with ``overrides`` applied.

    ``title`` and ``title_digest`` are kept consistent unless a test overrides the
    digest itself: a witness whose digest does not match its own title would make
    the soft tier fire for the wrong reason.
    """
    fields = dict(NOTEPAD)
    fields.update(overrides)
    title = str(fields.pop("title", ""))
    digest = fields.pop("title_digest", None)
    return Witness(
        hwnd=int(fields["hwnd"]),
        pid=int(fields["pid"]),
        exe_path=str(fields["exe_path"]),
        class_name=str(fields["class_name"]),
        rect=tuple(fields["rect"]),  # type: ignore[arg-type]
        title_digest=str(digest)
        if digest is not None
        else focus_witness.title_digest(title),
        control_id=str(fields["control_id"]),
        captured_at=float(fields["captured_at"]),
        title=title,
    )


def stub_capture(monkeypatch, readings: Iterable[Witness | None]) -> list[str]:
    """Make ``focus_witness.capture`` return each reading in turn.

    Returns the list of ``control_target`` values it was asked for, so a test can
    check that the control tier was given the action's own control rather than a
    blank. Running past the end of ``readings`` raises rather than repeating the
    last one: a test that captured more times than it meant to should say so.
    """
    remaining = list(readings)
    asked: list[str] = []

    def capture(*, control_target: str = "") -> Witness | None:
        asked.append(control_target)
        if not remaining:
            raise AssertionError(
                "focus_witness.capture was called more times than this test "
                f"supplied readings for (asked for {asked})"
            )
        return remaining.pop(0)

    monkeypatch.setattr(focus_witness, "capture", capture)
    return asked


__all__ = ["NOTEPAD", "make_witness", "stub_capture"]
