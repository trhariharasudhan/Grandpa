"""Nothing actuates in a test unless the test says so.

Six times in one session a test or probe changed a real machine: Notepad
opened, brightness changed, a Ctrl+C sent to the foreground window, Notepad
again, the master volume set to 30%, the screen locked. Each time the fix was
to add that category to a recorder -- which is a list of the things that have
already gone wrong, so the next category nobody thought of runs live.

This is the other way round. Every implementation the catalogue names is
replaced before each test, whatever it does, along with the low-level
primitives underneath them. The catalogue is the source of the list, so an
action added next month is covered the day it exists, by nobody's diligence.

A test that genuinely needs a real implementation says so:

    @pytest.mark.real_actions(reason="drives the notes store under tmp_path")

The reason is required, and it is read by a person, so it should say why the
real thing is needed and what stops it reaching the machine.

Denial raises :class:`ActuationDenied`, which derives from ``BaseException`` on
purpose: the code under test is full of ``except Exception`` handlers that turn
failures into friendly sentences, and a denial that gets turned into "I could
not complete that action" is a denial nobody sees.
"""

from __future__ import annotations

import ctypes
import importlib
import sys
from typing import Any

MARKER = "real_actions"


class ActuationDenied(BaseException):
    """A test reached a real implementation without asking for one."""


def _message(label: str) -> str:
    return (
        f"{label} was called in a test. Nothing actuates by default. If this "
        f"test needs the real implementation, mark it:\n"
        f'    @pytest.mark.{MARKER}(reason="why, and what keeps it off the machine")'
    )


def _deny(label: str):
    def denied(*_args: Any, **_kwargs: Any) -> Any:
        raise ActuationDenied(_message(label))

    denied.__actuation_denied__ = label  # type: ignore[attr-defined]
    return denied


def reason_for(marker: Any) -> str:
    """The marker's reason, or raise: an opt-out without one explains nothing.

    ``@pytest.mark.real_actions`` is how a test says it needs the real
    implementation. Whoever reads it next needs to know why, and what keeps the
    real implementation off the machine -- a temp directory, a fake window, a
    recorder underneath it.
    """
    reason = marker.kwargs.get("reason") or (marker.args[0] if marker.args else "")
    if not str(reason).strip():
        raise ValueError(
            f"@pytest.mark.{MARKER} needs a reason: why this test uses the real "
            "implementation, and what keeps it off the machine."
        )
    return str(reason)


def _resolve(dotted: str) -> tuple[object, str] | None:
    """Split ``a.b.C.method`` or ``a.b.func`` into the owner and attribute."""
    parts = dotted.split(".")
    for cut in range(len(parts) - 1, 0, -1):
        module_name = ".".join(parts[:cut])
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            continue
        owner: object = module
        for attribute in parts[cut:-1]:
            owner = getattr(owner, attribute, None)
            if owner is None:
                return None
        return (owner, parts[-1]) if hasattr(owner, parts[-1]) else None
    return None


def catalogued_targets() -> dict[str, tuple[object, str]]:
    """Every implementation the catalogue names, resolved to owner and attribute."""
    from grandpa.action_layer.catalogue import get, names

    targets: dict[str, tuple[object, str]] = {}
    for action in names():
        implementation = get(action).implementation
        if implementation in targets:
            continue
        resolved = _resolve(implementation)
        if resolved is not None:
            targets[implementation] = resolved
    return targets


# The primitives underneath the catalogue: reached directly by code that has
# not moved onto the action layer yet, and by anything that bypasses it.
PYAUTOGUI_NAMES = (
    "write",
    "typewrite",
    "hotkey",
    "press",
    "keyDown",
    "keyUp",
    "click",
    "leftClick",
    "doubleClick",
    "tripleClick",
    "rightClick",
    "middleClick",
    "mouseDown",
    "mouseUp",
    "moveTo",
    "moveRel",
    "move",
    "dragTo",
    "dragRel",
    "drag",
    "scroll",
    "hscroll",
    "vscroll",
    "screenshot",
)
USER32_NAMES = (
    "keybd_event",
    "SendInput",
    "mouse_event",
    "SetCursorPos",
    "SendMessageW",
    "PostMessageW",
    "SetForegroundWindow",
    "BringWindowToTop",
    "ShowWindow",
    "LockWorkStation",
    "ExitWindowsEx",
    "SetThreadExecutionState",
)
# Deliberately not here: os.remove, shutil.rmtree, subprocess.run and friends.
# pytest itself uses them for temp directories, and Grandpa's own file deletion
# is a catalogued action (file_delete), already denied above. Popen is listed
# because it is what actually starts a program -- subprocess.run goes through
# it, so patching it covers both.
MODULE_NAMES = {
    "webbrowser": ("open", "open_new", "open_new_tab"),
    "subprocess": ("Popen",),
    "os": ("startfile", "system"),
}
GRANDPA_NAMES = {
    "grandpa.windows_window_control": (
        "_apply_action",
        "_request_notepad_document_close",
        "invoke_dialog_choice",
        "invoke_uia_controls_by_id",
    ),
    "grandpa.automation.windows": (
        "focus_window_handle",
        "close_window_identity",
        "invoke_window_control_sequence",
    ),
    "grandpa.windows_app_resolver": ("launch_app",),
}


