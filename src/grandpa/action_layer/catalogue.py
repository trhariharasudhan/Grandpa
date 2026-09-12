"""One entry per action Grandpa can actually perform today.

The list is built from the audit's feature table
(``docs/audit/FEATURE-INVENTORY.md`` section 2) crossed with the four risk
tables in ``grandpa.pc_control``. Two rules decide what is in it:

* **Only what exists.** Every entry names the function that performs it, and
  ``tests/action_layer/test_catalogue_coverage.py`` resolves that dotted path. There
  are no entries for capabilities Grandpa does not have (process kill, software
  install, registry write) and none for the stubs the audit found -- those are
  in :data:`EXCLUSIONS` with a reason.
* **Including the orphans.** ``volume_*``, ``brightness_*``, ``clipboard_*``,
  ``file_create`` and ``desktop_navigate`` are implemented but no user-facing
  route reaches them. They are capabilities that exist, so they are catalogued;
  this layer is how they get a route later.

Risk comes from one table and one rule, never from a per-entry opinion: the
tier is ``pc_control``'s tier for that action, and confirmation is required
exactly when ``pc_control`` would require approval -- ``risk == HIGH`` or the
action is in ``APPROVAL_REQUIRED_ACTIONS`` (``pc_control.py`` lines 306-310).

Implementations are dotted-path *strings*. Nothing here imports ``pc_control``,
``local_actions``, ``desktop_automation`` or any handler: the catalogue
describes the existing stacks without depending on them.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from grandpa.action_layer.model import RiskLevel

__all__ = [
    "ActionSpec",
    "CATALOGUE",
    "EXCLUSIONS",
    "counts_by_risk",
    "get",
    "names",
]


# --- who performs what -------------------------------------------------------
#
# Dotted paths into the current implementations, as strings. These are the
# functions ``pc_control._execute`` dispatches to (``pc_control.py`` lines
# 713-900), except ``_OPEN_FOLDER``, which pc_control still performs inline.

_APPLICATIONS = "grandpa.desktop.control.applications.ApplicationControlService.execute"
_WINDOWS = "grandpa.desktop.control.windows.WindowControlService.execute"
_WINDOW_ALIAS = "grandpa.desktop.control.windows.WindowControlService.execute_alias"
_VOLUME = "grandpa.desktop.control.power.PowerControlService.execute_volume"
_BRIGHTNESS = "grandpa.desktop.control.power.PowerControlService.execute_brightness"
_SYSTEM = "grandpa.desktop.control.power.PowerControlService.execute_system"
_RECYCLE_BIN = (
    "grandpa.desktop.control.power.PowerControlService.execute_empty_recycle_bin"
)
_CLIPBOARD = "grandpa.desktop.control.clipboard.ClipboardControlService.execute"
_MONITORS = "grandpa.desktop.control.monitors.MonitorControlService.execute"
_DIAGNOSTICS = "grandpa.desktop.control.diagnostics.DesktopDiagnosticsService.execute"
_FILES = "grandpa.desktop.control.files.FileControlService.execute"
_AUTOMATION = "grandpa.desktop.control.automation.AutomationControlService.execute"
_BROWSER = "grandpa.browser_control.execute_browser_action"
_OPEN_FOLDER = "grandpa.pc_control._execute_open_folder"


# --- the one confirmation rule -----------------------------------------------

_ALWAYS_CONFIRM = frozenset(
    {
        # Mirrors pc_control.APPROVAL_REQUIRED_ACTIONS. Synthetic input is
        # arbitrary code execution in practice, so it is gated on approval
        # rather than by inflating its tier; mouse_move and mouse_scroll are
        # deliberately not in the set, because neither activates anything.
        "keyboard_type",
        "keyboard_hotkey",
        "mouse_click",
        "mouse_drag",
        # browser_form_fill and browser_download are in pc_control's set too,
        # but are excluded from this catalogue as stubs -- see EXCLUSIONS.
    }
)


def _confirmation_for(name: str, risk: RiskLevel) -> bool:
    """Exactly pc_control's gate: HIGH, or on the approval-required list."""
    return risk is RiskLevel.HIGH or name in _ALWAYS_CONFIRM


# --- schema helpers ----------------------------------------------------------


