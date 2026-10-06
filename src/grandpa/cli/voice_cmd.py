"""Voice assistant and diagnostics CLI commands."""

from __future__ import annotations

import functools
import tempfile
import time
from pathlib import Path

import click

from grandpa.cli.safe_output import safe_cli_error
from grandpa.jarvis.voice_input import save_preferred_microphone_name
from grandpa.voice.audio_diagnostics import (
    analyze_pcm16_wav,
    compare_audio,
    play_wav_bytes,
)
from grandpa.voice.cli_session import build_voice_session
from grandpa.voice.config import load_voice_assistant_config
from grandpa.voice.device_manager import (
    MicrophoneDeviceManager,
    import_sounddevice,
)
from grandpa.voice.diagnostics import (
    list_input_devices,
    log_voice_initialization_error,
    run_voice_doctor,
)
from grandpa.voice.errors import VoiceError, VoiceOutputUnavailableError
from grandpa.voice.microphone import MicrophoneCapture
from grandpa.voice.push_to_talk import (
    KEY_CODES,
    MAXIMUM_HOLD_SECONDS,
    PushToTalkSession,
    WindowsKeyProbe,
    hold_to_talk_vad_config,
)
from grandpa.voice.speech_output import SpeechOutputEngine
from grandpa.voice.speech_to_text import FasterWhisperSpeechToText
from grandpa.voice.text_to_speech import list_system_voices
from grandpa.voice.vad import VoiceActivityConfig


def handles_voice_errors(command):
    """Turn an expected voice failure into a sentence and exit 1.

    Every expected failure in this module is a ``VoiceError`` subclass, and
    seven of the eleven entry points let one escape to a traceback. Measured by
    driving each command with its helper patched to raise:

        voice doctor            TRACEBACK
        voice diagnose          TRACEBACK
        voice test              TRACEBACK
        voice set-device        TRACEBACK
        voice microphone-test   TRACEBACK
        voice push-to-talk      TRACEBACK
        voice --list-voices     TRACEBACK
        voice --diagnose        TRACEBACK
        voice devices           handled, but exit 0
        voice --list-microphones handled, but exit 0
        voice (group)           handled

    Two of those -- ``set-device`` and ``microphone-test`` -- do have an
    ``except VoiceError``; they call ``import_sounddevice()`` on the line
    *before* the ``try``, which is outside it. A decorator is used rather than
    eleven more try blocks precisely because the placement is what went wrong.

    A stack trace is not a user-facing error message: it buries the one
    sentence that matters and reads as a crash in Grandpa rather than something
    the user can fix.
    """

    @functools.wraps(command)
    def wrapper(*args, **kwargs):
        try:
            return command(*args, **kwargs)
        except VoiceError as exc:
            safe_cli_error(str(exc))
            if getattr(exc, "detail", None):
                safe_cli_error(f"Detail: {exc.detail}")
            raise SystemExit(1) from None

    return wrapper


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
@click.option(
    "--screen-reader",
    is_flag=True,
    default=False,
    help="Enable screen-reader friendly output.",
)
@click.pass_context
@handles_voice_errors
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
    screen_reader: bool,
) -> None:
    """Start Grandpa's offline-first voice assistant or run voice diagnostics.

    New here? Use `grandpa voice push-to-talk` instead. Hold SPACE, speak,
    release: you decide when the utterance begins and ends, so there is no
    speech detection to get wrong.

    This command is hands-free and has to detect speech itself, from the audio
    level against a threshold derived from a noise floor it estimates as it
    goes. If it answers "I could not understand" on speech you know was clear,
    try push-to-talk on the same microphone -- if that works, the audio is fine
    and the detection is at fault.
    """

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
            quiet=ctx.obj.get("quiet", False) if ctx.obj else False,
            verbose=ctx.obj.get("verbose", False) if ctx.obj else False,
            screen_reader=screen_reader,
        )
        raise SystemExit(session.run())
    except VoiceError as exc:
        safe_cli_error(str(exc))
        raise SystemExit(1) from None
    except Exception as exc:
        log_path = log_voice_initialization_error(exc)
        safe_cli_error(f"Voice mode could not initialize: {type(exc).__name__}: {exc}")
        safe_cli_error(f"Technical details were written to: {log_path}")
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
@handles_voice_errors
def doctor(device: int | None, duration: float) -> None:
    """Run bounded microphone, STT, and TTS readiness checks."""

    _print_diagnostics(
        run_voice_doctor(device=device, duration_seconds=max(0.0, duration))
    )


