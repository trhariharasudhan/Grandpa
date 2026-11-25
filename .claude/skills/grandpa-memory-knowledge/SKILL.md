---
name: grandpa-memory-knowledge
description: Work on Grandpa's memory and knowledge stores - personal memory (memory_context.py, personal_memory.db, Ollama embeddings with hashed fallback), Memory System V1 (memory/ package, memory.db), document indexing and RAG (knowledge/, connectors/, tools/storage), project memory, recall measurement, SQLite recovery, and schema migrations of live user data. Use when remember/recall/forget behaves wrongly, when adding a memory feature, changing embeddings, or touching any SQLite store under GRANDPA_HOME.
---

# Grandpa memory and knowledge

Memory is the **highest-risk subsystem to change**: it holds the owner's real
data in `GRANDPA_HOME` (default `~/.grandpa`), it is split across several
overlapping stores, and two of them share one file. Store map and schema
notes: [references/memory-stores.md](references/memory-stores.md).

## The stores (verified 2026-11-25)

| Store | Module | File | Used by |
|---|---|---|---|
| Personal memory: facts, preferences, activity, apps today | `memory_context.py` (~1.5k lines) | `personal_memory.db` | chat, voice, action layer (`memory_*` actions via `execute_memory_action`), server |
| Memory System V1 | `memory/` (store, service facade, retrieval, short/long term, preferences, project memory) | `memory.db` (`memories` table) | `grandpa memory …` CLI, server, planner |
| Inherited RAG backend | `tools/storage/sqlite.py` (FTS5) | **also `memory.db`** (`documents` table) | `grandpa memory index`, agents/tools path |
| Knowledge engine | `knowledge/` | `knowledge.db` | knowledge commands |
| Source-aware KnowledgeStore | `connectors/store.py` | configurable | ingestion pipeline, `knowledge_search` tool |

Embeddings: `memory_context` asks local Ollama (`grandpa-memory` → `nomic-embed-text`) and falls
back to an offline FNV-hashed bag-of-words named `SEMANTIC_MODEL = "grandpa-local-semantic-v1"`
(a name that sounds like a neural model; it is not).

## Workflow

1. Find which store the behaviour comes from: trace the caller (`rg -n "memory_context|grandpa.memory" src/grandpa/<caller>`).
   "Remember that…" in chat/voice goes to `memory_context`; `grandpa memory remember` goes to `memory/`.
2. Reproduce in a sandbox: `GRANDPA_HOME=$(mktemp -d) uv run grandpa memory remember "…"` then
   `grandpa memory search/relevant/explain "…"`.
3. Measure, don't guess: `grandpa memory recall-test` reports recall@1 / recall@3. The README's
   baseline: direct wording 100%, paraphrased 25% / 33%. A retrieval change must move these numbers.
4. Change the smallest layer; keep the offline fallback working when Ollama is down.
5. Tests: `uv run python -m pytest tests/memory tests/test_memory_*.py tests/test_natural_memory.py tests/test_multi_project_memory.py tests/action_layer/test_memory_actions.py -q`.

## Schema or data changes (live user data)

- Never drop, rename or rewrite a table in place. Add columns/tables with `IF NOT EXISTS`, version via
  the store's `schema_version` table (`memory/store.py`) and keep readers tolerant of old rows.
- Write a migration that is idempotent, runs on a copy first, and backs up the DB file before touching it.
  Use `memory_recovery.py` helpers for corruption handling, never `rm`.
- Resolving the `memory.db` double-ownership (RAG `documents` vs V1 `memories`) is a planned migration
  (`docs/architecture/MIGRATION_PLAN.md`); do it only with the owner's go-ahead and a data-preserving plan.
- Paths: resolve through `grandpa.runtime_paths` / `core.config` at call time. Module-level constants
  such as `DEFAULT_MEMORY_DB` are frozen at import, which is why tests set `GRANDPA_HOME` first.

## Privacy constraints

- Memory stays local; only local Ollama is called for embeddings.
- `memory_forget` and `memory_clear` exist; `memory_clear` is HIGH and asks. Never clear or purge
  real data as a debugging step.
- Do not log memory contents at INFO; tests must use synthetic facts.
