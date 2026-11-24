"""Grandpa's full-screen terminal interface (bare ``grandpa``).

The look follows the terminal assistants people already know (Claude Code,
Gemini CLI, opencode): the conversation scrolls in the middle, a framed input
box sits at the bottom, slash commands pop up as you type ``/``, and a status
line says what Grandpa is doing. Questions Grandpa must ask before acting
("Delete note 'x'? [y/N]") appear as a bar with Yes / No buttons right above
the input, so nothing risky happens without an answer.

The conversation itself is the existing chat engine, run by
:class:`grandpa.tui.bridge.ChatBridge`.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Iterable

from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Button, Label, OptionList, Static, TextArea
from textual.widgets.option_list import Option

import grandpa
from grandpa.tui.bridge import ChatBridge, Question, UiHooks, clean_terminal_text
from grandpa.tui.console_guard import ConsoleModeGuard

ACCENT = "#f5c542"

SLASH_COMMANDS: tuple[tuple[str, str], ...] = (
    ("/help", "Show what Grandpa can do"),
    ("/clear", "Clear the conversation"),
    ("/model", "Show or change the model"),
    ("/voice", "Voice settings"),
    ("/memory", "What Grandpa remembers about you"),
    ("/status", "Runtime status"),
    ("/doctor", "Check that everything works"),
    ("/history", "This session's history"),
    ("/apps", "Find and open apps"),
    ("/files", "Find files"),
    ("/browser", "Browser actions"),
    ("/calendar", "Calendar"),
    ("/gmail", "Mail"),
    ("/permissions", "What needs your yes"),
    ("/config", "Active configuration"),
    ("/compact", "Shorten the context"),
    ("/profile", "Your profile"),
    ("/exit", "Quit Grandpa"),
)


def matching_commands(text: str) -> list[tuple[str, str]]:
    """Slash commands that start with what was typed (``/`` alone lists all)."""
    if not text.startswith("/") or " " in text or "\n" in text:
        return []
    typed = text.lower()
    return [(name, about) for name, about in SLASH_COMMANDS if name.startswith(typed)]


class InputHistory:
    """Up/Down through earlier messages, kept between sessions."""

    def __init__(self, path: Path | None, limit: int = 500) -> None:
        self.path = path
        self.limit = limit
        self.items: list[str] = []
        self.index: int | None = None
        if path and path.exists():
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
                self.items = [line.replace("\\n", "\n") for line in lines if line][
                    -limit:
                ]
            except OSError:
                self.items = []

    def add(self, text: str) -> None:
        self.index = None
        if not text.strip() or (self.items and self.items[-1] == text):
            return
        self.items.append(text)
        self.items = self.items[-self.limit :]
        if self.path:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self.path.write_text(
                    "\n".join(i.replace("\n", "\\n") for i in self.items) + "\n",
                    encoding="utf-8",
                )
            except OSError:
                pass

    def previous(self) -> str | None:
        if not self.items:
            return None
        self.index = (
            len(self.items) - 1 if self.index is None else max(0, self.index - 1)
        )
        return self.items[self.index]

    def next(self) -> str | None:
        if self.index is None:
            return None
        self.index += 1
        if self.index >= len(self.items):
            self.index = None
            return ""
        return self.items[self.index]


class PromptBox(TextArea):
    """The input box: Enter sends, Shift+Enter / Alt+Enter / Ctrl+J add a line."""

    BINDINGS = [
        Binding("enter", "submit", "Send", show=False, priority=True),
        Binding(
            "shift+enter,alt+enter,ctrl+j",
            "newline",
            "New line",
            show=False,
            priority=True,
        ),
    ]

    def action_submit(self) -> None:
        self.app.submit_prompt()  # type: ignore[attr-defined]

    def action_newline(self) -> None:
        self.insert("\n")

    async def _on_key(self, event: events.Key) -> None:
        app = self.app
        if event.key == "up" and self.cursor_location[0] == 0:
            if app.slash_visible():  # type: ignore[attr-defined]
                app.move_slash(-1)  # type: ignore[attr-defined]
            else:
                app.history_step(-1)  # type: ignore[attr-defined]
            event.prevent_default()
            event.stop()
            return
        if (
            event.key == "down"
            and self.cursor_location[0] == self.document.line_count - 1
        ):
            if app.slash_visible():  # type: ignore[attr-defined]
                app.move_slash(1)  # type: ignore[attr-defined]
            else:
                app.history_step(1)  # type: ignore[attr-defined]
            event.prevent_default()
            event.stop()
            return
        if event.key == "tab" and app.slash_visible():  # type: ignore[attr-defined]
            app.complete_slash()  # type: ignore[attr-defined]
            event.prevent_default()
            event.stop()
            return
        await super()._on_key(event)


class OutputBlock(Static):
    """One stretch of what the chat engine printed (usually one turn)."""

    def __init__(self) -> None:
        super().__init__("", classes="block")
        self.raw = ""

    def feed(self, text: str) -> None:
        self.raw += text
        self.update(Text.from_ansi(clean_terminal_text(self.raw).rstrip("\n")))


class GrandpaApp(App):
    """The full-screen Grandpa terminal app."""

    TITLE = "Grandpa"
    CSS = f"""
    Screen {{ background: #0d0d0f; }}
    #header {{ height: 1; padding: 0 1; background: #16161a; color: #c8c8c8; }}
    #log {{ padding: 0 1; scrollbar-size-vertical: 1; }}
    .block {{ margin: 0 0 1 0; }}
    #question {{ display: none; height: auto; padding: 0 1; margin: 0 1;
                 border: round {ACCENT}; background: #1d1a10; }}
    #question.visible {{ display: block; }}
    #question-text {{ width: 1fr; color: {ACCENT}; padding: 1 0 0 0; }}
    #question Button {{ min-width: 10; margin: 0 0 0 1; }}
    #slash {{ display: none; height: auto; max-height: 10; margin: 0 1; border: round #3a3a44;
              background: #141418; }}
    #slash.visible {{ display: block; }}
    #choices {{ display: none; height: auto; max-height: 12; margin: 0 1; border: round {ACCENT}; }}
    #choices.visible {{ display: block; }}
    #prompt {{ height: auto; min-height: 3; max-height: 10; margin: 0 1; border: round #3a3a44;
               background: #0d0d0f; }}
    #prompt:focus {{ border: round {ACCENT}; }}
    #prompt .text-area--cursor-line {{ background: transparent; }}
    #status {{ height: 1; padding: 0 2; color: #8a8a8a; }}
    """
    BINDINGS = [
        Binding("ctrl+c,escape", "cancel", "Cancel reply", show=False, priority=True),
        Binding("ctrl+d", "quit_grandpa", "Quit", show=False, priority=True),
        Binding("ctrl+l", "clear_screen", "Clear screen", show=False),
        Binding("y", "answer_yes", show=False),
        Binding("n", "answer_no", show=False),
    ]

    def __init__(
        self, *, chat_args: Iterable[str] = (), bridge: ChatBridge | None = None
    ):
        super().__init__()
        self._chat_args = list(chat_args)
        self.bridge = bridge
        self._block: OutputBlock | None = None
        self._question: Question | None = None
        self._busy_since: float | None = None
        self._spinner = 0
        self._exit_code = 0
        self._stopped = False
        self.history = InputHistory(self._history_path())

    # --- layout ----------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Static(self._header_text(), id="header")
        yield VerticalScroll(id="log")
        with Horizontal(id="question"):
            yield Label("", id="question-text")
            yield Button("Yes (y)", id="yes", variant="success")
            yield Button("No (n)", id="no", variant="error")
        yield OptionList(id="slash")
        yield OptionList(id="choices")
        yield PromptBox(
            id="prompt", soft_wrap=True, show_line_numbers=False, tab_behavior="focus"
        )
        yield Static("", id="status")

    def on_mount(self) -> None:
        prompt = self.query_one("#prompt", PromptBox)
        prompt.border_title = "Ask Grandpa anything · / for commands"
        prompt.focus()
        self.set_interval(0.12, self._tick)
        # Windows: if anything resets the console input mode, put it back, or
        # the classic Command Prompt starts echoing mouse reports as text.
        self._console_guard = ConsoleModeGuard()
        self._console_guard.capture()
        if self._console_guard.active:
            self.set_interval(0.2, self._console_guard.check)
        if self.bridge is None:
            width = max(60, self.size.width - 4)
            hooks = UiHooks(
                output=lambda text: self.call_from_thread(self._on_output, text),
                ready_for_input=lambda p: self.call_from_thread(self._on_ready, p),
                ask=lambda q: self.call_from_thread(self._on_question, q),
                finished=lambda code: self.call_from_thread(self._on_finished, code),
            )
            self.bridge = ChatBridge(hooks, width=width, chat_args=self._chat_args)
        self._busy_since = time.monotonic()
        self.bridge.start()

    def on_key(self, event: events.Key) -> None:
        """Typing while the chat log has focus goes to the input box."""
        prompt = self.query_one("#prompt", PromptBox)
        if self.focused is prompt or prompt.disabled or not event.is_printable:
            return
        if not self.query_one("#question").has_class("visible") and event.character:
            prompt.focus()
            prompt.insert(event.character)
            event.stop()

    # --- what the chat engine sends -----------------------------------------------

    def _on_output(self, text: str) -> None:
        log = self.query_one("#log", VerticalScroll)
        if self._block is None:
            self._block = OutputBlock()
            log.mount(self._block)
        self._block.feed(text)
        log.scroll_end(animate=False)

    def _on_ready(self, _prompt: str) -> None:
        self._busy_since = None
        self._block = None  # the next turn starts a new block
        self._update_status()

    def _on_question(self, question: Question) -> None:
        self._question = question
        self._busy_since = None
        if question.kind == "choose":
            choices = self.query_one("#choices", OptionList)
            choices.clear_options()
            choices.add_options(
                [Option(str(o), id=str(i)) for i, o in enumerate(question.options)]
            )
            choices.border_title = question.prompt
            choices.highlighted = 0
            choices.add_class("visible")
            choices.focus()
        else:
            bar = self.query_one("#question", Horizontal)
            self.query_one("#question-text", Label).update(
                question.prompt or "Grandpa asks:"
            )
            for button in bar.query(Button):
                button.display = question.yes_no
            bar.add_class("visible")
            if not question.yes_no:
                self.query_one("#prompt", PromptBox).focus()
            else:
                self.query_one("#yes", Button).focus()
        self._update_status()

    def _on_finished(self, code: int) -> None:
        """The chat ended. A normal goodbye closes the app; a failure stays on
        screen, because closing would hide the reason (the old silent exit)."""
        self._exit_code = code
        self._busy_since = None
        if code == 0:
            self.exit(code)
            return
        self._block = None
        self._on_output(
            "\n\x1b[33mGrandpa stopped. The reason is above.\x1b[0m\n"
            "Fix it, then start again with \x1b[1mgrandpa\x1b[0m. "
            "Press Ctrl+D (or Ctrl+C) to close.\n"
        )
        self.query_one("#prompt", PromptBox).disabled = True
        self._stopped = True
        self._update_status()

    # --- user actions ---------------------------------------------------------------

    def submit_prompt(self) -> None:
        prompt = self.query_one("#prompt", PromptBox)
        if self.slash_visible():
            self.complete_slash()
            if prompt.text.strip() in {name for name, _ in SLASH_COMMANDS}:
                pass  # a full command name: send it now
            else:
                return
        text = prompt.text.rstrip()
        if self._question is not None and self._question.kind == "input":
            self._answer(text)
            prompt.clear()
            return
        if not text or self.bridge is None or self._busy_since is not None:
            return
        prompt.clear()
        self.history.add(text)
        self._block = None
        self._busy_since = time.monotonic()
        self.bridge.send(text)
        self._update_status()

    def _answer(self, value: str | None) -> None:
        question = self._question
        if question is None:
            return
        self._question = None
        self.query_one("#question", Horizontal).remove_class("visible")
        self.query_one("#choices", OptionList).remove_class("visible")
        self.query_one("#prompt", PromptBox).focus()
        self._busy_since = time.monotonic()
        question.answer(value)
        self._update_status()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id in {"yes", "no"}:
            self._answer("y" if event.button.id == "yes" else "n")

    def action_answer_yes(self) -> None:
        if self._question is not None and self._question.yes_no:
            self._answer("y")

    def action_answer_no(self) -> None:
        if self._question is not None and self._question.yes_no:
            self._answer("n")

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_list.id == "choices" and self._question is not None:
            index = int(event.option.id or 0)
            self._answer(self._question.options[index])
        elif event.option_list.id == "slash":
            self.complete_slash(event.option.id)

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if event.text_area.id != "prompt":
            return
        found = matching_commands(event.text_area.text)
        slash = self.query_one("#slash", OptionList)
        if found:
            slash.clear_options()
            slash.add_options(
                [Option(f"{name:<14} {about}", id=name) for name, about in found]
            )
            slash.highlighted = 0
            slash.add_class("visible")
        else:
            slash.remove_class("visible")

    def slash_visible(self) -> bool:
        return self.query_one("#slash", OptionList).has_class("visible")

    def move_slash(self, step: int) -> None:
        slash = self.query_one("#slash", OptionList)
        if slash.option_count:
            current = slash.highlighted or 0
            slash.highlighted = (current + step) % slash.option_count

    def complete_slash(self, name: str | None = None) -> None:
        slash = self.query_one("#slash", OptionList)
        if name is None and slash.highlighted is not None and slash.option_count:
            name = slash.get_option_at_index(slash.highlighted).id
        if name:
            prompt = self.query_one("#prompt", PromptBox)
            prompt.text = name
            prompt.move_cursor(prompt.document.end)
        slash.remove_class("visible")

    def history_step(self, step: int) -> None:
        text = self.history.previous() if step < 0 else self.history.next()
        if text is None:
            return
        prompt = self.query_one("#prompt", PromptBox)
        prompt.text = text
        prompt.move_cursor(prompt.document.end)

    def action_cancel(self) -> None:
        if self._stopped:
            self.exit(self._exit_code)
            return
        if self._question is not None:
            self._answer(None if not self._question.yes_no else "n")
            return
        if self.slash_visible():
            self.query_one("#slash", OptionList).remove_class("visible")
            return
        if (
            self.bridge is not None
            and self._busy_since is not None
            and self.bridge.cancel()
        ):
            self._on_output("\n[cancelled]\n")

    def action_quit_grandpa(self) -> None:
        if self._stopped:
            self.exit(self._exit_code)
        elif self.bridge is not None and self.bridge.alive:
            self.bridge.quit()
        else:
            self.exit(self._exit_code)

    def action_clear_screen(self) -> None:
        self.query_one("#log", VerticalScroll).remove_children()
        self._block = None

    # --- header and status --------------------------------------------------------

    def _header_text(self) -> Text:
        text = Text()
        text.append(" ✦ GRANDPA ", style=f"bold black on {ACCENT}")
        text.append(f"  v{grandpa.__version__}", style="#8a8a8a")
        text.append("  ·  local AI assistant", style="#8a8a8a")
        return text

    _FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def _tick(self) -> None:
        if self._busy_since is not None:
            self._spinner = (self._spinner + 1) % len(self._FRAMES)
            self._update_status()

    def _update_status(self) -> None:
        status = self.query_one("#status", Static)
        text = Text()
        if self._stopped:
            text.append("■ stopped", style="red")
            text.append("  ·  ctrl+d to close", style="#8a8a8a")
        elif self._question is not None:
            text.append("● waiting for your answer", style=ACCENT)
            hint = (
                "  y / n · esc = no"
                if self._question.yes_no
                else "  type the answer · enter"
            )
            text.append(hint, style="#8a8a8a")
        elif self._busy_since is not None:
            seconds = int(time.monotonic() - self._busy_since)
            text.append(
                f"{self._FRAMES[self._spinner]} Grandpa is thinking… {seconds}s",
                style=ACCENT,
            )
            text.append("  ·  esc to cancel", style="#8a8a8a")
        else:
            text.append(
                "enter send · shift+enter new line · ↑ history · / commands · ctrl+d quit",
                style="#6a6a6a",
            )
        status.update(text)

    @staticmethod
    def _history_path() -> Path | None:
        try:
            from grandpa.runtime_paths import grandpa_home

            return grandpa_home() / "tui_history"
        except Exception:  # noqa: BLE001
            return None


def can_run_fullscreen() -> bool:
    """A real interactive terminal, so the full-screen app can draw."""
    import sys

    return sys.stdin.isatty() and sys.stdout.isatty()


def run(chat_args: Iterable[str] = ()) -> int:
    app = GrandpaApp(chat_args=chat_args)
    result = app.run()
    return int(result or 0)


__all__ = [
    "GrandpaApp",
    "InputHistory",
    "SLASH_COMMANDS",
    "can_run_fullscreen",
    "matching_commands",
    "run",
]
