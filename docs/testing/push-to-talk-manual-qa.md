# Push-to-Talk Microphone Bridge Manual QA

These checks verify user-initiated push-to-talk only. They do not enable
always-on recording, live wake-word microphone detection, background
auto-start, or desktop automation bypasses.

There are two push-to-talk paths. They share the name and nothing else.

## Terminal: hold a key

```
grandpa voice push-to-talk
```

Hold Ctrl+Win, speak, release. The recording starts when both keys are down
and ends
on it coming up; every frame in between is kept. The voice activity detector is
configured so it cannot refuse or truncate anything -- no threshold, no noise
floor, no silence timeout -- so this is the path to use when automatic detection
is misbehaving and when a threshold needs to be ruled out as the cause.

| Option | Effect |
| --- | --- |
| `--key menu` | Hold a different key or combination: any `+`-joined mix of SPACE, CTRL, SHIFT, ALT, WIN, RWIN, MENU, F8, F9, F10. CTRL+WIN is the default for every command that takes one. A printable part types into whatever has focus (and into this terminal); a lone `ctrl` fires on every Ctrl+C, so avoid it on its own. |
| `--no-route` | Print the transcript and stop. Nothing is acted on. |
| `--once` | Handle one hold and exit. |
| `--no-tts` | Print the reply instead of speaking it. |
| `--device N` | Override the stored microphone preference. `grandpa voice --list-microphones` shows the indexes. |

Expected, per hold:

| Step | Expected behavior |
| --- | --- |
| Key down | `Recording...` |
| Key up | `Released after N.Ns. Transcribing...` |
| Speech recognised | `You said: <transcript>`, then the reply |
| Nothing recognisable | Says so with the audio level and which gate emptied it, and routes nothing. An empty transcription is never read as a command. |
| Microphone is not the saved one | Says which device the index actually is. PortAudio indexes shift when audio devices connect; nothing persists one. |
| Key tapped, not held | Says it was a tap and asks for a hold. Nothing is transcribed. |
| No audio captured | Says the device delivered nothing and points at `grandpa voice doctor`. |

Esc or Ctrl+C ends the loop. It never exits silently, and no expected failure
prints a stack trace.

## Terminal: measure accuracy

```
grandpa voice accuracy-test
```

Three phrases by default, read one at a time on the same held key, scored
as a word error rate against what was asked for. `--json` for comparing two
runs, `--model small.en` to score a different model, `--count 0` for the
whole list of ten, `--count 1` for a single phrase.

Three because ten read aloud is more than anyone does, and an abandoned run
measures nothing. The first three are a plain question, a routed command and
one long sentence -- sixteen words, no proper nouns. The two phrases containing
a name are last: they are the known `small.en` loop trigger and they inflate
the rate for a reason that has nothing to do with general accuracy.

| Step | Expected behavior |
| --- | --- |
| Phrase shown | The exact text to read, in bold |
| Read it | `OK` with the transcript, or `ERR` with the error breakdown |
| End of run | Word error rate, exact-match count, median SNR, and a verdict |
| Ctrl+C partway | Scores what was completed and reports it; remaining phrases listed as not attempted, and the number marked not comparable with the reason |
| Stopped before any phrase was read | Says there is no word error rate, names how many were requested and not attempted, and suggests `--count 1`. With `--json`, `corpus_wer` is `null` -- never `0.0`, which would read as perfect |

The operation counts distinguish the failure kinds: insertions mean the model
padded (one "hello" returning three), substitutions mean it misheard.

**No second speech gate.** The automatic path hands audio to Whisper with
`no_speech_threshold` 0.5, `log_prob_threshold` -0.85 and
`compression_ratio_threshold` 2.4, and then applies a stricter copy of the first
two on the decoded segments (`no_speech_prob > 0.45`), so a segment Whisper
chose to keep can still be dropped. Push-to-talk disables all of it: the user
holding a key down has already answered the question those thresholds ask. The
repetition filter stays, because it rejects a decoder failure mode rather than
judging the audio, and when it fires the command says so.

If a hold genuinely transcribes to nothing, the command prints which of the
gates emptied it (`no speech decoded`, `every segment dropped`, `repetition
loop`) rather than raising. `grandpa voice microphone-test` prints the same
per-segment numbers with the cutoff beside each one.

Windows only: the key is read through `GetAsyncKeyState`, which asks what the
keyboard is doing and synthesises nothing, so this requires no actuation
consent. On any other platform the command says so and exits non-zero.

## Browser: click to record

The rest of this document covers the browser bridge, which is a different
thing: it records between two button clicks rather than while a key is held,
and it needs the server running and a page open.

## Setup

1. Start Grandpa normally.
2. Open the Voice Assistant page in a browser that supports `MediaRecorder`.
3. Confirm the backend is reachable.

## Happy Path

| Step | Expected behavior |
| --- | --- |
| Click Start Recording | Browser asks for microphone permission if needed, then recording starts. |
| Speak a short command | Audio is captured only while recording is active. |
| Click Stop Recording | Recording stops, the browser microphone stream is closed, and audio is sent to `/v1/voice/listen`. |
| Transcript appears | The transcript preview fills in if local audio transcription is available. |
| Click Send as Command | The transcript is sent to `/v1/voice/command`. |
| Confirmation needed | Desktop actions that require approval show the existing Confirm Action flow. |

## Commands To Try

- `what is my voice status`
- `open notepad`
- `type hello in notepad`
- `remind me tomorrow at 7 PM to call Arjun`

## Failure Cases

| Case | Expected behavior |
| --- | --- |
| Browser has no `MediaRecorder` | UI shows `Browser recording is not available on this device.` |
| Microphone permission denied | UI shows the browser/device error without starting a recording loop. |
| No local Whisper/faster-whisper | `/v1/voice/listen` returns setup guidance: `uv sync --extra speech`. |
| Unclear or invalid audio | UI shows a friendly recognition failure and allows retry. |
| Empty transcript | Send as Command stays disabled. |

## Safety Notes

- Recording starts only after Start Recording is clicked.
- Recording stops when Stop Recording is clicked.
- The UI sends commands only after Send as Command is clicked.
- Wake-word live microphone mode is not part of this bridge.
- Dangerous or confirmation-required desktop actions must still use the
  existing local action approval flow.
