"""Speak text aloud with Grandpa's local TTS engine."""

from __future__ import annotations

import click

from grandpa.voice.errors import VoiceOutputUnavailableError
from grandpa.voice.speech_output import SpeechOutputEngine


@click.command("speak")
@click.argument("text")
@click.option(
    "--dry-run", is_flag=True, help="Validate speech output without speaking."
)
def speak(text: str, dry_run: bool) -> None:
    """Speak TEXT aloud using the best available local TTS backend."""

    engine = SpeechOutputEngine()
    try:
        result = engine.speak(text, interrupt=True, dry_run=dry_run)
    except VoiceOutputUnavailableError as exc:
        raise click.ClickException(str(exc)) from exc
    if result.status == "fallback":
        click.echo(text)
        click.echo("Speech output unavailable; printed response only.")
        return
    click.echo(result.message)


__all__ = ["speak"]
