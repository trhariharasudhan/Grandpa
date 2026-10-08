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
    DEFAULT_HOLD_KEY,
    MAXIMUM_HOLD_SECONDS,
    PushToTalkSession,
    WindowsKeyProbe,
    hold_to_talk_vad_config,
)
from grandpa.voice.speech_output import SpeechOutputEngine
from grandpa.voice.speech_to_text import FasterWhisperSpeechToText
from grandpa.voice.text_to_speech import list_system_voices
from grandpa.voice.vad import VoiceActivityConfig


def _hold_key_option(ctx, param, value):  # noqa: ANN001 - click callback
    """Validate ``--key``, which may name a combination like ``ctrl+win``.

    ``click.Choice`` was right while a hold was one key and wrong the moment it
    could be a chord: ``ctrl+win`` is not a member of ``KEY_CODES``, it is built
    from two of them.
    """
    from grandpa.voice.push_to_talk import parse_hold_key

    raw = (value or "").strip().lower()
    try:
        parse_hold_key(raw)
    except ValueError as exc:
        raise click.BadParameter(str(exc)) from exc
    return raw


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


@voice.command("accuracy-test")
@click.option("--key", default=DEFAULT_HOLD_KEY, show_default=True,
              callback=_hold_key_option,
              help="Key or combination to hold while reading each phrase.")
@click.option("--device", type=int, default=None, help="Microphone input device index.")
@click.option("--model", default=None, help="Whisper model to score, e.g. small.en.")
@click.option("--language", default=None, help="Recognition language code.")
@click.option("--phrases", type=click.Path(exists=True, dir_okay=False), default=None,
              help="File of phrases, one per line, instead of the fixed ten.")
@click.option("--count", type=int, default=3, show_default=True,
              help="How many phrases to score. 0 scores the whole list.")
@click.option("--json", "as_json", is_flag=True,
              help="Print the report as JSON for comparing runs.")
