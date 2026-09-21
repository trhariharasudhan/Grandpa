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
    "CORE_ACTIONS",
    "CORE_DOMAINS",
    "DOMAINS",
    "EXCLUSIONS",
    "LAYER_OWNED",
    "counts_by_risk",
    "domain_of",
    "extended_actions",
    "loadable_domains",
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
_FILES = "grandpa.files.executor.FileExecutor.execute"
_FILE_READ = _FILES
_SCREEN_DESCRIBE = "grandpa.vision.service.VisionEngine.describe"
_AUTOMATION = "grandpa.desktop.control.automation.AutomationControlService.execute"
AUTOMATION_IMPLEMENTATION = _AUTOMATION
"""Public name for the synthetic-input implementation.

Callers that must treat keys and mouse differently from every other action
-- deferred consent is never offered for them -- ask the catalogue which
actions those are, rather than keeping a second list that can drift.
"""
_BROWSER = "grandpa.browser_control.execute_browser_action"
_BROWSER_NAV = "grandpa.browser.executor.BrowserExecutor.execute"
_AWARENESS = "grandpa.browser_awareness.automation.execute_awareness"
_APPS_INVENTORY_IMPL = "grandpa.apps.automation.execute_inventory"
_OPEN_FOLDER = "grandpa.pc_control._execute_open_folder"
_NOTES = "grandpa.notes.automation.NotesAutomation.execute"
_DOWNLOADS = "grandpa.downloads.automation.DownloadsAutomation.execute"
_MEMORY = "grandpa.memory_context.execute_memory_action"
_REMINDERS = "grandpa.reminders.execute_reminder_action"
_SCHEDULER = "grandpa.task_scheduler.execute_scheduler_action"
_WEB_SEARCH = "grandpa.web_search.automation.WebSearchAutomation.execute"
_CLOCK = "grandpa.core.runtime_context.answer_datetime"
_CALENDAR = "grandpa.calendar.automation.CalendarAutomation.execute"
_GMAIL = "grandpa.gmail.automation.GmailAutomation.execute"


CALENDAR_NAMES: tuple[str, ...] = (
    "status",
    "setup",
    "disconnect",
    "list",
    "upcoming",
    "search",
    "read",
    "freebusy",
    "create",
    "update",
    "delete",
)

