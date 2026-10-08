"""``grandpa bubble`` -- the floating desktop assistant.

Blocks the terminal, because it owns the tkinter main loop. That is stated in the
help text rather than discovered: a command that silently never returns is
indistinguishable from a hang.
"""

from __future__ import annotations

import queue

import click

from grandpa.cli.safe_output import safe_cli_error

# Imported at module level, not inside the callback, because the option's
# show_default and the help text below are both built from it at import time. It
# costs nothing: bubble.py re-exports it from push_to_talk, and that chain is
# pure standard library.
from grandpa.ui.bubble import DEFAULT_HOLD_KEY
from grandpa.voice.push_to_talk import describe_hold_key

#: Built from the constant, because a docstring cannot interpolate one and the
#: literal that was there said "Hold SPACE" long after the default became f9.
#: ``--help`` is the first place a user looks for the key.
_HELP = f"""Show the floating assistant. Blocks this terminal until you close it.

A borderless always-on-top window with a held-key microphone, a live level
meter, a text box and a status line. Hold {describe_hold_key(DEFAULT_HOLD_KEY)}
anywhere to talk -- the key is read globally, so the bubble never needs focus and
never takes it. Esc closes it, as does Ctrl+C here.

While the key is held the meter shows what the microphone is picking up, so
"it is not hearing me" is distinguishable from "it heard me and got the words
wrong". Replies appear as text and are also read aloud; --no-speak starts muted,
the header toggles it while running, and holding the key cuts a reply off.

The model is loaded before the bubble reports itself ready; while it loads the
status says so and a hold is refused rather than recorded into nothing.
"""


