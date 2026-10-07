"""The bubble is a front end. It must not become a place where more can happen.

The UI routes through :class:`VoiceCommandProcessor` -- the same object
``grandpa voice`` uses -- so it inherits exactly the consent gates the voice path
has and adds none of its own. The property to protect is sharper than "the UI is
safe": **nothing may actuate from the bubble that could not actuate from the
CLI.** A window that could type into something the command line could not would
be a privilege escalation wearing a button.

Three things could break that, so three things are asserted:

1. the bridge does not widen ``focus_witness.WITNESS_ORIGINS``, which is the
   allowlist deciding who may carry a witness and therefore who may stage
   synthetic input at all;
2. the bridge reaches no catalogued automation action except through the voice
   responder, so the gates are the ones already tested;
3. nothing in ``grandpa.ui`` imports an actuation primitive directly.

The action set is read from the catalogue, in the shape
tests/security/test_no_staged_input.py uses, so an action added later is covered
the day it exists rather than the day someone remembers this file.
"""

from __future__ import annotations

import inspect
import pkgutil

import pytest

from grandpa.action_layer.catalogue import AUTOMATION_IMPLEMENTATION, DOMAINS, get
from grandpa.desktop import focus_witness
from grandpa.ui import bridge as bridge_module
from grandpa.ui.bridge import InProcessBridge

pytestmark = pytest.mark.core


def _input_actions() -> list[str]:
    """Every catalogued action the automation service performs.

    Same derivation as tests/security/test_no_staged_input.py: the catalogue is
    the source, with the known input names unioned in so a rename shows up as a
    missing action rather than as an empty parametrisation.
    """
    names = sorted(
        {name for actions in DOMAINS.values() for name in actions}
        | {
            "keyboard_type",
            "keyboard_hotkey",
            "mouse_move",
            "mouse_click",
            "mouse_scroll",
            "mouse_drag",
        }
    )
    found = []
    for name in names:
        try:
            spec = get(name)
        except KeyError:
            continue  # excluded from the catalogue on purpose
        if spec is not None and spec.implementation == AUTOMATION_IMPLEMENTATION:
            found.append(name)
    return found


def _ui_modules() -> list[str]:
    import grandpa.ui

    return [
        f"grandpa.ui.{info.name}"
        for info in pkgutil.iter_modules(grandpa.ui.__path__)
    ]


# --- 0. the enumeration is real ----------------------------------------------------


def test_the_catalogue_names_the_input_actions() -> None:
    """A parametrised test over an empty list asserts nothing."""
    actions = _input_actions()

    assert len(actions) >= 6, actions
    assert "keyboard_type" in actions
    assert "mouse_click" in actions


def test_there_are_ui_modules_to_check() -> None:
    assert len(_ui_modules()) >= 3, _ui_modules()


# --- 1. the witness allowlist is untouched -----------------------------------------


def test_the_ui_does_not_add_itself_to_the_witness_origins() -> None:
    """``{"voice"}`` and nothing else.

    This allowlist decides who may carry a reading of the foreground window, and
    therefore who may stage a keystroke for a later yes. Adding "ui" or
    "bubble" here would let the window do what the CLI cannot.
    """
    assert focus_witness.WITNESS_ORIGINS == frozenset({"voice"})


@pytest.mark.parametrize("origin", ["ui", "bubble", "desktop", "gui", "window"])
def test_no_ui_shaped_origin_may_carry_a_witness(origin: str) -> None:
    assert focus_witness.may_carry_a_witness(origin) is False


def test_the_ui_never_names_an_origin_at_all() -> None:
    """It routes through the voice responder, which supplies its own."""
    for module_name in _ui_modules():
        module = __import__(module_name, fromlist=["x"])
        source = inspect.getsource(module)
        for token in ("WITNESS_ORIGINS", "may_carry_a_witness", "stage_origin"):
            assert token not in source or module_name.endswith("bridge"), (
                f"{module_name} references {token}; only the bridge's docstring "
                f"should mention the allowlist, and only to say it is untouched"
            )


# --- 2. the bridge reaches actuation only through the voice responder --------------


@pytest.mark.parametrize("action", _input_actions())
def test_the_bridge_names_no_catalogued_action(action: str) -> None:
    """The UI must not address an action directly.

    If it did, it would be a second caller of the automation layer with its own
    consent story, which is precisely the surface this file exists to prevent.
    """
    for module_name in _ui_modules():
        module = __import__(module_name, fromlist=["x"])
        source = inspect.getsource(module)

        assert action not in source, f"{module_name} names {action}"


def test_send_goes_through_the_voice_responder_and_nothing_else() -> None:
    """Asserted by substitution: the only collaborator is the responder."""
    calls: list[str] = []

    class Responder:
        def handle_user_input(self, text: str):
            calls.append(text)

            class Reply:
                text = "done"
                status = "ok"

            return Reply()

    reply = InProcessBridge(responder=Responder()).send("open notepad")

    assert calls == ["open notepad"]
    assert reply.text == "done"
    assert reply.failed is False


def test_the_default_responder_is_the_voice_one() -> None:
    """So the UI's gates are the voice path's gates, already tested."""
    source = inspect.getsource(bridge_module._default_responder)

    assert "VoiceCommandProcessor" in source


def test_the_bridge_surface_is_exactly_two_methods() -> None:
    """A wider surface is a wider thing to audit."""
    from grandpa.ui.bridge import GrandpaBridge

    methods = {
        name
        for name in dir(GrandpaBridge)
        if not name.startswith("_") and callable(getattr(GrandpaBridge, name, None))
    }

    assert methods == {"send", "transcribe"}, methods


# --- 3. no UI module touches an actuation primitive -------------------------------


@pytest.mark.parametrize(
    "primitive",
    [
        "pyautogui",
        "keybd_event",
        "SendInput",
        "mouse_event",
        "SetCursorPos",
        "SetForegroundWindow",
        "pydirectinput",
        "pywinauto",
    ],
)
def test_no_ui_module_imports_an_actuation_primitive(primitive: str) -> None:
    for module_name in _ui_modules():
        module = __import__(module_name, fromlist=["x"])
        source = inspect.getsource(module)

        assert primitive not in source, f"{module_name} references {primitive}"


def test_the_ui_does_not_import_the_automation_service() -> None:
    """Even indirectly naming it would be a second route to the same actions."""
    for module_name in _ui_modules():
        module = __import__(module_name, fromlist=["x"])
        source = inspect.getsource(module)

        assert "AutomationControlService" not in source, module_name
        assert "run_local_action" not in source, module_name


def test_the_ui_reads_the_keyboard_but_never_writes_it() -> None:
    """``WindowsKeyProbe`` is a read: GetAsyncKeyState asks, it does not send.

    That is why the held key needs no actuation consent, and the distinction is
    worth pinning -- a probe that synthesised input would be an actuation path
    with no gate in front of it.
    """
    from grandpa.voice.push_to_talk import WindowsKeyProbe

    source = inspect.getsource(WindowsKeyProbe)

    assert "GetAsyncKeyState" in source
    for writer in ("SendInput", "keybd_event", "mouse_event", "SetCursorPos"):
        assert writer not in source, f"the key probe references {writer}"