GMAIL_NAMES: tuple[str, ...] = (
    "status",
    "setup",
    "disconnect",
    "list",
    "search",
    "read",
    "summarize",
    "labels",
    "draft",
    "send",
    "reply",
    "forward",
    "archive",
    "label",
    "trash",
)

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
        # Closing ends something the user was using. WM_CLOSE lets most
        # applications ask about unsaved work, but not all do: a console
        # window takes its running process with it, and a model chose the
        # target. close_app is close_window under another name, so both.
        "close_app",
        "close_window",
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

    CALENDAR_ACTION = "calendar_action"
    """``method(CalendarAction, confirmed=, confirm=)`` -- grandpa.calendar."""

    GMAIL_ACTION = "gmail_action"
    """``method(GmailAction, confirmed=, confirm=)`` -- grandpa.gmail."""

    BROWSER_ACTION = "browser_action"
    """``BrowserExecutor.execute(BrowserAction)`` -- the browser domain, which
    owns navigation and the confirmation rules that go with it, including
    tools.browser.trusted_domains."""

    APPLICATION_ACTION = "application_action"
    """``ApplicationControlService.execute(request, action, confirm=...)``.

    Its own binding because launching a browser asks, and only the service
    can tell that it is about to: the answer depends on resolving the name
    the user said to an application."""

    AWARENESS_ACTION = "awareness_action"
    """execute_awareness(action, query) -- browser_awareness, which
    captures the visible page, redacts it and answers from the snapshot.
    """

    FILE_ACTION = "file_action"
    """``FileExecutor.execute(FileAction, confirm=...)`` -- the files domain,
    which owns every file operation and applies its own safety policy to each
    one."""

    FUNCTION_KWARGS = "function_kwargs"
    """``function(**parameters)`` -- a plain function whose arguments are the
    action's parameters, with no action name and no request object."""

    WEB_SEARCH_ACTION = "web_search_action"
    """``method(WebSearchAction)`` -- grandpa.web_search. No confirmation hook:
    nothing it does changes the machine."""

    REMINDER_ACTION = "reminder_action"
    """``function(action, store=None, subject=...)`` -- grandpa.reminders."""

    SCHEDULER_ACTION = "scheduler_action"
    """``function(action, store=None, **parameters)`` -- task_scheduler."""

    MEMORY_ACTION = "memory_action"
    """``function(action, store=None, subject=...)`` -- grandpa.memory_context.

    A plain module-level function rather than a service method, because memory
    had no class to hang a seam on. Everything else is the notes shape.
    """

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
    "open_app": _Call(Binding.APPLICATION_ACTION, target="app"),
    "apps_scan": _Call(Binding.ACTION_TARGET),
    "apps_list": _Call(Binding.ACTION_TARGET),
    "apps_search": _Call(Binding.ACTION_TARGET, target="query"),
    "apps_running": _Call(Binding.ACTION_TARGET),
    "apps_is_running": _Call(Binding.ACTION_TARGET, target="query"),
    "apps_restart": _Call(Binding.ACTION_TARGET, target="query"),
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
    "system_info": _Call(_R_A),
    "screen_capture": _Call(Binding.FUNCTION_KWARGS),
    "screen_describe": _Call(Binding.FUNCTION_KWARGS),
    "screen_active_window": _Call(Binding.FUNCTION_KWARGS),
    "screen_diagnostics": _Call(Binding.FUNCTION_KWARGS),
    "screenshot_describe": _Call(Binding.SERVICE_ONLY),
    # files
    "file_create": _Call(Binding.FILE_ACTION, target="path", alias="create_file"),
    "file_rename": _Call(Binding.FILE_ACTION, target="path", alias="rename"),
    "file_move": _Call(Binding.FILE_ACTION, target="path", alias="move"),
    "file_copy": _Call(Binding.FILE_ACTION, target="path", alias="copy"),
    "file_delete": _Call(Binding.FILE_ACTION, target="path", alias="delete"),
    "file_read": _Call(Binding.FILE_ACTION, target="path", alias="read"),
    "file_search": _Call(Binding.FILE_ACTION, target="query", alias="search"),
    "file_open": _Call(Binding.FILE_ACTION, target="path", alias="open"),
    "file_open_folder": _Call(
        Binding.FILE_ACTION, target="path", alias="open_containing_folder"
    ),
    "file_properties": _Call(Binding.FILE_ACTION, target="path", alias="properties"),
    "file_zip": _Call(Binding.FILE_ACTION, target="path", alias="zip"),
    "file_extract": _Call(Binding.FILE_ACTION, target="path", alias="extract"),
    # synthetic input
    "keyboard_type": _Call(_R_A_P),
    "keyboard_hotkey": _Call(_R_A_P),
    "mouse_move": _Call(_R_A_P),
    "mouse_click": _Call(_R_A_P),
    "mouse_scroll": _Call(_R_A_P),
    "mouse_drag": _Call(_R_A_P),
    "desktop_navigate": _Call(_R_A_P),
    # browser
    "browser_open": _Call(Binding.BROWSER_ACTION, target="url", alias="open_url"),
    "browser_search": _Call(Binding.BROWSER_ACTION, target="query", alias="search"),
    "browser_page": _Call(Binding.BROWSER_ACTION, target="page", alias="open_page"),
    "browser_new_tab": _Call(Binding.BROWSER_ACTION, alias="new_tab"),
    "browser_close_tab": _Call(Binding.BROWSER_ACTION, alias="close_tab"),
    "browser_refresh": _Call(Binding.BROWSER_ACTION, alias="refresh"),
    "browser_back": _Call(Binding.BROWSER_ACTION, alias="back"),
    "browser_forward": _Call(Binding.BROWSER_ACTION, alias="forward"),
    "browser_reopen_closed_tab": _Call(
        Binding.BROWSER_ACTION, alias="reopen_closed_tab"
    ),
    "browser_focus_address_bar": _Call(
        Binding.BROWSER_ACTION, alias="focus_address_bar"
    ),
    "browser_context": _Call(Binding.AWARENESS_ACTION, alias="current"),
    "browser_title": _Call(Binding.AWARENESS_ACTION, alias="title"),
    "browser_url": _Call(Binding.AWARENESS_ACTION, alias="url"),
    "browser_read": _Call(Binding.AWARENESS_ACTION, alias="read"),
    "browser_selected_text": _Call(Binding.AWARENESS_ACTION, alias="selected_text"),
    "browser_find_text": _Call(
        Binding.AWARENESS_ACTION, target="query", alias="find_text"
    ),
    "browser_tabs": _Call(Binding.AWARENESS_ACTION, alias="tabs"),
    "browser_summary": _Call(Binding.AWARENESS_ACTION, alias="summarize"),
    "browser_headings": _Call(Binding.ACTION_TARGET, target="scope", alias="headings"),
    "browser_links": _Call(Binding.AWARENESS_ACTION, alias="links"),
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
    # memory. `alias` is the name execute_memory_action dispatches on.
    "memory_remember": _Call(Binding.MEMORY_ACTION, alias="remember"),
    "memory_recall": _Call(Binding.MEMORY_ACTION, alias="recall"),
    "memory_profile": _Call(Binding.MEMORY_ACTION, alias="profile"),
    "memory_preferences": _Call(Binding.MEMORY_ACTION, alias="preferences"),
    "memory_projects": _Call(Binding.MEMORY_ACTION, alias="projects"),
    "memory_project_name": _Call(Binding.MEMORY_ACTION, alias="project_name"),
    "memory_attribute": _Call(Binding.MEMORY_ACTION, alias="attribute"),
    "memory_apps_today": _Call(Binding.MEMORY_ACTION, alias="apps_today"),
    "memory_recent_activity": _Call(Binding.MEMORY_ACTION, alias="recent_activity"),
    "memory_continue_project": _Call(Binding.MEMORY_ACTION, alias="continue_project"),
    "memory_forget": _Call(Binding.MEMORY_ACTION, alias="forget"),
    "memory_clear": _Call(Binding.MEMORY_ACTION, alias="clear"),
    # one-shot reminders (reminders.db)
    "reminder_create": _Call(Binding.REMINDER_ACTION, alias="create"),
    "reminder_list": _Call(Binding.REMINDER_ACTION, alias="list"),
    "reminder_cancel": _Call(Binding.REMINDER_ACTION, alias="cancel"),
    # routines and recurring reminders (scheduler.db)
    "routine_create_morning": _Call(
        Binding.SCHEDULER_ACTION, alias="create_morning_routine"
    ),
    "routine_set_morning": _Call(Binding.SCHEDULER_ACTION, alias="set_morning_routine"),
    "routine_list": _Call(Binding.SCHEDULER_ACTION, alias="list_schedule"),
    "routine_enable": _Call(Binding.SCHEDULER_ACTION, alias="enable_routine"),
    "routine_disable": _Call(Binding.SCHEDULER_ACTION, alias="disable_routine"),
    "routine_run": _Call(Binding.SCHEDULER_ACTION, alias="run_routine"),
    "routine_create_reminder": _Call(
        Binding.SCHEDULER_ACTION, alias="create_recurring_reminder"
    ),
    # web search
    "web_search": _Call(Binding.WEB_SEARCH_ACTION, alias="search"),
    "web_sources": _Call(Binding.WEB_SEARCH_ACTION, alias="sources"),
    "web_search_status": _Call(Binding.WEB_SEARCH_ACTION, alias="status"),
    "web_clear_cache": _Call(Binding.WEB_SEARCH_ACTION, alias="clear_cache"),
    # the clock
    "datetime_now": _Call(Binding.FUNCTION_KWARGS),
    # calendar
    "calendar_status": _Call(Binding.CALENDAR_ACTION, alias="status"),
    "calendar_setup": _Call(Binding.CALENDAR_ACTION, alias="setup"),
    "calendar_disconnect": _Call(Binding.CALENDAR_ACTION, alias="disconnect"),
    "calendar_list": _Call(Binding.CALENDAR_ACTION, alias="list"),
    "calendar_upcoming": _Call(Binding.CALENDAR_ACTION, alias="upcoming"),
    "calendar_search": _Call(Binding.CALENDAR_ACTION, alias="search"),
    "calendar_read": _Call(Binding.CALENDAR_ACTION, alias="read"),
    "calendar_freebusy": _Call(Binding.CALENDAR_ACTION, alias="freebusy"),
    "calendar_create": _Call(Binding.CALENDAR_ACTION, alias="create"),
    "calendar_update": _Call(Binding.CALENDAR_ACTION, alias="update"),
    "calendar_delete": _Call(Binding.CALENDAR_ACTION, alias="delete"),
    # mail
    "gmail_status": _Call(Binding.GMAIL_ACTION, alias="status"),
    "gmail_setup": _Call(Binding.GMAIL_ACTION, alias="setup"),
    "gmail_disconnect": _Call(Binding.GMAIL_ACTION, alias="disconnect"),
    "gmail_list": _Call(Binding.GMAIL_ACTION, alias="list"),
    "gmail_search": _Call(Binding.GMAIL_ACTION, alias="search"),
    "gmail_read": _Call(Binding.GMAIL_ACTION, alias="read"),
    "gmail_summarize": _Call(Binding.GMAIL_ACTION, alias="summarize"),
    "gmail_labels": _Call(Binding.GMAIL_ACTION, alias="labels"),
    "gmail_draft": _Call(Binding.GMAIL_ACTION, alias="draft"),
    "gmail_send": _Call(Binding.GMAIL_ACTION, alias="send"),
    "gmail_reply": _Call(Binding.GMAIL_ACTION, alias="reply"),
    "gmail_forward": _Call(Binding.GMAIL_ACTION, alias="forward"),
    "gmail_archive": _Call(Binding.GMAIL_ACTION, alias="archive"),
    "gmail_label": _Call(Binding.GMAIL_ACTION, alias="label"),
    "gmail_trash": _Call(Binding.GMAIL_ACTION, alias="trash"),
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
        "system_info",
        _LOW,
        "Report what kind of computer this is: OS, architecture, processor.",
        _DIAGNOSTICS,
        _schema({}),
        notes="Platform facts only. Deliberately narrower than pc_diagnostics, "
        "which discloses the username and paths, and than list_processes, "
        "which adds every running executable.",
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
        "file_search",
        _LOW,
        "Find files by name under the searchable folders.",
        _FILES,
        _schema({"query": _string("What to look for.")}, ("query",)),
        notes="Walks grandpa.files.paths.safe_roots() and nothing wider.",
    ),
    _spec(
        "file_open",
        _LOW,
        "Open a file with whatever application handles it.",
        _FILES,
        _schema({"path": _PATH}, ("path",)),
        notes="os.startfile, the same tier as open_app and open_folder: it "
        "hands the file to an application rather than changing it.",
    ),
    _spec(
        "file_open_folder",
        _LOW,
        "Open the folder that contains a file.",
        _FILES,
        _schema({"path": _PATH}, ("path",)),
    ),
    _spec(
        "file_properties",
        _LOW,
        "Report a file's size, type and dates.",
        _FILES,
        _schema({"path": _PATH}, ("path",)),
    ),
    _spec(
        "file_zip",
        _MEDIUM,
        "Compress a file or folder into a zip archive.",
        _FILES,
        _schema({"path": _PATH, "destination": _DESTINATION}, ("path",)),
        notes="Writes a new archive. The domain refuses rather than "
        "overwriting one that already exists.",
    ),
    _spec(
        "file_extract",
        _MEDIUM,
        "Extract a zip archive.",
        _FILES,
        _schema({"path": _PATH, "destination": _DESTINATION}, ("path",)),
        notes="Writes many files at once, so it is rated with the other "
        "actions that change what is on disk.",
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
        _MEDIUM,
        "Open a URL in the default browser.",
        _BROWSER_NAV,
        _schema({"url": _string("Address to open. https:// is assumed.")}, ("url",)),
        confirmation=Confirmation.DOMAIN,
        notes="Navigates the real browser, so the browser domain decides: it "
        "shows the resolved address and skips the question only for a host in "
        "tools.browser.trusted_domains.",
    ),
    _spec(
        "browser_search",
        _MEDIUM,
        "Search the web in the default browser.",
        _BROWSER_NAV,
        _schema(
            {
                "query": _string("What to search for."),
                "provider": _string(
                    "Which search engine.",
                    enum=["google", "youtube", "github", "stackoverflow"],
                    default="google",
                ),
            },
            ("query",),
        ),
        confirmation=Confirmation.DOMAIN,
        notes="Same rule as browser_open; the search URL is built before the "
        "question so the user is shown what will actually open.",
    ),
    _spec(
        "browser_page",
        _MEDIUM,
        "Open one of the browser's own pages, such as history or downloads.",
        _BROWSER_NAV,
        _schema({"page": _string("Which page, e.g. 'history'.")}, ("page",)),
        confirmation=Confirmation.DOMAIN,
        notes="chrome://history and the like. Confirmed for the same reason: "
        "it navigates the window the user is looking at.",
    ),
    _spec(
        "browser_new_tab",
        _LOW,
        "Open a new, empty browser tab.",
        _BROWSER_NAV,
        _schema({}),
        notes="Ctrl+T. It opens nothing in particular, so there is no address "
        "to show and nothing to confirm -- use browser_open for a URL. This is "
        "narrower than the old execute_browser_action('new_tab', url), which "
        "navigated; that behaviour is browser_open now.",
    ),
    _spec(
        "browser_close_tab",
        _LOW,
        "Close the current browser tab.",
        _BROWSER_NAV,
        _schema({}),
        notes="Ctrl+W.",
    ),
    _spec(
        "browser_refresh",
        _LOW,
        "Reload the current page.",
        _BROWSER_NAV,
        _schema({}),
        notes="Ctrl+R.",
    ),
    _spec(
        "browser_back",
        _MEDIUM,
        "Go back one page.",
        _BROWSER_NAV,
        _schema({}),
        notes="Alt+Left.",
    ),
    _spec(
        "browser_forward",
        _MEDIUM,
        "Go forward one page.",
        _BROWSER_NAV,
        _schema({}),
        notes="Alt+Right.",
    ),
    _spec(
        "browser_reopen_closed_tab",
        _LOW,
        "Reopen the tab that was closed last.",
        _BROWSER_NAV,
        _schema({}),
        notes="Ctrl+Shift+T.",
    ),
    _spec(
        "browser_focus_address_bar",
        _LOW,
        "Put the cursor in the address bar.",
        _BROWSER_NAV,
        _schema({}),
        notes="Ctrl+L.",
    ),
    _spec(
        "browser_title",
        _LOW,
        "Report the title of the page in the visible browser.",
        _AWARENESS,
        _schema({}),
    ),
    _spec(
        "browser_url",
        _LOW,
        "Report the address of the page in the visible browser.",
        _AWARENESS,
        _schema({}),
    ),
    _spec(
        "browser_read",
        _LOW,
        "Read the visible text of the page.",
        _AWARENESS,
        _schema({}),
        notes="Redacted at the ingress boundary before it leaves the browser, "
        "and capped -- page text goes to a model, so a key or a one-time code "
        "on the page must not travel with it.",
    ),
    _spec(
        "browser_selected_text",
        _LOW,
        "Report the text the user has selected in the browser.",
        _AWARENESS,
        _schema({}),
    ),
    _spec(
        "browser_find_text",
        _LOW,
        "Find a phrase on the visible page.",
        _AWARENESS,
        _schema({"query": _string("What to look for.")}, ("query",)),
    ),
    _spec(
        "browser_context",
        _LOW,
        "Report what the visible browser window is showing.",
        _AWARENESS,
        _schema({"scope": _browser_scope("active")}),
        notes="execute_browser_action('context', 'active').",
    ),
    _spec(
        "browser_tabs",
        _LOW,
        "List recently seen browser tabs.",
        _AWARENESS,
        _schema({"scope": _browser_scope("recent")}),
        notes="execute_browser_action('tabs', 'recent').",
    ),
    _spec(
        "browser_summary",
        _LOW,
        "Summarise the readable text of the visible page.",
        _AWARENESS,
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
        _AWARENESS,
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


# --- memory -------------------------------------------------------------------
#
# The third domain, and the first that had no structured seam to migrate onto.
# Notes and downloads both already had `execute(action, ...)` underneath their
# parser; memory_context.handle_memory_command parsed and performed in one
# function, with forget and clear written inline in the dispatcher rather than
# as functions at all. So the seam was extracted first --
# parse_memory_command + execute_memory_action, the same bodies moved -- and
# these entries point at it.
#
# One deliberate behaviour change, flagged rather than hidden: memory_clear is
# HIGH, so it now asks. Chat wiped the store on "clear my memory" without a
# word. Rating an irreversible wipe as LOW to preserve a missing prompt would
# have put a falsehood in the catalogue.

_MEMORY_SUBJECT = _string("What the action is about: a fact, a query, a topic.")

_MEMORY_ACTIONS: tuple[ActionSpec, ...] = (
    _spec(
        "memory_remember",
        _LOW,
        "Remember a fact about the user.",
        _MEMORY,
        _schema({"subject": _string("The fact to remember.")}, ("subject",)),
    ),
    _spec(
        "memory_recall",
        _LOW,
        "Recall what is remembered about a subject.",
        _MEMORY,
        _schema({"subject": _string("What to recall.")}, ("subject",)),
    ),
    _spec(
        "memory_profile",
        _LOW,
        "Summarise everything remembered about the user.",
        _MEMORY,
    ),
    _spec(
        "memory_preferences", _LOW, "Summarise the user's stated preferences.", _MEMORY
    ),
    _spec(
        "memory_projects", _LOW, "List the projects the user is working on.", _MEMORY
    ),
    _spec("memory_project_name", _LOW, "Report the user's current project.", _MEMORY),
    _spec(
        "memory_attribute",
        _LOW,
        "Recall one remembered attribute, such as a name or a birthday.",
        _MEMORY,
        _schema({"subject": _string("Which attribute.")}, ("subject",)),
    ),
    _spec(
        "memory_apps_today",
        _LOW,
        "Report which applications were opened today.",
        _MEMORY,
    ),
    _spec(
        "memory_recent_activity",
        _LOW,
        "Report what the user was recently doing.",
        _MEMORY,
    ),
    _spec(
        "memory_continue_project",
        _LOW,
        "Pick a project back up from what is remembered about it.",
        _MEMORY,
        _schema({"subject": _string("Which project.")}, ("subject",)),
    ),
    _spec(
        "memory_forget",
        _MEDIUM,
        "Forget what is remembered about one subject.",
        _MEMORY,
        _schema({"subject": _string("What to forget.")}, ("subject",)),
        notes="Targeted, and does not ask -- as it has always behaved. Use "
        "memory_recall first if you are unsure what would be removed.",
    ),
    _spec(
        "memory_clear",
        _HIGH,
        "Erase all remembered personal facts and recent activity.",
        _MEMORY,
        notes="Irreversible and total. This now asks first; chat used to wipe "
        "the store without a word.",
    ),
)


# --- reminders and routines ---------------------------------------------------
#
# The fourth and fifth domains, migrated together because chat treats them as
# one subject and the user cannot tell them apart. They are not one thing:
#
#   reminder_*  one-shot reminders in reminders.db   (grandpa.reminders)
#   routine_*   routines and recurring reminders in scheduler.db
#               (grandpa.task_scheduler)
#
# Both are catalogued as they behave today, which includes two things the audit
# found and this migration deliberately did not fix:
#
# * "remind me" reaches one store or the other depending on which parser claims
#   the phrase first -- chat tries the one-shot parser before the scheduler.
# * routine_create_reminder reads "remind me to X at 5pm" as daily:17:00. It
#   repeats every day. A user asking for 5pm today gets a standing appointment.
#
# Splitting the stores, and deciding what "at 5pm" should mean, are their own
# tasks. Describing them accurately here is what makes them fixable.

_REMINDER_PHRASE = _string(
    "The whole phrase, including when: 'in 30 minutes to drink water'."
)

_REMINDER_ACTIONS: tuple[ActionSpec, ...] = (
    _spec(
        "reminder_create",
        _LOW,
        "Set a one-off reminder for a time you give.",
        _REMINDERS,
        _schema({"subject": _REMINDER_PHRASE}, ("subject",)),
        notes="Stored in reminders.db. For anything recurring the scheduler "
        "takes over -- see routine_create_reminder.",
    ),
    _spec(
        "reminder_list",
        _LOW,
        "List the reminders that have not fired yet.",
        _REMINDERS,
    ),
    _spec(
        "reminder_cancel",
        _MEDIUM,
        "Cancel a pending reminder by its id.",
        _REMINDERS,
        _schema({"subject": _string("The reminder's id.")}, ("subject",)),
        notes="Targeted and reversible in effect -- the reminder simply does "
        "not fire -- so it does not ask, as it never has.",
    ),
)

_ROUTINE_NAME = _string("Name of the routine, e.g. 'morning'.")

_SCHEDULER_ACTIONS: tuple[ActionSpec, ...] = (
    _spec(
        "routine_create_morning",
        _MEDIUM,
        "Create the default morning routine: open Chrome and VS Code at 9am.",
        _SCHEDULER,
    ),
    _spec(
        "routine_set_morning",
        _MEDIUM,
        "Replace what the morning routine opens.",
        _SCHEDULER,
        _schema(
            {"targets": _string("Applications to open, as a list in words.")},
            ("targets",),
        ),
        notes="Refuses anything that is not a safe 'open' action.",
    ),
    _spec("routine_list", _LOW, "List routines and recurring reminders.", _SCHEDULER),
    _spec(
        "routine_enable",
        _MEDIUM,
        "Turn a routine on.",
        _SCHEDULER,
        _schema({"name": _ROUTINE_NAME}, ("name",)),
    ),
    _spec(
        "routine_disable",
        _MEDIUM,
        "Turn a routine off.",
        _SCHEDULER,
        _schema({"name": _ROUTINE_NAME}, ("name",)),
    ),
    _spec(
        "routine_run",
        _MEDIUM,
        "Run a routine now.",
        _SCHEDULER,
        _schema({"name": _ROUTINE_NAME}, ("name",)),
        notes="Performs the routine's actions immediately, which for the "
        "default routines means opening applications.",
    ),
    _spec(
        "routine_create_reminder",
        _MEDIUM,
        "Set a repeating reminder: every minute, every hour, or daily at a time.",
        _SCHEDULER,
        _schema(
            {
                "text": _string("What to be reminded of."),
                "schedule": _string(
                    "minutely, hourly, or daily:HH:MM.", default="hourly"
                ),
            },
            ("text",),
        ),
        notes="Stored in scheduler.db, not reminders.db. Note that chat's "
        "phrasing 'remind me to X at 5pm' arrives here as daily:17:00 -- it "
        "repeats every day rather than firing once.",
    ),
)


# --- web search ---------------------------------------------------------------
#
# The sixth domain, and the simplest so far: WebSearchAutomation.execute already
# took a parsed action, so nothing needed extracting.
#
# One pre-existing quirk catalogued rather than fixed: "show sources" reads
# WebSearchAutomation._last_results, which is instance state, and every caller
# builds a fresh instance per command -- chat's handle_web_search_command does
# too. So sources has always come back empty unless the search happened on the
# same instance. Cataloguing it preserves that; fixing it means giving the
# domain somewhere to keep results, which is its own task.

_WEB_SEARCH_ACTIONS: tuple[ActionSpec, ...] = (
    _spec(
        "web_search",
        _LOW,
        "Search the web and summarise what comes back.",
        _WEB_SEARCH,
        _schema(
            {
                "query": _string("What to search for."),
                "max_results": _integer(
                    "How many results to consider.", minimum=1, maximum=20
                ),
            },
            ("query",),
        ),
    ),
    _spec(
        "web_sources",
        _LOW,
        "List the sources behind the last web search.",
        _WEB_SEARCH,
        notes="Reads instance state that every caller rebuilds per command, so "
        "in practice this reports no sources unless the search ran in the same "
        "call. Pre-existing; catalogued as it behaves.",
    ),
    _spec(
        "web_search_status",
        _LOW,
        "Report whether web search is configured and which provider is used.",
        _WEB_SEARCH,
    ),
    _spec(
        "web_clear_cache",
        _LOW,
        "Empty the cached web search results.",
        _WEB_SEARCH,
        notes="Only discards a cache; the next search simply fetches again.",
    ),
)


# --- the clock ----------------------------------------------------------------
#
# One action rather than five. The kinds are an enum on a single tool, because
# every definition sent costs prompt tokens on a cold start and "what is the
# date" versus "what year is it" is a parameter, not a different capability.
#
# handle_datetime_intent had to be split into parse_datetime_intent and
# answer_datetime first -- the same regexes and the same formatting, moved.

_CLOCK_ACTIONS: tuple[ActionSpec, ...] = (
    _spec(
        "datetime_now",
        _LOW,
        "Report the current date, time, day, month or year from the system clock.",
        _CLOCK,
        _schema(
            {
                "kind": _string(
                    "Which part to report.",
                    enum=["date", "time", "year", "month", "dispute"],
                    default="date",
                )
            }
        ),
        notes="'dispute' is the answer for someone insisting the date is wrong: "
        "it says where the answer came from.",
    ),
)


# --- calendar and mail --------------------------------------------------------
#
# Both already had execute(action, confirmed=, confirm=) -- the notes shape --
# and both decide whether to ask from what they parsed, like downloads:
# CalendarSafetyPolicy also asks for a recurring event, and both write the
# prompt from the event or message they found. So the changing actions are
# Confirmation.DOMAIN and the layer hands its callback over.
#
# Neither can be exercised without a Google account, so their e2e coverage is
# thin and stays that way. What is catalogued is the shape, honestly: an action
# with no credentials answers "not configured", and that is a real answer.

_WHICH_EVENT = _string("Which event: a title, or enough of one to find it.")
_WHICH_MESSAGE = _string("Which message: a sender, subject, or search term.")

_CALENDAR_ACTIONS: tuple[ActionSpec, ...] = (
    _spec("calendar_status", _LOW, "Report whether Calendar is connected.", _CALENDAR),
    _spec(
        "calendar_setup",
        _MEDIUM,
        "Start connecting a Google Calendar account.",
        _CALENDAR,
    ),
    _spec(
        "calendar_disconnect",
        _MEDIUM,
        "Disconnect the Google Calendar account.",
        _CALENDAR,
    ),
    _spec(
        "calendar_list",
        _LOW,
        "List calendar events.",
        _CALENDAR,
        _schema({"date_range": _string("Which days, e.g. 'this week'.")}),
    ),
    _spec("calendar_upcoming", _LOW, "List the events coming up next.", _CALENDAR),
    _spec(
        "calendar_search",
        _LOW,
        "Search the calendar for an event.",
        _CALENDAR,
        _schema({"query": _string("What to look for.")}, ("query",)),
    ),
    _spec(
        "calendar_read",
        _LOW,
        "Read one event in full.",
        _CALENDAR,
        _schema({"query": _WHICH_EVENT}, ("query",)),
    ),
    _spec(
        "calendar_freebusy",
        _LOW,
        "Report when the calendar is free or busy.",
        _CALENDAR,
        _schema({"date_range": _string("Which days to check.")}),
    ),
    _spec(
        "calendar_create",
        _MEDIUM,
        "Create a calendar event.",
        _CALENDAR,
        _schema(
            {
                "title": _string("What the event is called."),
                "start_text": _string("When it starts, in words."),
                "end_text": _string("When it ends, in words."),
                "duration_minutes": _integer("How long it lasts.", minimum=1),
                "timezone": _string("Timezone for the event."),
            },
            ("title",),
        ),
        confirmation=Confirmation.DOMAIN,
    ),
    _spec(
        "calendar_update",
        _MEDIUM,
        "Change an existing calendar event.",
        _CALENDAR,
        _schema(
            {
                "query": _WHICH_EVENT,
                "title": _string("A new title."),
                "start_text": _string("A new start, in words."),
                "end_text": _string("A new end, in words."),
            },
            ("query",),
        ),
        confirmation=Confirmation.DOMAIN,
    ),
    _spec(
        "calendar_delete",
        _HIGH,
        "Delete a calendar event.",
        _CALENDAR,
        _schema({"query": _WHICH_EVENT}, ("query",)),
        confirmation=Confirmation.DOMAIN,
    ),
)

_GMAIL_ACTIONS: tuple[ActionSpec, ...] = (
    _spec("gmail_status", _LOW, "Report whether Gmail is connected.", _GMAIL),
    _spec("gmail_setup", _MEDIUM, "Start connecting a Gmail account.", _GMAIL),
    _spec("gmail_disconnect", _MEDIUM, "Disconnect the Gmail account.", _GMAIL),
    _spec(
        "gmail_list",
        _LOW,
        "List recent messages.",
        _GMAIL,
        _schema({"query": _string("Narrow the list, e.g. 'unread'.")}),
    ),
    _spec(
        "gmail_search",
        _LOW,
        "Search the mailbox.",
        _GMAIL,
        _schema({"query": _string("What to look for.")}, ("query",)),
    ),
    _spec(
        "gmail_read",
        _LOW,
        "Read one message.",
        _GMAIL,
        _schema({"selector": _WHICH_MESSAGE}, ("selector",)),
    ),
    _spec(
        "gmail_summarize",
        _LOW,
        "Summarise a message.",
        _GMAIL,
        _schema({"selector": _WHICH_MESSAGE}, ("selector",)),
    ),
    _spec("gmail_labels", _LOW, "List the mailbox's labels.", _GMAIL),
    _spec(
        "gmail_draft",
        _LOW,
        "Write a draft without sending it.",
        _GMAIL,
        _schema(
            {
                "recipient": _string("Who it is to."),
                "subject": _string("The subject line."),
                "body": _string("What it says."),
            },
            ("recipient",),
        ),
        notes="A draft is saved, never sent. Sending is gmail_send.",
    ),
    _spec(
        "gmail_send",
        _MEDIUM,
        "Send an email.",
        _GMAIL,
        _schema(
            {
                "recipient": _string("Who it is to."),
                "subject": _string("The subject line."),
                "body": _string("What it says."),
            },
            ("recipient",),
        ),
        notes="Sends on the user's behalf and cannot be recalled.",
        confirmation=Confirmation.DOMAIN,
    ),
    _spec(
        "gmail_reply",
        _MEDIUM,
        "Reply to a message.",
        _GMAIL,
        _schema(
            {"selector": _WHICH_MESSAGE, "body": _string("What to say.")}, ("selector",)
        ),
        confirmation=Confirmation.DOMAIN,
    ),
    _spec(
        "gmail_forward",
        _MEDIUM,
        "Forward a message to someone.",
        _GMAIL,
        _schema(
            {"selector": _WHICH_MESSAGE, "recipient": _string("Who to forward to.")},
            ("selector", "recipient"),
        ),
        confirmation=Confirmation.DOMAIN,
    ),
    _spec(
        "gmail_archive",
        _MEDIUM,
        "Archive a message out of the inbox.",
        _GMAIL,
        _schema({"selector": _WHICH_MESSAGE}, ("selector",)),
        confirmation=Confirmation.DOMAIN,
    ),
    _spec(
        "gmail_label",
        _MEDIUM,
        "Put a label on a message.",
        _GMAIL,
        _schema(
            {"selector": _WHICH_MESSAGE, "label": _string("Which label.")},
            ("selector", "label"),
        ),
        confirmation=Confirmation.DOMAIN,
    ),
    _spec(
        "gmail_trash",
        _HIGH,
        "Move a message to the bin.",
        _GMAIL,
        _schema({"selector": _WHICH_MESSAGE}, ("selector",)),
        confirmation=Confirmation.DOMAIN,
    ),
)

# --- the application inventory -----------------------------------------------
#
# What is installed and what is running, as opposed to starting and stopping
# things, which is _APPLICATION_ACTIONS above. The formatting moved out of
# desktop/automation.py into the apps domain so that both the layer and that
# handler say the same sentences.

_APPS_INVENTORY: tuple[ActionSpec, ...] = (
    _spec(
        "apps_scan",
        _LOW,
        "Rebuild the list of installed applications.",
        _APPS_INVENTORY_IMPL,
        _schema({}),
        notes="Walks the start menu and registry and saves a local database.",
    ),
    _spec(
        "apps_list",
        _LOW,
        "List the applications installed on this computer.",
        _APPS_INVENTORY_IMPL,
        _schema({}),
    ),
    _spec(
        "apps_search",
        _LOW,
        "Find an installed application by name.",
        _APPS_INVENTORY_IMPL,
        _schema({"query": _string("What to look for.")}, ("query",)),
    ),
    _spec(
        "apps_running",
        _LOW,
        "List the applications running now.",
        _APPS_INVENTORY_IMPL,
        _schema({}),
    ),
    _spec(
        "apps_is_running",
        _LOW,
        "Say whether one application is running.",
        _APPS_INVENTORY_IMPL,
        _schema({"query": _string("Which application.")}, ("query",)),
    ),
    _spec(
        "apps_restart",
        _LOW,
        "Restart an application.",
        _APPS_INVENTORY_IMPL,
        _schema({"query": _string("Which application.")}, ("query",)),
        notes="Catalogued as it behaves: it refuses and explains that it does "
        "not restart anything automatically. Nothing performs it.",
    ),
)

# --- the screen, read by OCR --------------------------------------------------
#
# screen_awareness, which Phase 1.6 kept alongside the vision engine because it
# reads pixels rather than the accessibility tree. Its answers were formatted
# inside local_actions._execute; they now live in screen_awareness, so these
# point there.

_SCREEN = "grandpa.screen_awareness"

_SCREEN_ACTIONS: tuple[ActionSpec, ...] = (
    _spec(
        "screen_capture",
        _LOW,
        "Take a screenshot and save it.",
        f"{_SCREEN}.capture_screen_answer",
        _schema({}),
        notes="Writes an image to ~/.grandpa/screenshots, which the files "
        "domain protects. Refuses a credential or payment screen by its title "
        "before a pixel is grabbed -- until Phase 1.7 it wrote one to disk "
        "and kept it.",
    ),
    _spec(
        "screen_describe",
        _LOW,
        "Describe what is on the screen, reading its text.",
        f"{_SCREEN}.describe_screen_answer",
        _schema({}),
        notes="OCR text is redacted where pixels become text. A screen that "
        "shows credentials is refused, and the screenshot taken to find that "
        "out is removed rather than kept.",
    ),
    _spec(
        "screen_active_window",
        _LOW,
        "Name the window in front.",
        f"{_SCREEN}.active_window_answer",
        _schema({}),
    ),
    _spec(
        "screen_diagnostics",
        _LOW,
        "Report what screen reading can do on this machine.",
        f"{_SCREEN}.screen_diagnostics_answer",
        _schema({}),
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
    *_APPS_INVENTORY,
    *_SCREEN_ACTIONS,
    *_NOTES_ACTIONS,
    *_DOWNLOADS_ACTIONS,
    *_MEMORY_ACTIONS,
    *_REMINDER_ACTIONS,
    *_SCHEDULER_ACTIONS,
    *_WEB_SEARCH_ACTIONS,
    *_CLOCK_ACTIONS,
    *_CALENDAR_ACTIONS,
    *_GMAIL_ACTIONS,
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

_GOOGLE_OWNED: tuple[str, ...] = tuple(
    [f"calendar_{name}" for name in CALENDAR_NAMES]
    + [f"gmail_{name}" for name in GMAIL_NAMES]
)

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
            "the files domain, bounded by size and restricted to "
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
        **{
            f"memory_{action}": (
                "Memory is the third domain migrated, and the first with no "
                "structured seam of its own -- parse_memory_command and "
                "execute_memory_action were extracted from the dispatcher "
                "before it could be catalogued."
            )
            for action in (
                "remember",
                "recall",
                "profile",
                "preferences",
                "projects",
                "project_name",
                "attribute",
                "apps_today",
                "recent_activity",
                "continue_project",
                "forget",
                "clear",
            )
        },
        **{
            name: (
                "Reminders and routines, migrated together because chat treats "
                "them as one subject. They are two stores -- reminders.db and "
                "scheduler.db -- and the catalogue says so rather than "
                "pretending otherwise."
            )
            for name in (
                "reminder_create",
                "reminder_list",
                "reminder_cancel",
                "routine_create_morning",
                "routine_set_morning",
                "routine_list",
                "routine_enable",
                "routine_disable",
                "routine_run",
                "routine_create_reminder",
            )
        },
        **{
            name: (
                "Web search, migrated sixth. WebSearchAutomation.execute already "
                "took a parsed action, so nothing had to be extracted first."
            )
            for name in (
                "web_search",
                "web_sources",
                "web_search_status",
                "web_clear_cache",
            )
        },
        "screen_capture": (
            "screen_awareness grabs pixels; pc_control has no entry for it."
        ),
        "screen_describe": ("OCR of the screen. No pc_control entry."),
        "screen_active_window": ("The window in front. No pc_control entry."),
        "screen_diagnostics": ("Screen reading readiness. No pc_control entry."),
        "system_info": (
            "Platform facts. pc_control has no entry for them: the answer lived "
            "in a private helper in local_actions, so the layer could not give it "
            "without over-disclosing through pc_diagnostics, which names the user."
        ),
        "apps_scan": (
            "The application inventory. pc_control has no entry for it: "
            "desktop/automation.py answered these itself, which is why the "
            "layer could not reach them at all."
        ),
        "apps_list": ("Installed applications. No pc_control entry."),
        "apps_search": ("Find an installed application. No pc_control entry."),
        "apps_running": ("Running applications. No pc_control entry."),
        "apps_is_running": ("Is one application running. No pc_control entry."),
        "apps_restart": (
            "Catalogued as it behaves -- it refuses. Nothing restarts an "
            "application; the honest refusal is better than a guess."
        ),
        "browser_title": (
            "browser_awareness reads the visible page. pc_control has no "
            "entry for the page title."
        ),
        "browser_url": ("The address of the visible page. No pc_control entry."),
        "browser_read": (
            "The visible text, redacted and capped. No pc_control entry; its "
            "browser_summary summarises rather than reading out."
        ),
        "browser_selected_text": (
            "What the user has highlighted. No pc_control entry."
        ),
        "browser_find_text": ("Find a phrase on the page. No pc_control entry."),
        "file_search": (
            "grandpa.files walks the searchable roots; pc_control has no "
            "search of its own."
        ),
        "file_open": (
            "os.startfile on a document. pc_control opens folders and apps "
            "but never had an entry for opening a file."
        ),
        "file_open_folder": (
            "Reveals a file in its folder. pc_control's open_folder takes a "
            "folder, not a file to reveal."
        ),
        "file_properties": (
            "Size, type and dates. A read, and pc_control has no equivalent."
        ),
        "file_zip": (
            "Archive creation lives in grandpa.files; pc_control never had "
            "it. MEDIUM like file_move: it writes something new."
        ),
        "file_extract": (
            "The other half of zip, and the riskier one -- it writes many "
            "files at once."
        ),
        "browser_page": (
            "The browser's own pages -- history, downloads, settings. "
            "grandpa.browser knows the chrome:// URLs; pc_control never had an "
            "entry for them. Confirmed like any other navigation."
        ),
        "browser_close_tab": (
            "Ctrl+W through grandpa.browser. pc_control has no entry: its "
            "browser_control stubs never touched the visible window."
        ),
        "browser_refresh": (
            "Ctrl+R through grandpa.browser. pc_control's browser_reload was a "
            "stub that always returned requires_confirmation and reloaded "
            "nothing, so this is the capability appearing, not moving."
        ),
        "browser_reopen_closed_tab": (
            "Ctrl+Shift+T through grandpa.browser. No pc_control equivalent."
        ),
        "browser_focus_address_bar": (
            "Ctrl+L through grandpa.browser. No pc_control equivalent."
        ),
        "datetime_now": (
            "The system clock, migrated seventh. handle_datetime_intent was "
            "split into parse_datetime_intent and answer_datetime first -- the "
            "same regexes and formatting, moved."
        ),
        **{
            name: (
                "Calendar and mail, migrated eighth and ninth. Both already had "
                "the notes shape, and both decide whether to ask from what they "
                "parsed, so their changing actions ask through the domain."
            )
            for name in _GOOGLE_OWNED
        },
    }
)


# --- tiers: what a model is handed, and when ---------------------------------
#
# The whole catalogue is ~9,400 tokens of tool definitions. On a machine
# without a GPU, Ollama evaluates a cold prompt at roughly ten tokens a second,
# so handing a model all 108 actions costs about sixteen minutes before it can
# say anything. That is not a shippable first request.
#
# So the catalogue is served in two tiers. CORE is always sent and never
# changes, which is what lets Ollama reuse its cached prefix; everything else
# is grouped by domain and fetched on demand with the load_tools meta-tool.
# Nothing becomes unreachable -- only deferred by one round trip.

DOMAINS: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "apps": ("open_app", "detect_app", "close_app", "open_folder"),
        # Kept out of "apps" deliberately. apps is a core domain, sent whole on
        # every request, and core holds what someone does daily: starting and
        # stopping programs. Asking what is installed is a different question
        # and a rarer one, so it is its own subject and deferred -- putting it
        # in apps would have grown the cold start from 953 tokens to 1,302 for
        # six actions nobody asks for most days.
        "inventory": (
            "apps_scan",
            "apps_list",
            "apps_search",
            "apps_running",
            "apps_is_running",
            "apps_restart",
        ),
        "windows": (
            "list_windows",
            "focus_window",
            "minimize_window",
            "maximize_window",
            "restore_window",
            "close_window",
        ),
        "system": (
            "system_lock",
            "system_sleep",
            "system_restart",
            "system_shutdown",
            "empty_recycle_bin",
        ),
        "volume": (
            "volume_get",
            "volume_set",
            "volume_up",
            "volume_down",
            "volume_mute",
            "volume_unmute",
        ),
        "brightness": ("brightness_get", "brightness_set"),
        "clipboard": (
            "clipboard_read",
            "clipboard_write",
            "clipboard_clear",
            "clipboard_inspect",
            "clipboard_history",
        ),
        "display": ("list_monitors", "monitor_info"),
        "diagnostics": (
            "active_process",
            "list_processes",
            "desktop_summary",
            "pc_diagnostics",
            "system_info",
            "screen_capture",
            "screen_describe",
            "screen_active_window",
            "screen_diagnostics",
            "screenshot_describe",
        ),
        "files": (
            "file_read",
            "file_search",
            "file_open",
            "file_open_folder",
            "file_properties",
            "file_zip",
            "file_extract",
            "file_create",
            "file_rename",
            "file_move",
            "file_copy",
            "file_delete",
        ),
        "input": (
            "keyboard_type",
            "keyboard_hotkey",
            "mouse_move",
            "mouse_click",
            "mouse_scroll",
            "mouse_drag",
            "desktop_navigate",
        ),
        "browser": (
            "browser_open",
            "browser_search",
            "browser_page",
            "browser_new_tab",
            "browser_close_tab",
            "browser_refresh",
            "browser_back",
            "browser_forward",
            "browser_reopen_closed_tab",
            "browser_focus_address_bar",
            "browser_context",
            "browser_title",
            "browser_url",
            "browser_read",
            "browser_selected_text",
            "browser_find_text",
            "browser_tabs",
            "browser_summary",
            "browser_headings",
            "browser_links",
            "browser_buttons",
            "browser_media",
            "browser_diagnostics",
            "browser_task",
        ),
        "notes": (
            "notes_create",
            "notes_list",
            "notes_search",
            "notes_read",
            "notes_recent",
            "notes_append",
            "notes_rename",
            "notes_delete",
            "notes_archive",
            "notes_restore",
            "notes_pin",
            "notes_unpin",
        ),
        "downloads": (
            "downloads_recent",
            "downloads_today",
            "downloads_latest",
            "downloads_search",
            "downloads_large",
            "downloads_incomplete",
            "downloads_duplicates",
            "downloads_info",
            "downloads_open",
            "downloads_open_folder",
            "downloads_move",
            "downloads_organize",
            "downloads_archive",
            "downloads_delete",
        ),
        "memory": (
            "memory_remember",
            "memory_recall",
            "memory_profile",
            "memory_preferences",
            "memory_projects",
            "memory_project_name",
            "memory_attribute",
            "memory_apps_today",
            "memory_recent_activity",
            "memory_continue_project",
            "memory_forget",
            "memory_clear",
        ),
        "reminders": ("reminder_create", "reminder_list", "reminder_cancel"),
        "clock": ("datetime_now",),
        "calendar": tuple(f"calendar_{name}" for name in CALENDAR_NAMES),
        "mail": tuple(f"gmail_{name}" for name in GMAIL_NAMES),
        "web": (
            "web_search",
            "web_sources",
            "web_search_status",
            "web_clear_cache",
        ),
        "routines": (
            "routine_create_morning",
            "routine_set_morning",
            "routine_list",
            "routine_enable",
            "routine_disable",
            "routine_run",
            "routine_create_reminder",
        ),
    }
)
"""Every catalogued action, grouped by the subject a person would name.

The groups are what ``load_tools`` takes, so they are chosen to match how
someone asks -- "my notes", "my downloads", "the browser" -- rather than which
service class happens to implement them.
"""

