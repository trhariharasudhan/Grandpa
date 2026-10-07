"""``grandpa bubble`` -- the floating desktop assistant.

Blocks the terminal, because it owns the tkinter main loop. That is stated in the
help text rather than discovered: a command that silently never returns is
indistinguishable from a hang.
"""

from __future__ import annotations

import click

from grandpa.cli.safe_output import safe_cli_error


@click.command("bubble")
@click.option(
    "--key",
    default=None,
    show_default="f9",
    help="Key to hold while speaking. A printable key also types into whatever "
    "has focus; a modifier fires on ordinary shortcuts like Ctrl+C.",
)
@click.option("--device", type=int, default=None, help="Microphone input device index.")
@click.option("--model", default=None, help="Whisper model, e.g. small.en.")
@click.option(
    "--position",
    default=None,
    metavar="X,Y",
    help="Where to put the bubble. Overrides the remembered position.",
)
def bubble(
    key: str | None, device: int | None, model: str | None, position: str | None
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
    from grandpa.ui.bubble import DEFAULT_HOLD_KEY, BubbleController
    from grandpa.ui.tk_view import TkBubbleView
    from grandpa.voice.accuracy import quiet_model_downloads
    from grandpa.voice.config import load_voice_assistant_config
    from grandpa.voice.microphone import MicrophoneCapture
    from grandpa.voice.push_to_talk import (
        KEY_CODES,
        MAXIMUM_HOLD_SECONDS,
        WindowsKeyProbe,
        hold_to_talk_vad_config,
    )

    quiet_model_downloads()

    hold_key = (key or DEFAULT_HOLD_KEY).strip().lower()
    if hold_key not in KEY_CODES:
        raise click.ClickException(
            f"--key wants one of {', '.join(sorted(KEY_CODES))} (got {key!r})."
        )

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
        key=hold_key,
    )
    view.hold_key = hold_key
    view.on_submit = controller.submit
    # The other half of the fix. The view swallows the character so it cannot
    # land in the text box; this makes the press say so, because a key that
    # produced no character *and* no message is indistinguishable from a dead
    # key -- which is what was reported.
    view.on_hold_key = controller.note_key_seen
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
    """Start a hold when the key goes down, on the tk thread.

    This used to screen the press with ``can_record()`` and return quietly,
    which is why a held key produced nothing at all -- no indicator, no error,
    no recording. The controller's refusals each say why, and they only run if
    it is actually called, so the press is handed over and the decision is made
    where the explanation lives.

    Only the probe's absence is screened here, because there is nothing to poll
    without one.
    """

    def poll() -> None:
        probe = controller.probe
        if probe is None:
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
