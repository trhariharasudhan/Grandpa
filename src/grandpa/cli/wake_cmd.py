"""``grandpa wake``: the "Hey Grandpa" wake word (B1).

* ``status`` -- what is installed and which model would be used.
* ``setup``  -- fetch openWakeWord's shared feature models (~4 MB, once).
* ``test``   -- run a WAV file through the detector; ``--negative`` turns the
  count into false triggers per hour.
* ``listen`` -- the live microphone; prints each detection, and at the end the
  count per hour, so an hour of TV or talking measures the false-trigger rate.
"""

from __future__ import annotations

import time

import click

from grandpa.voice import wake_engine as we


def _engine(
    model: str | None, threshold: float | None, patience: int | None
) -> we.WakeWordEngine:
    try:
        config = we.WakeEngineConfig.from_env(
            model=model, threshold=threshold, patience=patience
        )
        return we.WakeWordEngine(config)
    except (we.WakeEngineUnavailable, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc


_model_option = click.option(
    "--model",
    default=None,
    help="A .onnx wake model, or a built-in name like hey_mycroft. "
    "Default: ~/.Grandpa/wakeword/hey_grandpa.onnx",
)
_threshold_option = click.option(
    "--threshold",
    type=float,
    default=None,
    help=f"Score (0-1) a frame must reach. Default {we.DEFAULT_THRESHOLD}.",
)
_patience_option = click.option(
    "--patience",
    type=int,
    default=None,
    help=f"Frames in a row over the threshold. Default {we.DEFAULT_PATIENCE}.",
)


@click.group("wake")
def wake() -> None:
    """The "Hey Grandpa" wake word (local, openWakeWord)."""


@wake.command("status")
def wake_status() -> None:
    """Show what the wake word needs and what is there."""

    info = we.status()
    click.echo(f"openWakeWord installed: {'yes' if info['openwakeword'] else 'no'}")
    click.echo(f"Feature models:         {'yes' if info['feature_models'] else 'no'}")
    click.echo(f"Hey Grandpa model:      {info['model'] or 'missing'}")
    if not info["openwakeword"]:
        click.echo("Next: uv sync --extra wake")
    elif not info["feature_models"]:
        click.echo("Next: grandpa wake setup")
    elif not info["model"]:
        click.echo(we.SETUP_HINT)
    else:
        click.echo("Ready: grandpa wake listen")


@wake.command("setup")
def wake_setup() -> None:
    """Download openWakeWord's feature models (about 4 MB, once)."""

    try:
        where = we.download_feature_models()
    except we.WakeEngineUnavailable as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Feature models are in {where}")
    if not we.status()["model"]:
        click.echo(we.SETUP_HINT)


@wake.command("test")
@click.argument("wav", type=click.Path(exists=True, dir_okay=False))
@click.option(
    "--negative",
    is_flag=True,
    help="The file has no wake phrase: report false triggers per hour.",
)
@_model_option
@_threshold_option
@_patience_option
def wake_test(
    wav: str,
    negative: bool,
    model: str | None,
    threshold: float | None,
    patience: int | None,
) -> None:
    """Run WAV (16-bit PCM, any rate) through the detector."""

    engine = _engine(model, threshold, patience)
    try:
        report = we.evaluate_file(wav, engine)
    except (ValueError, OSError) as exc:
        raise click.ClickException(str(exc)) from exc
    for event in report.events:
        click.echo(event.describe())
    click.echo(report.summary(negative=negative))


@wake.command("listen")
@click.option(
    "--minutes",
    type=float,
    default=0.0,
    help="Stop after this many minutes (0 = until Ctrl+C).",
)
@click.option("--device", default=None, help="Microphone index or name.")
@_model_option
@_threshold_option
@_patience_option
def wake_listen(
    minutes: float,
    device: str | None,
    model: str | None,
    threshold: float | None,
    patience: int | None,
) -> None:
    """Listen on the microphone and print every detection."""

    engine = _engine(model, threshold, patience)
    events: list[we.WakeEvent] = []

    def on_wake(event: we.WakeEvent) -> None:
        events.append(event)
        click.echo(event.describe())

    mic: int | str | None = device
    if isinstance(device, str) and device.isdigit():
        mic = int(device)
    listener = we.WakeWordListener(engine, on_wake, device=mic)
    click.echo(
        f"Listening for {engine.label} (threshold {engine.config.threshold}, "
        f"patience {engine.config.patience}). Ctrl+C to stop."
    )
    deadline = time.monotonic() + minutes * 60 if minutes > 0 else None
    try:
        listener.start()
    except Exception as exc:  # noqa: BLE001 - PortAudio has many failure shapes
        raise click.ClickException(f"Could not open the microphone: {exc}") from exc
    try:
        while deadline is None or time.monotonic() < deadline:
            if listener.error:
                raise click.ClickException(f"Microphone stopped: {listener.error}")
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    finally:
        listener.stop()
    report = we.WakeReport(
        seconds=engine.seconds_heard, events=events, peak_score=engine.peak_score
    )
    click.echo(report.summary(negative=True))
    click.echo("(Counts every detection; subtract the times you said it.)")


__all__ = ["wake"]
