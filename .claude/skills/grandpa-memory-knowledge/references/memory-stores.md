# Memory store reference

## Files and owners

- `src/grandpa/memory_context.py` – `CANONICAL_PERSONAL_MEMORY_DB = DEFAULT_CONFIG_DIR / "personal_memory.db"`,
  override `GRANDPA_PERSONAL_MEMORY_DB`. Defines its own `MemoryStore` class (name collides with `memory/store.py`).
  Entry for actions: `execute_memory_action` (catalogue `_MEMORY`). Embedder: `MemoryEmbedder`, `HASH_EMBEDDER`,
  `GRANDPA_MEMORY_EMBEDDER` env. ~20 modules import it.
- `src/grandpa/memory/store.py` – `DEFAULT_MEMORY_DB = DEFAULT_CONFIG_DIR / "memory.db"` (`GRANDPA_MEMORY_DB`),
  tables `schema_version`, `memories`. Facade: `memory/service.py` ("Unified Memory Service facade for Memory System V1").
  Other modules: `retrieval.py`, `intelligence.py`, `intent.py` (MemoryIntent), `context.py` (short-term, deterministic),
  `conversation.py`, `preferences.py`, `project_memory.py`, `long_term.py`, `short_term.py`, `recall_test.py`.
- `src/grandpa/tools/storage/sqlite.py` – inherited FTS5 backend; default path `DEFAULT_CONFIG_DIR / "memory.db"`
  (same file as V1), tables `documents`, `documents_fts`. Config `[tools.storage] db_path` defaults to `memory.db` too.
- `src/grandpa/tools/storage/embeddings.py` – an `OllamaEmbedder` (name also defined in `connectors/embeddings.py`).
- `src/grandpa/knowledge/storage.py` – `knowledge.db` (`GRANDPA_KNOWLEDGE_DB`, `GRANDPA_KNOWLEDGE_EMBEDDING_MODE`).
- `src/grandpa/connectors/store.py` – `KnowledgeStore` (name also used in `knowledge/`).
- `src/grandpa/memory_recovery.py` – SQLite corruption recovery helpers.
- `src/grandpa/core_ai_brain.py` – deterministic conversational brain state (recent turns, tone, language continuity).

## Docs

`docs/architecture/memory.md`, `docs/user-guide/memory.md`, `memory-integration.md`, `multi-project-memory-v1.md`,
`docs/testing/conversation-memory-manual-qa.md`.

## Optional extras

`memory-faiss`, `memory-colbert`, `memory-pdf`, `memory-bm25` – inherited retrieval backends; the default path is
SQLite FTS5 plus Ollama embeddings. Treat the extras as optional and verify a backend is actually wired before
relying on it.

## Open risks

1. Two schemas in one file (`memory.db`) with no single owner.
2. Two user-facing memory systems: facts said in chat land in `personal_memory.db`, facts added with
   `grandpa memory remember` land in `memory.db`. Check which one a feature reads before promising recall.
3. Paraphrase recall is weak (25% recall@1 in the README measurement).
