# Grandpa Local Voice Runtime

This directory keeps Grandpa's optional F5-TTS runtime inside the project while
isolating its heavy dependencies from Grandpa's main `.venv`.

## Boundaries

- Main application environment: `D:\Grandpa\.venv`
- Cloned-voice environment: `D:\Grandpa\voice_runtime\.venv`
- Private reference audio: `voice_runtime\references\` (ignored)
- Generated audio: `voice_runtime\outputs\` (ignored)
- Model/cache data: `voice_runtime\models_or_cache\` (ignored)
- HTTP service: localhost-only `127.0.0.1:8765`

Do not install this runtime's dependencies into Grandpa's main environment.
Do not commit reference recordings, generated audio, model checkpoints, or
caches.

## Proven Runtime

- Python 3.11.9 x64
- F5-TTS 1.1.22
- Torch 2.13.0
- torchaudio 2.11.0
- SoundFile 0.14.0
- CPU-only inference

The upstream F5-TTS code is MIT licensed. Its pretrained models are CC-BY-NC,
so commercial use requires separate licensing review.

## Setup

```powershell
powershell -ExecutionPolicy Bypass -File .\voice_runtime\scripts\setup.ps1
```

The setup script creates `voice_runtime\.venv`, installs the exact package set
from `requirements.lock`, applies the version-checked Windows CPU compatibility
fixes, and runs a lightweight validation without loading the model.

## Reference Voice

Copy the user-owned reference WAV to:

```text
voice_runtime\references\hari_reference.wav
```

Create the ignored local manifest from `references\reference.example.toml`, and
enter the exact verbatim transcript. The transcript must not be guessed or
automatically substituted for zero-shot validation.

## Direct Synthesis

```powershell
.\voice_runtime\.venv\Scripts\python.exe `
  .\voice_runtime\scripts\synthesize.py `
  --text "Hello Hari. Grandpa local voice runtime migration is working." `
  --output .\voice_runtime\outputs\migration_test.wav
```

Existing output files are never overwritten.

## Local Service

```powershell
powershell -ExecutionPolicy Bypass -File .\voice_runtime\scripts\start_service.ps1
```

The launcher resolves all paths relative to this directory, uses the isolated
Python environment, sets the local model cache, and binds only to
`127.0.0.1:8765`.

## Compatibility Fixes

`scripts\apply_f5_compatibility.py` applies two explicit fixes only to
F5-TTS 1.1.22:

1. Fall back to SoundFile when `torchaudio.load` cannot decode reference audio
   on Windows.
2. Make the training-only `Trainer` import optional so CPU inference can load
   without failing on training dependencies.

The script is idempotent and refuses unknown source layouts or package versions.
