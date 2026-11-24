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
    names = [n for n, _ in matching_commands("/m")]
    assert {"/model", "/memory", "/mode"} <= set(names)
    assert names.index("/memory") < names.index("/mode")  # everyday ones first
    everything = [n for n, _ in matching_commands("/")]
    from grandpa.cli.slash_commands import SLASH_COMMANDS as REGISTRY

    for command in REGISTRY:  # every working engine command is offered
        if command.implemented and command.name != "/quit":
            assert command.name in everything
    for name in ("/theme", "/talk", "/speak", "/copy", "/retry", "/export", "/keys"):
        assert name in everything
    assert matching_commands("hello") == []


def test_a_space_after_a_command_lists_its_subcommands() -> None:
    subs = [n for n, _ in matching_commands("/memory ")]
    assert "/memory list" in subs and "/memory search <query>" in subs
    narrowed = [n for n, _ in matching_commands("/memory se")]
    assert narrowed and all(n.startswith("/memory se") for n in narrowed)
    assert matching_commands("/memory search cats") == []


def test_completion_stops_before_an_argument() -> None:
    from grandpa.tui.app import completion_text

    assert completion_text("/notes search <query>") == "/notes search "
    assert completion_text("/memory list") == "/memory list"


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


# --- themes ----------------------------------------------------------------------


def test_themes_use_only_the_seven_colours_and_stay_readable() -> None:
    from grandpa.cli.theme import shade, tint
    from grandpa.tui.themes import BASES, GRANDPA_YELLOW, THEMES, USER_PURPLE, contrast

    family = {GRANDPA_YELLOW.lower(), USER_PURPLE.lower()}
    for base in BASES.values():
        for percent in range(0, 101):
            family.add(tint(base, percent).lower())
            family.add(shade(base, percent).lower())
    for colors in THEMES.values():
        everything = (
            *colors.allowed_foregrounds(),
            *colors.allowed_backgrounds(),
            colors.border,
            colors.faint,
        )
        for colour in everything:
            assert colour.lower() in family, (colors.name, colour)
        for colour in colors.allowed_foregrounds():
            assert contrast(colour, colors.background) >= 4.5, (colors.name, colour)
            assert contrast(colour, colors.surface) >= 4.5, (colors.name, colour)


def test_the_owner_chosen_message_colours() -> None:
    from grandpa.tui.themes import DARK

    assert DARK.user == "#B0A2E2"
    assert DARK.grandpa == "#FFE2A4"


def test_any_printed_colour_is_mapped_onto_the_theme() -> None:
    from rich.text import Text

    from grandpa.tui.app import fit_text
    from grandpa.tui.themes import DARK, LIGHT

    text = Text.from_ansi(
        "\x1b[38;2;95;179;179mcode\x1b[0m \x1b[35mmagenta\x1b[0m "
        "\x1b[48;2;39;40;34mbg\x1b[0m \x1b[38;2;255;255;0myellow\x1b[0m"
    )
    for colors in (DARK, LIGHT):
        fitted = fit_text(text, colors)
        assert fitted.plain == text.plain
        for span in fitted.spans:
            style = span.style
            if style.color is not None:
                assert style.color.get_truecolor().hex in {
                    c.lower() for c in colors.allowed_foregrounds()
                }
            if style.bgcolor is not None:
                assert style.bgcolor.get_truecolor().hex in {
                    c.lower() for c in colors.allowed_backgrounds()
                }


def test_theme_choice_is_saved(tmp_path) -> None:
    from grandpa.tui.themes import save_settings, saved_theme_name

    path = tmp_path / "s.json"
    assert saved_theme_name(path) == "dark"
    save_settings({"theme": "light"}, path)
    assert saved_theme_name(path) == "light"
    save_settings({"theme": "purple"}, path)
    assert saved_theme_name(path) == "dark"


# --- helpers -----------------------------------------------------------------------