def _schema(
    properties: Mapping[str, Any] | None = None,
    required: tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": dict(properties or {}),
        "required": list(required),
        "additionalProperties": False,
    }


def _string(description: str, **extra: Any) -> dict[str, Any]:
    return {"type": "string", "description": description, **extra}


def _integer(description: str, **extra: Any) -> dict[str, Any]:
    return {"type": "integer", "description": description, **extra}


_NO_PARAMS = _schema()


@dataclass(frozen=True, slots=True)
class ActionSpec:
    """One catalogued action: what it is, how risky, and who performs it."""

    name: str
    """Action name, matching ``pc_control``'s risk tables."""

    description: str
    """One line a person -- or a model choosing a tool -- can read."""

    parameters: Mapping[str, Any]
    """JSON Schema (draft 2020-12 subset) for the action's arguments."""

    risk: RiskLevel
    """The tier ``pc_control`` assigns this action."""

    requires_confirmation: bool
    """Whether a human must approve before it runs."""

    implementation: str
    """Dotted path to the function that performs it. Never imported here."""

    notes: str = ""
    """Anything a caller should know that the description cannot carry."""

    def __post_init__(self) -> None:
        object.__setattr__(self, "parameters", MappingProxyType(dict(self.parameters)))


def _spec(
    name: str,
    risk: RiskLevel,
    description: str,
    implementation: str,
    parameters: Mapping[str, Any] = _NO_PARAMS,
    notes: str = "",
) -> ActionSpec:
    return ActionSpec(
        name=name,
        description=description,
        parameters=parameters,
        risk=risk,
        requires_confirmation=_confirmation_for(name, risk),
        implementation=implementation,
        notes=notes,
    )


_LOW = RiskLevel.LOW
_MEDIUM = RiskLevel.MEDIUM
_HIGH = RiskLevel.HIGH

_APP = _string("Application name or path, e.g. 'notepad' or 'vs code'.")
_WINDOW = _string("Window title to match. Defaults to the active window.")
_LEVEL = _integer("Percentage from 0 to 100.", minimum=0, maximum=100)
_BROWSER_TARGET = _string("What to act on. Meaning depends on the action.")


# --- applications and windows ------------------------------------------------

_APPLICATION_ACTIONS: tuple[ActionSpec, ...] = (
    _spec(
        "open_app",
        _LOW,
        "Launch or focus a desktop application.",
        _APPLICATIONS,
        _schema(
            {
                "app": _APP,
                "new_instance": {
                    "type": "boolean",
                    "description": "Start a second copy instead of focusing the "
                    "running one.",
                },
                "project_path": _string(
                    "Folder or file to open the application with, where it "
                    "supports one."
                ),
            },
            ("app",),
        ),
    ),
    _spec(
        "detect_app",
        _LOW,
        "Report whether an application is installed and where it lives.",
        _APPLICATIONS,
        _schema({"app": _APP}, ("app",)),
    ),
    _spec(
        "open_folder",
        _LOW,
        "Open a folder in File Explorer.",
        _OPEN_FOLDER,
        _schema({"path": _string("Folder to open.")}, ("path",)),
        notes="Refuses a missing folder and blocks protected system paths.",
    ),
    _spec(
        "close_app",
        _MEDIUM,
        "Close an application by closing its window.",
        _WINDOW_ALIAS,
        _schema({"app": _APP}, ("app",)),
        notes="pc_control routes this to the window service as 'close_window'; "
        "it asks the window to close, it does not kill the process.",
    ),
)

_WINDOW_ACTIONS: tuple[ActionSpec, ...] = (
    _spec(
        "list_windows",
        _LOW,
        "List the open windows on the desktop.",
        _WINDOWS,
    ),
    _spec(
        "focus_window",
        _MEDIUM,
        "Bring a window to the front.",
        _WINDOWS,
        _schema({"window": _WINDOW}),
    ),
    _spec(
        "minimize_window",
        _MEDIUM,
        "Minimise a window.",
        _WINDOWS,
        _schema({"window": _WINDOW}),
    ),
    _spec(
        "maximize_window",
        _MEDIUM,
        "Maximise a window.",
        _WINDOWS,
        _schema({"window": _WINDOW}),
    ),
    _spec(
        "restore_window",
        _MEDIUM,
        "Restore a minimised or maximised window to its previous size.",
        _WINDOWS,
        _schema({"window": _WINDOW}),
    ),
    _spec(
        "close_window",
        _MEDIUM,
        "Close a window.",
        _WINDOWS,
        _schema({"window": _WINDOW}),
    ),
)