@voice.command("diagnose")
@click.option("--device", type=int, default=None, help="Input device index to inspect.")
@handles_voice_errors
def diagnose_voice(device: int | None) -> None:
    """Show voice runtime and device diagnostics without recording."""

    _print_diagnostics(run_voice_doctor(device=device, duration_seconds=0))


def _print_diagnostics(checks: list[dict]) -> None:
    for check in checks:
        click.echo(f"{check['status'].upper():4} {check['name']}: {check['message']}")


@voice.command("test")
@click.option("--dry-run", is_flag=True, help="Validate TTS without speaking.")
@handles_voice_errors
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
@handles_voice_errors
def devices() -> None:
    _print_microphones()


@voice.command("microphone-test")
@click.option("--device", type=int, default=None, help="Input device index to test.")
@click.option("--device-name", default=None, help="Stable input device name to test.")
@click.option(
    "--sentence",
    default="Hello Grandpa. This is a microphone speech recognition test.",
    show_default=True,
    help="Exact supervised sentence to display for the microphone test.",
)
@click.option(
    "--no-playback",
    is_flag=True,
    help="Skip capture playback for automated/non-interactive diagnostics.",
)
@handles_voice_errors
def microphone_test(
    device: int | None,
    device_name: str | None,
    sentence: str,
    no_playback: bool,
) -> None:
    """Record, replay, compare, and transcribe one supervised phrase."""

    config = load_voice_assistant_config(microphone=device)
    manager = MicrophoneDeviceManager(import_sounddevice())
    try:
        selection = manager.select(
            requested_index=device,
            requested_name=device_name,
            allow_fallback=device is None,
        )
    except VoiceError as exc:
        replacement = (
            manager.replacement_for_stale_index(device) if device is not None else None
        )
        if replacement is None:
            safe_cli_error(str(exc))
            raise SystemExit(1) from None
        click.echo(f"Requested microphone device {device} is no longer available.")
        click.echo(
            f"Current matching microphone: {replacement.index} - {replacement.name} "
            f"- {replacement.driver or 'unknown'}"
        )
        if not click.confirm("Retry with the current device?", default=True):
            click.echo("Microphone test cancelled.")
            return
        selection = manager.select(requested_index=replacement.index)
    device = selection.device.index
    device_name = None
    click.echo("Supervised microphone acceptance test")
    click.echo(f'Say: "{sentence}"')
    if not click.confirm("Ready to record?", default=True):
        click.echo("Microphone test cancelled.")
        return
    for remaining in (3, 2, 1):
        click.echo(f"Recording in {remaining}...")
        time.sleep(1)
    click.echo("Listening...")

    maximum_seconds = max(8.0, min(15.0, config.phrase_duration_limit))
    capture = MicrophoneCapture(
        duration_seconds=maximum_seconds,
        device=device,
        device_name=device_name,
        recovery_attempts=config.microphone_recovery_attempts,
        vad_config=VoiceActivityConfig(
            minimum_rms=config.speech_start_rms,
            minimum_speech_seconds=config.minimum_speech_seconds,
            silence_seconds=config.silence_timeout_seconds,
            maximum_utterance_seconds=maximum_seconds,
        ),
        device_manager=manager,
    )
    temporary_path: Path | None = None
    try:
        audio = capture.capture()
        with tempfile.NamedTemporaryFile(
            prefix="grandpa-microphone-test-", suffix=".wav", delete=False
        ) as temporary:
            temporary.write(audio.data)
            temporary_path = Path(temporary.name)

        live_metrics = analyze_pcm16_wav(audio.data)
        reference_path = (
            Path(__file__).resolve().parents[3]
            / "voice_runtime"
            / "references"
            / "hari_reference.wav"
        )
        reference_metrics = (
            analyze_pcm16_wav(reference_path.read_bytes())
            if reference_path.exists()
            else None
        )
        _print_capture_metrics(capture, audio, live_metrics)
        if reference_metrics is not None:
            click.echo("Live vs known-good reference:")
            for name, value in compare_audio(live_metrics, reference_metrics).items():
                click.echo(f"  {name}: {value:.3f}")

        if not no_playback:
            click.echo("Playing the captured phrase now...")
            play_wav_bytes(audio.data)
            clear = click.confirm("Did the recording sound clear?", default=False)
            click.echo(f"Human playback assessment: {'clear' if clear else 'unclear'}")

        click.echo("Transcribing with Grandpa's production STT path...")
        transcriber = FasterWhisperSpeechToText(
            language=config.language,
            model=config.stt_model,
            device=config.device,
            compute_type=config.compute_type,
        )
        started = time.perf_counter()
        production_error: VoiceError | None = None
        try:
            transcript = transcriber.transcribe(audio)
        except VoiceError as exc:
            transcript = ""
            production_error = exc
        production_diagnostics = transcriber.backend_diagnostics
        click.echo(f"Production transcript: {transcript or '<no transcript>'}")
        click.echo(f"STT latency: {time.perf_counter() - started:.3f}s")
        if production_error is not None:
            click.echo(f"Production STT error: {production_error}")
        elif transcriber.last_result is not None:
            click.echo(
                f"Detected language: {transcriber.last_result.language or 'unknown'}"
            )
        direct_transcript = transcriber.transcribe_file(temporary_path)
        direct_diagnostics = transcriber.backend_diagnostics
        click.echo(f"Direct same-WAV transcript: {direct_transcript}")
        click.echo(
            "Captured bytes identical to diagnostic WAV: "
            f"{audio.data == temporary_path.read_bytes()}"
        )
        _print_stt_diagnostics("Production", production_diagnostics)
        _print_stt_diagnostics("Direct same-WAV", direct_diagnostics)
    except VoiceError as exc:
        safe_cli_error(str(exc))
        raise SystemExit(1) from None
    finally:
        capture.close()
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _print_capture_metrics(capture, audio, metrics) -> None:
    selected = capture.last_device
    click.echo(
        "Selected microphone: "
        + (
            f"{selected.index}: {selected.name} ({selected.driver or 'unknown'})"
            if selected is not None
            else "unknown"
        )
    )
    click.echo(
        "Capture format: "
        f"{getattr(audio, 'capture_sample_rate', metrics.sample_rate)} Hz, "
        f"{getattr(audio, 'capture_channels', metrics.channels)} channel(s) "
        f"-> {metrics.sample_rate} Hz mono PCM16"
    )
    for name, value in metrics.to_dict().items():
        click.echo(f"  {name}: {value}")
    click.echo("Speech timing:")
    click.echo("  recording_start: 0.000s")
    click.echo(f"  speech_onset: {_seconds(audio.speech_onset_seconds)}")
    click.echo(f"  speech_active: {audio.speech_active_seconds:.3f}s")
    click.echo(f"  trailing_silence: {audio.trailing_silence_seconds:.3f}s")
    click.echo(f"  phrase_finalization: {audio.finalization_reason}")
    click.echo(f"  final_capture_duration: {metrics.duration_seconds:.3f}s")


