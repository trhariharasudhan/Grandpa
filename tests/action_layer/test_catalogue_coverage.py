"""The test that keeps the catalogue from rotting.

A catalogue is only worth having if it is true, so this file checks the four
ways it could quietly stop being true:

1. an entry names an implementation that no longer exists;
2. ``pc_control`` grows an action nobody decided about;
3. the catalogue and ``pc_control`` disagree about how risky something is;
4. an entry's JSON schema is malformed, so the tool export emits nonsense.

It imports ``pc_control`` deliberately. The *catalogue* must not depend on it --
that is the whole point of the layer -- but the test that proves the two agree
has to be able to see both.
"""

from __future__ import annotations

import importlib
import json
from typing import Any

import pytest

from grandpa import pc_control
from grandpa.action_layer.catalogue import (
    CATALOGUE,
    EXCLUSIONS,
    LAYER_OWNED,
    ActionSpec,
    Confirmation,
)
from grandpa.action_layer.model import RiskLevel

# pc_control's four risk tables, flattened into action -> tier.
PC_CONTROL_RISK: dict[str, str] = {
    **{action: "LOW" for action in pc_control.LOW_RISK_ACTIONS},
    **{action: "MEDIUM" for action in pc_control.MEDIUM_RISK_ACTIONS},
    **{action: "HIGH" for action in pc_control.HIGH_RISK_ACTIONS},
    **{action: "BLOCKED" for action in pc_control.BLOCKED_ACTIONS},
}

CATALOGUE_BY_NAME = {spec.name: spec for spec in CATALOGUE}

_JSON_TYPES = {"object", "array", "string", "integer", "number", "boolean", "null"}


def _resolve(dotted: str) -> Any:
    """Import the longest module prefix of ``dotted``, then walk the rest."""
    parts = dotted.split(".")
    for cut in range(len(parts) - 1, 0, -1):
        try:
            module = importlib.import_module(".".join(parts[:cut]))
        except ImportError:
            continue
        target: Any = module
        for attribute in parts[cut:]:
            target = getattr(target, attribute)  # AttributeError is the failure
        return target
    raise ModuleNotFoundError(f"no importable module prefix in {dotted!r}")


# --- 1. every implementation exists and can be called ------------------------


@pytest.mark.parametrize("spec", CATALOGUE, ids=lambda spec: spec.name)
def test_every_implementation_path_resolves_to_a_callable(spec: ActionSpec) -> None:
    target = _resolve(spec.implementation)

    assert callable(target), f"{spec.name}: {spec.implementation} is not callable"


def test_a_dangling_implementation_path_fails_this_check() -> None:
    """The check above is only worth running if a rename would break it."""
    # A renamed method, and a module that no longer exists under a package
    # that still does -- both land on the getattr walk.
    with pytest.raises(AttributeError):
        _resolve("grandpa.desktop.control.power.PowerControlService.execute_renamed")

    with pytest.raises(AttributeError):
        _resolve("grandpa.desktop.control.no_such_module.Service.execute")

    # Nothing importable at all.
    with pytest.raises(ModuleNotFoundError):
        _resolve("no_such_package.Service.execute")


# --- 2. nothing in pc_control's tables is undecided ---------------------------


@pytest.mark.parametrize("action", sorted(PC_CONTROL_RISK), ids=lambda name: name)
def test_every_pc_control_action_is_catalogued_or_excluded_with_a_reason(
    action: str,
) -> None:
    if action in CATALOGUE_BY_NAME:
        assert action not in EXCLUSIONS, f"{action} is both catalogued and excluded"
        return

    assert action in EXCLUSIONS, (
        f"{action} is in a pc_control risk table but is neither catalogued nor "
        "excluded. Add a catalogue entry, or an EXCLUSIONS entry saying why not."
    )
    reason = EXCLUSIONS[action]
    assert reason.strip(), f"{action} is excluded without a reason"


def test_the_catalogue_invents_no_actions() -> None:
    """Every entry is either pc_control's or declared as this layer's own.

    An action in neither place is a fiction: nothing performs it, or nothing
    decided what it is.
    """
    unknown = sorted(set(CATALOGUE_BY_NAME) - set(PC_CONTROL_RISK) - set(LAYER_OWNED))

    assert not unknown, (
        f"catalogued but absent from pc_control's tables and from LAYER_OWNED: "
        f"{unknown}. Add it to a risk table, or declare it in LAYER_OWNED with "
        "the reason it lives only in the layer."
    )


@pytest.mark.parametrize("action", sorted(LAYER_OWNED), ids=lambda name: name)
def test_a_layer_owned_action_is_catalogued_and_has_a_reason(action: str) -> None:
    assert action in CATALOGUE_BY_NAME, f"{action} is declared but not catalogued"
    assert LAYER_OWNED[action].strip(), f"{action} is declared without a reason"


