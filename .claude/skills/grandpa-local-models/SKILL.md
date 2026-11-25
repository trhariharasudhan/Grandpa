---
name: grandpa-local-models
description: Work on Grandpa's local AI models (the Odin model family) - Ollama runtime adapter and engine shim, Odin roles (brain, fast, mini, coder, eyes, guard, memory, ears, voice), Modelfiles, grandpa models roles/setup/eval, tool-call capability, keep_alive and latency, native GGUF manager, and the Odin-1 LoRA dataset and Colab notebook. Use when choosing or changing a default model, debugging slow or wrong model answers, adding a role, or preparing fine-tune data.
---

# Grandpa local models (Odin)

**Grandpa** is the product; **Odin** is the model family codename. Every role is
a stable tag such as `grandpa-brain:latest`, built from a Modelfile in the repo's
`models/` folder on top of a foundation model. Inference is local Ollama
(`http://localhost:11434`, override `GRANDPA_OLLAMA_HOST`). Details:
[references/odin-models.md](references/odin-models.md).

## Where things live

| Concern | Path |
|---|---|
| Role table (source of truth) | `src/grandpa/intelligence/odin_registry.py` (`ODIN_ROLES`, `get_odin_role`, setup plans) |
| Model names / catalog | `intelligence/grandpa_models.py`, `intelligence/model_catalog.py`, docs `docs/development/model-names.md` |
| Evaluation | `intelligence/model_eval.py`, `grandpa models eval <tag> [--baseline <tag>]` |
| Runtime | `runtime/ollama_adapter.py` (`OllamaBackendAdapter`, `_MAX_NUM_PREDICT = 2048`, `resolve_keep_alive`), `runtime/native_adapter.py` (llama-cpp, optional `native` extra), `runtime/manager.py` |
| Engine shim | `engine/` – older API with many importers; wraps `runtime/` |
| Tool support | `action_layer/loop.py:supports_tools()` reads Ollama `/api/show` capabilities |
| Persona / identity prompt | `prompt/identity.py` (`GRANDPA_IDENTITY_PROMPT` override) |
| Native GGUF downloads | `src/grandpa/models/` (HuggingFace source, sha256 + safe-path checks) |
| Modelfiles | `models/Modelfile.{brain,fast,mini,coder,eyes,guard,brain-odin1}` |
| Fine-tune data / notebooks | `scripts/odin/make_dataset.py`, `scripts/odin/README.md`, `notebooks/odin_brain_lora.ipynb` |

## Workflows

**Check what is installed** – `GRANDPA_HOME=$(mktemp -d) uv run grandpa models roles` (installed /
fallback / missing), `grandpa models status`, `grandpa doctor`.

**Build missing roles** – `grandpa models setup` prints the plan (`ollama create grandpa-<role> -f
models/Modelfile.<role>`, `ollama cp nomic-embed-text grandpa-memory`); `--yes` executes. Creating
models changes the user's Ollama store: get the owner's yes before running `--yes` on their machine.

**Change a default model** – never by taste. Run `grandpa models eval <candidate> --baseline
grandpa-brain:latest` (tool-call accuracy, argument accuracy, refusal correctness, latency; it never
acts), report the numbers, and let the owner decide. Only tool-capable roles (Brain, Fast) can drive
the action-layer loop; Mini/Coder/Eyes/Guard cannot.

**Add a role** – add an `OdinRole` to `ODIN_ROLES` (+ Modelfile if Ollama-built), keep
`GRANDPA_MODEL_ROLES` consistent (a test catches chat roles the table forgot), update
`docs/development/model-names.md`, add tests in `tests/intelligence/`.

**Slow first answer** – usually model load + prompt evaluation of the tool catalogue. See the timing
table in `runtime/ollama_adapter.py` and `[engine.ollama] keep_alive` / `GRANDPA_OLLAMA_KEEP_ALIVE`.
Tool tiering (`CORE_DOMAINS`) exists to keep the prompt prefix small and byte-stable for Ollama's cache.

**Fine-tune data** – `uv run python scripts/odin/make_dataset.py` derives train/eval JSONL from the
action catalogue (no personal data). Re-generate after catalogue changes; the README's
`"actions_covered": 167` predates the current 174-action catalogue.

## Constraints

- Local-first: no cloud inference providers (CONTRIBUTING). Do not add one without the owner's decision.
- Never commit weights, GGUF, LoRA adapters or generated datasets.
- Modelfile system prompts are product persona; keep them consistent with `prompt/identity.py`.
- `grandpa-guard` is registered but not used by any action path – do not describe it as a safety layer.
- Live model tests use the `live` marker and are excluded from CI's deterministic runs; mock Ollama with
  `respx` in unit tests.

## Verify

`uv run python -m pytest tests/intelligence tests/runtime tests/engine tests/models -q`
