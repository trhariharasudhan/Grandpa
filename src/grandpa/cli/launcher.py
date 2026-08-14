"""Grandpa CLI launcher menu."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Callable, List, Optional

import click
from rich.console import Console
from rich.text import Text

from grandpa.cli.theme import (
    FAREWELL_TEXT,
    alternate_screen,
    render_logo,
    render_status_message,
    resolve_username,
)
from grandpa.core.config import DEFAULT_CONFIG_DIR, load_config
from grandpa.profile import configure_profile, ensure_profile, reset_profile

if TYPE_CHECKING:
    from grandpa.core.config import GrandpaConfig

# Existing Grandpa ASCII logo generator
def get_logo_text() -> str:
    from grandpa.cli.theme import _logo
    return _logo()


def save_last_used_mode(mode_name: str) -> None:
    """Save the last selected mode to config.toml without modifying other fields."""
    import tomlkit

    config_path = Path(
        os.environ.get("Grandpa_CONFIG", DEFAULT_CONFIG_DIR / "config.toml")
    )
    try:
        if config_path.exists():
            doc = tomlkit.parse(config_path.read_text(encoding="utf-8"))
        else:
            doc = tomlkit.document()
            config_path.parent.mkdir(parents=True, exist_ok=True)

        doc["last_used_mode"] = mode_name
        config_path.write_text(tomlkit.dumps(doc), encoding="utf-8")
    except Exception:
        pass


def run_interactive_menu(
    console: Console,
    title: str,
    menu_items: list[tuple[str, str, str, str]],
    username: str,
    last_used: str | None,
) -> str | None:
    """Run menu selection using prompt_toolkit if available, falling back to raw stdin/stdout."""
    try:
        from prompt_toolkit import Application
        from prompt_toolkit.key_binding import KeyBindings
        from prompt_toolkit.layout import Layout
        from prompt_toolkit.layout.containers import Window
        from prompt_toolkit.layout.controls import FormattedTextControl
        from prompt_toolkit.styles import Style

        selected_index = 0
        kb = KeyBindings()

        @kb.add("up")
        def _up(event):
            nonlocal selected_index
            selected_index = (selected_index - 1) % len(menu_items)

        @kb.add("down")
        def _down(event):
            nonlocal selected_index
            selected_index = (selected_index + 1) % len(menu_items)

        @kb.add("enter")
        def _enter(event):
            event.app.exit(result=menu_items[selected_index][3])

        @kb.add("c-c")
        def _cancel(event):
            event.app.exit(result="cancel")

        def make_handler(act):
            return lambda event: event.app.exit(result=act)

        for key, hotkey, label, action in menu_items:
            kb.add(key)(make_handler(action))
            kb.add(hotkey)(make_handler(action))
            kb.add(hotkey.upper())(make_handler(action))

        def get_formatted_text():
            result = []
            result.append(("", "\n"))
            result.append(("class:logo", f"{get_logo_text()}\n\n"))
            result.append(("", "Welcome, "))
            result.append(("class:username", f"{username}\n"))
            if last_used:
                result.append(("class:last-used", f"Last used: {last_used}\n"))
            result.append(("", f"\n{title}:\n\n"))

            for idx, (key, hotkey, label, action) in enumerate(menu_items):
                if idx == selected_index:
                    result.append(
                        ("class:selected", f" > [{key}] {label} ({hotkey})\n")
                    )
                else:
                    result.append(("", f"   [{key}] {label} ({hotkey})\n"))

            result.append(
                (
                    "",
                    "\nUse Up/Down arrows to navigate, Enter to select, or press the shortcut key.\n",
                )
            )
            return result

        layout = Layout(Window(FormattedTextControl(get_formatted_text)))
        style = Style.from_dict(
            {
                "logo": "bold #ffc448",
                "username": "bold",
                "last-used": "italic dim",
                "selected": "bold #111111 bg:#ffc448",
            }
        )

        app = Application(
            layout=layout,
            key_bindings=kb,
            style=style,
            full_screen=False,  # Alt screen owned by Launcher context manager
            erase_when_done=True,
        )
        return app.run()

    except Exception:
        # Fallback to console input
        console.print()
        console.print(f"[bold #ffc448]{get_logo_text()}[/bold #ffc448]")
        console.print()
        console.print(f"Welcome, [bold]{username}[/bold]")
        if last_used:
            console.print(f"[dim]Last used: {last_used}[/dim]")
        console.print()
        console.print(f"{title}:")
        for key, hotkey, label, action in menu_items:
            console.print(f"  [{key}] {label} ({hotkey})")
        console.print()

        try:
            ans = input("Select an option: ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            return "cancel"

        for key, hotkey, label, action in menu_items:
            if ans == key or ans == hotkey:
                return action
        console.print("[red]Invalid selection.[/red]")
        time.sleep(1.0)
        return None


def run_doctor_action(ctx: click.Context, console: Console) -> bool:
    """Run doctor check and prompt user to return or exit."""
    from grandpa.cli.doctor_cmd import doctor as doctor_cmd

    console.print()
    try:
        ctx.invoke(doctor_cmd, as_json=False)
    except Exception as e:
        console.print(f"[red]Doctor error: {e}[/red]")

    console.print()
    try:
        ans = (
            input("Press Enter to return to the launcher, or type 'exit' to quit: ")
            .strip()
            .lower()
        )
        if ans == "exit":
            return False
    except (KeyboardInterrupt, EOFError):
        return False
    return True


def run_profile_submenu(
    ctx: click.Context, console: Console, config: GrandpaConfig, username: str
) -> tuple[bool, GrandpaConfig, str]:
    """Profile management submenu."""
    from grandpa.profile import format_profile, profile_from_config

    menu_items = [
        ("1", "v", "View profile", "view"),
        ("2", "e", "Edit display name", "edit"),
        ("3", "r", "Reset profile", "reset"),
        ("4", "b", "Back", "back"),
    ]

    while True:
        action = run_interactive_menu(
            console, "Profile", menu_items, username, None
        )
        if action == "back" or action == "cancel":
            return True, config, username

        if action == "view":
            console.print()
            console.print("[bold]Current Profile:[/bold]")
            console.print(format_profile(profile_from_config(config)))
            console.print()
            try:
                input("Press Enter to return to Profile menu...")
            except (KeyboardInterrupt, EOFError):
                pass

        elif action == "edit":
            console.print()
            updated = configure_profile(
                console=console, config=config, interactive=True
            )
            config = updated
            username = resolve_username(updated)

        elif action == "reset":
            console.print()
            try:
                ans = input("Reset local profile? [y/N]: ").strip().lower()
                if ans in ("y", "yes"):
                    reset_profile(confirmed=True)
                    config.user.onboarding_completed = False
                    console.print("[green]Profile reset.[/green]")
                    time.sleep(1.0)
                    # Exit entirely so onboarding runs on next startup
                    return False, config, username
            except (KeyboardInterrupt, EOFError):
                pass


def run_settings_submenu(
    ctx: click.Context, console: Console, config: GrandpaConfig, username: str
) -> bool:
    """Settings submenu exposing config/status options."""
    from grandpa.cli.config_cmd import _show_hardware_info, _show_loaded_config
    from grandpa.cli.daemon_cmd import status as status_cmd

    menu_items = [
        ("1", "l", "Show Effective Configuration (loaded)", "loaded"),
        ("2", "h", "Show Detected Hardware (hardware)", "hardware"),
        ("3", "t", "Show Raw TOML (toml)", "toml"),
        ("4", "s", "Show Server Daemon Status (status)", "status"),
        ("5", "b", "Back", "back"),
    ]

    config_path = Path(
        os.environ.get("Grandpa_CONFIG", DEFAULT_CONFIG_DIR / "config.toml")
    )

    while True:
        action = run_interactive_menu(
            console, "Settings", menu_items, username, None
        )
        if action == "back" or action == "cancel":
            return True

        if action == "loaded":
            console.print()
            _show_loaded_config(console, config_path, as_json=False)
            console.print()
            try:
                input("Press Enter to return to Settings...")
            except (KeyboardInterrupt, EOFError):
                pass

        elif action == "hardware":
            console.print()
            _show_hardware_info(console, show_recommendations=True)
            console.print()
            try:
                input("Press Enter to return to Settings...")
            except (KeyboardInterrupt, EOFError):
                pass

        elif action == "toml":
            console.print()
            if config_path.exists():
                from rich.panel import Panel
                from rich.syntax import Syntax

                syntax = Syntax(
                    config_path.read_text(encoding="utf-8"),
                    "toml",
                    theme="monokai",
                    line_numbers=True,
                )
                console.print(Panel(syntax, border_style="dim"))
            else:
                console.print("[yellow]TOML configuration file does not exist.[/yellow]")
            console.print()
            try:
                input("Press Enter to return to Settings...")
            except (KeyboardInterrupt, EOFError):
                pass

        elif action == "status":
            console.print()
            try:
                ctx.invoke(status_cmd)
            except Exception as e:
                console.print(f"[red]Status check failed: {e}[/red]")
            console.print()
            try:
                input("Press Enter to return to Settings...")
            except (KeyboardInterrupt, EOFError):
                pass


@click.command(hidden=True)
@click.pass_context
def launcher(ctx: click.Context) -> None:
    """Launch the interactive menu launcher."""
    console = Console(stderr=True)

    # Safe non-interactive fallback
    if not sys.stdin.isatty() and not os.environ.get("GRANDPA_TESTING"):
        console.print("Non-interactive mode detected. Exiting launcher.")
        return

    # Load configuration
    config = load_config()

    # Complete onboarding if display name is missing
    config = ensure_profile(console=console, config=config)
    username = resolve_username(config)

    # Alternate screen manager owns alternate screen for duration of session
    fullscreen = getattr(config, "fullscreen", True)

    menu_items = [
        ("1", "c", "Chat Assistant", "chat"),
        ("2", "v", "Voice Assistant", "voice"),
        ("3", "d", "Doctor / Health Check", "doctor"),
        ("4", "p", "Profile", "profile"),
        ("5", "s", "Settings", "settings"),
        ("6", "q", "Exit", "exit"),
    ]

    with alternate_screen(enabled=fullscreen):
        while True:
            # Refresh configs in loop in case profile updated
            config = load_config()
            username = resolve_username(config)
            last_used = getattr(config, "last_used_mode", None) or None

            action = run_interactive_menu(
                console, "Choose a mode", menu_items, username, last_used
            )

            if action == "exit" or action == "cancel":
                render_status_message(console, FAREWELL_TEXT)
                if fullscreen:
                    time.sleep(1.0)
                break

            if action == "chat":
                from grandpa.cli.chat_cmd import chat as chat_cmd

                save_last_used_mode("Chat Assistant")
                # Invoke chat subcommand with fullscreen=False to prevent nested corruption
                try:
                    ctx.invoke(chat_cmd, tui_mode=True, fullscreen=False)
                except Exception as e:
                    console.print(f"[red]Chat failed: {e}[/red]")
                    time.sleep(2.0)

            elif action == "voice":
                from grandpa.cli.voice_cmd import voice as voice_cmd

                save_last_used_mode("Voice Assistant")
                try:
                    ctx.invoke(
                        voice_cmd,
                        no_tts=False,
                        model=None,
                        language=None,
                        stt_device=None,
                        microphone=None,
                        wake_word=False,
                        wake_phrase=(),
                        no_wake_response=False,
                        list_microphones=False,
                        list_voices=False,
                        diagnose=False,
                        screen_reader=False,
                    )
                except Exception as e:
                    console.print(f"[red]Voice session failed: {e}[/red]")
                    time.sleep(2.0)

            elif action == "doctor":
                save_last_used_mode("Doctor / Health Check")
                keep_running = run_doctor_action(ctx, console)
                if not keep_running:
                    render_status_message(console, FAREWELL_TEXT)
                    if fullscreen:
                        time.sleep(1.0)
                    break

            elif action == "profile":
                keep_running, config, username = run_profile_submenu(
                    ctx, console, config, username
                )
                if not keep_running:
                    break

            elif action == "settings":
                keep_running = run_settings_submenu(ctx, console, config, username)
                if not keep_running:
                    break
