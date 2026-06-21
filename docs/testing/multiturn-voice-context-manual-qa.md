# Multiturn Voice Context Manual QA

Grandpa uses short-term in-process conversation memory for recent voice context.
This does not use a vector database, RAG, or a new LLM provider.

## Preconditions

- Start the Grandpa server normally.
- Open the Voice Assistant page.
- Leave Ollama stopped if you want to confirm deterministic fallback behavior.

## Test Cases

### First Command

1. Enter: `what is my voice status`
2. Click **Run Command**.
3. Verify the response is shown.
4. Verify **Context used** is `no` with `0 messages`.
5. Verify Recent Conversation now contains a user message and assistant message.

### Follow-Up Command

1. Enter: `tell me more about that`
2. Click **Run Command**.
3. Verify the response does not require Ollama.
4. Verify **Context used** is `yes`.
5. Verify the context message count is greater than `0`.

Expected deterministic fallback:

```text
I can use recent context, but I don't know how to answer that yet.
```

### View Conversation Context

1. Click **View Context** in Recent Conversation.
2. Verify the context section shows recent messages in role order.
3. Verify only recent short-term messages appear.

### Clear Conversation

1. Click **Clear conversation**.
2. Click **View Context**.
3. Verify the context is empty or reports no recent context.
4. Run another unsupported command.
5. Verify **Context used** returns to `no`.

### Context Reset

1. After clearing, enter: `tell me more`
2. Click **Run Command**.
3. Verify the fallback is:

```text
I don't know how to do that yet.
```

4. Verify context count is `0`.
