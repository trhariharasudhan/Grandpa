# Grandpa Odin Model Roles

Grandpa is the assistant and product identity. Odin is the internal model-family
codename. Foundation-model names remain visible in technical diagnostics, but
normal model selection uses stable Grandpa roles.

| Role | Runtime tag | Purpose | Calls tools | Min. memory | Foundation family |
|---|---|---|---|---|---|
| **Brain** | `grandpa-brain:latest` | **Default** — reliable tool use | yes | 6 GB | Qwen3 |
| Fast | `grandpa-fast:latest` | Middle ground, also calls tools | yes | 4 GB | Qwen3 |
| Mini | `grandpa-mini:latest` | Fastest; small machines | no | 1 GB | Qwen2.5 |
| Coder | `grandpa-coder:latest` | Coding specialist | no | 6 GB | DeepSeek Coder |
| Eyes | `grandpa-eyes:latest` | Local vision | no | 6 GB | LLaVA |
| Guard | `grandpa-guard:latest` | Safety classifier for actions | no | 8 GB | Llama Guard 3 |
| Memory | `grandpa-memory:latest` | Embeddings for semantic memory (a copy of `nomic-embed-text`, which it falls back to) | — | 0.5 GB | Nomic BERT |
| Ears | `grandpa-ears` (faster-whisper) | Speech-to-text; size from `[speech] model` | — | — | Whisper |
| Voice | `grandpa-voice` (local TTS) | Text-to-speech; backend from `[tts] backend` | — | — | — |

The code registry for every role above is
`grandpa.intelligence.odin_registry.ODIN_ROLES`. `grandpa models` lists each role
as installed, fallback or missing. `grandpa models setup` prints what it would do
for each missing Ollama role (`ollama create grandpa-<role> -f
models/Modelfile.<role>`, and `ollama cp nomic-embed-text grandpa-memory`); add
`--yes` to run it.

`grandpa models eval <tag> [--baseline <tag>]` scores any tag on the O2 held-out
split and the five-goal benchmark below (tool-call accuracy, argument accuracy,
refusal correctness, latency) without performing any action, and prints a
recommendation. It never changes the default.

## How the default is chosen

`core.config.recommend_model()` picks on available memory, not a constant:

- **6 GB usable or more** → `grandpa-brain:latest`
- **below that** → `grandpa-mini:latest`

Usable memory is GPU VRAM when a GPU is present, otherwise `(RAM − 4) × 0.8`.
So a 16 GB laptop gets Brain and an 8 GB one gets Mini; both work, but only the
Brain tier drives the action layer's tools.

## Why Brain is the default

The action layer hands the model the action catalogue as tool definitions, so
the default has to be a model that actually calls them. Measured over five goals
with three attempts each — raise the volume, read the volume, open Notepad and
type, a three-step file chain, describe the screen:

| | grandpa-mini | grandpa-brain |
|---|---|---|
| Goals completed | **0 / 15** | **15 / 15** |

Mini's failures were not marginal: it invented an `app` argument for
`volume_up` on every attempt, answered "what is my volume set to" with a made-up
number and no tool call at all, and opened Notepad without ever attempting to
type. The cost is speed — Brain takes about 48 s to a simple warm answer where
Mini takes 8 s, and several minutes on a cold first request. `grandpa-fast`
(4 GB, also calls tools) is the middle option for a machine that finds Brain
slow.

Legacy upstream tags remain supported during migration. They are not deleted
automatically. `nomic-embed-text` is intentionally hidden from conversational
model selectors because it cannot generate chat responses.
