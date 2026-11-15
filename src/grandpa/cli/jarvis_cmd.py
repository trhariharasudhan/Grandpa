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

    if result.payload is None and result.status != "blocked":
        # V1-T7: jarvis understood one phrase ("open my Grandpa project in VS
        # Code") and answered "I don't know how to route that" to everything
        # else, while 167 actions sat catalogued. Anything its own router does
        # not claim now goes to the same action-layer tool loop as `grandpa
        # ask --tool-loop` and chat: the model picks catalogued actions, and
        # every one passes the executor, which asks before anything that needs
        # confirming (and refuses those when there is no terminal to ask).
        if dry_run:
            from grandpa.action_layer.catalogue import candidate_domains

            domains = ", ".join(candidate_domains(text)) or "core only"
            console.print(
                "Would send this to the action layer's tool loop "
                f"(tools: {domains}). Nothing was run."
            )
            return
        from grandpa.cli._tool_loop import run_tool_loop

        code = run_tool_loop(text)
        if code:
            raise SystemExit(code)
        return

    if result.payload is None:
        console.print(f"[red]{result.message}[/red]")
        if not recognized:
            console.print(f"Recognized: {text}")
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
