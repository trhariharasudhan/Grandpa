"""The front end that moves local_actions' phrases onto the action layer.

Nothing here reads the real screen, browser or clipboard: every implementation
a migrated phrase would reach is replaced, and the replacement is asserted to
hold before anything that matters is checked.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from grandpa.natural_actions import MIGRATED, request_for, run_parsed

# Opted out of the default-deny actuation fixture (tests/actuation_guard.py):
pytestmark = pytest.mark.real_actions(
    reason="drives the real file implementation against paths the test creates; drives the real desktop service, with the OS-level calls under it stubbed or recorded by the test; drives the real browser implementation with the opener and hotkey runner the test supplies"
)


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
    from grandpa.local import handle_local_action

    assert handle_local_action("delete my registry").status == "blocked"
    assert handle_local_action("show my password").status == "blocked"


def test_a_migrated_phrase_is_performed_by_the_layer(monkeypatch) -> None:
    from grandpa.local import handle_local_action

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
    from grandpa.local import handle_local_action

    result = handle_local_action("switch to chrome")

    assert result.status == "handled"
    assert window_calls == [("focus", "chrome")]


def test_closing_asks_inline_and_no_closes_nothing(window_calls) -> None:
    """The pending store used to hold this; the layer asks on the spot."""
    from grandpa.local import handle_local_action

    result = handle_local_action("close notepad", confirm=lambda *_: False)

    assert result.status == "cancelled"
    assert window_calls == []


def test_closing_proceeds_on_yes(window_calls) -> None:
    from grandpa.local import handle_local_action

    result = handle_local_action("close notepad", confirm=lambda *_: True)

    assert result.status == "handled"
    assert window_calls == [("close", "notepad")]


def test_closing_task_manager_is_refused_without_asking(window_calls) -> None:
    """A refusal that asks first is a yes that does nothing."""
    from grandpa.local import handle_local_action

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


# --- tranche 4: launching -------------------------------------------------------
#
# Every launcher is replaced by tests.security.input_recorder before anything
# runs: this tranche's gates stand in front of starting programs and opening
# folders, and a gate test with a live launcher is how Notepad got opened on a
# real desktop in an earlier phase.


@pytest.fixture
def launches(monkeypatch):
    import grandpa.windows_app_resolver as resolver
    from tests.security.input_recorder import install

    rec = install(monkeypatch)

    def _found(name, **_kwargs):
        return resolver.AppResolution(
            app_id=str(name),
            display_name=str(name).title(),
            status="found",
            launch_kind="executable",
            launch_target=f"C:/Program Files/{name}/{name}.exe",
            source="test",
            message=f"{name} found.",
        )

    # Resolution is a read of this machine's installs; the tests should not
    # depend on what is installed where they run.
    monkeypatch.setattr(resolver, "resolve_app", _found)
    return rec


def _launched(rec) -> list[str]:
    return [
        name
        for name in rec.actuated
        if name
        in {
            "subprocess.Popen",
            "os.startfile",
            "launch_app",
            "ShellExecuteW",
            "ShellExecute",
        }
    ]


@pytest.mark.parametrize("phrase", ["open chrome", "launch edge"])
def test_starting_a_browser_with_no_one_to_ask_starts_nothing(launches, phrase) -> None:
    """Hole: local_actions called launch_app itself, around the browser rule."""
    from grandpa.local import handle_local_action

    result = handle_local_action(phrase)

    assert result.status != "handled", result
    assert _launched(launches) == []


@pytest.mark.parametrize("phrase", ["open chrome", "launch edge"])
def test_starting_a_browser_asks_and_no_starts_nothing(launches, phrase) -> None:
    from grandpa.local import handle_local_action

    asked: list[str] = []
    handle_local_action(phrase, confirm=lambda spec, _t: asked.append(spec) or False)

    assert len(asked) == 1, asked
    assert _launched(launches) == []


def test_starting_a_browser_on_yes_launches_it(launches) -> None:
    from grandpa.local import handle_local_action

    handle_local_action("open chrome", confirm=lambda *_a: True)

    assert _launched(launches) == ["launch_app"]


def test_voice_cannot_start_a_browser(launches) -> None:
    from grandpa.local import handle_local_action

    handle_local_action("open chrome", deferred_origin="voice")
    handle_local_action("yes", deferred_origin="voice")

    assert _launched(launches) == []


def test_an_ordinary_app_starts_without_asking(launches) -> None:
    from grandpa.local import handle_local_action

    asked: list[str] = []
    handle_local_action(
        "open calculator", confirm=lambda spec, _t: asked.append(spec) or True
    )

    assert asked == []
    assert _launched(launches) == ["launch_app"]


@pytest.mark.parametrize(
    "folder",
    [
        Path.home() / ".ssh",
        Path.home() / "AppData" / "Local" / "Google" / "Chrome" / "User Data",
    ],
    ids=["ssh", "chrome-profile"],
)
def test_a_protected_folder_is_refused_before_anyone_is_asked(launches, folder) -> None:
    """Hole: local_actions staged it, and opened it on a yes."""
    from grandpa.local import handle_local_action

    asked: list[str] = []
    result = handle_local_action(
        f"open {folder}", confirm=lambda spec, _t: asked.append(spec) or True
    )

    assert result.status == "blocked", result
    assert asked == []
    assert _launched(launches) == []


def test_a_protected_folder_is_not_staged_for_voice(launches) -> None:
    from grandpa import pc_control
    from grandpa.local import handle_local_action

    result = handle_local_action(
        f"open {Path.home() / '.ssh'}", deferred_origin="voice"
    )

    assert result.status == "blocked"
    with pc_control._connect_approval_db() as conn:
        assert (
            conn.execute("SELECT COUNT(*) FROM pc_control_approvals").fetchone()[0] == 0
        )


def test_an_unknown_folder_still_asks(launches, tmp_path) -> None:
    """open_folder alone would not ask; local_actions did, and still does."""
    from grandpa.local import handle_local_action

    asked: list[str] = []
    declined = handle_local_action(
        f"open {tmp_path}", confirm=lambda spec, _t: asked.append(spec) or False
    )
    assert declined.status == "cancelled"
    assert _launched(launches) == []

    handle_local_action(f"open {tmp_path}", confirm=lambda *_a: True)
    assert len(asked) == 1
    assert _launched(launches) == ["os.startfile"]


def test_a_folder_the_old_rule_trusted_opens_without_asking(launches, tmp_path) -> None:
    """Without require_consent, open_folder opens an ordinary folder unasked.

    Through handle_local_action, the two folders local_actions trusts
    (Downloads and the D: drive) are claimed earlier by the intent router, so
    the mapping is checked here directly.
    """
    asked: list[str] = []
    # The recorder refuses the launch after recording it, so the status is
    # an error; what was attempted is the evidence.
    run_parsed(
        "folder", str(tmp_path), confirm=lambda spec, _t: asked.append(spec) or True
    )

    assert asked == []
    assert _launched(launches) == ["os.startfile"]


# --- tranche 4: navigation ------------------------------------------------------

NAVIGATION = [
    ("open example.com", "https://example.com"),
    ("search python packaging", "https://www.google.com/search?q=python+packaging"),
    ("open youtube", "https://www.youtube.com"),
]


def _opened(rec) -> list[str]:
    return [str(args[0]) for name, args, _kw in rec.calls if name == "webbrowser.open"]


@pytest.mark.parametrize(("phrase", "address"), NAVIGATION, ids=lambda v: v.split()[0])
def test_navigating_with_no_one_to_ask_opens_nothing(launches, phrase, address) -> None:
    from grandpa.local import handle_local_action

    result = handle_local_action(phrase)

    assert result.status != "handled"
    assert _opened(launches) == []


@pytest.mark.parametrize(("phrase", "address"), NAVIGATION, ids=lambda v: v.split()[0])
def test_navigating_shows_the_address_and_no_opens_nothing(
    launches, phrase, address
) -> None:
    from grandpa.local import handle_local_action

    asked: list[str] = []
    handle_local_action(phrase, confirm=lambda spec, _t: asked.append(spec) or False)

    assert len(asked) == 1, asked
    assert address in asked[0], asked
    assert _opened(launches) == []


@pytest.mark.parametrize(("phrase", "address"), NAVIGATION, ids=lambda v: v.split()[0])
def test_navigating_on_yes_opens_exactly_that_address(
    launches, phrase, address
) -> None:
    from grandpa.local import handle_local_action

    handle_local_action(phrase, confirm=lambda *_a: True)

    assert _opened(launches) == [address]


def test_voice_navigation_waits_for_its_own_yes(launches) -> None:
    from grandpa.local import handle_local_action

    staged = handle_local_action("open example.com", deferred_origin="voice")
    assert staged.status == "requires_confirmation"
    assert _opened(launches) == []

    handle_local_action("yes", deferred_origin="chat")
    assert _opened(launches) == []

    handle_local_action("yes", deferred_origin="voice")
    assert _opened(launches) == ["https://example.com"]


def test_a_trusted_domain_opens_without_asking(launches, monkeypatch) -> None:
    import grandpa.local.router as local_actions

    # tools.browser.trusted_domains, as both local_actions and the browser
    # domain read it.
    monkeypatch.setattr(
        "grandpa.browser.safety.configured_trusted_domains",
        lambda *_a, **_k: ("example.com",),
    )
    asked: list[str] = []
    local_actions.handle_local_action(
        "open example.com", confirm=lambda spec, _t: asked.append(spec) or True
    )

    assert asked == []
    assert _opened(launches) == ["https://example.com"]
