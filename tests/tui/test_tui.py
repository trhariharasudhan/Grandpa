"""The full-screen interface, driven headless with a stand-in chat engine.

The stand-in is a tiny click command that behaves like ``grandpa chat`` at its
edges: it prints through ``chat_cmd.Console``, waits on
``chat_cmd.read_chat_input`` and asks with ``input()``. The bridge replaces
exactly those, so passing here means the real chat runs the same way.
"""

from __future__ import annotations

import asyncio

import click
import pytest

from grandpa.cli import chat_cmd
from grandpa.tui.app import GrandpaApp, InputHistory, matching_commands
from grandpa.tui.bridge import ChatBridge, UiHooks, clean_terminal_text

pytestmark = pytest.mark.core


@click.command()
@click.option("--fullscreen/--no-fullscreen", default=None)
def fake_chat(fullscreen):
    console = chat_cmd.Console(stderr=True)
    console.print("[bold]GRANDPA[/bold] ready")
    while True:
        text = chat_cmd.read_chat_input("You > ")
        if text is None or text == "/exit":
            console.print("Goodbye!")
            return
        if text.startswith("delete"):
            from rich.markup import escape

            console.print(
                "Confirm: delete note 'x'? (high risk) " + escape("[y/N] "), end=""
            )
            answer = input().strip().lower()
            console.print("deleted" if answer == "y" else "kept")
            continue
        if text == "pick":
            console.print(
                f"picked {chat_cmd.select_from_list('Select Model', ['a', 'b'])}"
            )
            continue
        console.print(f"Grandpa: you said {text}")


def _app() -> GrandpaApp:
    app = GrandpaApp()
    hooks = UiHooks(
        output=lambda t: app.call_from_thread(app._on_output, t),
        ready_for_input=lambda p: app.call_from_thread(app._on_ready, p),
        ask=lambda q: app.call_from_thread(app._on_question, q),
        finished=lambda c: app.call_from_thread(app._on_finished, c),
    )
    app.bridge = ChatBridge(hooks, width=80, chat_command=fake_chat)
    app.history.path = None
    app.history.items = []
    return app


def _log_text(app: GrandpaApp) -> str:
    return "\n".join(clean_terminal_text(b.raw) for b in app.query(".block"))


async def _until(pilot, condition, timeout: float = 5.0) -> None:
    for _ in range(int(timeout / 0.05)):
        if condition():
            return
        await pilot.pause(0.05)
    raise AssertionError("timed out")


def test_a_conversation_round_trip() -> None:
    async def scenario() -> None:
        app = _app()
        async with app.run_test(size=(100, 30)) as pilot:
            await _until(pilot, lambda: "ready" in _log_text(app))
            await pilot.press(*"hello")
            await pilot.press("enter")
            await _until(pilot, lambda: "you said hello" in _log_text(app))
            assert app.query_one("#prompt").text == ""
            await pilot.press(*"/exit")
            await pilot.press("escape")  # close the slash list
            await pilot.press("enter")
            await _until(pilot, lambda: not app.is_running)

    asyncio.run(scenario())


def test_a_risky_action_waits_for_yes_and_no_is_the_default() -> None:
    async def scenario() -> None:
        app = _app()
        async with app.run_test(size=(100, 30)) as pilot:
            await _until(pilot, lambda: "ready" in _log_text(app))
            await pilot.press(*"delete x")
            await pilot.press("enter")
            await _until(pilot, lambda: app._question is not None)
            assert app._question.yes_no
            assert app.query_one("#question").has_class("visible")
            await pilot.press("escape")  # escape answers no
            await _until(pilot, lambda: "kept" in _log_text(app))
            await pilot.press(*"delete y")
            await pilot.press("enter")
            await _until(pilot, lambda: app._question is not None)
            await pilot.click("#yes")
            await _until(pilot, lambda: "deleted" in _log_text(app))

    asyncio.run(scenario())


def test_the_model_picker_becomes_a_list() -> None:
    async def scenario() -> None:
        app = _app()
        async with app.run_test(size=(100, 30)) as pilot:
            await _until(pilot, lambda: "ready" in _log_text(app))
            await pilot.press(*"pick")
            await pilot.press("enter")
            await _until(pilot, lambda: app._question is not None)
            await pilot.press("down", "enter")
            await _until(pilot, lambda: "picked b" in _log_text(app))

    asyncio.run(scenario())