def _print_stt_diagnostics(label, diagnostics) -> None:
    if diagnostics is None:
        return
    click.echo(f"{label} STT configuration:")
    click.echo(f"  model: {diagnostics.model}")
    click.echo(f"  decoded_duration: {diagnostics.decoded_duration_seconds:.3f}s")
    click.echo(f"  language: {diagnostics.language or 'unknown'}")
    for name, value in diagnostics.options.items():
        click.echo(f"  {name}: {value}")
    # Why the transcript was empty, when it was. Without this an empty result is
    # indistinguishable from the several different things that cause one, and
    # the only trace was a logger.info with no file handler unless --verbose --
    # so a live failure left nothing to read.
    empty_reason = getattr(diagnostics, "empty_reason", "") or ""
    if empty_reason:
        click.echo(f"  empty_reason: {empty_reason}")
        click.echo(
            f"  segments_dropped_by_confidence_filter: "
            f"{getattr(diagnostics, 'segments_dropped', 0)}"
        )
    for index, segment in enumerate(diagnostics.segments, start=1):
        # The cutoffs this is compared against, beside the number, because 0.45
        # is stricter than the 0.5 passed to Whisper itself: a segment Whisper
        # kept can still be dropped here.
        no_speech = segment["no_speech_probability"]
        dropped = isinstance(no_speech, (int, float)) and no_speech > 0.45
        click.echo(
            f"  segment {index}: {segment['start']:.3f}-{segment['end']:.3f}s "
            f"{segment['text']!r}; no_speech={no_speech}"
            f"{' DROPPED (> 0.45)' if dropped else ''}"
        )


def _seconds(value: float | None) -> str:
    return "not detected" if value is None else f"{value:.3f}s"


def _print_microphones() -> None:
    found = list_input_devices()
    if not found:
        click.echo("No input devices found.")
        return
    click.echo("INDEX | NAME | HOST API | INPUT CHANNELS | DEFAULT RATE | DEFAULT?")
    for device in found:
        marker = " *default*" if device.default else ""
        click.echo(
            f"{device.index} | {device.name} | "
            f"{getattr(device, 'driver', '') or 'unknown'} | "
            f"{device.input_channels} | "
            f"{getattr(device, 'default_sample_rate', getattr(device, 'sample_rate', 16_000))} Hz | "
            f"{'yes' if marker else 'no'}"
        )