# --- volume, brightness, power ----------------------------------------------

_VOLUME_ACTIONS: tuple[ActionSpec, ...] = (
    _spec("volume_up", _LOW, "Raise the system volume one step.", _VOLUME),
    _spec("volume_down", _LOW, "Lower the system volume one step.", _VOLUME),
    _spec("volume_mute", _LOW, "Mute the system volume.", _VOLUME),
    _spec("volume_unmute", _LOW, "Unmute the system volume.", _VOLUME),
    _spec(
        "volume_set",
        _LOW,
        "Set the system volume to a percentage.",
        _VOLUME,
        _schema({"level": _LEVEL}, ("level",)),
    ),
)

_BRIGHTNESS_ACTIONS: tuple[ActionSpec, ...] = (
    _spec(
        "brightness_get",
        _LOW,
        "Report the current display brightness.",
        _BRIGHTNESS,
    ),
    _spec(
        "brightness_set",
        _LOW,
        "Set the display brightness to a percentage.",
        _BRIGHTNESS,
        _schema({"level": _LEVEL}, ("level",)),
    ),
)

_SYSTEM_ACTIONS: tuple[ActionSpec, ...] = (
    _spec("system_lock", _LOW, "Lock the workstation.", _SYSTEM),
    _spec("system_sleep", _HIGH, "Put the machine to sleep.", _SYSTEM),
    _spec("system_restart", _HIGH, "Restart the machine.", _SYSTEM),
    _spec("system_shutdown", _HIGH, "Shut the machine down.", _SYSTEM),
    _spec(
        "empty_recycle_bin",
        _HIGH,
        "Empty the Windows Recycle Bin.",
        _RECYCLE_BIN,
        notes="Irreversible: everything in the bin is destroyed.",
    ),
)


# --- clipboard, monitors, desktop context ------------------------------------

_CLIPBOARD_ACTIONS: tuple[ActionSpec, ...] = (
    _spec("clipboard_read", _LOW, "Read the current clipboard text.", _CLIPBOARD),
    _spec(
        "clipboard_write",
        _LOW,
        "Replace the clipboard with the given text.",
        _CLIPBOARD,
        _schema({"content": _string("Text to place on the clipboard.")}, ("content",)),
    ),
    _spec("clipboard_clear", _LOW, "Clear the clipboard.", _CLIPBOARD),
    _spec(
        "clipboard_inspect",
        _LOW,
        "Describe what is on the clipboard without returning the text itself.",
        _CLIPBOARD,
    ),
    _spec(
        "clipboard_history",
        _LOW,
        "List recent clipboard entries recorded by Grandpa.",
        _CLIPBOARD,
        _schema({"limit": _integer("How many entries to return.", minimum=1)}),
    ),
)

_MONITOR_ACTIONS: tuple[ActionSpec, ...] = (
    _spec("list_monitors", _LOW, "List the connected displays.", _MONITORS),
    _spec(
        "monitor_info",
        _LOW,
        "Describe one display: resolution, position, and whether it is primary.",
        _MONITORS,
        _schema({"monitor": _string("Monitor name, index, or 'primary'.")}),
    ),
)

_CONTEXT_ACTIONS: tuple[ActionSpec, ...] = (
    _spec(
        "active_process",
        _LOW,
        "Report the application currently in the foreground.",
        _DIAGNOSTICS,
    ),
    _spec(
        "list_processes",
        _LOW,
        "List running processes.",
        _DIAGNOSTICS,
        _schema({"limit": _integer("How many processes to return.", minimum=1)}),
    ),
    _spec(
        "desktop_summary",
        _LOW,
        "Summarise what is on the desktop right now.",
        _DIAGNOSTICS,
    ),
    _spec(
        "pc_diagnostics",
        _LOW,
        "Report machine health: CPU, memory, disk, and which controls are ready.",
        _DIAGNOSTICS,
    ),
)


# --- files -------------------------------------------------------------------