def test_nothing_is_sent_while_grandpa_is_still_answering() -> None:
    sent = []

    class Spy(ChatBridge):
        def send(self, text):
            sent.append(text)
            super().send(text)

    async def scenario() -> None:
        app = _app()
        app.bridge.__class__ = Spy
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause(0.01)
            app._busy_since = 1.0  # pretend a reply is being written
            await pilot.press(*"again", "enter")
            assert sent == []

    asyncio.run(scenario())


def test_slash_commands_pop_up() -> None:
    assert [n for n, _ in matching_commands("/m")] == ["/model", "/memory"]
    assert len(matching_commands("/")) > 10
    assert matching_commands("hello") == []
    assert matching_commands("/model x") == []


def test_history_survives_a_restart(tmp_path) -> None:
    path = tmp_path / "h"
    h = InputHistory(path)
    h.add("first")
    h.add("two\nlines")
    again = InputHistory(path)
    assert again.previous() == "two\nlines"
    assert again.previous() == "first"
    assert again.next() == "two\nlines"
    assert again.next() == ""


def test_spinners_and_cursor_codes_are_cleaned() -> None:
    assert clean_terminal_text("\r⠋ thinking\r⠙ thinking\rDone\n") == "Done\n"
    assert clean_terminal_text("\x1b]0;Grandpa\x07hi\x1b[2K") == "hi"
    assert clean_terminal_text("\x1b[33mgold\x1b[0m") == "\x1b[33mgold\x1b[0m"


@click.command()
@click.option("--fullscreen/--no-fullscreen", default=None)
def failing_chat(fullscreen):
    chat_cmd.Console(stderr=True).print("[red]No inference engine available.[/red]")
    raise SystemExit(1)


def test_a_failure_stays_on_screen_instead_of_a_blank_exit() -> None:
    async def scenario() -> None:
        app = _app()
        app.bridge._chat_command = failing_chat
        async with app.run_test(size=(100, 30)) as pilot:
            await _until(pilot, lambda: "Grandpa stopped" in _log_text(app))
            assert app.is_running
            assert "No inference engine available" in _log_text(app)
            await pilot.press("ctrl+d")
            await _until(pilot, lambda: not app.is_running)

    asyncio.run(scenario())


# --- console mode guard and log redirect ------------------------------------------


class _FakeKernel32:
    def __init__(self, mode: int) -> None:
        self.mode = mode
        self.sets: list[int] = []

    def GetConsoleMode(self, _handle, ref) -> int:  # noqa: N802 - Windows API name
        ref._obj.value = self.mode
        return 1

    def SetConsoleMode(self, _handle, mode) -> int:  # noqa: N802
        self.mode = mode
        self.sets.append(mode)
        return 1


def test_console_guard_restores_mode_after_echo_is_turned_back_on():
    from grandpa.tui.console_guard import ConsoleModeGuard

    app_mode = 0x0200 | 0x0010 | 0x0080  # VT input, mouse, extended flags
    kernel = _FakeKernel32(app_mode)
    guard = ConsoleModeGuard(kernel32=kernel, handle=1)
    guard.capture()
    assert guard.active
    assert guard.check() is False

    kernel.mode = 0x0001 | 0x0002 | 0x0004  # cooked mode with echo
    assert guard.check() is True
    assert kernel.mode == app_mode
    assert guard.repairs == 1


def test_console_guard_stays_off_when_the_console_still_echoes():
    from grandpa.tui.console_guard import ConsoleModeGuard

    kernel = _FakeKernel32(0x0001 | 0x0002 | 0x0004)
    guard = ConsoleModeGuard(kernel32=kernel, handle=1)
    guard.capture()
    assert not guard.active
    assert guard.check() is False
    assert kernel.sets == []


def test_log_lines_for_the_real_terminal_go_into_the_interface(monkeypatch):
    import logging
    import sys

    from grandpa.tui.bridge import redirect_terminal_log_handlers

    handler = logging.StreamHandler(sys.__stderr__)
    log = logging.getLogger("grandpa.test_tui_redirect")
    log.addHandler(handler)
    log.propagate = False
    seen: list[str] = []
    try:
        restore = redirect_terminal_log_handlers(seen.append)
        log.warning("something went wrong")
        restore()
        assert handler.stream is sys.__stderr__
    finally:
        log.removeHandler(handler)
    assert "something went wrong" in "".join(seen)


def test_typing_while_the_log_has_focus_goes_to_the_input_box() -> None:
    async def scenario() -> None:
        app = _app()
        async with app.run_test(size=(100, 30)) as pilot:
            await _until(pilot, lambda: "ready" in _log_text(app))
            app.set_focus(None)
            await pilot.press("h", "i")
            prompt = app.query_one("#prompt")
            assert app.focused is prompt
            assert prompt.text == "hi"

    asyncio.run(scenario())
