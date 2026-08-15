# Grandpa Odin Model Roles

Grandpa is the assistant and product identity. Odin is the internal model-family
codename. Foundation-model names remain visible in technical diagnostics, but
normal model selection uses stable Grandpa roles.

| Role | Runtime tag | Purpose | Foundation family |
|---|---|---|---|
| Mini | `grandpa-mini:latest` | Default low-resource chat | Qwen2.5 |
| Fast | `grandpa-fast:latest` | Better general responses | Qwen3 |
| Coder | `grandpa-coder:latest` | Coding specialist | DeepSeek Coder |
| Eyes | `grandpa-eyes:latest` | Local vision | LLaVA |
| Embeddings | `nomic-embed-text:latest` | Internal semantic memory/RAG | Nomic BERT |

Legacy upstream tags remain supported during migration. They are not deleted
automatically. `nomic-embed-text` is intentionally hidden from conversational
model selectors because it cannot generate chat responses.