@pytest.mark.parametrize("action", sorted(LAYER_OWNED), ids=lambda name: name)
def test_layer_owned_cannot_hide_a_risk_disagreement(action: str) -> None:
    """If pc_control does rate it, the contradiction check must apply."""
    assert action not in PC_CONTROL_RISK, (
        f"{action} is in a pc_control risk table, so it is not the layer's own "
        "and must be held to pc_control's tier"
    )


# A second, independent statement of what each layer-owned action is rated and
# who asks about it. pc_control's tables give the rest of the catalogue this
# property for free; the layer's own actions need it written down somewhere the
# catalogue cannot also change in the same edit, or "no contradictions" means
# nothing here.
NONE = Confirmation.NONE
LAYER = Confirmation.LAYER
DOMAIN = Confirmation.DOMAIN

EXPECTED_LAYER_RISK: dict[str, tuple[str, Confirmation]] = {
    # browser: navigation is confirmed by the domain, because whether to ask
    # depends on the resolved URL and on tools.browser.trusted_domains, neither
    # of which the layer can see. The hotkeys move the page but name no
    # address, so they ask nothing.
    # files: reading and listing are LOW, writing something new is MEDIUM,
    # matching file_create and file_move in pc_control's own table.
    # browser awareness: every one is a read of the visible page.
    "browser_title": ("LOW", NONE),
    "browser_url": ("LOW", NONE),
    "browser_read": ("LOW", NONE),
    "browser_selected_text": ("LOW", NONE),
    "browser_find_text": ("LOW", NONE),
    "file_search": ("LOW", NONE),
    "file_open": ("LOW", NONE),
    "file_open_folder": ("LOW", NONE),
    "file_properties": ("LOW", NONE),
    "file_zip": ("MEDIUM", NONE),
    "file_extract": ("MEDIUM", NONE),
    "browser_page": ("MEDIUM", DOMAIN),
    "browser_close_tab": ("LOW", NONE),
    "browser_refresh": ("LOW", NONE),
    "browser_reopen_closed_tab": ("LOW", NONE),
    "browser_focus_address_bar": ("LOW", NONE),
    "volume_get": ("LOW", NONE),
    "file_read": ("LOW", NONE),
    "screenshot_describe": ("LOW", NONE),
    # notes: reading and creating are LOW like file_create, changing existing
    # content is MEDIUM like file_rename, deleting is HIGH like file_delete
    # because NotesStore.delete unlinks the file. Its confirmation rule is
    # static, so the executor can ask before it calls.
    "notes_list": ("LOW", NONE),
    "notes_recent": ("LOW", NONE),
    "notes_search": ("LOW", NONE),
    "notes_read": ("LOW", NONE),
    "notes_create": ("LOW", NONE),
    "notes_pin": ("LOW", NONE),
    "notes_unpin": ("LOW", NONE),
    "notes_append": ("MEDIUM", NONE),
    "notes_rename": ("MEDIUM", NONE),
    "notes_archive": ("MEDIUM", NONE),
    "notes_restore": ("MEDIUM", NONE),
    "notes_delete": ("HIGH", LAYER),
    # downloads: the same file tiers, but everything that changes files asks
    # through the domain, because the prompt quotes the scan and a one-file
    # move is deliberately silent.
    "downloads_recent": ("LOW", NONE),
    "downloads_today": ("LOW", NONE),
    "downloads_latest": ("LOW", NONE),
    "downloads_search": ("LOW", NONE),
    "downloads_large": ("LOW", NONE),
    "downloads_incomplete": ("LOW", NONE),
    "downloads_duplicates": ("LOW", NONE),
    "downloads_info": ("LOW", NONE),
    "downloads_open_folder": ("LOW", NONE),
    "downloads_open": ("MEDIUM", NONE),
    "downloads_move": ("MEDIUM", DOMAIN),
    "downloads_organize": ("MEDIUM", DOMAIN),
    "downloads_archive": ("MEDIUM", DOMAIN),
    "downloads_delete": ("HIGH", DOMAIN),
    # memory: reading is LOW, forgetting one subject is MEDIUM and silent as it
    # has always been, and clearing everything is HIGH -- which is the one
    # deliberate behaviour change in the third migration, because chat used to
    # wipe the store without asking.
    "memory_remember": ("LOW", NONE),
    "memory_recall": ("LOW", NONE),
    "memory_profile": ("LOW", NONE),
    "memory_preferences": ("LOW", NONE),
    "memory_projects": ("LOW", NONE),
    "memory_project_name": ("LOW", NONE),
    "memory_attribute": ("LOW", NONE),
    "memory_apps_today": ("LOW", NONE),
    "memory_recent_activity": ("LOW", NONE),
    "memory_continue_project": ("LOW", NONE),
    "memory_forget": ("MEDIUM", NONE),
    "memory_clear": ("HIGH", LAYER),
    # one-shot reminders (reminders.db). Cancelling only stops a notification,
    # so it is MEDIUM and silent, as it has always been.
    "reminder_create": ("LOW", NONE),
    "reminder_list": ("LOW", NONE),
    "reminder_cancel": ("MEDIUM", NONE),
    # routines and recurring reminders (scheduler.db). Running one opens real
    # applications, so it is MEDIUM like the rest of the changes here.
    "routine_create_morning": ("MEDIUM", NONE),
    "routine_set_morning": ("MEDIUM", NONE),
    "routine_list": ("LOW", NONE),
    "routine_enable": ("MEDIUM", NONE),
    "routine_disable": ("MEDIUM", NONE),
    "routine_run": ("MEDIUM", NONE),
    "routine_create_reminder": ("MEDIUM", NONE),
    # web search: reads the web, empties a cache. Nothing to ask about.
    "web_search": ("LOW", NONE),
    "web_sources": ("LOW", NONE),
    "web_search_status": ("LOW", NONE),
    "web_clear_cache": ("LOW", NONE),
    # the clock
    "datetime_now": ("LOW", NONE),
    # calendar: reading is LOW, connecting and changing are MEDIUM, deleting an
    # event is HIGH. Everything that changes asks through the domain, because
    # the prompt quotes the event it matched.
    "calendar_status": ("LOW", NONE),
    "calendar_list": ("LOW", NONE),
    "calendar_upcoming": ("LOW", NONE),
    "calendar_search": ("LOW", NONE),
    "calendar_read": ("LOW", NONE),
    "calendar_freebusy": ("LOW", NONE),
    "calendar_setup": ("MEDIUM", NONE),
    "calendar_disconnect": ("MEDIUM", NONE),
    "calendar_create": ("MEDIUM", DOMAIN),
    "calendar_update": ("MEDIUM", DOMAIN),
    "calendar_delete": ("HIGH", DOMAIN),
    # mail: same shape. Sending cannot be recalled, so it asks; a draft is
    # saved and not sent, so it does not.
    "gmail_status": ("LOW", NONE),
    "gmail_list": ("LOW", NONE),
    "gmail_search": ("LOW", NONE),
    "gmail_read": ("LOW", NONE),
    "gmail_summarize": ("LOW", NONE),
    "gmail_labels": ("LOW", NONE),
    "gmail_draft": ("LOW", NONE),
    "gmail_setup": ("MEDIUM", NONE),
    "gmail_disconnect": ("MEDIUM", NONE),
    "gmail_send": ("MEDIUM", DOMAIN),
    "gmail_reply": ("MEDIUM", DOMAIN),
    "gmail_forward": ("MEDIUM", DOMAIN),
    "gmail_archive": ("MEDIUM", DOMAIN),
    "gmail_label": ("MEDIUM", DOMAIN),
    "gmail_trash": ("HIGH", DOMAIN),
}


