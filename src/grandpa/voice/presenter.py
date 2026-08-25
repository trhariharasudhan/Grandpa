from __future__ import annotations

import os
import sys
import threading
from typing import Callable

from rich.console import Console
from rich.panel import Panel

from grandpa.cli.theme import (
    VOICE_STARTUP_TEXT,
    render_assistant_response,
    render_logo_borderless,
    render_user_message,
)


def is_interactive_terminal() -> bool:
    """Detect if we are running in an interactive terminal (VS Code, Windows Terminal, WT, etc.)."""
    # Check TTY
    if hasattr(sys.stdout, "isatty") and sys.stdout.isatty():
        return True
    # Check common terminal indicators
    for env in ("TERM_PROGRAM", "VSCODE_GIT_IPC_HANDLE", "COLORTERM", "WT_SESSION"):
        if env in os.environ:
            return True
    term = os.environ.get("TERM", "")
    if term and term.lower() not in ("dumb", "unknown"):
        return True
    if hasattr(sys.stdin, "isatty") and sys.stdin.isatty():
        return True
    return False


class ListeningAnimation:
    """Small terminal-only animation for microphone capture."""

    def __init__(self, console: Console, *, interval: float = 0.4) -> None:
        self._console = console
        self._interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

        self._enabled = is_interactive_terminal() and not getattr(
            console, "no_color", False
        )

    def start(self) -> None:
        if not self._enabled or self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="grandpa-listening-animation",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        if not self._thread:
            return
        self._stop.set()
        self._thread.join(timeout=1.0)
        self._clear_line()
        self._thread = None

    def _run(self) -> None:
        frames = ["Listening", "Listening.", "Listening..", "Listening..."]
        index = 0
        while not self._stop.is_set():
            frame = frames[index % len(frames)]
            self._write(f"\r{frame}")
            index += 1
            self._stop.wait(self._interval)

    def _clear_line(self) -> None:
        self._write("\r\033[2K")

    def _write(self, text: str) -> None:
        try:
            file = self._console.file
            file.write(text)
            file.flush()
        except Exception:
            pass


