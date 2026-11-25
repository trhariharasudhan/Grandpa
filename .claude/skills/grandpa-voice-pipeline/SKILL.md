---
name: grandpa-voice-pipeline
description: Work on Grandpa's voice - microphone capture, push-to-talk (Ctrl+Win chord), adaptive VAD, faster-whisper speech-to-text, "Hey Grandpa" openWakeWord wake engine and barge-in, voice operator mode, TTS backends (pyttsx3 default, Piper, MMS Tamil, Kokoro, F5 grandpa_voice service, opt-in ElevenLabs), bubble and avatar speech/lip-sync, and voice dataset/training tooling. Use for any bug like "it did not hear me", "wrong words", "no speech output", wake word tuning, or adding a voice backend.
---

# Grandpa voice pipeline

Voice is the most-iterated subsystem (≈10k lines in `src/grandpa/voice/`, plus
`speech/`, `voice_service/`, `ui/lipsync.py`, `voice_runtime/`). The README's
voice sections record hard-won measurements – read them before "fixing"
thresholds. Architecture and file map: [references/voice-architecture.md](references/voice-architecture.md).

## Pipeline

```
mic (sounddevice) ─► capture mode
   push_to_talk.py   hold chord (default Ctrl+Win), no VAD
   vad.py            adaptive noise floor + threshold (hands-free `grandpa voice`)
   wake_engine.py    openWakeWord 80 ms frames → hands_free.WakeGate (barge-in)
        │
STT  speech/faster_whisper.py  ("faster-whisper", only registered STT backend; [speech] model, default base.en)
        │ vocabulary correction (speech/vocabulary.py, GRANDPA_VOICE_VOCABULARY)
ROUTE voice/assistant.py → handle_local_action / action layer (no confirm callback ⇒ confirmable actions refused)
        │
TTS  voice/speech_output.SpeechOutputEngine  (CLI voice, bubble)
       order from [tts] backend: piper | grandpa_voice | kokoro | pyttsx3 (default)
     ui/lipsync.py (avatar): ElevenLabs (if key) → Piper / MMS Tamil → pyttsx3, 60 s local fallback
```

## Diagnose first (never tune blind)

1. `uv run grandpa voice --diagnose` – deps, Python env, devices.
2. `uv run grandpa voice --list-microphones`, `grandpa voice devices`.
3. Reproduce with **push-to-talk** (`grandpa voice push-to-talk`, `--no-route` to see only the
   transcript). If PTT works and hands-free does not, the problem is VAD, not STT.
4. Ask for `grandpa oops --export`: it records `speech_window_rms`, `noise_floor`,
   `max_chunk_rms`, voiced seconds, key-hold time and which gate emptied the transcript.
5. Accuracy claims need numbers: `grandpa voice accuracy-test` (word error rate). The README's table
   says how many words are needed to detect a given difference; one run is not evidence.
6. Wake word: `grandpa wake status`, `grandpa wake setup` (downloads ~4 MB feature models once),
   `grandpa wake test <file.wav>`, `grandpa wake listen`.

## Workflow: change behaviour

1. Locate the stage above; read that module's docstring (they explain past failures, e.g. why the
   chord is Ctrl+Win and not Space/Ctrl/F9).
2. Keep every stage testable without hardware: inject fake audio frames / fake recogniser.
3. Microphone tests carry the `microphone` marker and self-skip unless `GRANDPA_RUN_MICROPHONE_TESTS=1`.
4. Run `uv run python -m pytest tests/voice tests/speech tests/test_voice_*.py -q`.
5. Manual QA scripts live in `docs/testing/*voice*`, `wake-word-manual-qa.md`, `push-to-talk-manual-qa.md`.

## Workflow: add a TTS backend

1. Subclass `speech/tts.py:TTSBackend`, register with `@TTSRegistry.register("<id>")`, implement `health()`.
2. Import it in `grandpa/speech/__init__.py` registration path; heavy deps import lazily.
3. Add it to the ordering in `voice/speech_output.py:available_local_engines` **and** decide whether
   `ui/lipsync.py` (avatar) should use it – the two selection paths are separate today.
4. Add an optional extra in `pyproject.toml`, a `doctor` line, and tests in `tests/speech/`.

## Constraints

- Offline-first: cloud TTS (ElevenLabs) must stay opt-in, key from env (`GRANDPA_ELEVENLABS_API_KEY`
  / `ELEVENLABS_API_KEY`) or the secret store, with local fallback. Say in docs that reply text leaves the PC.
- Never treat a recognised voice as authentication or as confirmation for a HIGH action.
- Voice has no confirm callback for synthetic input; do not add an "auto-yes" to make voice actions work.
- Do not commit audio, datasets, model weights or `.onnx` files; `voice_runtime/` holds scripts only.
- Text speech is "in addition, never instead": the text reply must still appear if TTS fails.

## Known issues (verified 2026-11-25)

- `[speech] backend` comment lists `openai`, `deepgram`; only `faster-whisper` is implemented.
- Some model paths use `Path.home()/".Grandpa"` (`speech/tamil_tts.py`, ElevenLabs cache, wake model
  default) instead of `GRANDPA_HOME` (`~/.grandpa`) – different folder on case-sensitive systems
  (the Linux headless node) and not sandboxed by `GRANDPA_HOME` in tests.
