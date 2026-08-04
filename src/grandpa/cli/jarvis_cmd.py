"""Jarvis text command entrypoint."""

from __future__ import annotations

import json

import click
from rich.console import Console

from grandpa.jarvis import route_jarvis_command
from grandpa.jarvis.voice_input import listen_for_jarvis_command
from grandpa.pc_control import run_local_action
from grandpa.voice.errors import VoiceError


@click.command("jarvis")
@click.option(
    "--dry-run", is_flag=True, help="Resolve and print the action without executing it."
)
@click.option(
    "--voice",
    is_flag=True,
    help="Listen once from the microphone and route the transcript.",
)
@click.argument("command", nargs=-1, required=False)
def jarvis(dry_run: bool, voice: bool, command: tuple[str, ...]) -> None:
    """Route a Jarvis-style local text command through safe actions."""
    console = Console()
    recognized = False
    if voice:
        text = _listen_for_voice_command(console)
        recognized = True
    else:
        text = " ".join(command).strip()
        if not text:
            raise click.ClickException(
                'Provide a command, or use "grandpa jarvis --voice".'
            )

    _run_jarvis_text(text, dry_run=dry_run, console=console, recognized=recognized)


def _listen_for_voice_command(console: Console) -> str:
    console.print("Listening for one Jarvis command...")
    console.print("Speak now. Press Ctrl+C to cancel.")
    try:
        if console.is_interactive:
            with console.status("Listening...", spinner="dots"):
                voice_result = listen_for_jarvis_command()
        else:
            voice_result = listen_for_jarvis_command()
    except KeyboardInterrupt:
        _safe_error("Voice input cancelled.")
        raise SystemExit(1) from None
    except VoiceError as exc:
        _safe_error(str(exc))
        raise SystemExit(1) from exc

    console.print(f"Recognized: {voice_result.transcript}")
    return voice_result.transcript


def _safe_error(message: str) -> None:
    try:
        click.echo(message, err=True)
    except OSError:
        pass


def _run_jarvis_text(
    text: str, *, dry_run: bool, console: Console, recognized: bool = False
) -> None:
    result = route_jarvis_command(text, dry_run=dry_run)

    if result.payload is None:
        style = "red" if result.status == "blocked" else "yellow"
        console.print(f"[{style}]{result.message}[/{style}]")
        if not recognized:
            console.print(f"Recognized: {text}")
        console.print("Try: open my Grandpa project in VS Code")
        raise SystemExit(1)

    console.print(result.message)
    console.print(json.dumps(result.payload, indent=2, sort_keys=True))
    if dry_run:
        return

    response = run_local_action(result.payload)
    console.print(response.message)
    if not response.ok and response.status not in {"approval_required", "dry_run"}:
        raise click.ClickException(response.status)


__all__ = ["jarvis"]