def test_the_expected_risk_table_covers_exactly_what_the_layer_owns() -> None:
    assert set(EXPECTED_LAYER_RISK) == set(LAYER_OWNED), (
        "a layer-owned action was added or removed without saying what it is "
        "rated: "
        f"{sorted(set(EXPECTED_LAYER_RISK) ^ set(LAYER_OWNED))}"
    )


@pytest.mark.parametrize("action", sorted(EXPECTED_LAYER_RISK), ids=lambda name: name)
def test_a_layer_owned_action_is_rated_as_declared(action: str) -> None:
    expected_risk, expected_confirmation = EXPECTED_LAYER_RISK[action]
    spec = CATALOGUE_BY_NAME[action]

    assert spec.risk.value == expected_risk, action
    assert spec.confirmation is expected_confirmation, action


@pytest.mark.parametrize("action", sorted(LAYER_OWNED), ids=lambda name: name)
def test_every_high_risk_layer_action_is_confirmed_by_someone(action: str) -> None:
    """Who asks may vary; whether anyone asks may not."""
    spec = CATALOGUE_BY_NAME[action]

    if spec.risk is RiskLevel.HIGH:
        assert spec.confirmation is not Confirmation.NONE, action
    if spec.confirmation is Confirmation.NONE:
        assert spec.risk is not RiskLevel.HIGH, action


