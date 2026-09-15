"""One entry per action Grandpa can actually perform today.

The list started from the audit's feature table
(``docs/audit/FEATURE-INVENTORY.md`` section 2) crossed with the four risk
tables in ``grandpa.pc_control``, and now also holds what the layer owns
itself -- read actions those tables never had, and the domains migrated off
chat's keyword waterfall, each declared in :data:`LAYER_OWNED` with its reason.
Two rules decide what is in it:

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
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

from grandpa.action_layer.model import RiskLevel

__all__ = [
    "ActionSpec",
    "Binding",
    "Confirmation",
    "CATALOGUE",
    "EXCLUSIONS",
    "LAYER_OWNED",
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
_VOLUME_GET = "grandpa.desktop.control.power.PowerControlService.execute_volume_get"
_CLIPBOARD = "grandpa.desktop.control.clipboard.ClipboardControlService.execute"
_MONITORS = "grandpa.desktop.control.monitors.MonitorControlService.execute"
_DIAGNOSTICS = "grandpa.desktop.control.diagnostics.DesktopDiagnosticsService.execute"
_FILES = "grandpa.desktop.control.files.FileControlService.execute"
_FILE_READ = "grandpa.desktop.control.files.FileControlService.execute_read"
_SCREEN_DESCRIBE = "grandpa.vision.service.VisionEngine.describe"
_AUTOMATION = "grandpa.desktop.control.automation.AutomationControlService.execute"
_BROWSER = "grandpa.browser_control.execute_browser_action"
_OPEN_FOLDER = "grandpa.pc_control._execute_open_folder"
_NOTES = "grandpa.notes.automation.NotesAutomation.execute"
_DOWNLOADS = "grandpa.downloads.automation.DownloadsAutomation.execute"


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


class Confirmation(str, Enum):
    """Who asks the user, when an action needs asking.

    Notes only ever needed one answer to this: the executor asks before it
    calls, because "delete this note" is fully described by its parameters.
    Downloads is not like that. Its prompt is "Archive 1 download (6 B)?" --
    a sentence that cannot exist until the folder has been scanned, and whether
    it asks at all depends on how many files the scan found (a one-file move is
    silent, a two-file move asks). The layer cannot know either thing before
    calling.

    So confirmation has three shapes, not two, and each entry says which.
    """

    NONE = "none"
    """Nothing to ask. Reads, and changes small enough not to warrant it."""

    LAYER = "layer"
    """The executor asks before calling, from the parameters alone."""

    DOMAIN = "domain"
    """The domain asks, through the layer's callback, because only it knows
    what is about to happen or whether it is worth asking about. The executor
    still refuses outright when there is no callback to hand over, so "nobody
    to ask" blocks here exactly as it does for LAYER."""


def _confirmation_for(name: str, risk: RiskLevel) -> Confirmation:
    """pc_control's gate: HIGH, or on the approval-required list."""
    if risk is RiskLevel.HIGH or name in _ALWAYS_CONFIRM:
        return Confirmation.LAYER
    return Confirmation.NONE


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