class VoicePresenter:
    """Presenter class for formatting and displaying Grandpa Voice CLI output using Rich."""

    def __init__(
        self,
        console: Console | None = None,
        quiet: bool = False,
        verbose: bool = False,
        no_color: bool = False,
        screen_reader: bool | None = None,
        output: Callable[[str], None] = print,
        debug: bool = False,
    ) -> None:
        self.quiet = quiet
        self.verbose = verbose
        self.output = output
        self.debug = debug
        self._current_ui_state: str = ""

        interactive = is_interactive_terminal()
        custom_output = output != print

        if custom_output and console is None:
            if screen_reader is None:
                screen_reader = True
            self.no_color = True
        else:
            if screen_reader is None:
                screen_reader = not interactive
            self.no_color = (
                no_color or getattr(console, "no_color", False) or not interactive
            )

        self.screen_reader = screen_reader

        # Disable colors/styles if no_color or screen_reader is true
        if self.no_color or self.screen_reader:
            self.console = console or Console(color_system=None, force_terminal=False)
        else:
            self.console = console or Console(stderr=True, force_terminal=True)
            try:
                self.console._is_terminal = True
            except Exception:
                pass

    def on_idle_listening(self) -> None:
        """Emitted once when entering idle microphone listening."""
        if self._current_ui_state == "idle":
            return
        self._current_ui_state = "idle"
        self.stop_thinking()
        self.stop_listening()
        if self.debug:
            self.print_status("[IDLE] Listening...")
        else:
            self.print_status("Listening...")
            self.start_listening()

    def on_speech_detected(self) -> None:
        """Emitted when speech onset is detected by VAD."""
        if self._current_ui_state == "capturing":
            return
        self._current_ui_state = "capturing"
        self.stop_listening()
        if self.debug:
            self.print_status("[CAPTURING] Speech detected")

    def on_transcribing(self) -> None:
        """Emitted when audio capture is sent to STT."""
        if self._current_ui_state == "transcribing":
            return
        self._current_ui_state = "transcribing"
        self.stop_listening()
        if self.debug:
            self.print_status("[PROCESSING] Transcribing...")
        else:
            self.start_thinking()

    def on_routing(self) -> None:
        """Emitted when transcript is being routed."""
        if self._current_ui_state == "routing":
            return
        self._current_ui_state = "routing"
        if self.debug:
            self.print_status("[PROCESSING] Routing...")

    def on_executing(self, action: str = "") -> None:
        """Emitted when action execution starts."""
        self._current_ui_state = "executing"
        self.stop_thinking()
        if self.debug:
            msg = f"[EXECUTING] {action}" if action else "[EXECUTING] ..."
            self.print_status(msg)

    def print_banner(self, engine: str, model: str) -> None:
        """Print the large GRANDPA banner and setup instructions."""
        if self.quiet:
            return

        if not self.no_color and not self.screen_reader:
            self.console.print()
            render_logo_borderless(self.console)
            self.console.print()
            self.console.print(VOICE_STARTUP_TEXT)
            self.console.print()
        else:
            self.output(VOICE_STARTUP_TEXT)
            self.output("")

    def print_status(self, state: str) -> None:
        """Print current session status (Listening, Thinking, etc.) with rich style."""
        if self.quiet:
            return

        if not self.no_color and not self.screen_reader:
            self.console.print(f"[dim]{state}[/dim]", highlight=False)
        else:
            self.output(state)

    def start_listening(self) -> None:
        """Start the temporary animated listening indicator."""
        if self.quiet or self.screen_reader or self.no_color:
            return
        self._listening = ListeningAnimation(self.console)
        self._listening.start()

    def stop_listening(self) -> None:
        """Stop and clear the temporary animated listening indicator."""
        listening = getattr(self, "_listening", None)
        if listening is not None:
            listening.stop()
            self._listening = None

    def start_thinking(self) -> None:
        """Start the temporary animated thinking spinner."""
        if self.quiet or self.screen_reader or self.no_color:
            return
        from grandpa.cli.chat_cmd import ThinkingAnimation

        self._thinking = ThinkingAnimation(self.console)
        self._thinking.start()

    def stop_thinking(self) -> None:
        """Stop and clear the temporary animated thinking spinner."""
        thinking = getattr(self, "_thinking", None)
        if thinking is not None:
            thinking.stop()
            self._thinking = None

    def print_blank_line(self) -> None:
        """Print exactly one blank line."""
        if self.quiet:
            return
        if not self.no_color and not self.screen_reader:
            self.console.print()
        else:
            self.output("")

    def print_user_message(self, content: str) -> None:
        """Print recognized user transcription."""
        if self.quiet:
            return
        if not self.no_color and not self.screen_reader:
            render_user_message(self.console, content)
        elif self.screen_reader:
            self.output(f"You: {content}")
        else:
            self.output(f"> {content}")

    def print_assistant_message(self, content: str) -> None:
        """Print assistant response message with wrapping support."""
        if self.quiet:
            return
        if not self.no_color and not self.screen_reader:
            render_assistant_response(self.console, content)
        elif self.screen_reader:
            self.output(f"Grandpa: {content}")
        else:
            self.output(f"< {content}")

    def print_farewell(self, content: str) -> None:
        """Print a session-status farewell without an assistant prefix."""
        if self.quiet:
            return
        if not self.no_color and not self.screen_reader:
            self.console.print(f"[dim]{content}[/dim]")
        else:
            self.output(content)

    def print_confirmation_required(self, command: str) -> None:
        """Render action confirmation warning and instruction."""
        if self.quiet:
            return

        use_emoji = not self.no_color and not self.screen_reader
        prefix = "⚠ " if use_emoji else "Warning: "

        msg = (
            f"{prefix}Confirmation required before executing: {command}\n"
            f"Reply with yes/confirm to approve, or cancel to deny."
        )
        if not self.no_color and not self.screen_reader:
            self.console.print(
                Panel(
                    msg,
                    border_style="yellow",
                    title="Confirmation Required",
                    title_align="left",
                )
            )
        else:
            self.output(msg)

    def print_action_completed(self, message: str) -> None:
        """Print completed action message."""
        if self.quiet:
            return
        use_emoji = not self.no_color and not self.screen_reader
        prefix = "✓ " if use_emoji else "Success: "
        if not self.no_color and not self.screen_reader:
            self.console.print(f"[bold green]{prefix}{message}[/bold green]")
        else:
            self.output(f"{prefix}{message}")

    def print_error(self, message: str) -> None:
        """Display error messages inside a red Panel."""
        if self.quiet:
            return
        use_emoji = not self.no_color and not self.screen_reader
        prefix = "✕ " if use_emoji else "Error: "
        if not self.no_color and not self.screen_reader:
            self.console.print(
                Panel(
                    f"[red]{prefix}{message}[/red]",
                    border_style="red",
                    title="System Error",
                    title_align="left",
                )
            )
        else:
            self.output(f"{prefix}{message}")
