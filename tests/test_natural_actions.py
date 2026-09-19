"""The front end that moves local_actions' phrases onto the action layer.

Nothing here reads the real screen, browser or clipboard: every implementation
a migrated phrase would reach is replaced, and the replacement is asserted to
hold before anything that matters is checked.
"""

from __future__ import annotations

import pytest

from grandpa.natural_actions import MIGRATED, request_for, run_parsed


@pytest.fixture(autouse=True)
def _audit_log(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GRANDPA_LOCAL_ACTION_LOG", str(tmp_path / "actions.jsonl"))


def test_every_migrated_shape_names_a_catalogued_action() -> None:
    from grandpa.action_layer.catalogue import get

    for shape, value in MIGRATED.items():
        name, parameters = value(shape[1]) if callable(value) else value
        spec = get(name)
        assert spec is not None, shape
        allowed = set(spec.parameters.get("properties", {}))
        assert set(parameters) <= allowed, (shape, parameters, allowed)


def test_an_unmigrated_shape_is_left_to_the_legacy_dispatch() -> None:
    assert request_for("chrome_profile", "Someone") is None
    assert run_parsed("chrome_profile", "Someone") is None


def test_an_app_lookup_by_name_asks_the_same_resolver() -> None:
    assert request_for("app_lookup", "chrome") == ("detect_app", {"app": "chrome"})
    # ... and the exact entry wins over the kind-wide one.
    assert request_for("app_lookup", "installed_apps") == ("apps_list", {})


def test_a_dry_run_describes_and_performs_nothing(monkeypatch) -> None:
    called: list[str] = []
    monkeypatch.setattr(
        "grandpa.action_layer.executor.execute",
        lambda *a, **k: called.append("executed"),
    )

    result = run_parsed("system_info", "system_info", execute=False)

    assert result.status == "handled"
    assert "system_info" in result.message
    assert called == []


def test_the_dangerous_text_guard_still_runs_first() -> None:
    """The catalogue has no text-level refusal, so it must stay in front."""
    from grandpa.local_actions import handle_local_action

    assert handle_local_action("delete my registry").status == "blocked"
    assert handle_local_action("show my password").status == "blocked"


def test_a_migrated_phrase_is_performed_by_the_layer(monkeypatch) -> None:
    from grandpa.local_actions import handle_local_action

    monkeypatch.setattr(
        "grandpa.desktop.control.diagnostics.system_info_message",
        lambda: "Basic system info: probe",
    )
    from grandpa.desktop.control.diagnostics import system_info_message

    assert system_info_message() == "Basic system info: probe", "mock did not hold"

    result = handle_local_action("system info")

    assert result.status == "handled"
    assert result.message == "Basic system info: probe"


# --- tranche 3: windows ---------------------------------------------------------


@pytest.fixture
def window_calls(monkeypatch):
    import grandpa.windows_window_control as wc

    calls: list[tuple[str, str]] = []

    class _Done:
        status = "handled"
        message = "done"

    monkeypatch.setattr(
        wc,
        "control_window",
        lambda action, target="active": calls.append((action, target)) or _Done(),
    )
    assert wc.control_window("probe", "x").status == "handled", "mock did not hold"
    calls.clear()
    return calls


def test_focusing_a_window_does_not_ask(window_calls) -> None:
    from grandpa.local_actions import handle_local_action

    result = handle_local_action("switch to chrome")

    assert result.status == "handled"
    assert window_calls == [("focus", "chrome")]


def test_closing_asks_inline_and_no_closes_nothing(window_calls) -> None:
    """The pending store used to hold this; the layer asks on the spot."""
    from grandpa.local_actions import handle_local_action

    result = handle_local_action("close notepad", confirm=lambda *_: False)

    assert result.status == "cancelled"
    assert window_calls == []


def test_closing_proceeds_on_yes(window_calls) -> None:
    from grandpa.local_actions import handle_local_action

    result = handle_local_action("close notepad", confirm=lambda *_: True)

    assert result.status == "handled"
    assert window_calls == [("close", "notepad")]


def test_closing_task_manager_is_refused_without_asking(window_calls) -> None:
    """A refusal that asks first is a yes that does nothing."""
    from grandpa.local_actions import handle_local_action

    asked: list[str] = []
    result = handle_local_action(
        "close task manager", confirm=lambda spec, _t: asked.append(spec) or True
    )

    assert result.status == "blocked"
    assert asked == []
    assert window_calls == []


def test_a_dry_run_of_an_action_that_asks_says_so() -> None:
    """Reporting "handled" made a confirmation-gated action look like it would run."""
    result = run_parsed("window", "close|notepad", execute=False)

    assert result.status == "requires_confirmation"
    assert result.permission == "requires_confirmation"


def test_a_dry_run_of_an_action_that_does_not_ask_is_handled() -> None:
    assert run_parsed("window", "focus|notepad", execute=False).status == "handled"
