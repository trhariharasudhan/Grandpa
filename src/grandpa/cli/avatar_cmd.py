"""``grandpa avatar`` -- the Phase A presence window.

Blocks this terminal, because the window owns the UI loop. The tkinter bubble
is unchanged and still available as ``grandpa bubble``.
"""

from __future__ import annotations

import threading
import time

import click

from grandpa.cli.safe_output import safe_cli_error

_HELP = """Show Grandpa's avatar window. Blocks this terminal until you close it.

It opens as a small glowing ring that stays on top. Click the ring to open
the chat (the ring hides while it is open); the chat's ✕ closes it and the
ring comes back. Drag the ring, or the chat's top bar, to move it. "Open app"
starts the full desktop app as its own program: closing either one leaves the
other running. The
ring's colour shows what is happening: thinking, working (with the action's
name), done, error, or waiting for your yes/no. Risky actions still ask
first, exactly as in `grandpa bubble` and `grandpa voice`.

With --character, while Grandpa thinks, speaks, works or asks, the ring
turns into his 3D head (on hold for now; the ring alone is the default):
a built-in placeholder, or your own model from assets/avatar/grandpa.glb
(glTF 2.0, at most 30,000 triangles). The first line printed says which.
His face follows the state: he smiles while speaking, looks thoughtful while
thinking, and raises his brows when he asks you something.

Say "Hey Grandpa" and then what you want ("Hey Grandpa, open Notepad"
works in one breath too). The ring turns blue while he listens. The mic
button in the panel turns this on or off (remembered); --no-wake starts with
it off. Without a trained wake model it reads only the moments someone
speaks, with a small local Whisper; nothing is saved or sent anywhere.

Hold Ctrl+Win anywhere, speak, and let go: Grandpa answers as if you had
typed it (--hold-key picks other keys). Right-clicking the ring listens for
one sentence. --no-mic turns talking off.

A tray icon (next to the clock) shows or hides the window and quits it.
--no-tray leaves it out.

To keep the PC fast while Ollama works, the window stays within 20% of the
GPU and 300 MB of RAM. If it stays over for 30 seconds, Grandpa shows only
his ring for the rest of the run, and so does the page by itself if its
frames get slow. --orb-only starts that way; --no-budget turns the check
off; --perf-log prints the window's use every 10 seconds.

Grandpa says each reply aloud (pyttsx3) and his mouth moves with the words.
--quiet keeps him silent; so does tts.enabled = false in your config.

--no-window starts only the local connection and prints an address to open in
a browser, which is useful when the window will not open.
"""

TALK_SECONDS = 10.0
"""Longest a click-to-talk recording runs; it usually ends at the first pause."""


SERVER_START_TIMEOUT_S = 20.0
"""A slow, busy laptop (Ollama loading, antivirus scanning) can take longer than 5 s."""


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


class HoldToTalk:
    """Hold Ctrl+Win (anywhere on Windows), speak, release: Grandpa hears it.

    The key is read with ``GetAsyncKeyState`` (read-only; nothing is typed or
    sent), exactly like ``grandpa bubble``. While it is held the microphone
    records with no voice detection at all -- the keys say when speech starts
    and ends -- and on release the words go through the controller like a
    typed line, so a spoken request meets the same confirmations.
    """

    def __init__(
        self, controller, bridge, *, key=None, probe=None, capture_factory=None
    ):
        from grandpa.voice.push_to_talk import DEFAULT_HOLD_KEY

        self.controller = controller
        self.bridge = bridge
        self.key = key or DEFAULT_HOLD_KEY
        self.probe = probe
        self.capture_factory = capture_factory or self._capture
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @staticmethod
    def _capture():
        from grandpa.voice.config import load_voice_assistant_config
        from grandpa.voice.microphone import MicrophoneCapture
        from grandpa.voice.push_to_talk import (
            MAXIMUM_HOLD_SECONDS,
            hold_to_talk_vad_config,
        )

        config = load_voice_assistant_config(tts_enabled=False)
        return MicrophoneCapture(
            duration_seconds=MAXIMUM_HOLD_SECONDS,
            device=config.microphone,
            recovery_attempts=config.microphone_recovery_attempts,
            vad_config=hold_to_talk_vad_config(),
        )

    def start(self) -> bool:
        if self.probe is None:
            from grandpa.voice.push_to_talk import WindowsKeyProbe

            if not WindowsKeyProbe.available():
                return False
            self.probe = WindowsKeyProbe()
        self._thread = threading.Thread(
            target=self._run, name="grandpa-orb-hold-to-talk", daemon=True
        )
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()

    def _session(self, capture):
        from grandpa.voice.push_to_talk import PushToTalkSession

        return PushToTalkSession(
            capture=capture,
            transcriber=None,  # the bridge transcribes, as for click-to-talk
            probe=self.probe,
            key=self.key,
            echo=lambda _m: None,
            on_idle=self._stop.is_set,
        )

    def listen_while_held(self) -> str | None:
        capture = self.capture_factory()
        try:
            audio, held, _reason = self._session(capture).record_while_held()
        finally:
            close = getattr(capture, "close", None)
            if callable(close):
                close()
        if held < 0.4 or not getattr(audio, "captured_frame_count", 1):
            return None  # a tap (or Ctrl+Win for something else), not an utterance
        return self.bridge.transcribe(audio)

    def _run(self) -> None:
        waiter = self._session(None)
        while not self._stop.is_set():
            if not waiter.wait_for_press():
                return
            self.controller.talk(self.listen_while_held)
            # Busy (a reply in flight) or done: wait for the keys to come up
            # before listening again, so one hold is one utterance.
            while self.probe.is_down(self.key) and not self._stop.is_set():
                time.sleep(0.05)


