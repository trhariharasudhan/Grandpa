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
