"""``grandpa avatar`` -- the Phase A presence window.

Blocks this terminal, because the window owns the UI loop. The tkinter bubble
is unchanged and still available as ``grandpa bubble``.
"""

from __future__ import annotations

import threading

import click

from grandpa.cli.safe_output import safe_cli_error

_HELP = """Show Grandpa's avatar window. Blocks this terminal until you close it.

It opens as a small glowing ring that stays on top. Click the ring to open
the chat panel, click it again to close it; drag the ring to move it. The
ring's colour shows what is happening: thinking, working (with the action's
name), done, error, or waiting for your yes/no. Risky actions still ask
first, exactly as in `grandpa bubble` and `grandpa voice`.

While Grandpa thinks, speaks, works or asks, the ring turns into his 3D head:
a built-in placeholder, or your own model from assets/avatar/grandpa.glb
(glTF 2.0, at most 30,000 triangles). The first line printed says which.
His face follows the state: he smiles while speaking, looks thoughtful while
thinking, and raises his brows when he asks you something.

Click Talk in the chat panel and say one sentence: Grandpa listens until you
stop, then answers as if you had typed it. --no-mic turns Talk off.

A tray icon (next to the clock) shows or hides the window and quits it.
--no-tray leaves it out.

Grandpa says each reply aloud (pyttsx3) and his mouth moves with the words.
--quiet keeps him silent; so does tts.enabled = false in your config.

--no-window starts only the local connection and prints an address to open in
a browser, which is useful when the window will not open.
"""

TALK_SECONDS = 10.0
"""Longest a click-to-talk recording runs; it usually ends at the first pause."""


def microphone_listener(bridge, *, device=None, capture_factory=None):
    """Click-to-talk's listener: record one line, transcribe it with ``bridge``.

    The microphone is opened for one sentence and closed again; it ends at the
    first pause (the voice config's silence timeout) or after
    :data:`TALK_SECONDS`. The words come from ``bridge.transcribe``, the same
    trusted path the bubble uses, and are then routed like typed text.
    """

    def _capture():
        from grandpa.voice.config import load_voice_assistant_config
        from grandpa.voice.microphone import MicrophoneCapture
        from grandpa.voice.vad import VoiceActivityConfig

        config = load_voice_assistant_config(microphone=device, tts_enabled=False)
        return MicrophoneCapture(
            duration_seconds=TALK_SECONDS,
            device=config.microphone,
            recovery_attempts=config.microphone_recovery_attempts,
            vad_config=VoiceActivityConfig(
                minimum_rms=config.speech_start_rms,
                minimum_speech_seconds=config.minimum_speech_seconds,
                silence_seconds=config.silence_timeout_seconds,
                maximum_utterance_seconds=TALK_SECONDS,
            ),
        )

    factory = capture_factory or _capture

    def listen():
        capture = factory()
        try:
            audio = capture.capture()
        finally:
            close = getattr(capture, "close", None)
            if callable(close):
                close()
        if not getattr(audio, "speech_detected", True):
            return ""
        return bridge.transcribe(audio)

    return listen


def build(bridge=None, speaker=None, listener=None):
    """The controller and server, wired together. Separate for tests."""
    from grandpa.ui.avatar_controller import AvatarController
    from grandpa.ui.avatar_server import AvatarServer
    from grandpa.ui.bridge import InProcessBridge

    holder: dict = {}

    def publish(message) -> None:
        server = holder.get("server")
        if server is not None:
            server.broadcast(message)

    controller = AvatarController(
        bridge=bridge or InProcessBridge(),
        publish=publish,
        speaker=speaker,
        listener=listener,
    )
    server = AvatarServer(
        on_send=controller.submit,
        on_talk=controller.talk,
        snapshot=controller.snapshot,
    )
    holder["server"] = server
    return controller, server


@click.command("avatar", help=_HELP)
@click.option(
    "--no-window",
    is_flag=True,
    help="Do not open the desktop window; print an address to open in a browser.",
)
@click.option("--not-on-top", is_flag=True, help="Let other windows cover it.")
@click.option("--debug", is_flag=True, help="Open the web inspector with the window.")
@click.option("--quiet", is_flag=True, help="Do not say replies aloud.")
@click.option("--no-mic", is_flag=True, help="Turn click-to-talk off.")
@click.option("--no-tray", is_flag=True, help="Do not show the tray icon.")
def avatar(
    no_window: bool,
    not_on_top: bool,
    debug: bool,
    quiet: bool,
    no_mic: bool,
    no_tray: bool,
) -> None:
    from grandpa.ui.avatar_character import load_character
    from grandpa.ui.bridge import InProcessBridge
    from grandpa.ui.lipsync import default_speaker

    if quiet:
        speaker, voice_line = None, "Voice: off (--quiet)."
    else:
        speaker, voice_line = default_speaker()
    bridge = InProcessBridge()
    listener = None if no_mic else microphone_listener(bridge)
    controller, server = build(bridge=bridge, speaker=speaker, listener=listener)

    server.character, report = load_character()
    click.echo(report.describe())
    click.echo(voice_line)
    click.echo(
        "Talk: off (--no-mic)." if no_mic else "Talk: click Talk in the chat panel."
    )
    try:
        server.start()
    except RuntimeError as exc:
        safe_cli_error(str(exc))
        raise SystemExit(1) from None
    controller.watch_actions()

    try:
        if no_window:
            from grandpa.ui.avatar_window import browser_address, serve_page

            page, port = serve_page()
            click.echo("Grandpa avatar is running. Open this address in your browser:")
            click.echo(browser_address(server.url, port))
            click.echo("Press Ctrl+C here to stop.")
            try:
                threading.Event().wait()
            except KeyboardInterrupt:
                pass
            finally:
                page.shutdown()
        else:
            from grandpa.ui.avatar_window import run_window

            try:
                run_window(
                    server.url,
                    on_top=not not_on_top,
                    debug=debug,
                    tray=not no_tray,
                    echo=click.echo,
                )
            except RuntimeError as exc:
                safe_cli_error(str(exc))
                raise SystemExit(1) from None
    finally:
        controller.unwatch_actions()
        server.stop()


__all__ = ["TALK_SECONDS", "avatar", "build", "microphone_listener"]
