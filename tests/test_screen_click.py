"""C3: act on what Grandpa sees -- press a named control, asking first.

No Windows here: the UI Automation walk is a fake control reader, the press a
fake presser, and the active window a fixed WindowInfo. What is tested is
everything around them: matching names, refusing credential screens, password
fields, greyed-out and risky controls, asking before pressing (chat, the
catalogue, the CLI), and the phrases.
"""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from click.testing import CliRunner

from grandpa.action_layer import catalogue
from grandpa.local import parsers, permissions
from grandpa.local_action_result import LocalActionResult
from grandpa.natural_actions import request_for
from grandpa.screen.errors import SensitiveScreenDetectedError
from grandpa.screen.models import WindowInfo
from grandpa.screen.service import ScreenVisionService
from grandpa.screen.window_click import (
    UiControl,
    clean_target,
    find_control,
    is_risky,
    press,
    read_uia_controls,
)
from grandpa.screen.window_text import UiNode

SAVE_DIALOG = [
    UiControl("button", "&Save"),
    UiControl("button", "Do&n't Save"),
    UiControl("button", "Cancel"),
    UiControl("button", "Close"),
]


def _window(title: str = "Notepad", process: str = "Notepad.exe") -> WindowInfo:
    return WindowInfo(title=title, process_name=process, handle=4242)


def _service(controls=SAVE_DIALOG, *, title="Notepad", nodes=(), pressed=True):
    presser = Mock(return_value=pressed)
    reader = Mock(return_value=list(controls))
    window = _window(title)
    service = ScreenVisionService(
        capture=Mock(),
        ocr=Mock(),
        analyzer=Mock(),
        window_reader=Mock(return_value=list(nodes)),
        active_window_provider=lambda: window,
        control_reader=reader,
        presser=presser,
    )
    return service, presser, reader


# --- matching -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("said", "expected"),
    [
        ("Save", "save"),
        ("the save button", "save"),
        ("on the OK button", "ok"),
        ("Don’t Save", "don't save"),
        ("Save As...", "save as"),
    ],
)
def test_clean_target(said, expected):
    assert clean_target(said) == expected


def test_an_exact_name_wins_over_a_longer_one():
    match = find_control(SAVE_DIALOG, "save")

    assert match.control is not None
    assert match.control.name == "&Save"


def test_accelerators_and_curly_quotes_do_not_matter():
    assert find_control(SAVE_DIALOG, "don’t save").control.name == "Do&n't Save"


def test_a_part_of_a_name_matches_when_only_one_has_it():
    controls = [UiControl("hyperlink", "Read the full forecast"), *SAVE_DIALOG]

    assert find_control(controls, "full forecast").control.control == "hyperlink"


def test_two_controls_with_the_name_are_ambiguous_and_nothing_is_chosen():
    controls = [UiControl("button", "OK"), UiControl("button", "OK")]

    match = find_control(controls, "ok")

    assert match.control is None
    assert match.ambiguous


def test_text_that_is_not_a_control_is_never_matched():
    controls = [UiControl("text", "Save"), UiControl("pane", "Save")]

    assert find_control(controls, "save").control is None


@pytest.mark.parametrize(
    "name",
    ["Buy now", "Place order", "Sign in", "Log in", "Pay ₹499", "Delete", "Send"],
)
def test_risky_names(name):
    assert is_risky(name)


@pytest.mark.parametrize("name", ["Save", "Don't Save", "OK", "Payments history"])
def test_ordinary_names_are_not_risky(name):
    # "Payments" is not the word "pay"; a whole-word match, not a substring.
    assert not is_risky(name)


# --- ScreenVisionService.find_click / click -----------------------------------


def test_click_presses_the_named_control_once():
    service, presser, _ = _service()

    result = service.click("Don't Save")

    assert result.status == "handled"
    assert result.message == 'Pressed the "Do&n\'t Save" button in Notepad.'
    presser.assert_called_once()
    assert presser.call_args.args[0].name == "Do&n't Save"


def test_find_click_presses_nothing():
    service, presser, _ = _service()

    found = service.find_click("save")

    assert found.status == "handled"
    assert found.data["window"].handle == 4242
    presser.assert_not_called()


def test_click_goes_to_the_window_it_is_given_not_the_one_in_front():
    service, presser, reader = _service()
    other = WindowInfo(title="Untitled - Paint", handle=7)

    service.click("save", window=other)

    reader.assert_called_with(7)


def test_an_unknown_name_presses_nothing_and_says_what_is_there():
    service, presser, _ = _service()

    result = service.click("Print")

    assert result.status == "not_found"
    assert '"Cancel"' in result.message
    presser.assert_not_called()


def test_an_ambiguous_name_presses_nothing():
    service, presser, _ = _service(
        [UiControl("button", "Save draft"), UiControl("button", "Save copy")]
    )

    result = service.click("save")

    assert result.status == "not_found"
    assert "More than one" in result.message
    presser.assert_not_called()


def test_a_credential_window_is_refused_by_its_title_before_the_walk():
    service, presser, reader = _service(title="Windows Security")

    with pytest.raises(SensitiveScreenDetectedError):
        service.click("OK")

    reader.assert_not_called()
    presser.assert_not_called()


def test_a_credential_window_is_refused_by_its_text():
    service, presser, _ = _service(
        title="Account",
        nodes=[UiNode("other", "Enter password"), UiNode("other", "Password")],
    )

    with pytest.raises(SensitiveScreenDetectedError):
        service.click("OK")
    presser.assert_not_called()


def test_a_password_field_is_never_pressed():
    service, presser, _ = _service(
        [UiControl("button", "Show", is_password=True), *SAVE_DIALOG]
    )

    result = service.click("show")

    assert result.status == "blocked"
    presser.assert_not_called()