_PATH = _string("Path to the file or folder. User folder names are resolved.")
_DESTINATION = _string("Destination path.")

_FILE_ACTIONS: tuple[ActionSpec, ...] = (
    _spec(
        "file_create",
        _LOW,
        "Create a file or folder.",
        _FILES,
        _schema(
            {
                "path": _PATH,
                "kind": _string(
                    "What to create.", enum=["file", "folder"], default="file"
                ),
                "content": _string("Initial text, for a file."),
            },
            ("path",),
        ),
    ),
    _spec(
        "file_rename",
        _MEDIUM,
        "Rename a file or folder in place.",
        _FILES,
        _schema(
            {"path": _PATH, "new_name": _string("New name, without a directory.")},
            ("path", "new_name"),
        ),
    ),
    _spec(
        "file_move",
        _MEDIUM,
        "Move a file or folder to another location.",
        _FILES,
        _schema({"path": _PATH, "destination": _DESTINATION}, ("path", "destination")),
    ),
    _spec(
        "file_copy",
        _MEDIUM,
        "Copy a file or folder to another location.",
        _FILES,
        _schema({"path": _PATH, "destination": _DESTINATION}, ("path", "destination")),
    ),
    _spec(
        "file_delete",
        _HIGH,
        "Delete a file or folder.",
        _FILES,
        _schema({"path": _PATH}, ("path",)),
        notes="Deletes outright (unlink / rmtree). It does not go to the "
        "Recycle Bin, so there is nothing to restore.",
    ),
)


# --- synthetic input ---------------------------------------------------------

_COORD_X = _integer("X coordinate in screen pixels.")
_COORD_Y = _integer("Y coordinate in screen pixels.")

_INPUT_ACTIONS: tuple[ActionSpec, ...] = (
    _spec(
        "keyboard_type",
        _MEDIUM,
        "Type text into whatever currently has keyboard focus.",
        _AUTOMATION,
        _schema({"text": _string("Text to type.")}, ("text",)),
    ),
    _spec(
        "keyboard_hotkey",
        _MEDIUM,
        "Press a key combination, e.g. ctrl+s.",
        _AUTOMATION,
        _schema(
            {
                "keys": {
                    "type": "array",
                    "description": "Keys to press together, in order.",
                    "items": {"type": "string"},
                    "minItems": 1,
                }
            },
            ("keys",),
        ),
    ),
    _spec(
        "mouse_move",
        _MEDIUM,
        "Move the mouse pointer, absolutely or by an offset.",
        _AUTOMATION,
        _schema(
            {
                "x": _COORD_X,
                "y": _COORD_Y,
                "relative_x": _integer("Horizontal offset from the current position."),
                "relative_y": _integer("Vertical offset from the current position."),
                "duration": {
                    "type": "number",
                    "description": "Seconds the movement takes (0 to 1).",
                    "minimum": 0,
                    "maximum": 1,
                },
            }
        ),
        notes="Not on the approval list: moving the pointer activates nothing.",
    ),
    _spec(
        "mouse_click",
        _MEDIUM,
        "Click the mouse at a screen position.",
        _AUTOMATION,
        _schema(
            {
                "x": _COORD_X,
                "y": _COORD_Y,
                "clicks": _integer(
                    "1 for a click, 2 for a double-click.", minimum=1, maximum=2
                ),
                "button": _string(
                    "Which button.", enum=["left", "right", "middle"], default="left"
                ),
            },
            ("x", "y"),
        ),
    ),
    _spec(
        "mouse_scroll",
        _MEDIUM,
        "Scroll the wheel at the pointer's current position.",
        _AUTOMATION,
        _schema({"amount": _integer("Notches: positive scrolls up.")}, ("amount",)),
        notes="Not on the approval list: scrolling activates nothing.",
    ),
    _spec(
        "mouse_drag",
        _MEDIUM,
        "Press the mouse button at one point and release it at another.",
        _AUTOMATION,
        _schema(
            {
                "start_x": _integer("Where the drag begins, X."),
                "start_y": _integer("Where the drag begins, Y."),
                "end_x": _integer("Where the drag ends, X."),
                "end_y": _integer("Where the drag ends, Y."),
                "duration": {
                    "type": "number",
                    "description": "Seconds the drag takes (0.1 to 2).",
                    "minimum": 0.1,
                    "maximum": 2,
                },
                "button": _string(
                    "Which button.", enum=["left", "right", "middle"], default="left"
                ),
            },
            ("start_x", "start_y", "end_x", "end_y"),
        ),
    ),
    _spec(
        "desktop_navigate",
        _MEDIUM,
        "Move the selection one step with an arrow key.",
        _AUTOMATION,
        _schema(
            {
                "direction": _string(
                    "Which way to move.", enum=["up", "down", "left", "right"]
                )
            },
            ("direction",),
        ),
        notes="Implemented, but unreachable today: pc_control._execute only "
        "routes keyboard_* and mouse_* to the automation service, so this "
        "action falls through to 'unknown_action_type'.",
    ),
)


