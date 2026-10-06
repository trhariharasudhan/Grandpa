# Voice Runtime

Grandpa's local voice runtime is phrase-based and offline-first. It does not
start a permanent microphone service or a background listening thread.

## Architecture

```text
grandpa voice
  -> VoiceSession
     -> MicrophoneDeviceManager
     -> MicrophoneCapture + VoiceActivityDetector
     -> FasterWhisperSpeechToText
     -> WakeWordDetector (optional transcript gate)
     -> VoiceCommandProcessor
     -> GrandpaTextToSpeech (optional)
```

The `VoiceSession` owns its microphone, stop event, wake state, command
processor, and speech output. State is not shared across CLI sessions.

## Microphone Selection

Grandpa selects an input in this order:

1. Explicit `--microphone <index>`
2. Saved microphone name from `grandpa voice set-device "<name>"`
3. Windows/PortAudio default input
4. A physical microphone such as a Microphone Array, Realtek input, USB mic,
   or Bluetooth headset
5. The first usable input device

An explicit index is never silently replaced. A missing saved device may fall
back to another usable input and emits a warning. Device names are resolved
again each time, so a saved USB or Bluetooth microphone can move to a different
PortAudio index.

During phrase capture, device-open or read failures close the old stream,
re-enumerate inputs, and make a bounded number of recovery attempts. Grandpa
never leaves the failed stream open.

## Speech Detection

The local energy detector:

- learns a small ambient noise floor before speech starts;
- waits for a minimum amount of speech;
- stops after trailing silence;
- enforces a maximum utterance duration;
- never records indefinitely.

Environment overrides:

```text
GRANDPA_VOICE_SPEECH_START_RMS
GRANDPA_VOICE_MINIMUM_SPEECH_SECONDS
GRANDPA_VOICE_SILENCE_TIMEOUT_SECONDS
GRANDPA_VOICE_PHRASE_DURATION_LIMIT
GRANDPA_VOICE_RECOVERY_ATTEMPTS
```

## Wake Phrases

Transcript-gated wake mode recognizes:

- Grandpa
- Hey Grandpa
- Hi Grandpa
- Wake Grandpa

An inline phrase such as `Hey Grandpa, open Chrome` executes the command from
the same utterance. A short cooldown rejects immediate duplicate activations.

## Diagnostics

```powershell
grandpa voice devices
grandpa voice diagnose
grandpa voice doctor --duration 5
grandpa voice test
grandpa voice set-device "Microphone Array"
```

`diagnose` does not record. `doctor` performs a bounded capture and reports the
selected device, channels, sample rate, driver/host API, transport, RMS, frame
count, STT readiness, TTS readiness, and Windows permission guidance.

## Vocabulary: names the model will not guess

Whisper decodes toward what it has seen in training, so an uncommon proper noun
becomes a common one that sounds like it. "Hari" transcribes as "Harry". This is
not a confidence problem -- the decode is confident and wrong -- so no threshold
addresses it. What does is `initial_prompt`, which biases the decoder toward
spellings it would otherwise rank lower. Grandpa already used it for the
application names it controls; a user vocabulary is the same mechanism.

```toml
[voice]
vocabulary = ["Hari Hara Sudhan", "Arjun", "Tiruchirappalli"]
```

or, for one run:

```powershell
$env:GRANDPA_VOICE_VOCABULARY = "Hari Hara Sudhan,Arjun"
```

The environment variable wins over config. Entries are additive to the
application names, which routing needs; `vocabulary_replaces_defaults = true`
drops them. Whitespace is normalised, blanks and case-insensitive duplicates are
dropped, and a malformed setting falls back to the default rather than stopping
speech recognition.

Include the full name even when only part of it is misheard: Whisper conditions
on sequences, so "Hari Hara Sudhan" helps "Hari" more than "Hari" alone does.

### Model size, measured

If the vocabulary setting is not enough, a larger model is the next lever. On
this machine, CPU int8, decoding the same 3-second input:

| model | one-off load | warm decode |
| --- | --- | --- |
| `tiny.en` | 6.2s | 1.7s |
| `base.en` (default) | 6.9s | 1.0s |
| `small.en` | 17.0s | 3.7s |

`small.en` costs about **+2.8s per phrase** and **+10s** once at startup, and
needs a ~480MB download.

Read the warm column with care: it was measured on a synthetic signal, not
speech, and decode time scales with how many tokens a model emits. The models
hallucinated different amounts on it, which is why `tiny.en` looks slower than
`base.en`. The load column is clean; the per-phrase column is indicative only.

Settle it on your own voice, which is the only input that answers the accuracy
question:

```powershell
uv run grandpa voice push-to-talk --model base.en
uv run grandpa voice push-to-talk --model small.en
```

## Limitations

- PortAudio does not expose the Windows "default communications device" role,
  so diagnostics report that field as unknown instead of guessing.
- Disabled or physically disconnected devices normally disappear from
  PortAudio enumeration; Grandpa can recover to another input but cannot
  distinguish every Windows driver state without a native MMDevice adapter.
- Wake detection runs on locally transcribed phrases. There is no permanent
  low-power hotword engine in this runtime.
- Speech recognition still depends on the configured local faster-whisper
  model being present and loadable.