def test_a_risky_control_is_refused_even_after_a_yes():
    service, presser, _ = _service([UiControl("button", "Place order")])

    result = service.click("place order")

    assert result.status == "blocked"
    assert "yourself" in result.message
    presser.assert_not_called()


def test_a_greyed_out_control_is_not_pressed():
    service, presser, _ = _service([UiControl("button", "Save", is_enabled=False)])

    result = service.click("save")

    assert result.status == "unsupported"
    assert "greyed out" in result.message
    presser.assert_not_called()


def test_a_window_with_no_controls_says_so():
    service, presser, _ = _service([])

    result = service.click("save")

    assert result.status == "unsupported"
    presser.assert_not_called()


def test_a_control_with_no_press_pattern_is_reported():
    service, _, _ = _service(pressed=False)

    result = service.click("save")

    assert result.status == "unsupported"
    assert "cannot be pressed" in result.message


def test_the_uia_walk_and_press_are_off_under_pytest():
    assert read_uia_controls(4242) == []
    assert press(UiControl("button", "Save", element=object())) is False


# --- the catalogue action -----------------------------------------------------


def test_screen_click_is_catalogued_medium_and_always_asks():
    spec = catalogue.get("screen_click")

    assert spec.risk.value == "MEDIUM"
    assert spec.requires_confirmation
    assert spec.parameters["required"] == ["target"]
    assert "screen_click" in catalogue.DOMAINS["windows"]


def test_the_layer_asks_and_a_no_presses_nothing(monkeypatch):
    from grandpa.action_layer.executor import execute
    from grandpa.action_layer.model import ActionRequest, Origin

    service, presser, _ = _service()
    monkeypatch.setattr(
        "grandpa.screen.service.ScreenVisionService", lambda *a, **k: service
    )
    asked: list[tuple] = []

    def no(*args, **kwargs):
        asked.append(args)
        return False

    spec = catalogue.get("screen_click")
    request = ActionRequest(
        "screen_click",
        {"target": "Save"},
        origin=Origin.USER_CHAT,
        risk=spec.risk,
        requires_confirmation=True,
    )
    result = execute(request, no)

    assert asked
    assert not result.success
    presser.assert_not_called()


@pytest.mark.real_actions(
    reason="screen_click_answer runs against a fake service; the press is a Mock"
)
def test_the_layer_presses_after_a_yes(monkeypatch):
    from grandpa.action_layer.executor import execute
    from grandpa.action_layer.model import ActionRequest, Origin

    service, presser, _ = _service()
    monkeypatch.setattr(
        "grandpa.screen.service.ScreenVisionService", lambda *a, **k: service
    )
    spec = catalogue.get("screen_click")
    request = ActionRequest(
        "screen_click",
        {"target": "Save"},
        origin=Origin.USER_CHAT,
        risk=spec.risk,
        requires_confirmation=True,
    )

    result = execute(request, lambda *a, **k: True)

    assert result.success, result
    presser.assert_called_once()


# --- phrases ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("phrase", "name"),
    [
        ("click save", "save"),
        ("click on the ok button", "ok"),
        ("click don't save", "don't save"),
        ("press the cancel button", "cancel"),
        ("tap the downloads tab", "downloads"),
    ],
)
def test_click_phrases_name_a_control(phrase, name):
    result = parsers._parse_screen_action(phrase)

    assert result.kind == "screen"
    assert result.target == f"click|{name}"
    assert request_for("screen", f"click|{name}") == (
        "screen_click",
        {"target": name},
    )


@pytest.mark.parametrize(
    "phrase",
    [
        "click the center of the screen",
        "click the highlighted button",
        "click here",
        "click 300 400",
        "press enter",
        "press ctrl c",
    ],
)
def test_other_click_shapes_are_left_alone(phrase):
    assert parsers._parse_screen_action(phrase).status == "no_match"


def test_a_phrase_click_asks_and_a_risky_one_is_refused_before_asking():
    ok = LocalActionResult(status="handled", kind="screen", target="click|save")
    risky = LocalActionResult(status="handled", kind="screen", target="click|buy now")

    assert permissions.classify_permission("click save", ok) == "requires_confirmation"
    assert permissions.classify_permission("click buy now", risky) == "blocked"
    assert '"save"' in permissions._confirmation_summary("click save", ok)


# --- CLI ----------------------------------------------------------------------


def _cli(monkeypatch, service):
    from grandpa.cli import screen_cmd

    monkeypatch.setattr(screen_cmd, "_service", lambda **kwargs: service)
    return screen_cmd.screen


def test_cli_asks_and_presses_on_yes(monkeypatch):
    service, presser, _ = _service()

    result = CliRunner().invoke(
        _cli(monkeypatch, service), ["click", "Don't", "Save"], input="y\n"
    )

    assert result.exit_code == 0, result.output
    assert 'Press the "Do&n\'t Save" button in Notepad?' in result.output
    assert "Pressed" in result.output
    presser.assert_called_once()


def test_cli_presses_nothing_on_no(monkeypatch):
    service, presser, _ = _service()

    result = CliRunner().invoke(
        _cli(monkeypatch, service), ["click", "Save"], input="n\n"
    )

    assert result.exit_code == 0, result.output
    assert "Nothing was pressed" in result.output
    presser.assert_not_called()


def test_cli_does_not_ask_about_a_name_it_cannot_find(monkeypatch):
    service, presser, _ = _service()

    result = CliRunner().invoke(_cli(monkeypatch, service), ["click", "Print"])

    assert "Press " not in result.output
    assert "could not find" in result.output
    presser.assert_not_called()
