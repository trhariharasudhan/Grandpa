# Conversation Memory Manual QA

These checks verify short-term conversation session context only. This feature
does not write to long-term memory, create embeddings, use RAG, or call an LLM
for summaries.

## Setup

1. Start Grandpa normally.
2. Open the Voice Assistant page.
3. Use typed voice commands or push-to-talk transcripts.

## Test Cases

| Case | Steps | Expected behavior |
| --- | --- | --- |
| Normal conversation | Run `what is my voice status`. | Recent Conversation shows the user transcript and assistant response. |
| Multiple commands | Run several supported commands. | Recent Conversation appends user/assistant pairs in timestamp order. |
| Summary | Click Summary or call `POST /v1/conversation/summary`. | A short deterministic summary of recent messages appears. |
| Clear | Click Clear conversation or call `POST /v1/conversation/clear`. | Recent Conversation becomes empty without clearing command history. |
| Limit behavior | Run more than 10 commands, creating more than 20 messages. | Only the latest 20 messages remain. |

## API Smoke Checks

- `GET /v1/conversation/status`
- `GET /v1/conversation/history`
- `POST /v1/conversation/summary`
- `POST /v1/conversation/clear`

Expected responses include:

- `session_id`
- `message_count`
- `created_at`
- `last_updated_at`

## Safety Notes

- This is process-local short-term session context.
- No vector database is used.
- No long-term memory store is changed.
- No RAG pipeline is invoked.
