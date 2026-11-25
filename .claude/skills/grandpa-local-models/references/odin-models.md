# Odin roles (from docs/development/model-names.md and odin_registry.py, 2026-11-24)

| Role | Tag | Purpose | Calls tools | Min memory | Foundation |
|---|---|---|---|---|---|
| Brain (default) | `grandpa-brain:latest` | reliable tool use | yes | 6 GB | Qwen3 8B (`FROM qwen3:8b`) |
| Fast | `grandpa-fast:latest` | middle ground | yes | 4 GB | Qwen3 |
| Mini | `grandpa-mini:latest` | small machines | no | 1 GB | Qwen2.5 |
| Coder | `grandpa-coder:latest` | coding | no | 6 GB | DeepSeek Coder |
| Eyes | `grandpa-eyes:latest` | local vision (screen describe) | no | 6 GB | LLaVA |
| Guard | `grandpa-guard:latest` | safety classifier (registered, unused) | no | 8 GB | Llama Guard 3 |
| Memory | `grandpa-memory:latest` | embeddings; falls back to `nomic-embed-text` | – | 0.5 GB | Nomic BERT |
| Ears | `grandpa-ears` | STT via faster-whisper, size from `[speech] model` | – | – | Whisper |
| Voice | `grandpa-voice` | TTS via `[tts] backend` | – | – | – |

Experimental: `models/Modelfile.brain-odin1` – Brain plus a LoRA adapter trained with
`notebooks/odin_brain_lora.ipynb` (Colab/Kaggle T4).

## Runtime notes

- `runtime/ollama_adapter.py` caps generation at `_MAX_NUM_PREDICT = 2048` tokens.
- `keep_alive` default and the measured cold/warm timings are documented in the adapter's docstring.
- `engine/` re-exports runtime behaviour for older callers; new code should import from `grandpa.runtime`
  unless an existing pattern in the same package uses `engine`.
- Environment: `GRANDPA_OLLAMA_HOST`, `GRANDPA_OLLAMA_TIMEOUT`, `GRANDPA_OLLAMA_KEEP_ALIVE`,
  `GRANDPA_MODEL_ROLES`, `GRANDPA_VISION_MODEL`, `GRANDPA_EYES_MODEL`, `GRANDPA_MEMORY_EMBEDDER`.
- README quick start pulls `qwen3:8b`; CONTRIBUTING suggests `qwen3.5:2b` – CONTRIBUTING is older.
- The headless node (`grandpa server --headless`) runs no model; it forwards chat to the PC.

## Rust / native

`rust/` contains inherited crates (engine, learning, …) that are not used by the Python model path.
`_rust_bridge.py` callers all fall back to Python (PR #59). Do not route model work through Rust.