# --- browser -----------------------------------------------------------------
#
# pc_control maps each of these onto grandpa.browser_control.execute_browser_action
# with a shorter sub-action name, recorded in each entry's notes. Only the ones
# that actually complete are here; the seven that always return
# "requires_confirmation" and never finish are in EXCLUSIONS.

_BROWSER_ACTIONS: tuple[ActionSpec, ...] = (
    _spec(
        "browser_open",
        _LOW,
        "Open a URL in the default browser.",
        _BROWSER,
        _schema({"url": _string("Address to open. https:// is assumed.")}, ("url",)),
        notes="execute_browser_action('open', url). Opens a real window.",
    ),
    _spec(
        "browser_search",
        _LOW,
        "Search the web in the default browser.",
        _BROWSER,
        _schema({"query": _string("What to search for.")}, ("query",)),
        notes="execute_browser_action('search', query). Opens a real window.",
    ),
    _spec(
        "browser_new_tab",
        _LOW,
        "Open a new browser tab.",
        _BROWSER,
        _schema({"url": _string("Address for the new tab. Blank opens about:blank.")}),
        notes="execute_browser_action('new_tab', url). Opens a real tab.",
    ),
    _spec(
        "browser_context",
        _LOW,
        "Report what the visible browser window is showing.",
        _BROWSER,
        _schema({"scope": _BROWSER_TARGET}),
        notes="execute_browser_action('context', 'active').",
    ),
    _spec(
        "browser_tabs",
        _LOW,
        "List recently seen browser tabs.",
        _BROWSER,
        _schema({"scope": _BROWSER_TARGET}),
        notes="execute_browser_action('tabs', 'recent').",
    ),
    _spec(
        "browser_summary",
        _LOW,
        "Summarise the readable text of the visible page.",
        _BROWSER,
        _schema({"scope": _BROWSER_TARGET}),
        notes="execute_browser_action('summary', 'visible'). Reports that page "
        "text is unavailable when the DOM cannot be read.",
    ),
    _spec(
        "browser_headings",
        _LOW,
        "List the headings on the visible page.",
        _BROWSER,
        _schema({"scope": _BROWSER_TARGET}),
        notes="execute_browser_action('headings', 'visible').",
    ),
    _spec(
        "browser_links",
        _LOW,
        "List the links on the visible page.",
        _BROWSER,
        _schema({"scope": _BROWSER_TARGET}),
        notes="execute_browser_action('links', 'visible').",
    ),
    _spec(
        "browser_buttons",
        _LOW,
        "List the buttons on the visible page.",
        _BROWSER,
        _schema({"scope": _BROWSER_TARGET}),
        notes="execute_browser_action('buttons', 'visible').",
    ),
    _spec(
        "browser_media",
        _LOW,
        "Report the media playing in the visible browser window.",
        _BROWSER,
        _schema({"scope": _BROWSER_TARGET}),
        notes="execute_browser_action('media', 'visible').",
    ),
    _spec(
        "browser_diagnostics",
        _LOW,
        "Report what browser awareness can currently see.",
        _BROWSER,
        _schema({"scope": _BROWSER_TARGET}),
        notes="execute_browser_action('diagnostics', 'visible').",
    ),
    _spec(
        "browser_task",
        _LOW,
        "Record a browser task in the local context store.",
        _BROWSER,
        _schema({"task": _string("What the task is.")}, ("task",)),
        notes="execute_browser_action('task', task). Records a note only -- it "
        "does not drive the browser.",
    ),
)