def budget_watch(controller, echo, *, perf_log=False, fall_back=True, sample=None):
    """A7: watch the window's GPU and RAM; over budget, show only the ring."""
    from grandpa.ui.avatar_budget import BudgetWatch, sample_window

    def on_over(reasons):
        reason = "; ".join(reasons)
        if fall_back and controller.ring_only(reason):
            echo(f"Over budget ({reason}): showing only the ring from now on.")

    def on_sample(reading):
        if perf_log:
            echo(reading.describe())

    return BudgetWatch(
        sample or sample_window,
        on_over if fall_back else (lambda _reasons: None),
        on_sample=on_sample,
    )


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
@click.option(
    "--no-mic", is_flag=True, help="Turn talking off (hold-to-talk and click-to-talk)."
)
@click.option(
    "--hold-key",
    default=None,
    help="Keys to hold while speaking (default ctrl+win; e.g. f8, menu).",
)
@click.option(
    "--no-wake",
    is_flag=True,
    help='Do not listen for "Hey Grandpa" (the mic button in the panel turns it on/off too).',
)
@click.option("--no-tray", is_flag=True, help="Do not show the tray icon.")
@click.option(
    "--orb-only",
    is_flag=True,
    help="Show only the ring (the default while the 3D character is on hold).",
)
@click.option(
    "--character",
    is_flag=True,
    help="Also show the 3D character while Grandpa works (on hold; experimental).",
)
@click.option(
    "--no-budget",
    is_flag=True,
    help="Do not fall back to the ring when over the GPU/RAM budget.",
)
@click.option(
    "--perf-log",
    is_flag=True,
    help="Print the window's RAM and GPU use every 10 seconds.",
)
def avatar(
    no_window: bool,
    not_on_top: bool,
    debug: bool,
    quiet: bool,
    no_mic: bool,
    hold_key: str | None,
    no_wake: bool,
    no_tray: bool,
    orb_only: bool,
    character: bool,
    no_budget: bool,
    perf_log: bool,
) -> None:
    from grandpa.app.launch import claim, release
    from grandpa.ui.avatar_character import load_character
    from grandpa.ui.bridge import InProcessBridge
    from grandpa.ui.lipsync import default_speaker

    if not no_window and not claim("avatar"):
        click.echo("Grandpa's orb is already on screen.")
        return
    orb_only = orb_only or not character
    bridge = InProcessBridge()
    listener = None if no_mic else microphone_listener(bridge)
    # The voices are chosen after the server is up: loading them (the MMS Tamil
    # model holds Python's lock for ~5 s) used to starve the server's start.
    controller, server = build(bridge=bridge, speaker=None, listener=listener)

    if orb_only:
        controller.ring_only("--orb-only", announce=False)
        click.echo("Character: off; the ring only (--character turns it on).")
    else:
        server.character, report = load_character()
        click.echo(report.describe())
    try:
        server.start(timeout=SERVER_START_TIMEOUT_S)
    except RuntimeError as exc:
        safe_cli_error(str(exc))
        raise SystemExit(1) from None
    if quiet:
        voice_line = "Voice: off (--quiet)."
    else:
        controller.speaker, voice_line = default_speaker()
    click.echo(voice_line)
    hold = None
    if no_mic:
        click.echo("Talk: off (--no-mic).")
    else:
        from grandpa.voice.push_to_talk import describe_hold_key, parse_hold_key

        try:
            if hold_key:
                parse_hold_key(hold_key)
        except ValueError as exc:
            raise click.BadParameter(str(exc), param_hint="--hold-key") from None
        hold = HoldToTalk(controller, bridge, key=hold_key)
        if hold.start():
            click.echo(f"Talk: hold {describe_hold_key(hold.key)}, speak, release.")
        else:
            hold = None
            click.echo("Talk: right-click the ring (hold-to-talk needs Windows).")
    wake = None
    if not no_mic:
        from grandpa.ui.wake_talk import WakeToTalk, load_wake_enabled

        wake = WakeToTalk(
            controller,
            bridge,
            microphone_listener(bridge),
            enabled=False if no_wake else load_wake_enabled(),
        )
        if not wake.enabled:
            click.echo('Wake: off (turn on with the mic button in the panel).')
        elif wake.start():
            click.echo(f'Wake: say "Hey Grandpa" ({wake.label}).')
        else:
            click.echo(f"Wake: not available ({wake.error}).")
    controller.watch_actions()
    watch = None

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

            if not no_budget or perf_log:
                watch = budget_watch(
                    controller, click.echo, perf_log=perf_log, fall_back=not no_budget
                )
                watch.start()
                click.echo(
                    "Budget: off (--no-budget)."
                    if no_budget
                    else f"Budget: ring only if the window stays over "
                    f"{watch.budget.gpu_pct:.0f}% GPU or {watch.budget.ram_mb:.0f} MB."
                )
            try:
                run_window(
                    server.url,
                    on_top=not not_on_top,
                    debug=debug,
                    tray=not no_tray,
                    echo=click.echo,
                    wake=wake,
                )
            except RuntimeError as exc:
                safe_cli_error(str(exc))
                raise SystemExit(1) from None
    finally:
        if watch is not None:
            watch.stop()
        controller.unwatch_actions()
        if hold is not None:
            hold.stop()
        if wake is not None:
            wake.stop()
        server.stop()
        if not no_window:
            release("avatar")


__all__ = ["TALK_SECONDS", "avatar", "budget_watch", "build", "microphone_listener"]