@click.command("bubble", help=_HELP)
@click.option(
    "--key",
    default=None,
    show_default=DEFAULT_HOLD_KEY,
    help="Key or combination to hold while speaking, e.g. ctrl+win, f9, "
    "ctrl+shift. A printable key also types into whatever has focus, and a "
    "lone modifier fires on ordinary shortcuts like Ctrl+C -- which is why "
    "the default is a chord nothing else claims.",
)
@click.option("--device", type=int, default=None, help="Microphone input device index.")
@click.option("--model", default=None, help="Whisper model, e.g. small.en.")
@click.option(
    "--no-speak",
    is_flag=True,
    help="Show replies without speaking them. Replies are spoken by default; "
    "the toggle in the window turns it off while running, and holding the key "
    "interrupts a reply mid-sentence.",
)
@click.option(
    "--position",
    default=None,
    metavar="X,Y",
    help="Where to put the bubble. Overrides the remembered position.",
)
def bubble(
    key: str | None,
    device: int | None,
    model: str | None,
    no_speak: bool,
    position: str | None,
) -> None:
    """Show the floating assistant.

    The user-facing text is ``_HELP``, which names the hold key from
    ``DEFAULT_HOLD_KEY`` instead of repeating it. Click uses that, not this.
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
        parse_hold_key,
    )

    quiet_model_downloads()

    hold_key = (key or DEFAULT_HOLD_KEY).strip().lower()
    try:
        parse_hold_key(hold_key)
    except ValueError as exc:
        raise click.ClickException(f"--key: {exc}.") from exc

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
    bridge = InProcessBridge()
    view = TkBubbleView()
    controller = BubbleController(
        view=view,
        bridge=bridge,
        probe=WindowsKeyProbe(),
        capture=None,  # set below, once the controller exists to receive levels
        key=hold_key,
        speak_replies=not no_speak,
        speaker=None if no_speak else _bubble_speaker(),
    )
    # The level meter's seam. The callback goes on the recorder, which means
    # PushToTalkSession is untouched: it forwards only stop_event and never
    # needs to know a meter exists. The RMS handed over is the one the voice
    # detector already computes for every chunk, so this adds no arithmetic.
    capture = MicrophoneCapture(
        duration_seconds=MAXIMUM_HOLD_SECONDS,
        device=config.microphone if device is None else device,
        recovery_attempts=config.microphone_recovery_attempts,
        vad_config=hold_to_talk_vad_config(MAXIMUM_HOLD_SECONDS),
        on_level=controller.note_level,
    )
    controller.capture = capture

    # Updates cross threads from here on, so they are queued and applied by the
    # tk tick. tkinter may only be touched from the thread that owns the widgets.
    updates: queue.SimpleQueue = queue.SimpleQueue()
    controller.dispatch = updates.put

    view.hold_key = hold_key
    # Typed text goes to a worker too: routing calls the model and speaking the
    # reply both block, and on the tk thread that freezes the window.
    def submit_off_thread(text: str) -> None:
        _run_off_thread(controller, controller.submit, text)

    view.on_submit = submit_off_thread
    view.on_toggle_speech = lambda: view.set_speech_enabled(controller.toggle_speech())
    # The other half of the fix. The view swallows the character so it cannot
    # land in the text box; this makes the press say so, because a key that
    # produced no character *and* no message is indistinguishable from a dead
    # key -- which is what was reported.
    view.on_hold_key = controller.note_key_seen
    view.combo_is_down = lambda: bool(
        controller.probe is not None
        and controller.probe.is_down(controller.key)
    )
    view.on_close = lambda: (controller.stop(), None)[1]

    start_at = _parse_position(position)
    controller.start()
    if start_at is not None:
        controller.position = start_at
        view.show(position=start_at, topmost=True)

    click.echo("Bubble open. Hold the key to talk; Esc or Ctrl+C to close.")

    view.set_speech_enabled(controller.speak_replies)

    # Two ticks, deliberately at different rates. The key is polled often enough
    # to feel immediate; the meter is redrawn at about the rate chunks arrive
    # (one per 0.1s) and no faster, because redrawing between chunks would draw
    # the same 32 numbers again.
    view.pump(30, _hold_poller(controller))
    view.pump(60, _ui_tick(controller, updates))
    if view.root is not None:
        # Warming blocks for seconds, so it goes to a worker too -- on the tk
        # thread it froze the window for the whole model load.
        view.root.after(10, lambda: _run_off_thread(controller, controller.warm))
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
                # Off the tk thread: the hold blocks until the key is released,
                # and on this thread it froze the window -- which is why no
                # meter could have animated during a recording.
                _run_off_thread(controller, controller.on_hold)
        except Exception:  # noqa: BLE001 - a poll must not kill the loop
            pass

    return poll


def _run_off_thread(controller, work, *args):
    """Run *work* on a worker, one at a time. Returns the thread, or None.

    The flag is what stops a second hold starting while the first is still
    recording. The controller's own state checks refuse that too, but they are
    read and written on different threads, so a flag owned by the only thread
    that starts work is the part that cannot race.

    The thread is returned, and also left on the controller as
    ``_bubble_worker``, so a test can wait for the work instead of racing it.
    Nothing in the running command reads either.
    """
    import threading

    if getattr(controller, "_bubble_busy", False):
        return None
    controller._bubble_busy = True

    def run() -> None:
        try:
            work(*args)
        except Exception:  # noqa: BLE001 - a worker must not kill the process
            pass
        finally:
            controller._bubble_busy = False

    worker = threading.Thread(target=run, name="grandpa-bubble-work", daemon=True)
    controller._bubble_worker = worker
    worker.start()
    return worker


def _ui_tick(controller, updates):
    """Apply queued view updates and redraw the meter, on the tk thread."""

    def tick() -> None:
        while True:
            try:
                update = updates.get_nowait()
            except queue.Empty:
                break
            try:
                update()
            except Exception:  # noqa: BLE001 - one bad update must not stop the UI
                pass
        try:
            controller.refresh_meter()
        except Exception:  # noqa: BLE001
            pass

    return tick


def _bubble_speaker():
    """The TTS engine, with its engine list resolved once.

    ``SpeechOutputEngine.speak`` calls ``available_local_engines()`` on every
    call, and that costs ~2.25s on this machine -- not for kokoro, which fails
    its health check in 1.4ms, but for ``grandpa_voice``, whose health check
    takes 2248ms and then returns False. Paying that before every spoken reply
    is not acceptable, so the list is resolved once and pinned.
    """
    from grandpa.voice.speech_output import SpeechOutputEngine

    engine = SpeechOutputEngine()
    try:
        resolved = engine.available_local_engines()
    except Exception:  # noqa: BLE001 - a missing engine is not a failed bubble
        return engine
    engine.available_local_engines = lambda _resolved=resolved: _resolved
    return engine


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