@handles_voice_errors
def accuracy_test(
    key: str,
    device: int | None,
    model: str | None,
    language: str | None,
    phrases: str | None,
    count: int | None,
    as_json: bool,
) -> None:
    """Read phrases aloud and get a word error rate.

    Shows a phrase, you hold the key and read it, and it scores what came back
    against what it asked for. Run it before and after a change and the two
    numbers are comparable, which an impression of how it sounded is not.

    Uses the push-to-talk capture path, so the recording is bounded by the key
    rather than by speech detection -- a detection failure would otherwise be
    scored as a recognition failure.
    """


    from grandpa.voice.accuracy import (
        CAPTURE_FAILURES,
        DEFAULT_PHRASES,
        MODEL_DOWNLOAD_MB,
        AccuracyReport,
        CaptureFailure,
        PhraseScore,
        model_is_cached,
        quiet_model_downloads,
        score_phrase,
        warm_transcriber,
    )

    # Before anything else: the download must not draw over the first prompt.
    quiet_model_downloads()

    if not WindowsKeyProbe.available():
        safe_cli_error(
            "The accuracy test needs the Windows keyboard API (user32) to run "
            "push-to-talk capture, which is not available here."
        )
        raise SystemExit(1)

    if phrases is not None:
        lines = tuple(
            line.strip()
            for line in Path(phrases).read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
        if not lines:
            raise click.ClickException(f"No phrases found in {phrases}.")
    else:
        lines = DEFAULT_PHRASES
    # 0 means the whole list. Three is the default because ten phrases
    # read aloud is more than anyone does -- two runs were abandoned at
    # phrase 1 -- and an abandoned run measures nothing.
    if count:
        lines = lines[: max(1, count)]

    config = load_voice_assistant_config(
        model=model, language=language, microphone=device, tts_enabled=False
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
    probe = WindowsKeyProbe()
    report = AccuracyReport(model=config.stt_model, requested=len(lines))

    click.echo(f"Accuracy test: {len(lines)} phrases, model {config.stt_model}.")
    click.echo("")

    # Step one, with its own line, because this used to happen silently during
    # the first prompt: the model was fetched and loaded while the first
    # prompt to hold and read was on screen, so the phrase was spoken into a
    # transcriber
    # that did not exist yet and measured against progress bars drawn over the
    # prompt.
    size_mb = MODEL_DOWNLOAD_MB.get(config.stt_model)
    cached = model_is_cached(config.stt_model)
    if cached:
        click.echo(f"Loading {config.stt_model} (already downloaded).")
    elif size_mb:
        click.echo(
            f"Downloading {config.stt_model}, about {size_mb} MB. This happens "
            f"once and can take a minute or two."
        )
    else:
        click.echo(f"Loading {config.stt_model}.")
    click.echo("Nothing is recorded until this finishes.")
    warm_started = time.perf_counter()
    ready, detail = warm_transcriber(transcriber)
    warm_seconds = time.perf_counter() - warm_started
    if not ready:
        capture.close()
        safe_cli_error(f"The model could not be loaded: {detail}")
        raise SystemExit(1)
    click.echo(f"Model ready in {warm_seconds:.1f}s.")
    click.echo("")
    click.echo(f"Hold {key.upper()} and read each phrase aloud. Ctrl+C to stop.")
    click.echo("")
    try:
        for number, phrase in enumerate(lines, start=1):
            click.echo(f"[{number}/{len(lines)}] Read this:")
            click.secho(f"    {phrase}", bold=True)
            # The session's own messages carry the reason an empty transcript
            # was empty -- which gate emptied it -- so they are collected rather
            # than discarded. Only the useful ones are reprinted.
            session_messages: list[str] = []
            session = PushToTalkSession(
                capture=capture,
                transcriber=transcriber,
                probe=probe,
                key=key,
                responder=None,
                speaker=None,
                echo=session_messages.append,
                on_idle=_console_idle_check,
            )
            click.echo(f"    Hold {key.upper()} and read it...")
            started = time.perf_counter()
            result = session.run_once()
            seconds = time.perf_counter() - started
            if result is None:
                # This phrase *and the rest*. Appending only this one
                # made a run abandoned at phrase 1 report nine phrases
                # as neither scored nor skipped -- they simply vanished.
                report.skipped.extend(lines[number - 1 :])
                click.echo("    Skipped.")
                break
            audio = result.audio
            # A recording that never happened is not a recognition result.
            # Scoring these as deletions is what turned two failed holds into
            # full word errors and produced WER 1.167 on three phrases.
            if result.reason in CAPTURE_FAILURES:
                failure = CaptureFailure(
                    reference=phrase,
                    reason=result.reason,
                    held_seconds=result.held_seconds,
                )
                report.failures.append(failure)
                click.echo(
                    f"    {click.style('SKIP', fg='red')} not scored: "
                    f"{failure.advice}"
                )
                click.echo("    Press the key again to retry this phrase.")
                click.echo("")
                retry = session.run_once()
                if retry is None or retry.reason in CAPTURE_FAILURES:
                    continue
                result = retry
                audio = result.audio
                report.failures.pop()
            substitutions, deletions, insertions, words = score_phrase(
                phrase, result.transcript
            )
            score = PhraseScore(
                reference=phrase,
                actual=result.transcript,
                substitutions=substitutions,
                deletions=deletions,
                insertions=insertions,
                reference_words=words,
                seconds=seconds,
                speech_rms=float(getattr(audio, "speech_window_rms", 0.0) or 0.0),
                noise_floor=float(getattr(audio, "noise_floor", 0.0) or 0.0),
                voiced_seconds=float(
                    getattr(audio, "speech_active_seconds", 0.0) or 0.0
                ),
            )
            report.scores.append(score)
            marker = click.style("OK ", fg="green") if score.exact else click.style(
                "ERR", fg="yellow"
            )
            click.echo(f"    {marker} heard: {score.actual or '<nothing>'}")
            if not score.actual:
                # Audio was captured and the model returned nothing, which is a
                # real result -- but the user needs to know it is not the same
                # fault as the microphone failing, and which gate emptied it.
                note = next(
                    (
                        message
                        for message in session_messages
                        if "Nothing recognisable" in message
                    ),
                    "",
                )
                click.echo(
                    f"        audio was captured "
                    f"({score.voiced_seconds:.1f}s voiced, level "
                    f"{score.speech_rms:.0f}); the model returned nothing."
                )
                if note:
                    click.echo(f"        {note.strip()}")
            if not score.exact:
                click.echo(
                    f"        {score.errors} error(s): {substitutions} wrong, "
                    f"{deletions} missed, {insertions} extra  (wer {score.wer:.2f})"
                )
            click.echo("")
    except KeyboardInterrupt:
        click.echo("")
        report.skipped.extend(lines[len(report.scores) :])
    finally:
        capture.close()

    _print_accuracy_report(report, as_json=as_json)


def _print_accuracy_report(report, *, as_json: bool) -> None:
    import json as json_module

    if as_json:
        click.echo(
            json_module.dumps(
                {
                    "model": report.model,
                    # null, not 0.0, when nothing was scored: zero errors out of
                    # zero words is not a word error rate, and 0.0 reads as a
                    # perfect score.
                    "corpus_wer": (
                        None
                        if report.corpus_wer is None
                        else round(report.corpus_wer, 4)
                    ),
                    "total_errors": report.total_errors,
                    "total_words": report.total_words,
                    "exact_matches": report.exact_matches,
                    "phrases_scored": len(report.scores),
                    "phrases_requested": report.requested,
                    "median_snr_db": round(report.median_snr_db, 2),
                    "skipped": report.skipped,
                    # Held apart from the score: a recording that never
                    # happened says nothing about recognition.
                    "representative": report.is_representative,
                    # The reason, not just the flag, so a JSON run says why it
                    # cannot be compared without the text report beside it.
                    "not_comparable_because": report.incomparable_reason,
                    "capture_failures": [
                        {
                            "reference": failure.reference,
                            "reason": failure.reason,
                            "held_seconds": round(failure.held_seconds, 2),
                        }
                        for failure in report.failures
                    ],
                    "scores": [
                        {
                            "reference": score.reference,
                            "actual": score.actual,
                            "wer": round(score.wer, 4),
                            "substitutions": score.substitutions,
                            "deletions": score.deletions,
                            "insertions": score.insertions,
                            "speech_rms": round(score.speech_rms, 1),
                            "noise_floor": round(score.noise_floor, 1),
                            "snr_db": round(score.signal_to_noise_db, 2),
                        }
                        for score in report.scores
                    ],
                },
                indent=2,
            )
        )
        return

    click.echo("=" * 58)
    if not report.scores:
        # Still a report. A run abandoned at the first phrase used to print one
        # line here and, with --json, an object whose corpus_wer was 0.0.
        click.echo("No phrases were scored, so there is no word error rate.")
        click.echo(f"Model:           {report.model}")
        if report.requested:
            click.echo(
                f"Requested:       {report.requested} phrase(s), "
                f"{len(report.skipped)} not attempted"
            )
        for failure in report.failures:
            click.echo(f"  {failure.reference!r}: {failure.advice}")
        click.echo("")
        click.secho(
            f"Not comparable to another run: {report.incomparable_reason}.",
            fg="yellow",
            bold=True,
        )
        # Only when it adds something. With no failures the verdict is
        # "Nothing was scored.", which the line above has just said.
        if report.failures:
            click.echo(report.verdict())
        click.echo("")
        click.echo("Try --count 1 for a single phrase if this is too long a sit.")
        return
    click.echo(f"Model:          {report.model}")
    click.echo(
        f"Word error rate: {report.corpus_wer:.3f}  "
        f"({report.total_errors} errors / {report.total_words} words)"
    )
    click.echo(
        f"Exact matches:   {report.exact_matches} of {len(report.scores)} phrases"
    )
    if report.median_snr_db:
        click.echo(f"Median SNR:      {report.median_snr_db:.1f} dB")
    if report.failures:
        click.echo(
            f"Failed to record: {len(report.failures)} phrase(s), "
            f"excluded from the score"
        )
        for failure in report.failures:
            click.echo(f"    {failure.reference!r}: {failure.advice}")
    if report.skipped:
        click.echo(f"Not attempted:   {len(report.skipped)} phrase(s)")
    click.echo("")
    if not report.is_representative:
        click.secho(
            f"This number is not comparable to another run: "
            f"{report.incomparable_reason}.",
            fg="yellow",
            bold=True,
        )
    click.echo(report.verdict())
    click.echo("")
    click.echo("Compare runs with --json. The word error rate is the number to")
    click.echo("quote; it is only comparable against the same phrase list.")


@voice.command("push-to-talk")
@click.option("--key", default=DEFAULT_HOLD_KEY, show_default=True,
              callback=_hold_key_option,
              help="Key or combination to hold while speaking, e.g. ctrl+win.")
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
