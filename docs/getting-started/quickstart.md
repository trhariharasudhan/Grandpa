---
title: Quick Start
description: Get up and running with grandpa in minutes
search:
  boost: 3
---

# Quick Start

!!! tip "Running `Grandpa` commands"
    Every `Grandpa ...` example below assumes you have either activated the project venv
    (`source .venv/bin/activate`) or are prefixing each command with `uv run`. A bare
    `Grandpa init --preset ...` from a fresh clone will fail with `command not found`.

## What You Can Build

grandpa is a modular AI assistant framework. Here's what developers build with it:

=== "Chat with Any Model"

    ```bash
    Grandpa ask "Explain quantum entanglement" -m qwen3.5:4b   # use qwen3.5:9b or larger on GPU
    ```

=== "Agent + Tools"

    ```bash
    Grandpa ask --agent orchestrator --tools calculator,web_search "What is the GDP of France in USD?"
    ```

=== "Index Docs & Ask"

    ```bash
    Grandpa memory index ./docs/
    Grandpa ask "How do I configure the engine?"
    ```

    !!! warning "Requires the Rust extension"
        `Grandpa memory index` and `Grandpa memory search` import `grandpa_rust`. If you
        skipped the `uv run maturin develop -m rust/crates/grandpa-python/Cargo.toml`
        step in [Installation](installation.md), these commands fail with
        `ModuleNotFoundError: No module named 'grandpa_rust'`. Build the extension
        once and any preset (including `deep-research`) will work.

=== "5-Line Python SDK"

    ```python
    from grandpa import Grandpa
    with Grandpa() as j:
        print(j.ask("Hello!"))
    ```

=== "API Server"

    ```bash
    Grandpa serve --port 8000
    # Now use any OpenAI-compatible client
    ```

=== "Morning Digest"

    ```bash
    cp configs/grandpa/examples/morning-digest-mac.toml ~/.grandpa/config.toml
    Grandpa connect gdrive       # one OAuth flow for Gmail, Calendar, Tasks
    CARTESIA_API_KEY="..." Grandpa digest --fresh
    # Plays a spoken daily briefing with your email, calendar, health, and news
    ```

=== "Deep Research"

    ```bash
    Grandpa init --preset deep-research
    Grandpa memory index ~/Documents/papers/
    Grandpa ask "Summarize all documents about transformer architectures"
    # Multi-hop search across your indexed docs with citations
    ```

=== "Code Assistant"

    ```bash
    Grandpa init --preset code-assistant
    Grandpa ask "Write a Python script that parses CSV files"
    # Orchestrator agent with code execution, file I/O, and shell access
    ```

=== "Scheduled Monitor"

    ```bash
    Grandpa init --preset scheduled-monitor
    Grandpa memory index ~/Documents/
    Grandpa scheduler start
    Grandpa scheduler create \
      --prompt "Check for new emails about Project X" \
      --schedule "0 9 * * 1-5" --agent operative
    # Persistent agent that runs on a cron schedule
    ```

For complete copy-paste patterns, see [Code Snippets](snippets.md).

## Starter Configs

Copy one of these to `~/.grandpa/config.toml` to get a pre-configured setup:

