# Memory Integration V1 — User Guide & Architecture

Grandpa Memory Integration V1 connects persistent SQLite memory (`~/.grandpa/memory.db`) safely, selectively, and transparently across Chat, Voice, Executive Planner, and Project workflows.

---

## 1. Architecture Overview

```
User Request (Chat / Voice / CLI / Planner)
       │
       ▼
Memory Intent Router (Deterministic Regex & Scope Classifier)
       │
       ├───────────────────────────────────────────┐
       ▼ (Explicit Memory Command)                ▼ (General Query)
Direct Memory Action                         Bounded Relevance Retrieval Engine
 (remember, recall, forget,                     (max 5 items, max 1,500 chars)
  clear, preferences, projects)                    │
       │                                           ▼
       │                                  Sanitization & Redaction
       │                                           │
       ▼                                           ▼
MemoryService Facade <────────────── Context Injection / Planning
       │
       ▼
SQLite Persistent Store (~/.grandpa/memory.db)
```

---

## 2. Memory Scopes

1. **`session`**: Short-term, in-memory transient buffer. Isolated per session ID. Never automatically persisted unless explicitly promoted.
2. **`project`**: Tracked project state (project path, latest completed feature, latest verified Git commit, last failed plan, next task).
3. **`preference`**: User-defined preferences (`preferred_shell`, `default_browser`, `preferred_microphone`, `response_language`).
4. **`knowledge`**: Durable long-term facts stored across sessions.

---

## 3. Retrieval Limits & Bounded Context

- **Maximum Item Limit**: 5 items per query.
- **Maximum Character Bound**: 1,500 characters total.
- **Priority Ranking**:
  1. Exact key match (`+10`)
  2. Current project match (`+8`)
  3. Preference match (`+6`)
  4. Keyword match (`+2.5` per keyword)
  5. Recency decay & access count boost.
- **No Database Dumps**: Full database dumps into LLM prompts are strictly forbidden.

---

## 4. Non-Negotiable Privacy & Write Policy

### Allowed Automatic Writes
- Verified project completion status from Executive Planner.
- Verified Git commit hashes (`git rev-parse HEAD`).
- Explicit user preferences (`"Remember my default browser is Chrome"`).
- Explicit user instructions (`"Remember that..."`).

### Strictly Rejected Writes
- Passwords, secrets, tokens, API keys, bearer tokens.
- OTPs, credit card numbers, CVV, private auth material.
- Arbitrary prompt injection text or unverified webpage content.

---

## 5. CLI Usage Examples

```bash
# Store memories
grandpa memory remember "PowerShell" --category preference --key preferred_shell
grandpa memory remember "Memory System V1 completed" --category project --project Grandpa --key latest_feature

# List and Inspect
grandpa memory list
grandpa memory recent
grandpa memory show preferred_shell
grandpa memory projects
grandpa memory preferences

# Bounded Retrieval & Explanation
grandpa memory search "Browser"
grandpa memory relevant "shell"
grandpa memory explain "PowerShell"

# Session & Privacy Controls
grandpa memory disable
grandpa memory enable
grandpa memory session status
grandpa memory session clear

# Deletion & Clearing
grandpa memory delete preferred_shell -y
grandpa memory clear --category preference -y
```

---

## 6. Voice & Chat Integration

### Voice Commands
- *"Grandpa, remember that I prefer Chrome."*
- *"Grandpa, what did we work on last?"*
- *"Grandpa, forget my preferred browser."*
- *"Grandpa, continue the Grandpa project."*
- *"Grandpa, don't remember this."*

Voice responses output clean, concise spoken sentences without exposing raw database IDs, metadata JSON, or internal file paths.

---

## 7. Future Roadmap

- **Vector Embedding Hybrid Search (V2)**: Optional hybrid semantic scoring alongside exact SQLite keyword retrieval.
- **Auto-Summarizing Project Archival**: Compression of historical task logs into long-term project timeline milestones.
