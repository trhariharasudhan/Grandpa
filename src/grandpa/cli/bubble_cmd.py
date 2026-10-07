"""``grandpa bubble`` -- the floating desktop assistant.

Blocks the terminal, because it owns the tkinter main loop. That is stated in the
help text rather than discovered: a command that silently never returns is
indistinguishable from a hang.
"""

from __future__ import annotations

import click

from grandpa.cli.safe_output import safe_cli_error


@click.command("bubble")
@click.option("--key", default="space", help="Key to hold while speaking.")
@click.option("--device", type=int, default=None, help="Microphone input device index.")
@click.option("--model", default=None, help="Whisper model, e.g. small.en.")
@click.option(
    "--position",
    default=None,
    metavar="X,Y",
    help="Where to put the bubble. Overrides the remembered position.",
)
def bubble(
    key: str, device: int | None, model: str | None, position: str | None
) -> None:
    """Show the floating assistant. Blocks this terminal until you close it.

    A borderless always-on-top window with a held-key microphone, a text box and
    a status line. Hold SPACE anywhere to talk -- the key is read globally, so
    the bubble never needs focus and never takes it. Esc closes it, as does
    Ctrl+C here.

    The model is loaded before the bubble reports itself ready; while it loads
    the status says so and a hold is refused rather than recorded into nothing.
    """

    from grandpa.ui.bridge import InProcessBridge
    from grandpa.ui.bubble import BubbleController
    from grandpa.ui.tk_view import TkBubbleView
    from grandpa.voice.accuracy import quiet_model_downloads
    from grandpa.voice.config import load_voice_assistant_config
    from grandpa.voice.microphone import MicrophoneCapture
    from grandpa.voice.push_to_talk import (
        MAXIMUM_HOLD_SECONDS,
        WindowsKeyProbe,
        hold_to_talk_vad_config,
    )

    quiet_model_downloads()

    if not WindowsKeyProbe.available():
        safe_cli_error(
            "The bubble needs the Windows keyboard API (user32) for its held "
            "key, which is not available here."
        )
        raise SystemExit(1)

    try:
        import tkinter  # noqa: F401
    except Exception as exc:
        safe_cli_error(
            f"tkinter is not available in this Python install ({exc}). It ships "
            f"with CPython on Windows; a stripped build will not have it."
        )
        raise SystemExit(1) from None

    config = load_voice_assistant_config(
        model=model, microphone=device, tts_enabled=False
    )
    capture = MicrophoneCapture(
        duration_seconds=MAXIMUM_HOLD_SECONDS,
        device=config.microphone if device is None else device,
        recovery_attempts=config.microphone_recovery_attempts,
        vad_config=hold_to_talk_vad_config(MAXIMUM_HOLD_SECONDS),
    )
    bridge = InProcessBridge()
    view = TkBubbleView()
    controller = BubbleController(
        view=view,
        bridge=bridge,
        probe=WindowsKeyProbe(),
        capture=capture,
        key=key,
    )
    view.on_submit = controller.submit
    view.on_close = lambda: (controller.stop(), None)[1]

    start_at = _parse_position(position)
    controller.start()
    if start_at is not None:
        controller.position = start_at
        view.show(position=start_at, topmost=True)

    click.echo("Bubble open. Hold the key to talk; Esc or Ctrl+C to close.")

    # Warm on the tk loop's first tick rather than before show(), so the window
    # is visible while the model loads and its status says LOADING.
    view.pump(50, _hold_poller(controller))
    if view.root is not None:
        view.root.after(10, controller.warm)
    try:
        view.run()
    except KeyboardInterrupt:
        pass
    finally:
        controller.stop()
        capture.close()


def _hold_poller(controller):
    """Start a hold when the key goes down, on the tk thread."""

    def poll() -> None:
        probe = controller.probe
        if probe is None or not controller.can_record():
            return
        try:
            if probe.is_down(controller.key):
                controller.on_hold()
        except Exception:  # noqa: BLE001 - a poll must not kill the loop
            pass

    return poll


def _parse_position(raw: str | None) -> tuple[int, int] | None:
    if not raw:
        return None
    try:
        x, y = (part.strip() for part in raw.split(","))
        return int(x), int(y)
    except Exception:
        raise click.ClickException(
            f"--position wants X,Y in pixels, for example 40,40 (got {raw!r})."
        ) from None


__all__ = ["bubble"]