CORE_DOMAINS: tuple[str, ...] = ("apps", "clock", "volume")
"""The subjects sent in full on every request.

**Whole domains only, and that is the point.** Measured on grandpa-brain: the
model calls ``load_tools`` for a subject that is wholly absent from its list,
and does not when part of the subject is already in front of it. Asked to pin a
note while holding notes_create, notes_list, notes_read and notes_search, it
answered "I cannot directly pin a note to the top"; handed the whole catalogue
it calls ``notes_pin`` at once. Seeing four notes tools reads as having all the
notes tools. Splitting a domain therefore does not defer its other actions, it
hides them.

These three were chosen as the smallest set of whole domains covering what is
asked most:

* **apps** -- "open spotify", "close chrome", "open my downloads". The single
  most frequent request, and the one where a round trip is most noticeable.
* **volume** -- "turn it down", "mute". Constant, and six small definitions.
* **clock** -- "what time is it". One action, 110 tokens, asked daily.

Eleven actions and roughly 960 tokens with ``load_tools``, against 1,665 for
the twenty split actions this replaces. Notes and browser are the next most
common and cost twelve actions each; they are deferred deliberately, because
with the split repaired a deferred domain costs one round trip rather than
being unreachable.
"""

CORE_ACTIONS: tuple[str, ...] = tuple(
    action for domain in CORE_DOMAINS for action in DOMAINS[domain]
)
"""The core actions, derived so that a domain cannot be half-included.

Derivation is the guard: there is no hand-written list to fall out of step with
DOMAINS, and adding a subject to core means adding all of it. The order follows
CORE_DOMAINS and then each domain's own order, so the block stays byte-identical
between requests -- which is what makes Ollama reuse the prefix instead of
re-evaluating it.
"""


