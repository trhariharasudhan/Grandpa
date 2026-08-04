"""Voice Operator Mode CLI command."""

from __future__ import annotations

import os

import click

from grandpa.voice.operator import run_voice_operator_loop
from grandpa.voice.speech_output import SpeechOutputEngine


@click.command("voice-operator")
@click.option("--dry-run", is_flag=True, help="Resolve actions without executing them.")
@click.option(
    "--duration", type=float, default=None, help="Recording duration in seconds."
)
@click.option("--device", type=int, default=None, help="Input device index.")
@click.option("--device-name", default=None, help="Input device name or partial name.")
@click.option("--typed", is_flag=True, help="Use typed commands only.")
@click.option("--no-tts", is_flag=True, help="Disable spoken responses.")
@click.option("--debug", is_flag=True, help="Print microphone capture diagnostics.")
def voice_operator(
    dry_run: bool,
    duration: float | None,
    device: int | None,
    device_name: str | None,
    typed: bool,
    no_tts: bool,
    debug: bool,
) -> None:
    """Start command-first Windows voice operator mode."""

    selected_duration = _duration_from_option_or_env(duration)
    selected_device = _device_from_option_or_env(device)
    if selected_device is not None and selected_device < 0:
        raise click.ClickException(
            "Invalid microphone device index. Run `grandpa voice devices` to list devices."
        )
    typed_only = typed or os.environ.get("GRANDPA_VOICE_TYPED", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    speech_output = SpeechOutputEngine(enabled=not no_tts)
    raise SystemExit(
        run_voice_operator_loop(
            dry_run=dry_run,
            duration_seconds=selected_duration,
            device=selected_device,
            device_name=device_name,
            prefer_voice=False if typed_only else None,
            speech_output=speech_output,
            debug=debug,
        )
    )


def _duration_from_option_or_env(value: float | None) -> float:
    if value is not None:
        return max(0.5, min(30.0, value))
    raw = os.environ.get("GRANDPA_VOICE_DURATION", "").strip()
    if not raw:
        return 4.0
    try:
        return max(0.5, min(30.0, float(raw)))
    except ValueError:
        return 4.0


def _device_from_option_or_env(value: int | None) -> int | None:
    if value is not None:
        return value
    raw = os.environ.get("GRANDPA_VOICE_DEVICE", "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


__all__ = ["voice_operator"]
