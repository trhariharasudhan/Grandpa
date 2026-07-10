"""Voice diagnostics CLI commands."""

from __future__ import annotations

import click

from grandpa.jarvis.voice_input import save_preferred_microphone_name
from grandpa.voice.diagnostics import list_input_devices, run_voice_doctor
from grandpa.voice.errors import VoiceError, VoiceOutputUnavailableError
from grandpa.voice.speech_output import SpeechOutputEngine


@click.group("voice")
def voice() -> None:
    """Voice diagnostics and setup commands."""


@voice.command("doctor")
@click.option("--device", type=int, default=None, help="Input device index to test.")
def doctor(device: int | None) -> None:
    checks = run_voice_doctor(device=device)
    for check in checks:
        click.echo(f"{check['status'].upper():4} {check['name']}: {check['message']}")


@voice.command("test")
@click.option("--dry-run", is_flag=True, help="Validate TTS without speaking.")
def test_voice(dry_run: bool) -> None:
    """Say a short test phrase through the configured TTS backend."""

    engine = SpeechOutputEngine()
    text = "Hello, I am Grandpa."
    try:
        result = engine.speak(text, interrupt=True, dry_run=dry_run)
    except VoiceOutputUnavailableError as exc:
        raise click.ClickException(str(exc)) from exc
    if result.status == "fallback":
        click.echo(text)
        click.echo("Speech output unavailable; printed response only.")
        return
    click.echo(result.message)


@voice.command("devices")
def devices() -> None:
    try:
        found = list_input_devices()
    except VoiceError as exc:
        click.echo(str(exc))
        return
    if not found:
        click.echo("No input devices found.")
        return
    for device in found:
        marker = " *default*" if device.default else ""
        click.echo(f"{device.index}: {device.name} ({device.input_channels} input channel(s)){marker}")


@voice.command("set-device")
@click.argument("name")
def set_device(name: str) -> None:
    """Save the preferred microphone by name."""

    requested = name.strip()
    if not requested:
        raise click.ClickException("Microphone name cannot be empty.")
    try:
        found = list_input_devices()
    except VoiceError as exc:
        raise click.ClickException(str(exc)) from exc
    matches = [device for device in found if requested.casefold() in device.name.casefold()]
    if not matches:
        available = "\n".join(f"- {device.index}: {device.name}" for device in found) or "- none"
        raise click.ClickException(f"Microphone named '{requested}' was not found.\nAvailable input devices:\n{available}")
    selected = matches[0]
    saved = save_preferred_microphone_name(selected.name)
    click.echo(f"Saved preferred microphone: {saved}")


__all__ = ["voice"]
