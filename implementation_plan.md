# Implementation Plan - Production-Ready Local Cloned-Voice TTS System for Grandpa

This document outlines the proposed design and implementation strategy for integrating a fully local, offline cloned-voice Text-to-Speech (TTS) system into Grandpa.

---

## 1. Current Architecture Discovered

### Pluggable TTS Registry & Backends
- **`src/grandpa/speech/tts.py`**: Defines abstract base classes `TTSBackend`, `TTSResult`.
- **`src/grandpa/speech/kokoro_tts.py`**: Registers `"kokoro"` using `@TTSRegistry.register("kokoro")`. It synthesizes text to a `TTSResult` object containing audio bytes, format, and metadata.
- **`src/grandpa/core/registry.py`**: Declares `TTSRegistry` inheriting from `RegistryBase[Any]`.
- **`src/grandpa/tools/text_to_speech.py`**: The `TextToSpeechTool` looks up the active backend via `TTSRegistry` and saves the synthesized bytes to a local file.

### Voice mode and CLI Playback
- **`src/grandpa/voice/config.py`**: Loads settings for STT and TTS (`pyttsx3`, rate, volume, etc.). Currently, `pyttsx3` (SAPI5 on Windows) or `edge_tts` are the only output methods.
- **`src/grandpa/voice/speech_output.py`**: Defines `SpeechOutputEngine`, which handles actual audio playback through `pyttsx3` or `edge_tts`. It currently does not use `TTSRegistry` or any `TTSBackend` interfaces.
- **`src/grandpa/voice/text_to_speech.py`**: Defines `GrandpaTextToSpeech` wrapping `SpeechOutputEngine` for `cli_session.py`.
- **`src/grandpa/cli/voice_cmd.py`**: Implements CLI subcommands for `grandpa voice`, including `diagnose`, `doctor`, `test`, `devices`, and `set-device`.

---

## 2. Selected Local Voice Engine

We select **F5-TTS** as the primary local cloned-voice engine because:
1. **Zero-shot capability**: High similarity using a single 15-second reference audio clip.
2. **Multilingual/Code-switching (Tanglish)**: Uses character-level flow matching, which naturally handles mixed languages like Tanglish.
3. **Open-source & Local**: Fully offline, Apache 2.0 licensed, and does not require cloud APIs.

---

## 3. Dependency Strategy

To avoid polluting the main Grandpa virtual environment with massive machine learning dependencies (`torch`, `torchaudio`, `f5-tts`, etc.), we will separate the runtime:
- **Client Side (Grandpa Core)**: Interacts with the local voice service via standard lightweight HTTP calls to localhost.
- **Server Side (Separate Local Voice Runtime)**: The tracked service entrypoint is `src/grandpa/voice_service/service.py`; models, datasets, caches, and generated audio remain outside source control. It loads the F5-TTS model and synthesizes speech on demand.

---

## 4. CPU Compatibility Assessment

- F5-TTS runs on CPU, but joint-duration diffusion models can have significant latency on consumer-grade CPUs (typically 2-4x real-time depending on core count).
- We will support model optimization (quantization / CPU-friendly parameters) and cache speaker embeddings.
- If CPU latency is too high, the system gracefully falls back to Kokoro, which uses ONNX Runtime and achieves extremely fast CPU inference (<1.0x real-time).

---

## 5. Proposed Changes (Exact Files)

### Exact Files to Modify:
1. **`src/grandpa/core/config.py`**:
   - Add a `tts` section/dataclass to configure the active TTS backend.
   - Add a `grandpa_voice` section/dataclass to specify the cloned voice engine (e.g., `device`, `reference_audio`, `reference_text`, `service_url`).
   - Register these sections dynamically in `top_sections`.
2. **`src/grandpa/speech/__init__.py`**:
   - Register both `kokoro` and `grandpa_voice` during import.
3. **`src/grandpa/voice/speech_output.py`**:
   - Update `SpeechOutputEngine` to support registered `TTSBackend`s.
   - Add a unified audio playback wrapper using the `sounddevice` and `soundfile` libraries to play generated audio bytes directly from memory, supporting thread-safe interruption.
