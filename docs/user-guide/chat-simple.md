# Simple Chat

A lightweight conversational AI with no tools and no agent overhead. This is the simplest possible grandpa setup: just Ollama and a local model. Ideal for general-purpose chat, Q&A, brainstorming, and getting started quickly.

## Quickstart (3 minutes)

### 1. Install Ollama and pull a model

```bash
# Install Ollama: https://ollama.com
ollama pull qwen3.5:4b
```

### 2. Install and initialize grandpa

```bash
git clone https://github.com/grandpa/grandpa.git
cd grandpa
uv sync
Grandpa init --preset chat-simple
```

### 3. Ask a question

```bash
Grandpa ask "What is quantum computing?"
```

That's it. No API keys, no tools, no cloud -- just a local model answering your questions.

## CLI Commands

```bash
# Single question
Grandpa ask "Explain the difference between TCP and UDP"

# Interactive chat session (multi-turn conversation)
Grandpa chat

# Start the API server for the browser or desktop app
Grandpa serve

# Override the model for a single query
Grandpa ask -m qwen3.5:9b "Explain general relativity"

# Adjust temperature (0.0 = deterministic, 1.0 = creative)
Grandpa ask -t 0.2 "List the planets in our solar system"

# Output raw JSON
Grandpa ask --json "What is 2+2?"
```

## Configuration Reference

The preset writes this to `~/.grandpa/config.toml`:

```toml
[engine]
default = "ollama"

[intelligence]
default_model = "qwen3.5:4b"       # Fast and lightweight
# default_model = "qwen3.5:9b"     # Better quality
# default_model = "llama3.1:8b"    # Alternative model

[agent]
default_agent = "simple"            # Single-turn, no tools

[server]
host = "0.0.0.0"
port = 8000
```

### Model options

| Model | Parameters | Speed | Quality | Best for |
|-------|-----------|-------|---------|----------|
| `qwen3.5:4b` | 4B | Fast | Good | Quick answers, lightweight hardware |
| `qwen3.5:9b` | 9B | Balanced | Better | General-purpose chat, explanations |
| `qwen3.5:35b` | 35B | Slower | Best | Complex reasoning, detailed analysis |
| `llama3.1:8b` | 8B | Balanced | Good | Alternative if you prefer Meta models |

To switch models, either edit `~/.grandpa/config.toml` or override per-query:

```bash
Grandpa ask -m qwen3.5:35b "Write a detailed comparison of REST and GraphQL"
```

To pull a new model:

```bash
ollama pull qwen3.5:35b
```

## Switching Models

You can change the default model at any time:

**Edit the config:**

```bash
# Open the config file
${EDITOR:-nano} ~/.grandpa/config.toml
# Change default_model to your preferred model
```

**Pull and switch in one step:**

```bash
ollama pull deepseek-r1:14b
Grandpa ask -m deepseek-r1:14b "Hello"
```

**Use an environment variable:**

```bash
grandpa_MODEL=qwen3.5:9b Grandpa ask "Hello"
```

## Troubleshooting

**"No running engine found"** -- Make sure Ollama is running. Start it with `ollama serve` or open the Ollama desktop app.

**"Model not found"** -- Pull the model first with `ollama pull <model-name>`. List available models with `ollama list`.

**Slow responses** -- Use a smaller model (`qwen3.5:4b`). Check available memory; models need RAM roughly equal to their parameter count in GB (e.g., 9B model needs ~9 GB).

**Want to add tools later?** -- Switch to the [Code Assistant](code-assistant.md) or [Deep Research](deep-research.md) config. Simple chat is intentionally minimal.
