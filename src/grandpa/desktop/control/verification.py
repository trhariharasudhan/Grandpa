"""Read device state back after an action to confirm it took effect.

``run_local_action`` used to report success whenever the actuator call returned
without raising. That is not the same as the action having happened: a volume
backend can be missing, a window can refuse focus, a clipboard write can be
swallowed by another application. For a voice user with no screen in front of
them the difference is invisible, and "Volume set to 50%" gets said either way.

This module answers one question -- *did the requested state actually come
about?* -- and nothing else. It performs no actuation, makes no policy
decisions, and never changes risk or approval. It reads, compares, and reports.

Two rules shape it:

* **Never claim verification that did not happen.** An action with no reliable
  read-back returns ``unknown``. So does a reader that is unavailable or that
  raises. ``unknown`` is not a failure -- it means "not checked" -- and leaves
  the actuator's own result alone.
* **Reuse the read APIs the actuators already use.** ``pycaw`` for volume,
  ``screen_brightness_control`` for brightness, ``pyperclip`` for the clipboard,
  the existing window helpers for focus and app state. Nothing new is
  introduced to make an action checkable.

File operations are judged on the filesystem itself: ``file_create``,
``file_delete``, ``file_move``, ``file_copy`` and ``file_rename`` read back the
paths the actuator reports, because ``Path.exists()`` is the least ambiguous
evidence available anywhere in this module and these are the actions where
being wrong costs the most.

Deliberately ``unknown``, with the reason:

``open_folder``
    Opening a folder surfaces an Explorer window whose title varies by view
    settings and localisation. Matching on it would be a guess.
keyboard, mouse, file and browser actions
    No read-back that distinguishes "it worked" from "it silently did nothing".
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal

VerificationStatus = Literal["verified", "failed", "unknown"]

#: Brightness hardware commonly lands a few percent off the requested value,
#: so an exact match would report false failures. Volume via pycaw is exact
#: enough not to need slack beyond rounding.
_BRIGHTNESS_TOLERANCE = 5
_VOLUME_TOLERANCE = 2

#: How much the volume must move before a relative change counts as real.
#: pycaw reports a float scalar that is rounded to a whole percent here, so a
#: reading can wobble by one without anything having happened. Windows' own
#: volume step is 2%, so 1 absorbs the rounding without masking a real press.
_RELATIVE_VOLUME_TOLERANCE = 1

#: Actions whose verification needs a reading from *before* execution.
#:
#: Relative changes cannot be judged from the end state alone -- 47% is neither
#: right nor wrong without knowing what it was before. Every other action is
#: absolute or idempotent and is checked from the post-state only.
#:
#: This set is deliberately tiny. The pre-read costs a device call on the
#: request path, so it is taken only where it is the difference between a real
#: answer and ``unknown``, never for all ~70 action types.
PRE_READ_ACTIONS = frozenset({"volume_up", "volume_down"})


@dataclass(frozen=True)
class VerificationOutcome:
    """What reading the state back showed."""

    status: VerificationStatus
    detail: str = ""
    expected: Any = None
    observed: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "detail": self.detail,
            "expected": self.expected,
            "observed": self.observed,
        }


_UNKNOWN = VerificationOutcome("unknown", "no reliable read-back for this action")


# ---------------------------------------------------------------------------
# State readers.
#
# Each returns None when the state cannot be read -- an optional backend is
# missing, or the platform does not support it. Module-level so tests can
# substitute them without touching real hardware.
# ---------------------------------------------------------------------------


def read_volume_percent() -> int | None:
    """Master volume 0-100, or None when the pycaw backend is unavailable."""
    try:
        from comtypes import CLSCTX_ALL  # type: ignore
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume  # type: ignore

        devices = AudioUtilities.GetSpeakers()
        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        volume = interface.QueryInterface(IAudioEndpointVolume)
        return int(round(volume.GetMasterVolumeLevelScalar() * 100))
    except Exception:
        return None


def read_muted() -> bool | None:
    """Whether the master output is muted, or None when unreadable."""
    try:
        from comtypes import CLSCTX_ALL  # type: ignore
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume  # type: ignore

        devices = AudioUtilities.GetSpeakers()
        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        volume = interface.QueryInterface(IAudioEndpointVolume)
        return bool(volume.GetMute())
    except Exception:
        return None


def read_brightness_percent() -> int | None:
    """Display brightness 0-100, or None when the backend is unavailable."""
    try:
        import screen_brightness_control as sbc  # type: ignore

        value = sbc.get_brightness()
        if isinstance(value, (list, tuple)):
            value = value[0] if value else None
        return None if value is None else int(value)
    except Exception:
        return None


def read_clipboard_text() -> str | None:
    """Current clipboard text, or None when the clipboard cannot be read."""
    try:
        import pyperclip  # type: ignore

        return str(pyperclip.paste())
    except Exception:
        return None


def read_foreground_title() -> str | None:
    """Title of the foreground window, or None when it cannot be read."""
    try:
        from grandpa.windows_window_control import (
            _get_foreground_window,
            _get_window_title,
        )

        handle = _get_foreground_window()
        if not handle:
            return None
        title = _get_window_title(handle)
        return title or None
    except Exception:
        return None


def read_window_show_state(target: str) -> dict[str, Any] | None:
    """Current maximized/minimized state of *target*, or None when unreadable.

    Resolved fresh at verification time through the same helper the window
    actions use, so "active" and title matching behave identically here. A
    window that vanished between acting and checking cannot be resolved and
    returns None, which the verifier reports as unknown rather than failure.
    """
    try:
        from grandpa.windows_window_control import read_window_state

        return read_window_state(target or "active")
    except Exception:
        return None


def read_path_exists(path: str) -> bool | None:
    """Whether *path* is on disk, or None when that cannot be answered.

    The only reader here whose evidence is unambiguous: a path either resolves
    to something or it does not. None is reserved for the cases where the
    question itself could not be asked -- an empty path, a name the platform
    rejects, a volume that is not responding -- and those are reported unknown
    rather than as a failed action.
    """
    if not path:
        return None
    try:
        return Path(path).expanduser().exists()
    except (OSError, ValueError):
        return None


def read_app_is_running(app_id: str) -> bool | None:
    """True when *app_id* is confirmed running, else None. Never False.

    Two positive signals: a pid recorded by the launcher, or a matching window
    on screen. Either confirms the launch.

    The absence of both is deliberately **not** reported as a failure. An
    application takes time to put a window on screen, so a check made
    immediately after launching would call a perfectly good launch a failure
    purely for being early -- and a false failure is worse than an honest
    "unchecked", which is the rule this whole module runs on.

    That distinction is not theoretical: returning False here made the result
    depend on what happened to be running on the machine, so a test that faked
    the launcher saw a successful action downgraded to failed depending on
    ambient desktop state.
    """
    if not app_id:
        return None
    try:
        from grandpa.windows_window_control import _matching_windows, get_launched_pids

        if get_launched_pids(app_id):
            return True
        if _matching_windows(app_id):
            return True
        return None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Per-action verifiers
# ---------------------------------------------------------------------------


def _requested_level(request: Any) -> int | None:
    args = getattr(request, "args", None) or {}
    raw = args.get("level", getattr(request, "target", "") or "")
    try:
        return max(0, min(100, int(raw)))
    except (TypeError, ValueError):
        return None


def _compare_number(
    expected: int | None, observed: int | None, tolerance: int, label: str
) -> VerificationOutcome:
    if expected is None:
        return VerificationOutcome("unknown", f"no requested {label} to compare")
    if observed is None:
        return VerificationOutcome(
            "unknown", f"{label} could not be read back", expected=expected
        )
    if abs(observed - expected) <= tolerance:
        return VerificationOutcome(
            "verified", f"{label} is {observed}", expected, observed
        )
    return VerificationOutcome(
        "failed", f"{label} is {observed}, expected {expected}", expected, observed
    )


def _verify_volume_set(request: Any, _response: Any) -> VerificationOutcome:
    return _compare_number(
        _requested_level(request), read_volume_percent(), _VOLUME_TOLERANCE, "volume"
    )


def _verify_brightness_set(request: Any, _response: Any) -> VerificationOutcome:
    return _compare_number(
        _requested_level(request),
        read_brightness_percent(),
        _BRIGHTNESS_TOLERANCE,
        "brightness",
    )


def _verify_mute(expected_muted: bool) -> Callable[[Any, Any], VerificationOutcome]:
    def _verify(_request: Any, _response: Any) -> VerificationOutcome:
        observed = read_muted()
        if observed is None:
            return VerificationOutcome("unknown", "mute state could not be read back")
        if observed is expected_muted:
            return VerificationOutcome(
                "verified", f"muted={observed}", expected_muted, observed
            )
        return VerificationOutcome(
            "failed",
            f"muted={observed}, expected {expected_muted}",
            expected_muted,
            observed,
        )

    return _verify


def _verify_clipboard_write(request: Any, _response: Any) -> VerificationOutcome:
    args = getattr(request, "args", None) or {}
    expected = str(args.get("content", getattr(request, "target", "") or ""))
    observed = read_clipboard_text()
    if observed is None:
        return VerificationOutcome("unknown", "clipboard could not be read back")
    if observed == expected:
        # The text itself is not recorded: the clipboard routinely holds
        # credentials, and this outcome is written to the audit log.
        return VerificationOutcome("verified", "clipboard matches the requested text")
    return VerificationOutcome("failed", "clipboard does not hold the requested text")


def _verify_clipboard_clear(_request: Any, _response: Any) -> VerificationOutcome:
    observed = read_clipboard_text()
    if observed is None:
        return VerificationOutcome("unknown", "clipboard could not be read back")
    if observed == "":
        return VerificationOutcome("verified", "clipboard is empty")
    return VerificationOutcome("failed", "clipboard is not empty")


def _verify_focus_window(request: Any, _response: Any) -> VerificationOutcome:
    target = str(getattr(request, "target", "") or "").strip().lower()
    if not target or target == "active":
        return VerificationOutcome("unknown", "no specific window was requested")
    observed = read_foreground_title()
    if observed is None:
        return VerificationOutcome("unknown", "foreground window could not be read")
    if target in observed.lower():
        return VerificationOutcome(
            "verified", "requested window is in the foreground", target, observed
        )
    return VerificationOutcome(
        "failed", f"foreground window is {observed!r}", target, observed
    )


def _verify_open_app(request: Any, _response: Any) -> VerificationOutcome:
    """Confirm a launch, or report unchecked -- never accuse it of failing.

    See ``read_app_is_running``: an application that has not yet drawn a window
    is indistinguishable from one that failed to start, and only a settle
    period would tell them apart. Waiting does not belong on the synchronous
    request path, so this confirms what it can and stays quiet otherwise.
    """
    target = str(getattr(request, "target", "") or "").strip()
    if read_app_is_running(target):
        return VerificationOutcome("verified", f"{target} is running", target, True)
    return VerificationOutcome(
        "unknown", f"could not confirm {target} is running yet", target
    )


def _verify_window_show_state(
    expected: Literal["maximized", "minimized", "restored"],
) -> Callable[[Any, Any], VerificationOutcome]:
    """Build a verifier for one window show-state.

    maximize -> IsZoomed, minimize -> IsIconic, restore -> neither. A window
    that cannot be resolved or read is unknown: it may have been closed by the
    user between the action and the check, which is not the action failing.
    """

    def _verify(request: Any, _response: Any) -> VerificationOutcome:
        target = str(getattr(request, "target", "") or "active")
        state = read_window_show_state(target)
        if not state:
            return VerificationOutcome(
                "unknown", "window state could not be read back", expected
            )

        maximized = state.get("maximized")
        minimized = state.get("minimized")
        if maximized is None or minimized is None:
            return VerificationOutcome(
                "unknown", "window show-state is unavailable", expected
            )

        observed = (
            "maximized" if maximized else "minimized" if minimized else "restored"
        )
        if observed == expected:
            return VerificationOutcome(
                "verified", f"window is {observed}", expected, observed
            )
        return VerificationOutcome(
            "failed", f"window is {observed}, expected {expected}", expected, observed
        )

    return _verify


def _evidence_path(response: Any, key: str) -> str:
    """One resolved path from the actuator's own evidence.

    Read from the response rather than the request on purpose.
    ``file_rename`` derives its destination inside the file service from
    ``args["new_name"]``, so the request does not know where the file went, and
    every path the service reports has already been through ``resolve_path``.
    Re-deriving them here would be a second, divergent answer to a question the
    actuator has already answered.
    """
    evidence = getattr(response, "evidence", None)
    if not isinstance(evidence, dict):
        return ""
    return str(evidence.get(key) or "").strip()


def _verify_file_create(_request: Any, response: Any) -> VerificationOutcome:
    path = _evidence_path(response, "path")
    exists = read_path_exists(path)
    if exists is None:
        return VerificationOutcome("unknown", "the path could not be read", path)
    if exists:
        return VerificationOutcome("verified", f"{path} exists", path, True)
    return VerificationOutcome("failed", f"{path} was not created", path, False)


def _verify_file_delete(_request: Any, response: Any) -> VerificationOutcome:
    path = _evidence_path(response, "path")
    exists = read_path_exists(path)
    if exists is None:
        return VerificationOutcome("unknown", "the path could not be read", path)
    if not exists:
        return VerificationOutcome("verified", f"{path} is gone", path, False)
    return VerificationOutcome("failed", f"{path} is still there", path, True)


def _verify_file_relocation(
    *, source_should_remain: bool, label: str
) -> Callable[[Any, Any], VerificationOutcome]:
    """Build a verifier for an action with a source and a destination.

    A move and a rename empty their source; a copy leaves it. Both require the
    destination to have arrived, and both are judged on the two readings
    together -- a destination alone would call a failed move successful, and a
    vanished source alone would call a lost file a success.

    One honest limit: when the destination given was an existing directory, the
    file lands *inside* it and the recorded destination existed beforehand, so
    that half of the check is weaker than it looks. The source reading still
    carries a move, and inventing a filename to probe for is not something this
    module does.
    """

    def _verify(_request: Any, response: Any) -> VerificationOutcome:
        source = _evidence_path(response, "from")
        destination = _evidence_path(response, "to")
        source_exists = read_path_exists(source)
        destination_exists = read_path_exists(destination)
        expected = f"{source} -> {destination}"
        if source_exists is None or destination_exists is None:
            return VerificationOutcome(
                "unknown", "the paths could not be read", expected
            )

        problems: list[str] = []
        if source_exists is not source_should_remain:
            problems.append(
                f"{source} is still there" if source_exists else f"{source} is missing"
            )
        if not destination_exists:
            problems.append(f"{destination} was not created")
        if problems:
            return VerificationOutcome(
                "failed", "; ".join(problems), expected, destination_exists
            )
        return VerificationOutcome("verified", f"{label} {expected}", expected, True)

    return _verify


_VERIFIERS: dict[str, Callable[[Any, Any], VerificationOutcome]] = {
    "file_create": _verify_file_create,
    "file_delete": _verify_file_delete,
    "file_move": _verify_file_relocation(source_should_remain=False, label="moved"),
    "file_rename": _verify_file_relocation(source_should_remain=False, label="renamed"),
    "file_copy": _verify_file_relocation(source_should_remain=True, label="copied"),
    "volume_set": _verify_volume_set,
    "volume_mute": _verify_mute(True),
    "volume_unmute": _verify_mute(False),
    "brightness_set": _verify_brightness_set,
    "clipboard_write": _verify_clipboard_write,
    "clipboard_clear": _verify_clipboard_clear,
    "focus_window": _verify_focus_window,
    "open_app": _verify_open_app,
    "maximize_window": _verify_window_show_state("maximized"),
    "minimize_window": _verify_window_show_state("minimized"),
    "restore_window": _verify_window_show_state("restored"),
}


def capture_pre_state(request: Any) -> dict[str, Any] | None:
    """Read the state a relative action will be judged against, or None.

    Called immediately before ``_execute`` for the few actions in
    ``PRE_READ_ACTIONS``. Everything else returns None **without touching any
    device**, which is what keeps this off the request path for the other
    action types.

    A reader that is unavailable or raises also returns None, and the verifier
    then reports ``unknown`` -- the same conservative default used everywhere
    else here. Failing to take a baseline is never treated as the action
    having failed.
    """
    action_type = str(getattr(request, "action_type", "") or "")
    if action_type not in PRE_READ_ACTIONS:
        return None
    try:
        volume = read_volume_percent()
    except Exception:
        return None
    if volume is None:
        return None
    return {"volume": int(volume)}


def _verify_relative_volume(
    direction: Literal["up", "down"],
) -> Callable[[Any, Any, dict[str, Any] | None], VerificationOutcome]:
    """Build a verifier comparing the volume against its pre-execute reading."""

    def _verify(
        _request: Any, _response: Any, pre_state: dict[str, Any] | None
    ) -> VerificationOutcome:
        before = (pre_state or {}).get("volume")
        if before is None:
            return VerificationOutcome(
                "unknown", "no volume reading was taken before the change"
            )
        after = read_volume_percent()
        if after is None:
            return VerificationOutcome(
                "unknown", "volume could not be read back", before
            )

        delta = after - before
        expected = f"{direction} from {before}"
        if abs(delta) <= _RELATIVE_VOLUME_TOLERANCE:
            return VerificationOutcome(
                "failed", f"volume is still {after}", expected, after
            )
        moved_up = delta > 0
        if moved_up == (direction == "up"):
            return VerificationOutcome(
                "verified", f"volume moved from {before} to {after}", expected, after
            )
        return VerificationOutcome(
            "failed",
            f"volume moved from {before} to {after}, the wrong direction",
            expected,
            after,
        )

    return _verify


#: Verifiers that need the pre-execute reading, keyed the same way as the
#: post-state-only ones but taking a third argument.
_RELATIVE_VERIFIERS: dict[
    str, Callable[[Any, Any, dict[str, Any] | None], VerificationOutcome]
] = {
    "volume_up": _verify_relative_volume("up"),
    "volume_down": _verify_relative_volume("down"),
}


def verify_action(
    request: Any, response: Any, pre_state: dict[str, Any] | None = None
) -> VerificationOutcome:
    """Read state back for *request* and report whether it took effect.

    ``pre_state`` carries the reading taken before execution, for the relative
    actions that need one; it defaults to None so existing two-argument callers
    keep working and simply get ``unknown`` for those actions.

    Returns ``unknown`` for any action without a verifier, and for any reader
    that fails -- a verification step must never turn a working action into a
    reported failure because a backend was missing.
    """
    action_type = str(getattr(request, "action_type", "") or "")
    try:
        relative = _RELATIVE_VERIFIERS.get(action_type)
        if relative is not None:
            return relative(request, response, pre_state)
        verifier = _VERIFIERS.get(action_type)
        if verifier is None:
            return _UNKNOWN
        return verifier(request, response)
    except Exception as exc:  # a reader failing is not the action failing
        return VerificationOutcome(
            "unknown", f"verification unavailable: {type(exc).__name__}"
        )


def aggregate_plan_verification(
    step_metadata: Iterable[Any],
) -> VerificationOutcome:
    """Summarise a multi-step plan from the evidence its steps already carry.

    Each entry is one step's ``result_metadata`` -- the dict ``ExecutivePlanner``
    copies off ``StepResult.data``, which is where a step's
    ``LocalActionResponse.evidence`` ends up. Nothing is verified here; this
    only reads what the run already produced, so an action with no read-back
    stays unknown exactly as it does on the single-action path.

    Precedence is ``failed`` > ``unknown`` > ``verified``:

    * one step that demonstrably did not happen makes the sequence a failure,
      whatever the other steps did, and
    * a step with no evidence -- most planner steps, since browser and vision
      actions have no device read-back -- counts as unknown. Absence of
      evidence must never be reported as success, which is the whole reason
      the aggregate exists.

    ``verified`` therefore means every step was positively confirmed, and only
    then.
    """
    failures: list[str] = []
    unknown = False
    verified = 0
    total = 0

    for metadata in step_metadata or ():
        total += 1
        verification = (
            metadata.get("verification") if isinstance(metadata, dict) else None
        )
        status = (
            str(verification.get("status") or "").strip().lower()
            if isinstance(verification, dict)
            else ""
        )
        detail = (
            str(verification.get("detail") or "").strip().rstrip(".")
            if isinstance(verification, dict)
            else ""
        )
        if status == "failed":
            failures.append(detail or "a step did not take effect")
        elif status == "verified":
            verified += 1
        else:
            unknown = True

    if failures:
        return VerificationOutcome("failed", "; ".join(failures), total, verified)
    if unknown or total == 0:
        return VerificationOutcome(
            "unknown", "not every step could be confirmed", total, verified
        )
    return VerificationOutcome("verified", "every step was confirmed", total, verified)


def verification_sentence(status: str, detail: str, message: str) -> str:
    """Phrase *message* according to what verification found.

    The single vocabulary for both the single-action and the plan paths, so
    they cannot drift into describing the same three states differently.

    ``verified``
        The plain message. It has been confirmed, so there is nothing to hedge.
    ``failed``
        Lead with the failure. In speech the opening words are what get heard,
        and messages like "Task completed." or "Window maximized." start by
        sounding like success.
    ``unknown``
        Say what ran and that confirmation was not available -- neither a claim
        of success nor an accusation of failure.

    Anything unrecognised returns *message* untouched, so a caller that has no
    verification to report keeps its existing wording.
    """
    detail = str(detail or "").strip().rstrip(".")
    if status == "failed":
        if detail:
            return f"I tried that, but it did not take effect: {detail}."
        return "I tried that, but it did not take effect."
    if status == "unknown":
        spoken = str(message or "").strip()
        if spoken and not spoken.endswith((".", "!", "?")):
            spoken = f"{spoken}."
        return f"{spoken} I could not confirm it took effect.".strip()
    return message


def verifiable_actions() -> tuple[str, ...]:
    """Action types this module can check. Used by tests and diagnostics."""
    return tuple(sorted(set(_VERIFIERS) | set(_RELATIVE_VERIFIERS)))


__all__ = [
    "PRE_READ_ACTIONS",
    "VerificationOutcome",
    "VerificationStatus",
    "read_app_is_running",
    "read_brightness_percent",
    "read_clipboard_text",
    "read_foreground_title",
    "read_muted",
    "read_window_show_state",
    "read_volume_percent",
    "capture_pre_state",
    "verifiable_actions",
    "verify_action",
]