def primitive_targets() -> list[tuple[object, str, str]]:
    """The low-level actuators, as ``(owner, attribute, label)``."""
    found: list[tuple[object, str, str]] = []
    try:
        import pyautogui

        found += [(pyautogui, name, f"pyautogui.{name}") for name in PYAUTOGUI_NAMES]
    except Exception:  # pragma: no cover - not installed everywhere
        pass
    if sys.platform == "win32":
        user32 = ctypes.windll.user32
        found += [(user32, name, f"user32.{name}") for name in USER32_NAMES]
        found.append(
            (ctypes.windll.shell32, "SHEmptyRecycleBinW", "shell32.SHEmptyRecycleBinW")
        )
    for module_name, attributes in MODULE_NAMES.items():
        module = importlib.import_module(module_name)
        found += [
            (module, name, f"{module_name}.{name}")
            for name in attributes
            if hasattr(module, name)
        ]
    for module_name, attributes in GRANDPA_NAMES.items():
        try:
            module = importlib.import_module(module_name)
        except ImportError:  # pragma: no cover
            continue
        found += [
            (module, name, f"{module_name}.{name}")
            for name in attributes
            if hasattr(module, name)
        ]
    return found


def deny_everything(monkeypatch, *, skip: set[str] | None = None) -> int:
    """Replace every catalogued implementation and primitive. Returns the count."""
    skipped = skip or set()
    replaced = 0
    for label, (owner, attribute) in catalogued_targets().items():
        if label in skipped:
            continue
        monkeypatch.setattr(owner, attribute, _deny(label), raising=False)
        replaced += 1
    for owner, attribute, label in primitive_targets():
        if label in skipped:
            continue
        monkeypatch.setattr(owner, attribute, _deny(label), raising=False)
        replaced += 1
    return replaced


def is_denied(owner: object, attribute: str) -> bool:
    return bool(getattr(getattr(owner, attribute, None), "__actuation_denied__", None))


__all__ = [
    "MARKER",
    "ActuationDenied",
    "catalogued_targets",
    "deny_everything",
    "is_denied",
    "primitive_targets",
]


# ---------------------------------------------------------------------------
# The marker is function-scope only
# ---------------------------------------------------------------------------

SCOPE_ERROR = """\
@pytest.mark.{marker} is function-scope only, and these apply it to a whole
module or class:

{offenders}
The marker switches off both guards -- nothing-actuates and the write bound --
so its reason is the only thing between a test and the machine it runs on. A
reason attached to a file cannot be true of every test in the file:
tests/cli/test_chat_cmd.py claimed "against the store under the test's own
GRANDPA_HOME" for 107 tests, and one of them wrote a traceback into a real
~/.grandpa/server.log. The sentence was true of most of them and false of that
one, and nothing on the file could tell them apart.

Mark the tests that need it, one at a time, and say what each one reaches:

    @pytest.mark.{marker}(reason="drives the real X; kept off the machine by Y")
    def test_one_thing(): ...
"""


def scope_violations(items: list[Any]) -> dict[str, list[str]]:
    """Which collected tests inherit the marker rather than carrying it.

    ``own_markers`` holds only what was applied to the test function itself, so a
    marker in ``iter_markers`` but not in ``own_markers`` came from a module-level
    ``pytestmark`` or from a class.
    """
    offenders: dict[str, list[str]] = {}
    for item in items:
        own = {mark.name for mark in getattr(item, "own_markers", [])}
        if MARKER in own:
            continue
        if next(item.iter_markers(MARKER), None) is not None:
            where = str(getattr(item, "location", ("?",))[0])
            offenders.setdefault(where, []).append(item.name)
    return offenders


def scope_error_message(offenders: dict[str, list[str]]) -> str:
    listing = "\n".join(
        f"  {where}  ({len(names)} tests)" for where, names in sorted(offenders.items())
    )
    return SCOPE_ERROR.format(marker=MARKER, offenders=listing + "\n")