def test_files_can_be_attached_with_at(tmp_path) -> None:
    from grandpa.tui.helpers import (
        expand_file_mentions,
        file_suggestions,
        mention_at_cursor,
    )

    (tmp_path / "notes.txt").write_text("buy milk", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print(1)", encoding="utf-8")
    (tmp_path / "image.bin").write_bytes(b"\x00\x01\x02")

    assert mention_at_cursor("summarise @no") == "no"
    assert mention_at_cursor("email a@b.com") is None
    assert file_suggestions("no", tmp_path) == ["notes.txt"]
    assert file_suggestions("src/", tmp_path) == ["src/app.py"]

    message, attached, notes = expand_file_mentions(
        "check @notes.txt and @src/app.py and @image.bin and @missing.txt", tmp_path
    )
    assert attached == ["notes.txt", "src/app.py"]
    assert "buy milk" in message and "print(1)" in message
    assert any("binary" in n for n in notes) and any("no such file" in n for n in notes)


def test_files_outside_the_folder_and_home_are_refused(tmp_path, monkeypatch) -> None:
    from pathlib import Path

    from grandpa.tui.helpers import read_attachment

    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
    (tmp_path / "home").mkdir()
    (tmp_path / "work").mkdir()
    (tmp_path / "secret.txt").write_text("x", encoding="utf-8")
    contents, note = read_attachment("../secret.txt", tmp_path / "work")
    assert contents is None and "only files" in note


def test_export_writes_markdown(tmp_path) -> None:
    from datetime import datetime

    from grandpa.tui.helpers import Turn, export_markdown

    at = datetime(2026, 11, 24, 10, 30)
    path = export_markdown(
        [Turn("user", "hello", at), Turn("grandpa", "Hi Captain", at)], tmp_path, now=at
    )
    text = path.read_text(encoding="utf-8")
    assert path.name == "grandpa-chat-20261124-103000.md"
    assert "**You** · 10:30" in text and "Hi Captain" in text


def test_reply_text_is_cleaned_before_speaking() -> None:
    from grandpa.tui.voice import speakable

    said = speakable("**Done.** Run `ls`:\n```bash\nls -la\n```\n# Next")
    assert "ls -la" not in said and "*" not in said and "#" not in said
    assert said.startswith("Done.")


# --- the app with turns -------------------------------------------------------------


@click.command()
@click.option("--fullscreen/--no-fullscreen", default=None)
def turn_chat(fullscreen):
    console = chat_cmd.Console(stderr=True)
    while True:
        text = chat_cmd.read_chat_input("You > ")
        if text is None:
            return
        chat_cmd.render_user_message(console, text)
        chat_cmd.render_assistant_response(console, f"you said {text[:40]}")


def _turn_app(tmp_path) -> GrandpaApp:
    app = GrandpaApp(theme_name="dark")
    hooks = UiHooks(
        output=lambda t: app.call_from_thread(app._on_output, t),
        ready_for_input=lambda p: app.call_from_thread(app._on_ready, p),
        ask=lambda q: app.call_from_thread(app._on_question, q),
        finished=lambda c: app.call_from_thread(app._on_finished, c),
        turn=lambda r: app.call_from_thread(app._on_turn, r),
    )
    app.bridge = ChatBridge(hooks, width=80, chat_command=turn_chat)
    app.history.path = None
    app.history.items = []
    return app


def test_messages_are_labelled_and_coloured(tmp_path, monkeypatch) -> None:
    import grandpa.tui.themes as themes
    from grandpa.tui.app import OutputBlock, UserMessage

    monkeypatch.setattr(themes, "settings_path", lambda: tmp_path / "s.json")

    async def scenario() -> None:
        app = _turn_app(tmp_path)
        async with app.run_test(size=(100, 30)) as pilot:
            await _until(pilot, lambda: app._busy_since is None)
            await pilot.press(*"hello")
            await pilot.press("enter")
            await _until(
                pilot,
                lambda: len(app.query(".grandpa")) == 1 and app._busy_since is None,
            )
            user = app.query_one(UserMessage)
            reply = app.query_one(".grandpa", OutputBlock)
            assert user.text == "hello"
            assert reply.plain() == "you said hello"
            assert app.last_reply() == "you said hello"
            assert [t.role for t in app.turns] == ["user", "grandpa"]

            await pilot.press("ctrl+t")  # light theme, saved
            assert app.palette.name == "light"
            assert themes.saved_theme_name(tmp_path / "s.json") == "light"

            await pilot.press("f5")  # retry
            await _until(
                pilot,
                lambda: len(app.query(".grandpa")) == 2 and app._busy_since is None,
            )

            await pilot.press(*"/theme dark")
            await pilot.press("escape")
            await pilot.press("enter")
            assert app.palette.name == "dark"

    asyncio.run(scenario())


def test_local_commands_never_reach_the_engine(tmp_path, monkeypatch) -> None:
    import grandpa.tui.themes as themes

    monkeypatch.setattr(themes, "settings_path", lambda: tmp_path / "s.json")
    monkeypatch.setattr("grandpa.runtime_paths.grandpa_home", lambda: tmp_path)

    async def scenario() -> None:
        app = _turn_app(tmp_path)
        async with app.run_test(size=(100, 30)) as pilot:
            await _until(pilot, lambda: app._busy_since is None)
            await pilot.press(*"hi")
            await pilot.press("enter")
            await _until(
                pilot, lambda: app.last_reply() is not None and app._busy_since is None
            )
            for command in ("/export", "/keys"):
                await pilot.press(*command)
                await pilot.press("escape")
                await pilot.press("enter")
            assert app.query_one("#help").has_class("visible")
            assert len(list((tmp_path / "exports").glob("*.md"))) == 1
            assert [t.role for t in app.turns] == ["user", "grandpa"]

    asyncio.run(scenario())
