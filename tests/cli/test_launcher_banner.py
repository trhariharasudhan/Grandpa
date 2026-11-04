"""Chat's banner survives being launched from the menu.

The reported symptom was "chat opens from the launcher but renders nothing".
That report turned out to be wrong -- the diagnostic used to chase it
redirected stderr, which is where chat's console writes, so it hid the banner
and the missing output was the instrument, not the product.

Wrong report, real structure though. The launcher's alternate screen used to
wrap the whole loop, dispatch included, so anything a mode printed went into a
screen buffer the launcher tore down on return. Nothing proved it did not. The
two facts these tests pin are the two that made the symptom plausible, and
either one changing silently would make it real:

  * chat's console writes to stderr, so anything capturing chat must capture
    stderr -- the mis-diagnosis these tests exist to stop being repeated;
  * the alternate screen closes BEFORE a mode is dispatched, so a mode's
    output is never written into a buffer that is about to be discarded.
"""

from __future__ import annotations

import contextlib
import inspect
from pathlib import Path

import click
import pytest
from click.testing import CliRunner

from grandpa.cli import launcher as launcher_module
from grandpa.cli.launcher import launcher as launcher_cmd
from grandpa.core.config import load_config
from grandpa.profile import atomic_update_profile


@pytest.fixture
def temp_config(tmp_path: Path, monkeypatch) -> Path:
    config_file = tmp_path / "config.toml"
    monkeypatch.setenv("Grandpa_CONFIG", str(config_file))
    monkeypatch.setenv("GRANDPA_TESTING", "1")
    atomic_update_profile(
        config_file,
        username="TestUser",
        onboarding_completed=True,
    )
    load_config.cache_clear()
    return config_file


def test_chat_console_writes_to_stderr() -> None:
    """The fact that made "renders nothing" look true.

    If this ever flips to stdout, the change is fine in itself -- but every
    diagnostic that captures chat is then looking at the wrong stream, which is
    exactly how an hour went last time.
    """
    source = inspect.getsource(
        __import__("grandpa.cli.chat_cmd", fromlist=["chat"]).chat.callback
    )
    assert "Console(stderr=True" in source, (
        "chat's console is no longer on stderr -- update the diagnostics that "
        "capture it, and this test's reason for existing"
    )


def test_alternate_screen_closes_before_a_mode_is_dispatched(
    temp_config, monkeypatch
) -> None:
    """Order of events, not a screenshot.

    A mode printing inside the launcher's alternate screen would have its
    output discarded when the buffer was torn down. So the check is that the
    screen has already closed by the time the mode prints.
    """
    events: list[str] = []

    @contextlib.contextmanager
    def recording_alternate_screen(enabled: bool = True):
        events.append("screen-enter")
        try:
            yield
        finally:
            events.append("screen-exit")

    monkeypatch.setattr(
        launcher_module, "alternate_screen", recording_alternate_screen
    )

    def fake_menu(console, title, items, greeting, last_used):
        events.append("menu-shown")
        # First pass picks chat, second pass leaves.
        return "chat" if events.count("menu-shown") == 1 else "exit"

    monkeypatch.setattr(launcher_module, "run_interactive_menu", fake_menu)

    # The signature has to match what the launcher invokes it with. A fake
    # that rejects the kwargs raises inside ctx.invoke, the launcher catches
    # it, and the test then reports "chat never ran" for the wrong reason --
    # which is what the first version of this test did.
    @click.command()
    @click.option("--tui-mode", is_flag=True)
    @click.option("--fullscreen", is_flag=True)
    def fake_chat(tui_mode: bool, fullscreen: bool) -> None:
        events.append("chat-printed-banner")

    monkeypatch.setattr("grandpa.cli.chat_cmd.chat", fake_chat, raising=False)

    runner = CliRunner()
    runner.invoke(launcher_cmd, [], obj={"fullscreen": True})

    assert "chat-printed-banner" in events, f"chat never ran: {events}"
    banner = events.index("chat-printed-banner")
    # Every screen-enter before the banner must have a matching screen-exit
    # before it too, or the banner was printed inside a live buffer.
    before = events[:banner]
    assert before.count("screen-enter") == before.count("screen-exit"), (
        f"chat printed while an alternate screen was still open: {events}"
    )


def test_the_menu_is_the_only_thing_inside_the_alternate_screen() -> None:
    """Structural, so it fails on the edit rather than on the symptom.

    The `with alternate_screen(...)` in the launcher loop must contain the menu
    call and nothing that dispatches a mode.
    """
    source = inspect.getsource(launcher_module)
    lines = source.splitlines()
    starts = [i for i, line in enumerate(lines) if "with alternate_screen(" in line]
    assert len(starts) == 1, f"expected one alternate_screen block, found {len(starts)}"

    start = starts[0]
    indent = len(lines[start]) - len(lines[start].lstrip())
    body: list[str] = []
    for line in lines[start + 1 :]:
        if line.strip() and (len(line) - len(line.lstrip())) <= indent:
            break
        body.append(line)

    joined = "\n".join(body)
    assert "run_interactive_menu(" in joined, (
        "the alternate screen no longer wraps the menu"
    )
    assert "ctx.invoke(" not in joined, (
        "a mode is dispatched inside the alternate screen -- its output will be "
        "written into a buffer that is torn down on return"
    )