CATALOGUE: tuple[ActionSpec, ...] = (
    *_APPLICATION_ACTIONS,
    *_WINDOW_ACTIONS,
    *_VOLUME_ACTIONS,
    *_BRIGHTNESS_ACTIONS,
    *_SYSTEM_ACTIONS,
    *_CLIPBOARD_ACTIONS,
    *_MONITOR_ACTIONS,
    *_CONTEXT_ACTIONS,
    *_FILE_ACTIONS,
    *_INPUT_ACTIONS,
    *_BROWSER_ACTIONS,
)


# --- what is deliberately not here -------------------------------------------

EXCLUSIONS: Mapping[str, str] = MappingProxyType(
    {
        # pc_control.BLOCKED_ACTIONS: named so a refusal can be explicit, never
        # performed. Cataloguing them would offer them as tools.
        "file_permanent_delete": (
            "BLOCKED in pc_control: destroys data with no Recycle Bin to "
            "restore from. Named only so the refusal is explicit."
        ),
        "script_run": (
            "BLOCKED in pc_control: running a script is arbitrary code execution."
        ),
        "shell_run": (
            "BLOCKED in pc_control: running a shell command is arbitrary code "
            "execution."
        ),
        "browser_submit_form": (
            "BLOCKED in pc_control: submitting a form can spend money or "
            "publish on the user's behalf."
        ),
        "browser_extract_password": (
            "BLOCKED in pc_control: reading stored credentials, never."
        ),
        "browser_purchase": (
            "BLOCKED in pc_control: spending the user's money, never."
        ),
        # Stubs. browser_control.execute_browser_action returns
        # "requires_confirmation" for each of these and nothing in the
        # repository ever completes them (audit section 2.7,
        # browser_control.py:436-539). They are capabilities Grandpa does not
        # have, so they are not offered as tools.
        "browser_click": (
            "Stub: always returns requires_confirmation and nothing completes "
            "the click. No implementation behind it."
        ),
        "browser_focus": (
            "Stub: maps to 'focus_search', which always returns "
            "requires_confirmation and is never completed."
        ),
        "browser_back": (
            "Stub: always returns requires_confirmation; no code navigates "
            "the visible browser back."
        ),
        "browser_forward": (
            "Stub: always returns requires_confirmation; no code navigates "
            "the visible browser forward."
        ),
        "browser_reload": (
            "Stub: always returns requires_confirmation; no code reloads the "
            "visible browser."
        ),
        "browser_form_fill": (
            "Stub: always returns requires_confirmation; no code fills the "
            "field. On pc_control's approval list, but there is nothing to "
            "approve."
        ),
        "browser_download": (
            "Stub: always returns requires_confirmation; no code starts the download."
        ),
    }
)


# --- lookups -----------------------------------------------------------------

_BY_NAME: Mapping[str, ActionSpec] = MappingProxyType(
    {spec.name: spec for spec in CATALOGUE}
)


def names() -> tuple[str, ...]:
    """Every catalogued action name, in catalogue order."""
    return tuple(spec.name for spec in CATALOGUE)


def get(name: str) -> ActionSpec:
    """Return one action's spec.

    Raises ``KeyError`` for anything not catalogued -- including the excluded
    actions, which exist as names but are not capabilities.
    """
    return _BY_NAME[name]


def counts_by_risk() -> dict[RiskLevel, int]:
    """How many catalogued actions sit at each tier."""
    counted = Counter(spec.risk for spec in CATALOGUE)
    return {risk: counted.get(risk, 0) for risk in RiskLevel}


# Guard against a duplicate name silently shadowing an earlier entry.
if len(_BY_NAME) != len(CATALOGUE):  # pragma: no cover - construction-time check
    _seen: Counter[str] = Counter(spec.name for spec in CATALOGUE)
    raise RuntimeError(
        "duplicate action names in the catalogue: "
        + ", ".join(sorted(name for name, count in _seen.items() if count > 1))
    )

# An action cannot be both catalogued and excluded.
if set(_BY_NAME) & set(EXCLUSIONS):  # pragma: no cover - construction-time check
    raise RuntimeError(
        "actions are both catalogued and excluded: "
        + ", ".join(sorted(set(_BY_NAME) & set(EXCLUSIONS)))
    )
