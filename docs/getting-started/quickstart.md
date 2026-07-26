# Quick Start

## 1. Start Local Inference

```powershell
ollama serve
ollama pull qwen2.5:3b
```

## 2. Check Grandpa

```powershell
cd D:\Grandpa
uv run grandpa doctor
uv run grandpa status
```

## 3. Chat

```powershell
uv run grandpa chat
```

Try:

```text
What is my system status?
Open Notepad.
Show my reminders.
What is on my screen?
```

## 4. Voice

```powershell
uv run grandpa voice --diagnose
uv run grandpa voice
```

Voice and typed commands share the same intent, permission, and confirmation
layers.

## 5. Windows Automation

```powershell
uv run grandpa apps scan
uv run grandpa screen active
uv run grandpa automation --help
```

Destructive and sensitive actions are never executed solely because a model or
OCR result suggested them.

## 6. Optional API

```powershell
uv sync --extra server
uv run grandpa serve --host 127.0.0.1 --port 8000
```

The API is OpenAI-compatible for trusted local clients. The CLI and voice
assistant do not require it.