class Binding(str, Enum):
    """The argument shape an implementation expects.

    ``pc_control._execute`` hides six different calling conventions behind one
    dispatch. The layer cannot, so the catalogue names which one each entry
    needs and the executor has one adapter per shape. ``self`` is supplied by
    the executor: every dotted path that names a method is resolved to its
    class, which is constructed with no arguments.
    """

    REQUEST_ACTION = "request_action"
    """``method(request, action)`` -- applications, windows, clipboard,
    monitors, diagnostics, files, brightness."""

    REQUEST_ACTION_PLATFORM = "request_action_platform"
    """``method(request, action, platform=...)`` -- volume and synthetic
    input."""

    ACTION_PLATFORM = "action_platform"
    """``method(action, platform=...)`` -- system power. Takes no request."""

    PLATFORM_ONLY = "platform_only"
    """``method(platform=...)`` -- emptying the Recycle Bin."""

    REQUEST_ONLY = "request_only"
    """``function(request)`` -- open_folder, still inline in pc_control."""

    SERVICE_REQUEST = "service_request"
    """``method(request)`` -- a service method that needs no action name
    because it only does one thing, such as reading a file."""

    SERVICE_ONLY = "service_only"
    """``method()`` -- a service method that takes nothing at all, such as
    describing what is on screen."""

    ACTION_TARGET = "action_target"
    """``function(action, target)`` -- browser_control.execute_browser_action,
    which takes its own shorter sub-action names."""

    DOWNLOADS_ACTION = "downloads_action"
    """``method(DownloadAction, confirmed=, confirm=)`` -- grandpa.downloads.

    Like the notes binding, but the callback is forwarded rather than consumed:
    downloads decides whether to ask and writes the sentence itself, because
    neither is knowable until it has scanned the folder.
    """

    NOTES_ACTION = "notes_action"
    """``method(NotesAction, confirmed=True)`` -- grandpa.notes.

    The notes package takes a structured ``NotesAction``, not a request, and has
    its own confirmation step. The executor has already obtained consent by the
    time it calls -- ``notes_delete`` is HIGH, so it cannot reach an
    implementation unconfirmed -- so it passes ``confirmed=True`` rather than
    letting notes ask a second time for the same thing.

    A new domain will often need a new shape like this. That is the point of
    keeping the conventions in one table: adding one is a single, reviewable
    entry rather than a branch buried in a dispatch chain.
    """


@dataclass(frozen=True, slots=True)
class _Call:
    """How to call one entry's implementation."""

    binding: Binding
    target: str | None = None
    """Which schema property becomes the request's ``.target``. Everything
    else in the parameters becomes ``.args``."""

    alias: str | None = None
    """The name the implementation expects, when it differs from the catalogue
    name -- ``close_app`` arrives at the window service as ``close``, and every
    browser action has a shorter sub-action name."""


_R_A = Binding.REQUEST_ACTION
_R_A_P = Binding.REQUEST_ACTION_PLATFORM