def test_confirmation_is_not_decoration() -> None:
    """It belongs where something is lost or moved, and nowhere else."""
    asking = {
        name for name in LAYER_OWNED if CATALOGUE_BY_NAME[name].requires_confirmation
    }

    assert asking == {
        "notes_delete",
        "downloads_delete",
        "downloads_move",
        "downloads_organize",
        "downloads_archive",
        "memory_clear",
        "calendar_create",
        "calendar_update",
        "calendar_delete",
        "gmail_send",
        "gmail_reply",
        "gmail_forward",
        "gmail_archive",
        "gmail_label",
        "gmail_trash",
        "browser_page",
    }, asking


def test_the_exclusion_list_excludes_only_real_actions() -> None:
    unknown = sorted(set(EXCLUSIONS) - set(PC_CONTROL_RISK))

    assert not unknown, f"excluded but absent from pc_control's tables: {unknown}"


# --- 3. the two never disagree about risk ------------------------------------


@pytest.mark.parametrize(
    "spec",
    [spec for spec in CATALOGUE if spec.name in PC_CONTROL_RISK],
    ids=lambda spec: spec.name,
)
def test_no_entry_contradicts_pc_controls_risk_table(spec: ActionSpec) -> None:
    assert spec.risk.value == PC_CONTROL_RISK[spec.name], (
        f"{spec.name}: catalogue says {spec.risk.value}, pc_control says "
        f"{PC_CONTROL_RISK[spec.name]}"
    )


def test_nothing_blocked_is_offered_as_a_capability() -> None:
    blocked = sorted(spec.name for spec in CATALOGUE if spec.risk is RiskLevel.BLOCKED)

    assert not blocked, f"BLOCKED actions must never be catalogued: {blocked}"
    assert set(pc_control.BLOCKED_ACTIONS) <= set(EXCLUSIONS)


@pytest.mark.parametrize(
    "spec",
    [spec for spec in CATALOGUE if spec.name in PC_CONTROL_RISK],
    ids=lambda spec: spec.name,
)
def test_confirmation_matches_pc_controls_approval_gate(spec: ActionSpec) -> None:
    """pc_control.py:306-310 -- HIGH, or on the approval-required list."""
    expected = (
        spec.risk is RiskLevel.HIGH or spec.name in pc_control.APPROVAL_REQUIRED_ACTIONS
    )

    assert spec.requires_confirmation is expected, (
        f"{spec.name}: catalogue asks for confirmation="
        f"{spec.requires_confirmation}, pc_control would use {expected}"
    )


# --- 4. every schema is a valid schema ---------------------------------------


def _assert_valid_property(action: str, name: str, schema: Any) -> None:
    where = f"{action}.{name}"
    assert isinstance(schema, dict), f"{where}: property schema must be an object"
    declared = schema.get("type")
    assert declared in _JSON_TYPES, f"{where}: bad or missing type {declared!r}"
    assert schema.get("description", "").strip(), f"{where}: needs a description"

    if "enum" in schema:
        assert isinstance(schema["enum"], list) and schema["enum"], (
            f"{where}: enum must be a non-empty list"
        )
        if declared == "string":
            assert all(isinstance(value, str) for value in schema["enum"]), (
                f"{where}: enum values must match the declared type"
            )
    if "default" in schema and "enum" in schema:
        assert schema["default"] in schema["enum"], f"{where}: default is not in enum"
    if "minimum" in schema and "maximum" in schema:
        assert schema["minimum"] <= schema["maximum"], f"{where}: minimum > maximum"
    if declared == "array":
        assert isinstance(schema.get("items"), dict), f"{where}: array needs items"
        assert schema["items"].get("type") in _JSON_TYPES, f"{where}: bad items type"


@pytest.mark.parametrize("spec", CATALOGUE, ids=lambda spec: spec.name)
def test_every_entrys_json_schema_is_valid(spec: ActionSpec) -> None:
    schema = dict(spec.parameters)

    assert schema.get("type") == "object", f"{spec.name}: schema must be an object"
    properties = schema.get("properties")
    assert isinstance(properties, dict), f"{spec.name}: properties must be an object"
    required = schema.get("required", [])
    assert isinstance(required, list), f"{spec.name}: required must be a list"
    assert len(set(required)) == len(required), f"{spec.name}: duplicate required key"

    missing = sorted(set(required) - set(properties))
    assert not missing, f"{spec.name}: required names no such property: {missing}"

    for name, property_schema in properties.items():
        _assert_valid_property(spec.name, name, property_schema)

    # It has to survive the trip to a model as JSON.
    assert json.loads(json.dumps(schema)) == schema, f"{spec.name}: not JSON round-trip"


@pytest.mark.parametrize("spec", CATALOGUE, ids=lambda spec: spec.name)
def test_every_entry_says_what_it_does(spec: ActionSpec) -> None:
    assert spec.description.strip(), f"{spec.name}: no description"
    assert spec.description.strip().endswith("."), f"{spec.name}: description is a line"
