"""``grandpa avatar`` -- the Phase A presence window (A1: window + live states).

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

Grandpa says each reply aloud (pyttsx3) and his mouth moves with the words.
--quiet keeps him silent; so does tts.enabled = false in your config.

--no-window starts only the local connection and prints an address to open in
a browser, which is useful when the window will not open.
"""


def build(bridge=None, speaker=None):
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
        bridge=bridge or InProcessBridge(), publish=publish, speaker=speaker
    )
    server = AvatarServer(on_send=controller.submit, snapshot=controller.snapshot)
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
def avatar(no_window: bool, not_on_top: bool, debug: bool, quiet: bool) -> None:
    from grandpa.ui.avatar_character import load_character
    from grandpa.ui.lipsync import default_speaker

    if quiet:
        speaker, voice_line = None, "Voice: off (--quiet)."
    else:
        speaker, voice_line = default_speaker()
    controller, server = build(speaker=speaker)

    server.character, report = load_character()
    click.echo(report.describe())
    click.echo(voice_line)
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
                )
            except RuntimeError as exc:
                safe_cli_error(str(exc))
                raise SystemExit(1) from None
    finally:
        controller.unwatch_actions()
        server.stop()


__all__ = ["avatar", "build"]