# One row per catalogue entry. A missing row is an import-time error, so an
# entry cannot be added without saying how it is called.
_CALLS: dict[str, _Call] = {
    # applications and windows
    "open_app": _Call(_R_A, target="app"),
    "detect_app": _Call(_R_A, target="app"),
    "open_folder": _Call(Binding.REQUEST_ONLY, target="path"),
    "close_app": _Call(_R_A, target="app", alias="close"),
    "list_windows": _Call(_R_A, target="window"),
    "focus_window": _Call(_R_A, target="window"),
    "minimize_window": _Call(_R_A, target="window"),
    "maximize_window": _Call(_R_A, target="window"),
    "restore_window": _Call(_R_A, target="window"),
    "close_window": _Call(_R_A, target="window"),
    # volume, brightness, power
    "volume_up": _Call(_R_A_P),
    "volume_down": _Call(_R_A_P),
    "volume_mute": _Call(_R_A_P),
    "volume_unmute": _Call(_R_A_P),
    "volume_set": _Call(_R_A_P),
    "volume_get": _Call(Binding.PLATFORM_ONLY),
    "brightness_get": _Call(_R_A),
    "brightness_set": _Call(_R_A),
    "system_lock": _Call(Binding.ACTION_PLATFORM),
    "system_sleep": _Call(Binding.ACTION_PLATFORM),
    "system_restart": _Call(Binding.ACTION_PLATFORM),
    "system_shutdown": _Call(Binding.ACTION_PLATFORM),
    "empty_recycle_bin": _Call(Binding.PLATFORM_ONLY),
    # clipboard, monitors, desktop context
    "clipboard_read": _Call(_R_A),
    "clipboard_write": _Call(_R_A),
    "clipboard_clear": _Call(_R_A),
    "clipboard_inspect": _Call(_R_A),
    "clipboard_history": _Call(_R_A),
    "list_monitors": _Call(_R_A, target="monitor"),
    "monitor_info": _Call(_R_A, target="monitor"),
    "active_process": _Call(_R_A),
    "list_processes": _Call(_R_A),
    "desktop_summary": _Call(_R_A),
    "pc_diagnostics": _Call(_R_A),
    "screenshot_describe": _Call(Binding.SERVICE_ONLY),
    # files
    "file_create": _Call(_R_A, target="path"),
    "file_rename": _Call(_R_A, target="path"),
    "file_move": _Call(_R_A, target="path"),
    "file_copy": _Call(_R_A, target="path"),
    "file_delete": _Call(_R_A, target="path"),
    "file_read": _Call(Binding.SERVICE_REQUEST, target="path"),
    # synthetic input
    "keyboard_type": _Call(_R_A_P),
    "keyboard_hotkey": _Call(_R_A_P),
    "mouse_move": _Call(_R_A_P),
    "mouse_click": _Call(_R_A_P),
    "mouse_scroll": _Call(_R_A_P),
    "mouse_drag": _Call(_R_A_P),
    "desktop_navigate": _Call(_R_A_P),
    # browser
    "browser_open": _Call(Binding.ACTION_TARGET, target="url", alias="open"),
    "browser_search": _Call(Binding.ACTION_TARGET, target="query", alias="search"),
    "browser_new_tab": _Call(Binding.ACTION_TARGET, target="url", alias="new_tab"),
    "browser_context": _Call(Binding.ACTION_TARGET, target="scope", alias="context"),
    "browser_tabs": _Call(Binding.ACTION_TARGET, target="scope", alias="tabs"),
    "browser_summary": _Call(Binding.ACTION_TARGET, target="scope", alias="summary"),
    "browser_headings": _Call(Binding.ACTION_TARGET, target="scope", alias="headings"),
    "browser_links": _Call(Binding.ACTION_TARGET, target="scope", alias="links"),
    "browser_buttons": _Call(Binding.ACTION_TARGET, target="scope", alias="buttons"),
    "browser_media": _Call(Binding.ACTION_TARGET, target="scope", alias="media"),
    "browser_diagnostics": _Call(
        Binding.ACTION_TARGET, target="scope", alias="diagnostics"
    ),
    "browser_task": _Call(Binding.ACTION_TARGET, target="task", alias="task"),
    # notes. `alias` is the NotesAction action name; `target` names the
    # parameter that identifies an existing note, which is mirrored into
    # NotesAction.query because notes looks a note up by `query or title`.
    "notes_list": _Call(Binding.NOTES_ACTION, alias="list"),
    "notes_recent": _Call(Binding.NOTES_ACTION, alias="recent"),
    "notes_search": _Call(Binding.NOTES_ACTION, alias="search"),
    "notes_read": _Call(Binding.NOTES_ACTION, alias="open", target="title"),
    "notes_create": _Call(Binding.NOTES_ACTION, alias="create"),
    "notes_append": _Call(Binding.NOTES_ACTION, alias="append", target="title"),
    "notes_rename": _Call(Binding.NOTES_ACTION, alias="rename", target="title"),
    "notes_delete": _Call(Binding.NOTES_ACTION, alias="delete", target="title"),
    "notes_archive": _Call(Binding.NOTES_ACTION, alias="archive", target="title"),
    "notes_restore": _Call(Binding.NOTES_ACTION, alias="restore", target="title"),
    "notes_pin": _Call(Binding.NOTES_ACTION, alias="pin", target="title"),
    "notes_unpin": _Call(Binding.NOTES_ACTION, alias="unpin", target="title"),
    # downloads. `target` names the parameter that selects which files, which
    # downloads reads as DownloadAction.selector.
    "downloads_recent": _Call(Binding.DOWNLOADS_ACTION, alias="recent"),
    "downloads_today": _Call(Binding.DOWNLOADS_ACTION, alias="today"),
    "downloads_latest": _Call(Binding.DOWNLOADS_ACTION, alias="latest"),
    "downloads_search": _Call(Binding.DOWNLOADS_ACTION, alias="search"),
    "downloads_large": _Call(Binding.DOWNLOADS_ACTION, alias="large"),
    "downloads_incomplete": _Call(Binding.DOWNLOADS_ACTION, alias="incomplete"),
    "downloads_duplicates": _Call(Binding.DOWNLOADS_ACTION, alias="duplicates"),
    "downloads_info": _Call(Binding.DOWNLOADS_ACTION, alias="info", target="which"),
    "downloads_open": _Call(Binding.DOWNLOADS_ACTION, alias="open", target="which"),
    "downloads_open_folder": _Call(
        Binding.DOWNLOADS_ACTION, alias="open_folder", target="which"
    ),
    "downloads_move": _Call(Binding.DOWNLOADS_ACTION, alias="move", target="which"),
    "downloads_organize": _Call(Binding.DOWNLOADS_ACTION, alias="organize"),
    "downloads_archive": _Call(
        Binding.DOWNLOADS_ACTION, alias="archive", target="which"
    ),
    "downloads_delete": _Call(Binding.DOWNLOADS_ACTION, alias="delete", target="which"),
}


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

    confirmation: Confirmation
    """Whether a human must approve, and who does the asking."""

    implementation: str
    """Dotted path to the function that performs it. Never imported here."""

    notes: str = ""
    """Anything a caller should know that the description cannot carry."""

    binding: Binding = Binding.REQUEST_ACTION
    """Which argument shape :data:`implementation` expects."""

    target_parameter: str | None = None
    """Which parameter becomes the request's ``.target``, if any."""

    action_alias: str | None = None
    """The name the implementation expects, when it differs from ``name``."""

    @property
    def requires_confirmation(self) -> bool:
        """Whether a human must approve, regardless of who asks."""
        return self.confirmation is not Confirmation.NONE

    def __post_init__(self) -> None:
        object.__setattr__(self, "parameters", MappingProxyType(dict(self.parameters)))