| Config | For | What it does |
|--------|-----|-------------|
| [`chat-simple.toml`](https://github.com/grandpa/grandpa/blob/main/configs/grandpa/examples/chat-simple.toml) | Any machine | Lightweight chat, no tools -- simplest setup |
| [`code-assistant.toml`](https://github.com/grandpa/grandpa/blob/main/configs/grandpa/examples/code-assistant.toml) | Any machine | Orchestrator agent with code execution, file I/O, shell |
| [`deep-research.toml`](https://github.com/grandpa/grandpa/blob/main/configs/grandpa/examples/deep-research.toml) | Any machine | Multi-hop research across indexed documents with citations |
| [`scheduled-monitor.toml`](https://github.com/grandpa/grandpa/blob/main/configs/grandpa/examples/scheduled-monitor.toml) | Any machine | Persistent operative agent on a cron schedule |
| [`morning-digest-mac.toml`](https://github.com/grandpa/grandpa/blob/main/configs/grandpa/examples/morning-digest-mac.toml) | Mac (Apple Silicon) | Daily spoken briefing from email, calendar, health, news |
| [`morning-digest-linux.toml`](https://github.com/grandpa/grandpa/blob/main/configs/grandpa/examples/morning-digest-linux.toml) | Linux / GPU server | Same, with vLLM support |
| [`morning-digest-minimal.toml`](https://github.com/grandpa/grandpa/blob/main/configs/grandpa/examples/morning-digest-minimal.toml) | Any machine | Just Gmail + Calendar |

Or generate a config with digest included:

```bash
Grandpa init --digest
```

This guide walks through the core workflows of grandpa: the browser app, CLI, Python SDK, agents with tools, memory, benchmarks, and the API server.

!!! info "Prerequisites"
    Make sure you have [installed grandpa](installation.md) and have at least one inference backend running (e.g., `ollama serve`).

## Browser App

The quickest way to experience grandpa is the full chat UI running in your browser:

```bash
git clone https://github.com/grandpa/grandpa.git
cd grandpa
./scripts/quickstart.sh
```

This launches the backend API server and a React frontend at [http://localhost:5173](http://localhost:5173).
You get a ChatGPT-like interface with streaming responses, tool use, energy monitoring, and a telemetry dashboard — all running locally on your hardware.

To stop all services, press ++ctrl+c++ in the terminal.

!!! tip "Environment variable"
    Set `grandpa_MODEL` to change the default model: `grandpa_MODEL=deepseek-r1:14b ./scripts/quickstart.sh`

## Initialize Configuration

Start by detecting your hardware and generating a configuration file:

```bash
Grandpa init
```

This runs hardware auto-detection (GPU vendor, VRAM, CPU, RAM) and writes a config file to `~/.grandpa/config.toml` with sensible defaults for your system. It also selects the recommended inference engine.

```
Detecting hardware...
  Platform : linux
  CPU      : AMD EPYC 7763 (128 cores)
  RAM      : 512.0 GB
  GPU      : NVIDIA A100 (80.0 GB VRAM, x8)

Config written successfully.
```

To overwrite an existing config:

```bash
Grandpa init --force
```

See [Configuration](configuration.md) for the full config reference.

## Your First Question

### Via CLI

The simplest way to interact with grandpa is the `ask` command:

```bash
Grandpa ask "What is the capital of France?"
```

grandpa will auto-detect a running engine, select a model using the configured router policy, and return the response.

#### CLI Options

| Option | Description | Example |
|--------|-------------|---------|
| `-m`, `--model` | Override model selection | `Grandpa ask -m qwen3:8b "Hello"` |
| `-e`, `--engine` | Force a specific engine | `Grandpa ask -e ollama "Hello"` |
| `-t`, `--temperature` | Sampling temperature (default: 0.7) | `Grandpa ask -t 0.2 "Hello"` |
| `--max-tokens` | Max tokens to generate (default: 1024) | `Grandpa ask --max-tokens 2048 "Hello"` |
| `--json` | Output raw JSON result | `Grandpa ask --json "Hello"` |
| `--no-stream` | Disable streaming | `Grandpa ask --no-stream "Hello"` |
| `--no-context` | Disable memory context injection | `Grandpa ask --no-context "Hello"` |
| `-a`, `--agent` | Use an agent | `Grandpa ask -a orchestrator "Hello"` |
| `--tools` | Comma-separated tools | `Grandpa ask --tools calculator,think "2+2"` |
| `--router` | Router policy for model selection | `Grandpa ask --router heuristic "Hello"` |

### Via Python SDK

The `Grandpa` class provides a high-level Python interface:

```python
from grandpa import Grandpa

j = Grandpa()
response = j.ask("What is the capital of France?")
print(response)
j.close()
```

For detailed results including token usage and model info:

```python
result = j.ask_full("What is the capital of France?")
print(result["content"])  # The response text
print(result["model"])    # Model that handled the query
print(result["engine"])   # Engine that ran inference
print(result["usage"])    # Token usage statistics
```

#### SDK Constructor Options

```python
# Use default config (auto-detected hardware, ~/.grandpa/config.toml)
j = Grandpa()

# Override the model
j = Grandpa(model="qwen3:8b")

# Override the engine
j = Grandpa(engine_key="ollama")

# Use a custom config file
j = Grandpa(config_path="/path/to/config.toml")
```

!!! warning "Always call `close()`"
    The `Grandpa` instance holds references to telemetry stores and memory backends. Call `j.close()` when you are done to release resources.

## Using Agents with Tools

Agents add multi-turn reasoning and tool-calling capabilities. The `orchestrator` agent runs a tool-calling loop, invoking tools as needed to answer the query.

### Available Agents

| Agent | Description |
|-------|-------------|
| `simple` | Single-turn, no tools. Sends the query directly to the model. |
| `orchestrator` | Multi-turn tool-calling loop. Invokes tools iteratively until it has an answer. |
| `custom` | Template for user-defined agent logic. |
| `operative` | Task-oriented agent with structured planning and execution. |

### Available Built-in Tools

| Tool | Description |
|------|-------------|
| `calculator` | Safe mathematical expression evaluation (ast-based). |
| `think` | Reasoning scratchpad for chain-of-thought. |
| `retrieval` | Search the memory store for relevant context. |
| `llm` | Make sub-queries to another model. |
| `file_read` | Read files with path validation. |
| `web_search` | Web search via the Tavily API (requires `tools-search` extra). |

### CLI Example

```bash
Grandpa ask --agent orchestrator --tools calculator,think "What is 137 * 42?"
```

### SDK Example

```python
from grandpa import Grandpa

j = Grandpa()
result = j.ask_full(
    "What is the square root of 144?",
    agent="orchestrator",
    tools=["calculator", "think"],
)
print(result["content"])
print(result["tool_results"])  # List of tool invocations and results
print(result["turns"])         # Number of agent turns
j.close()
```

## Memory: Indexing and Search

The memory system lets you index documents and inject relevant context into queries automatically.

### Index Documents

Index a file or directory. grandpa chunks the content and stores it in the configured memory backend (SQLite/FTS5 by default).

=== "CLI"

    ```bash
    # Index a directory
    Grandpa memory index ./docs/

    # Index a single file with custom chunk size
    Grandpa memory index ./paper.txt --chunk-size 256 --chunk-overlap 32
    ```

=== "Python SDK"

    ```python
    from grandpa import Grandpa

    j = Grandpa()
    result = j.memory.index("./docs/", chunk_size=512, chunk_overlap=64)
    print(f"Indexed {result['chunks']} chunks")
    j.close()
    ```

### Search Memory

Query the memory store to find relevant chunks:

=== "CLI"

    ```bash
    Grandpa memory search "configuration options"
    Grandpa memory search -k 10 "how to deploy"
    ```

=== "Python SDK"

    ```python
    results = j.memory.search("configuration options", top_k=5)
    for r in results:
        print(f"[{r['score']:.4f}] {r['source']}: {r['content'][:100]}")
    ```

### Check Memory Statistics

=== "CLI"

    ```bash
    Grandpa memory stats
    ```

=== "Python SDK"

    ```python
    stats = j.memory.stats()
    print(f"Backend: {stats['backend']}, Documents: {stats.get('count', 'N/A')}")
    ```

### Automatic Context Injection

When you have indexed documents, grandpa automatically injects relevant context into your queries. The memory system searches for chunks matching your query and prepends them as system context before sending to the model.

To disable this behavior:

=== "CLI"

    ```bash
    Grandpa ask --no-context "Hello"
    ```

=== "Python SDK"

    ```python
    response = j.ask("Hello", context=False)
    ```

Context injection is controlled by `agent.context_from_memory` in `config.toml`. The retrieval parameters (`context_top_k`, `context_min_score`, `context_max_tokens`) live under `[tools.storage]`. See [Configuration](configuration.md) for details.

## Model Management

### List Available Models

See all models available on running engines:

```bash
Grandpa model list
```

This produces a table showing each model, its engine, parameter count, context length, and VRAM requirements.

### Get Model Details

```bash
Grandpa model info qwen3:8b
```

### Pull a Model (Ollama)

```bash
Grandpa model pull qwen3:8b
```

### SDK Model Listing

```python
from grandpa import Grandpa

j = Grandpa()
models = j.list_models()
engines = j.list_engines()
print(f"Models: {models}")
print(f"Engines: {engines}")
j.close()
```

## Running Benchmarks

The benchmarking framework measures inference latency and throughput against your engine.

=== "All benchmarks"

    ```bash
    Grandpa bench run
    ```

=== "Specific benchmark"

    ```bash
    Grandpa bench run -b latency
    Grandpa bench run -b throughput
    ```

=== "Custom options"

    ```bash
    # 20 samples, JSON output
    Grandpa bench run -n 20 --json

    # Specific model and engine, write to file
    Grandpa bench run -m qwen3:8b -e ollama -o results.jsonl
    ```

Example output:

```
Running 2 benchmark(s) on ollama/qwen3:8b (10 samples)...

latency (10 samples, 0 errors)
  mean_ms: 245.3200
  p50_ms: 238.1000
  p95_ms: 312.4500
  min_ms: 201.2000
  max_ms: 345.6000

throughput (10 samples, 0 errors)
  tokens_per_second: 42.1500
  total_tokens: 4215
  total_seconds: 100.0000
```

## Starting the API Server

grandpa provides an OpenAI-compatible API server for integration with existing tools and frontends.

!!! note "Requires the `server` extra"
    ```bash
    uv sync --extra server
    ```

### Start the Server

```bash
Grandpa serve --port 8000
```

With custom options:

```bash
Grandpa serve --host 0.0.0.0 --port 8000 --engine ollama --model qwen3:8b --agent orchestrator
```

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/v1/chat/completions` | `POST` | Chat completions (streaming and non-streaming) |
| `/v1/models` | `GET` | List available models |
| `/health` | `GET` | Health check |

### Use with Any OpenAI-Compatible Client

Once the server is running, point any OpenAI-compatible client at it:

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8000/v1", api_key="not-needed")
response = client.chat.completions.create(
    model="qwen3:8b",
    messages=[{"role": "user", "content": "Hello!"}],
)
print(response.choices[0].message.content)
```

Or with `curl`:

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3:8b",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```

## Telemetry

grandpa records telemetry for every inference call (timing, tokens, cost). View aggregated statistics:

```bash
Grandpa telemetry stats
```

Export telemetry data:

```bash
Grandpa telemetry export --format json
Grandpa telemetry export --format csv -o telemetry.csv
```

Clear all telemetry records:

```bash
Grandpa telemetry clear --yes
```

## Complete Working Example

Here is a complete end-to-end session combining multiple features:

```python
from grandpa import Grandpa

# Initialize with defaults (auto-detect hardware and engine)
j = Grandpa()

# 1. Index some documentation
index_result = j.memory.index("./docs/", chunk_size=512)
print(f"Indexed {index_result['chunks']} chunks from {index_result['path']}")

# 2. Search memory
results = j.memory.search("how to configure engines")
for r in results:
    print(f"  [{r['score']:.3f}] {r['source']}")

# 3. Ask a question (memory context is injected automatically)
answer = j.ask("How do I configure the Ollama engine host?")
print(f"\nAnswer: {answer}")

# 4. Use an agent with tools
calc_result = j.ask_full(
    "Calculate the compound interest on $10,000 at 5% for 10 years",
    agent="orchestrator",
    tools=["calculator", "think"],
)
print(f"\nCalculation: {calc_result['content']}")
print(f"Tools used: {[t['tool_name'] for t in calc_result['tool_results']]}")
print(f"Agent turns: {calc_result['turns']}")

# 5. List available models
models = j.list_models()
print(f"\nAvailable models: {models}")

# 6. Clean up
j.close()
```

## Next Steps

- [Configuration](configuration.md) — Fine-tune engine hosts, model routing, memory settings, and more
- [CLI Reference](../user-guide/cli.md) — Full reference for all CLI commands and options
- [Python SDK](../user-guide/python-sdk.md) — Detailed SDK documentation
- [Architecture Overview](../architecture/overview.md) — Understand the five-primitive design