4. **`src/grandpa/cli/interactive_tui.py`**:
   - Extend the `/voice` command to support:
     - `/voice status` (displays detailed runtime status and health metrics)
     - `/voice backend <name>` (switches the active TTS backend)
     - `/voice test` (runs a live voice test)
     - `/voice off` / `/voice on` (toggles voice output)

### Exact Files to Create:
1. **`src/grandpa/speech/grandpa_voice_tts.py`** (already created, will be completed):
   - Implement `GrandpaVoiceTTSBackend` making requests to the local runtime.
2. **`src/grandpa/speech/local_voice/engine.py`**:
   - Abstract class `LocalVoiceEngine` for local voice abstraction.
3. **`src/grandpa/speech/local_voice/f5_engine.py`**:
   - Adapter implementing `LocalVoiceEngine` for F5-TTS (makes HTTP requests).
4. **`src/grandpa/speech/local_voice/service_client.py`**:
   - Lightweight client for calling the local service API.
5. **`src/grandpa/voice_service/service.py`**:
   - FastAPI server containing the standalone F5-TTS inference code.
6. **`src/grandpa/speech/dataset_prep.py`**:
   - Ingests cloned voice wav samples, normalizes, resamples, strips silence, validates transcripts, and outputs a metadata manifest.
7. **`tests/speech/test_grandpa_voice.py`**:
   - Unit tests for the registry, fallback, available voices, health checks, mock server synthesis, and timeout behaviors.

---

## 6. Dataset Strategy

To prepare a high-quality dataset of 20-30 minutes for potential future fine-tuning or zero-shot reference clips:
- **Ingestion**: Ingest audio files from a specified raw folder.
- **Preprocessing**: Convert all clips to mono, resample to 24kHz, normalize audio amplitudes, and strip excessive silence.
- **Metadata**: Align transcripts with audio files, compile metadata manifest (`metadata.csv` or JSON), and validate clip duration.
- **Reporting**: Output a validation report detailing sample rates, total duration, clip count, and average duration.

---

## 7. Fallback Strategy

- If `grandpa_voice` is selected but the local service is unreachable or unhealthy, the system prints a warning and falls back to `kokoro`.
- If `kokoro` fails or is not installed, it falls back to system TTS (`pyttsx3`).
- If all fail, text output still prints normally and Grandpa continues to function.

---

## 8. Testing Strategy

- Unit tests will run fully offline and mock the local FastAPI service using pytest monkeypatch / mock.
- Test scenarios:
  1. `grandpa_voice` registry registration.
  2. Health check behavior when service is online/offline.
  3. Proper synthesis of audio bytes.
  4. Fallback execution chain.
  5. Invalid output format / empty text.
- Heavy model inference will be isolated to optional integration tests.

---

## 9. Risks

- **Latency on CPU**: Joint-duration diffusion models are slow on standard CPUs. Fallback to Kokoro must be seamless.
- **Port Conflicts**: Standalone voice service defaults to configurable `127.0.0.1:8765` and binds strictly to localhost unless the user explicitly overrides the host.
- **Dependencies**: Windows package compatibility for C++ dependencies (e.g. `sounddevice` or `soundfile` DLLs).

---

## 10. Implementation Phases

1. **Phase 1**: Configure `GrandpaConfig` and register `grandpa_voice` backend in `TTSRegistry`.
2. **Phase 2**: Add tests for registry/backend.
3. **Phase 3**: Implement `local_voice` client abstraction and HTTP client.
4. **Phase 4**: Implement the standalone FastAPI `service.py`.
5. **Phase 5**: Update `SpeechOutputEngine` to integrate `TTSBackend`s and direct `sounddevice` playback.
6. **Phase 6**: Integrate the fallback strategy and update TUI slash commands.
7. **Phase 7**: Build dataset preparation scripts.
8. **Phase 8**: Final regression testing and documentation.
