# Voice file map

| Area | Files |
|---|---|
| CLI | `cli/voice_cmd.py` (`grandpa voice`, `push-to-talk`, `accuracy-test`, `devices`, `--diagnose`), `cli/voice_operator_cmd.py`, `cli/wake_cmd.py`, `cli/speak_cmd.py`, `cli/bubble_cmd.py`, `cli/avatar_cmd.py`, `cli/jarvis_cmd.py` |
| Session / loop | `voice/session.py`, `voice/cli_session.py`, `voice/loop.py`, `voice/conversation.py`, `voice/conversation_mode.py`, `voice/history.py` |
| Capture | `voice/microphone.py`, `voice/live_capture.py`, `voice/device_manager.py`, `voice/push_to_talk.py`, `voice/vad.py` |
| Wake | `voice/wake_word.py` (phrase in transcript), `voice/wake_engine.py` (openWakeWord ONNX), `voice/hands_free.py` (WakeGate, barge-in) |
| STT | `voice/speech_to_text.py`, `voice/speech_input.py`, `speech/faster_whisper.py`, `speech/vocabulary.py`, `speech/_discovery.py` |
| Routing | `voice/assistant.py` (shared text-command processor), `voice/operator.py` (command-first desktop control through the action layer) |
| TTS | `voice/text_to_speech.py`, `voice/speech_output.py`, `speech/tts.py` (ABC), `speech/piper_tts.py`, `speech/tamil_tts.py`, `speech/kokoro_tts.py`, `speech/grandpa_voice_tts.py` (HTTP client to `voice_service`), `speech/elevenlabs_tts.py`, `speech/local_voice/` |
| Cloned voice service | `voice_service/service.py`, `voice_service/post_processing.py`; runtime scripts in `voice_runtime/scripts/`; plan in `implementation_plan.md` (F5-TTS) |
| Diagnostics | `voice/diagnostics.py`, `voice/audio_diagnostics.py`, `voice/accuracy.py`, `voice/accuracy_stats.py`, `voice/errors.py`, `voice/presenter.py` |
| UI / lip-sync | `ui/bubble.py`, `ui/tk_view.py`, `ui/lipsync.py`, `ui/avatar_web/` |
| Training | `notebooks/grandpa_voice_piper.ipynb`, `voice_runtime/datasets/hari_piper/scripts/`, `voice_runtime/rvc_training_package/`, `piper_pilot_plan.md` |

## Config

`[speech]` (`SpeechConfig`): `backend` (auto), `model` (base.en), `language`, `device`, `compute_type`.
`[tts]` (`TTSConfig`): `backend` (default `pyttsx3`, `DEFAULT_TTS_BACKEND`). `[grandpa_voice]`: F5 service
settings. `VoiceConfig` holds vocabulary, preferred microphone, live microphone flag.
Env overrides: `GRANDPA_VOICE_*` (≈30 variables: STT model, device, rate, volume, silence timeout,
echo window, wake phrases…), `GRANDPA_WAKE_*`, `GRANDPA_PIPER_VOICE`, `GRANDPA_AVATAR_VOICE`,
`GRANDPA_TAMIL_VOICE_DIR`, `GRANDPA_ELEVENLABS_*`. Grep `GRANDPA_VOICE_` in `voice/config.py` for the list.

## Optional extras (pyproject)

`voice` (faster-whisper, numpy, sounddevice, soundfile, pyttsx3 on Windows), `speech`, `wake`
(openwakeword), `piper` (piper-tts), `tamil-voice` (sherpa-onnx), `avatar` (pywebview, websockets).
Downloads: `python -m grandpa.speech.piper_tts download`, `python -m grandpa.speech.tamil_tts download`,
`grandpa wake setup`.

## Tests

`tests/voice/`, `tests/speech/`, `tests/voice_runtime/`, `tests/ui/`, flat `tests/test_voice_*.py`,
`tests/test_microphone_capture.py`, `tests/test_audio_is_denied_by_default.py`.
