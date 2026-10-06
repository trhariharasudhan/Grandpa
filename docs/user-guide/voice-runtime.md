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

## Measuring accuracy

```
grandpa voice accuracy-test
grandpa voice accuracy-test --json > before.json
grandpa voice accuracy-test --model small.en --count 5
```

Ten fixed phrases are shown one at a time; hold the key and read each aloud. The
report gives a word error rate — `(substitutions + deletions + insertions)` over
reference words, after lowercasing and stripping punctuation — plus the per-phrase
operation counts and the signal-to-noise ratio of each recording.

The corpus WER is errors over *all* words, not the mean of the per-phrase rates:
a mean would weight "Hello" as heavily as a nine-word sentence, so one wrong
short word would swamp the score and two runs would stop being comparable.

The operation counts say what kind of failure it was. All insertions means the
model padded — one spoken "hello" returning "Hello. Hello. Hello." scores as two
insertions. All substitutions means it misheard. The phrase list is fixed because
a score is only comparable against the same text; `--phrases` exists for
deliberately measuring something else.

Capture uses the push-to-talk path, so the recording is bounded by the key rather
than by speech detection. A detection failure would otherwise be scored as a
recognition failure.

| median SNR | reading |
| --- | --- |
| below 10 dB | the recording is the limit; move closer or reduce noise first |
| 10 dB or more, WER above 0.25 | the recording is adequate; try `--model small.en` |

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

If the vocabulary setting is not enough, the model is the next lever — and on
measurement it is the **only** one left. Scored over 120 degraded clips of
synthesised speech, 504 reference words, at four signal-to-noise ratios and
three noise realisations each:

| model | WER | significance vs `base.en` | latency |
| --- | --- | --- | --- |
| `small.en` | **0.087** | z = +2.32, significant | 2.85× |
| `small` | 0.107 | z = +1.26, not significant | 7.14× |
| `base.en` (default) | 0.133 | — | 1.00× |
| `base` | 0.177 | z = −1.91, not significant | 2.36× |
| `distil-small.en` | 0.284 | z = −5.89, significantly worse | 3.09× |

`small.en` is a 35% relative reduction in word errors for 2.85× the decode time
— about 2.7s per phrase instead of 1.0s — plus a ~480MB download and roughly
10s more at startup.

Two results worth knowing because they are counter-intuitive:

* **the multilingual models are worse, not better.** `base` scored 0.177 against
  `base.en`'s 0.133. Reaching for a multilingual model to handle an accent is
  the obvious move and it does not work here.
* **`distil-small.en` is much worse** at 0.284, despite existing to be
  `small.en` at lower cost. It is not a shortcut.
* **`small.en` with `beam_size=5` costs 76× the latency** — 112s per clip — for
  no accuracy gain (0.089 against 0.087). Do not combine them.

`beam_size`, `temperature` fallback, `condition_on_previous_text` and
`vad_filter` were each measured and changed nothing significant. `beam_size=5`
looked like a win on a 42-word sample (4 errors to 3) and evaporated at 504
words, z = +0.47.

To switch permanently:

```toml
[speech]
model = "small.en"
```

or `GRANDPA_VOICE_STT_MODEL=small.en` for one session, or `--model small.en` on
a single command.

Then settle it on your own voice, which is the only input that answers the
question for your accent and your microphone:

```powershell
uv run grandpa voice accuracy-test --json > base-en.json
uv run grandpa voice accuracy-test --model small.en --json > small-en.json
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
