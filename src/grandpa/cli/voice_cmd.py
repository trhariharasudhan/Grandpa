"""Voice assistant and diagnostics CLI commands."""

from __future__ import annotations

import click

from grandpa.jarvis.voice_input import save_preferred_microphone_name
from grandpa.voice.cli_session import build_voice_session
from grandpa.voice.config import load_voice_assistant_config
from grandpa.voice.diagnostics import (
    list_input_devices,
    log_voice_initialization_error,
    run_voice_doctor,
)
from grandpa.voice.errors import VoiceError, VoiceOutputUnavailableError
from grandpa.voice.speech_output import SpeechOutputEngine
from grandpa.voice.text_to_speech import list_system_voices


@click.group("voice", invoke_without_command=True)
@click.option("--no-tts", is_flag=True, help="Disable spoken responses and print only.")
@click.option(
    "--model",
    default=None,
    help="Offline Whisper/faster-whisper model name, e.g. tiny.en or base.en.",
)
@click.option(
    "--language",
    default=None,
    help="Speech recognition language code, e.g. en. Empty means auto where supported.",
)
@click.option(
    "--device",
    "stt_device",
    default=None,
    help="STT compute device: cpu, cuda, or auto.",
)
@click.option(
    "--microphone", type=int, default=None, help="Microphone input device index."
)
@click.option(
    "--wake-word",
    is_flag=True,
    help="Wait for a wake phrase before listening for commands.",
)
@click.option(
    "--wake-phrase",
    multiple=True,
    help="Wake phrase to listen for. Can be passed more than once.",
)
@click.option(
    "--no-wake-response",
    is_flag=True,
    help='Do not speak the "Yes?" wake acknowledgement.',
)
@click.option(
    "--list-microphones", is_flag=True, help="List input microphone devices and exit."
)
@click.option("--list-voices", is_flag=True, help="List local TTS voices and exit.")
@click.option(
    "--diagnose",
    is_flag=True,
    help="Show voice dependencies and active Python environment, then exit.",
)
@click.pass_context
def voice(
    ctx: click.Context,
    no_tts: bool,
    model: str | None,
    language: str | None,
    stt_device: str | None,
    microphone: int | None,
    wake_word: bool,
    wake_phrase: tuple[str, ...],
    no_wake_response: bool,
    list_microphones: bool,
    list_voices: bool,
    diagnose: bool,
) -> None:
    """Start Grandpa's offline-first voice assistant or run voice diagnostics."""

    if ctx.invoked_subcommand is not None:
        return

    if list_microphones:
        _print_microphones()
        return
    if list_voices:
        _print_voices()
        return
    if diagnose:
        _print_diagnostics(run_voice_doctor(duration_seconds=0))
        return

    try:
        config = load_voice_assistant_config(
            model=model,
            language=language,
            device=stt_device,
            microphone=microphone,
            tts_enabled=not no_tts,
            wake_word_enabled=wake_word,
            wake_phrases=wake_phrase or None,
            wake_response_enabled=not no_wake_response,
        )
        session = build_voice_session(
            model=config.stt_model,
            language=config.language,
            device=config.device,
            microphone=config.microphone,
            no_tts=no_tts,
            wake_word=config.wake_word_enabled,
            wake_phrases=config.wake_phrases,
            wake_response_enabled=config.wake_response_enabled,
            output=click.echo,
        )
        raise SystemExit(session.run())
    except VoiceError as exc:
        raise click.ClickException(str(exc)) from exc
    except Exception as exc:
        log_path = log_voice_initialization_error(exc)
        click.echo(
            f"Voice mode could not initialize: {type(exc).__name__}: {exc}", err=True
        )
        click.echo(f"Technical details were written to: {log_path}", err=True)
        raise SystemExit(1) from None


@voice.command("doctor")
@click.option("--device", type=int, default=None, help="Input device index to test.")
@click.option(
    "--duration",
    type=float,
    default=2.0,
    show_default=True,
    help="Microphone test duration.",
)
def doctor(device: int | None, duration: float) -> None:
    """Run bounded microphone, STT, and TTS readiness checks."""

    _print_diagnostics(
        run_voice_doctor(device=device, duration_seconds=max(0.0, duration))
    )


@voice.command("diagnose")
@click.option("--device", type=int, default=None, help="Input device index to inspect.")
def diagnose_voice(device: int | None) -> None:
    """Show voice runtime and device diagnostics without recording."""

    _print_diagnostics(run_voice_doctor(device=device, duration_seconds=0))


def _print_diagnostics(checks: list[dict]) -> None:
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
    _print_microphones()


def _print_microphones() -> None:
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
        details = (
            f"{device.input_channels} input channel(s), "
            f"{getattr(device, 'sample_rate', 16_000)} Hz, "
            f"{getattr(device, 'transport', 'unknown')}"
        )
        click.echo(f"{device.index}: {device.name} ({details}){marker}")


def _print_voices() -> None:
    voices = list_system_voices()
    if not voices:
        click.echo(
            "No local TTS voices found. On Windows, pyttsx3 uses installed SAPI voices."
        )
        return
    for voice_name in voices:
        click.echo(voice_name)


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
    matches = [
        device for device in found if requested.casefold() in device.name.casefold()
    ]
    if not matches:
        available = (
            "\n".join(f"- {device.index}: {device.name}" for device in found)
            or "- none"
        )
        raise click.ClickException(
            f"Microphone named '{requested}' was not found.\nAvailable input devices:\n{available}"
        )
    selected = matches[0]
    saved = save_preferred_microphone_name(selected.name)
    click.echo(f"Saved preferred microphone: {saved}")


__all__ = ["voice"]