def domain_of(action: str) -> str | None:
    """Which domain an action belongs to, or ``None`` if it is not catalogued."""
    return _DOMAIN_BY_ACTION.get(action)


def loadable_domains() -> tuple[str, ...]:
    """Subjects ``load_tools`` can add, sorted.

    A core domain is sent whole, so asking for it would add nothing. It
    is left out of the offer rather than accepted and silently ignored --
    a round trip that buys no tools is the cost this tiering exists to
    avoid.
    """
    return tuple(sorted(set(DOMAINS) - set(CORE_DOMAINS)))


def extended_actions(domain: str) -> tuple[ActionSpec, ...]:
    """The specs a domain adds beyond CORE, in catalogue order."""
    wanted = set(DOMAINS.get(domain, ())) - set(CORE_ACTIONS)
    return tuple(spec for spec in CATALOGUE if spec.name in wanted)


_DOMAIN_BY_ACTION: Mapping[str, str] = MappingProxyType(
    {action: domain for domain, actions in DOMAINS.items() for action in actions}
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

# Every catalogued action belongs to exactly one domain, and no domain names
# an action that does not exist. Without this the tiering silently drops things.
_GROUPED = [action for actions in DOMAINS.values() for action in actions]
if sorted(_GROUPED) != sorted(_BY_NAME):  # pragma: no cover - construction check
    missing = sorted(set(_BY_NAME) - set(_GROUPED))
    unknown = sorted(set(_GROUPED) - set(_BY_NAME))
    raise RuntimeError(
        f"DOMAINS does not cover the catalogue: missing={missing} unknown={unknown}"
    )
if len(_GROUPED) != len(set(_GROUPED)):  # pragma: no cover - construction check
    raise RuntimeError("an action appears in more than one domain")
if set(CORE_ACTIONS) - set(_BY_NAME):  # pragma: no cover - construction check
    raise RuntimeError(
        f"CORE_ACTIONS names actions that do not exist: "
        f"{sorted(set(CORE_ACTIONS) - set(_BY_NAME))}"
    )

# An action cannot be both catalogued and excluded.
if set(_BY_NAME) & set(EXCLUSIONS):  # pragma: no cover - construction-time check
    raise RuntimeError(
        "actions are both catalogued and excluded: "
        + ", ".join(sorted(set(_BY_NAME) & set(EXCLUSIONS)))
    )