def _print_voices() -> None:
    voices = list_system_voices()
    if not voices:
        click.echo(
            "No local TTS voices found. On Windows, pyttsx3 uses installed SAPI voices."
        )
        return
    for voice_name in voices:
        click.echo(voice_name)


@voice.command("push-to-talk")
@click.option("--key", type=click.Choice(sorted(KEY_CODES)), default="space",
              help="Key to hold while speaking.")
@click.option("--device", type=int, default=None, help="Microphone input device index.")
@click.option("--no-tts", is_flag=True, help="Print responses instead of speaking.")
@click.option("--once", is_flag=True, help="Handle one utterance and exit.")
@click.option("--no-route", is_flag=True,
              help="Print the transcript only. Do not act on it.")
@click.option("--model", default=None, help="Whisper model name, e.g. base.en.")
@click.option("--language", default=None, help="Recognition language code, e.g. en.")
@handles_voice_errors
def push_to_talk(
    key: str,
    device: int | None,
    no_tts: bool,
    once: bool,
    no_route: bool,
    model: str | None,
    language: str | None,
) -> None:
    """Record while a key is held. No voice activity detection.

    The adaptive detector decides for itself when speech starts, from a
    threshold it derives from a noise floor it estimates as it goes. This
    command removes that decision: the key down is the start, the key up is the
    end, and every frame in between is kept.
    """

    if not WindowsKeyProbe.available():
        safe_cli_error(
            "Push-to-talk needs the Windows keyboard API (user32), which is not "
            "available here. 'grandpa voice' uses automatic speech detection "
            "instead."
        )
        raise SystemExit(1)

    config = load_voice_assistant_config(
        model=model, language=language, microphone=device, tts_enabled=not no_tts
    )
    capture = MicrophoneCapture(
        duration_seconds=MAXIMUM_HOLD_SECONDS,
        device=config.microphone if device is None else device,
        recovery_attempts=config.microphone_recovery_attempts,
        vad_config=hold_to_talk_vad_config(MAXIMUM_HOLD_SECONDS),
    )
    transcriber = FasterWhisperSpeechToText(
        language=config.language,
        model=config.stt_model,
        device=config.device,
        compute_type=config.compute_type,
    )

    responder = None
    speaker = None
    if not no_route:
        from grandpa.voice.assistant import VoiceCommandProcessor

        responder = VoiceCommandProcessor(model_name=None)
        if not no_tts:
            try:
                speaker = SpeechOutputEngine()
            except VoiceOutputUnavailableError as exc:
                click.echo(f"Speech output unavailable, printing instead: {exc}")

    session = PushToTalkSession(
        capture=capture,
        transcriber=transcriber,
        probe=WindowsKeyProbe(),
        key=key,
        responder=responder,
        speaker=speaker,
        echo=click.echo,
        on_idle=_console_idle_check,
    )
    click.echo(f"Push-to-talk ready on device {capture.device}.")
    try:
        session.run(once=once)
    except KeyboardInterrupt:
        click.echo("")
    finally:
        capture.close()


def _console_idle_check() -> bool:
    """Drain whatever the held key typed, and report Esc as a request to stop.

    Holding a printable key in a terminal also fills the console input buffer
    with it. Draining here keeps the prompt clean and gives Esc somewhere to be
    noticed. Absent a console -- a pipe, a test -- there is nothing to drain and
    nothing to stop for.
    """

    try:
        import msvcrt
    except ImportError:
        return False
    stop = False
    try:
        while msvcrt.kbhit():
            if msvcrt.getwch() == "\x1b":
                stop = True
    except Exception:
        return False
    return stop


@voice.command("set-device")
@click.argument("name")
@handles_voice_errors
def set_device(name: str) -> None:
    """Save the preferred microphone by name."""

    requested = name.strip()
    if not requested:
        raise click.ClickException("Microphone name cannot be empty.")
    manager = MicrophoneDeviceManager(import_sounddevice())
    try:
        selected = manager.select(requested_name=requested, allow_fallback=False).device
    except VoiceError as exc:
        safe_cli_error(str(exc))
        raise SystemExit(1) from None
    saved = save_preferred_microphone_name(
        selected.name,
        host_api=selected.driver,
        input_channels=selected.input_channels,
        sample_rate=selected.default_sample_rate,
    )
    click.echo(f"Saved preferred microphone: {saved}")


__all__ = ["voice"]