def _spec(
    name: str,
    risk: RiskLevel,
    description: str,
    implementation: str,
    parameters: Mapping[str, Any] = _NO_PARAMS,
    notes: str = "",
    confirmation: Confirmation | None = None,
) -> ActionSpec:
    call = _CALLS[name]  # KeyError: a new entry must say how it is called
    return ActionSpec(
        name=name,
        description=description,
        parameters=parameters,
        risk=risk,
        confirmation=confirmation or _confirmation_for(name, risk),
        implementation=implementation,
        notes=notes,
        binding=call.binding,
        target_parameter=call.target,
        action_alias=call.alias,
    )


_LOW = RiskLevel.LOW
_MEDIUM = RiskLevel.MEDIUM
_HIGH = RiskLevel.HIGH

_APP = _string("Application name or path, e.g. 'notepad' or 'vs code'.")
_WINDOW = _string("Window title to match. Defaults to the active window.")
_LEVEL = _integer("Percentage from 0 to 100.", minimum=0, maximum=100)


def _browser_scope(default: str) -> dict[str, Any]:
    """What the browser action reads. pc_control passes these same defaults."""
    return _string("Which part of the visible browser to read.", default=default)


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
    _spec(
        "volume_get",
        _LOW,
        "Report the current system volume and whether it is muted.",
        _VOLUME_GET,
        notes="Needs the optional pycaw backend (the 'desktop-hardware' extra); "
        "without it this says so rather than returning a number.",
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
    _spec(
        "screenshot_describe",
        _LOW,
        "Describe what is on the screen right now: window, buttons, fields, text.",
        _SCREEN_DESCRIBE,
        notes="Reads the screen; it does not save an image. Refuses outright on "
        "a screen that looks like it holds passwords or payment details.",
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
    _spec(
        "file_read",
        _LOW,
        "Read the text of a file.",
        _FILE_READ,
        _schema(
            {
                "path": _PATH,
                "max_bytes": _integer(
                    "Refuse a file larger than this. Capped at 262144.",
                    minimum=1,
                    maximum=262144,
                ),
            },
            ("path",),
        ),
        notes="Only reads inside the folders file search already walks "
        "(grandpa.files.paths.safe_roots), and refuses a file over the byte "
        "limit rather than putting it all in the prompt.",
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
        _schema({"url": _string("Address for the new tab.", default="about:blank")}),
        notes="execute_browser_action('new_tab', url). Opens a real tab.",
    ),
    _spec(
        "browser_context",
        _LOW,
        "Report what the visible browser window is showing.",
        _BROWSER,
        _schema({"scope": _browser_scope("active")}),
        notes="execute_browser_action('context', 'active').",
    ),
    _spec(
        "browser_tabs",
        _LOW,
        "List recently seen browser tabs.",
        _BROWSER,
        _schema({"scope": _browser_scope("recent")}),
        notes="execute_browser_action('tabs', 'recent').",
    ),
    _spec(
        "browser_summary",
        _LOW,
        "Summarise the readable text of the visible page.",
        _BROWSER,
        _schema({"scope": _browser_scope("visible")}),
        notes="execute_browser_action('summary', 'visible'). Reports that page "
        "text is unavailable when the DOM cannot be read.",
    ),
    _spec(
        "browser_headings",
        _LOW,
        "List the headings on the visible page.",
        _BROWSER,
        _schema({"scope": _browser_scope("visible")}),
        notes="execute_browser_action('headings', 'visible').",
    ),
    _spec(
        "browser_links",
        _LOW,
        "List the links on the visible page.",
        _BROWSER,
        _schema({"scope": _browser_scope("visible")}),
        notes="execute_browser_action('links', 'visible').",
    ),
    _spec(
        "browser_buttons",
        _LOW,
        "List the buttons on the visible page.",
        _BROWSER,
        _schema({"scope": _browser_scope("visible")}),
        notes="execute_browser_action('buttons', 'visible').",
    ),
    _spec(
        "browser_media",
        _LOW,
        "Report the media playing in the visible browser window.",
        _BROWSER,
        _schema({"scope": _browser_scope("visible")}),
        notes="execute_browser_action('media', 'visible').",
    ),
    _spec(
        "browser_diagnostics",
        _LOW,
        "Report what browser awareness can currently see.",
        _BROWSER,
        _schema({"scope": _browser_scope("visible")}),
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


# --- notes -------------------------------------------------------------------
#
# The first handler migrated off chat's keyword waterfall. All twelve actions
# the notes parser can produce are here, not just the common six: leaving half
# of them on the old path would mean two routes to the same store, which is the
# thing the migration exists to remove.
#
# Tiers follow pc_control's own file tiers rather than a new opinion -- reading
# and creating are LOW like file_create, changing existing content is MEDIUM
# like file_rename, and deleting is HIGH like file_delete because
# NotesStore.delete unlinks the file. Confirmation therefore falls exactly where
# NotesSafetyPolicy.requires_confirmation already put it: on delete and nowhere
# else.

_NOTE_NAME = _string("Title of the note, or enough of it to identify one.")
_NOTE_TEXT = _string("The note's text.")

_NOTES_ACTIONS: tuple[ActionSpec, ...] = (
    _spec("notes_list", _LOW, "List the saved notes.", _NOTES),
    _spec("notes_recent", _LOW, "List the notes touched most recently.", _NOTES),
    _spec(
        "notes_search",
        _LOW,
        "Search the notes for a word or phrase.",
        _NOTES,
        _schema({"query": _string("What to look for.")}, ("query",)),
    ),
    _spec(
        "notes_read",
        _LOW,
        "Read one note back in full.",
        _NOTES,
        _schema({"title": _NOTE_NAME}, ("title",)),
    ),
    _spec(
        "notes_create",
        _LOW,
        "Create a note.",
        _NOTES,
        _schema(
            {
                "title": _string("Title for the new note."),
                "content": _NOTE_TEXT,
                "tags": {
                    "type": "array",
                    "description": "Tags to file the note under.",
                    "items": {"type": "string"},
                },
                "category": _string("Category to file the note under."),
            },
            ("title",),
        ),
    ),
    _spec(
        "notes_append",
        _MEDIUM,
        "Add text to the end of an existing note.",
        _NOTES,
        # content is not required: the notes store appends an empty line
        # happily, and chat's parser can legitimately produce one.
        _schema({"title": _NOTE_NAME, "content": _NOTE_TEXT}, ("title",)),
    ),
    _spec(
        "notes_rename",
        _MEDIUM,
        "Rename a note.",
        _NOTES,
        _schema(
            {"title": _NOTE_NAME, "new_title": _string("The new title.")},
            ("title", "new_title"),
        ),
    ),
    _spec(
        "notes_delete",
        _HIGH,
        "Delete a note.",
        _NOTES,
        _schema({"title": _NOTE_NAME}, ("title",)),
        notes="NotesStore.delete unlinks the file, so there is nothing to "
        "restore afterwards. Use notes_archive to put one aside instead.",
    ),
    _spec(
        "notes_archive",
        _MEDIUM,
        "Archive a note, hiding it from the normal list without deleting it.",
        _NOTES,
        _schema({"title": _NOTE_NAME}, ("title",)),
    ),
    _spec(
        "notes_restore",
        _MEDIUM,
        "Bring an archived note back into the normal list.",
        _NOTES,
        _schema({"title": _NOTE_NAME}, ("title",)),
    ),
    _spec(
        "notes_pin",
        _LOW,
        "Pin a note to the top of the list.",
        _NOTES,
        _schema({"title": _NOTE_NAME}, ("title",)),
    ),
    _spec(
        "notes_unpin",
        _LOW,
        "Unpin a note.",
        _NOTES,
        _schema({"title": _NOTE_NAME}, ("title",)),
    ),
)


# --- downloads ----------------------------------------------------------------
#
# The second domain off the waterfall, and the one that showed confirmation has
# three shapes rather than two. Downloads decides whether to ask *after*
# scanning -- a one-file move is silent, a two-file move asks -- and its prompt
# quotes what it found ("Archive 1 download (6 B)?"). Neither is knowable before
# the call, so these use Confirmation.DOMAIN: the layer hands its callback over
# instead of using it up front.
#
# Tiers follow the desktop file tiers again: listing is LOW, moving and
# archiving are MEDIUM like file_move, deleting is HIGH like file_delete.

_WHICH = _string(
    "Which downloads: a filename or search term, 'latest', 'old', "
    "or 'incomplete'. Defaults to the most recent download.",
    default="latest",
)
_DAYS = _integer("How many days counts as old, for selector 'old'.", minimum=1)

_DOWNLOADS_ACTIONS: tuple[ActionSpec, ...] = (
    _spec("downloads_recent", _LOW, "List recent downloads.", _DOWNLOADS),
    _spec("downloads_today", _LOW, "List downloads from today.", _DOWNLOADS),
    _spec(
        "downloads_latest",
        _LOW,
        "Report the most recent download.",
        _DOWNLOADS,
        notes="Currently answers 'That Downloads action is not supported yet.' "
        "-- the parser produces it and DownloadsAutomation._execute has no "
        "branch for it. Catalogued so the honest refusal is preserved.",
    ),
    _spec(
        "downloads_search",
        _LOW,
        "Search the downloads folder by name.",
        _DOWNLOADS,
        _schema({"query": _string("What to look for.")}, ("query",)),
    ),
    _spec("downloads_large", _LOW, "List the largest downloads.", _DOWNLOADS),
    _spec(
        "downloads_incomplete",
        _LOW,
        "List part-downloaded or temporary files.",
        _DOWNLOADS,
    ),
    _spec(
        "downloads_duplicates",
        _LOW,
        "List downloads that look like duplicates.",
        _DOWNLOADS,
    ),
    _spec(
        "downloads_info",
        _LOW,
        "Describe one download: size, type, when it arrived, whether it is safe.",
        _DOWNLOADS,
        _schema({"which": _WHICH}),
    ),
    _spec(
        "downloads_open",
        _MEDIUM,
        "Open a download in its default application.",
        _DOWNLOADS,
        _schema({"which": _WHICH}),
        notes="Refuses anything the safety policy rates unsafe to open.",
    ),
    _spec(
        "downloads_open_folder",
        _LOW,
        "Open the folder containing a download.",
        _DOWNLOADS,
        _schema({"which": _WHICH}),
    ),
    _spec(
        "downloads_move",
        _MEDIUM,
        "Move downloads somewhere else.",
        _DOWNLOADS,
        _schema(
            {
                "which": _WHICH,
                "destination": _string("Where to move them."),
                "days": _DAYS,
            },
            ("destination",),
        ),
        notes="Asks first when it would move more than one file; a single file "
        "moves without a prompt, as it always has.",
        confirmation=Confirmation.DOMAIN,
    ),
    _spec(
        "downloads_organize",
        _MEDIUM,
        "Sort the downloads folder into subfolders by type.",
        _DOWNLOADS,
        confirmation=Confirmation.DOMAIN,
    ),
    _spec(
        "downloads_archive",
        _MEDIUM,
        "Move downloads into the Archives folder.",
        _DOWNLOADS,
        _schema({"which": _WHICH, "days": _DAYS}),
        confirmation=Confirmation.DOMAIN,
    ),
    _spec(
        "downloads_delete",
        _HIGH,
        "Delete downloads.",
        _DOWNLOADS,
        _schema({"which": _WHICH, "days": _DAYS}),
        notes="Deletes the files outright. Prefer downloads_archive to put "
        "something aside instead.",
        confirmation=Confirmation.DOMAIN,
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
    *_NOTES_ACTIONS,
    *_DOWNLOADS_ACTIONS,
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


# --- actions this layer owns --------------------------------------------------

LAYER_OWNED: Mapping[str, str] = MappingProxyType(
    {
        # pc_control's tables are the authority on every action it dispatches,
        # and the coverage test still holds the catalogue to them. But the layer
        # now grows capabilities of its own, and an action that pc_control has
        # never heard of would otherwise look like an invention. Naming them
        # here keeps both properties: nothing silently appears, and nothing in
        # this list may also be in a pc_control table, so it cannot be used to
        # hide a disagreement about risk.
        "volume_get": (
            "There was a volume setter and no getter, which is why 'what is my "
            "volume set to' could only be answered by inventing a number. Added "
            "as PowerControlService.execute_volume_get; read-only, so LOW."
        ),
        "file_read": (
            "Every other file action writes. Added as "
            "FileControlService.execute_read, bounded by size and restricted to "
            "the roots file search already walks; read-only, so LOW."
        ),
        "screenshot_describe": (
            "The vision engine could already describe the screen "
            "(VisionEngine.describe) but no risk table named it, so no action "
            "layer could offer it. Read-only, so LOW."
        ),
        **{
            f"notes_{action}": (
                "Notes is the first handler migrated off chat's keyword "
                "waterfall. pc_control's tables only ever covered desktop "
                "control, so every notes action lives in the layer; the tiers "
                "follow pc_control's file tiers and confirmation falls exactly "
                "where NotesSafetyPolicy already put it."
            )
            for action in (
                "list",
                "recent",
                "search",
                "read",
                "create",
                "append",
                "rename",
                "delete",
                "archive",
                "restore",
                "pin",
                "unpin",
            )
        },
        **{
            f"downloads_{action}": (
                "Downloads is the second domain migrated off the waterfall. "
                "pc_control never rated it; tiers follow pc_control's file "
                "tiers, and confirmation stays where DownloadsSafetyPolicy "
                "puts it -- including its count-dependent rule for move."
            )
            for action in (
                "recent",
                "today",
                "latest",
                "search",
                "large",
                "incomplete",
                "duplicates",
                "info",
                "open",
                "open_folder",
                "move",
                "organize",
                "archive",
                "delete",
            )
        },
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
