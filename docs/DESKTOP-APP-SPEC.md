# Grandpa Desktop App: Specification

Status: **Implemented** unless marked otherwise. Last updated 2026-11-24.

Grandpa's desktop app (`grandpa app`) follows the shape of the desktop chat apps people already know (Claude Desktop, ChatGPT Desktop): a quiet left panel, the conversation in a centred column, and the typing box as the main control. It differs where Grandpa differs: everything runs on this PC, it can act on Windows, it has a floating orb, and it uses only the seven project colours and line icons (no emoji).

## 1. Programs

| Program | Command | What it is |
|---|---|---|
| Desktop app | `grandpa app` | The full window: chats, projects, memory, settings |
| Orb | `grandpa avatar` | A small always-on-top ring; click it for a compact chat; hold Ctrl+Win anywhere to talk |
| Terminal | `grandpa` | Full-screen terminal interface (Textual) |

- The app and the orb are **separate programs**. Each can start the other detached: app ＋ menu → *Show the orb*; orb chat bar → *Open app*. Closing one never closes the other.
- One copy of each: `<grandpa home>/run/app.pid` and `avatar.pid`. A second launch is refused while the first is alive. A stale pid is ignored.
- All three use the same chat engine (`grandpa chat`), the same profile, the same models and the same safety confirmations.

## 2. Architecture

```
pywebview window (WebView2)                 Python process
┌──────────────────────────────┐   WebSocket (loopback, per-run token)
│ index.html / app.css / app.js│ ───────────────────────────────► AvatarServer
│ markdown.js  icons.js        │ ◄─────── state, user, reply, delta, ask, model, note
│                              │
│ window.pywebview.api ────────┼── js_api ──► AppApi (files, profile, memory, orb,
└──────────────────────────────┘                     project instructions)
                                             AppSession ──► ChatBridge ──► grandpa chat
                                                                         └► action layer tool loop
                                                                            └► Ollama (streaming)
```

- **AppSession** turns chat-engine events into page messages: `state`, `user`, `reply`, `note`, `ask`, `model`, `delta` (streaming words, never stored), `listening` / `heard` (voice typing).
- **Page → Python** over the socket: only `send` (text ≤ 2,000 characters), `talk` and `cancel` (`parse_inbound`).
- **Page → Python** over `js_api`: `pick_files`, `get_profile`, `save_profile`, `list_memories`, `forget_memory(id)`, `add_memory(text)`, `set_next_context(text)`, `open_orb`. The window and session objects are private (pywebview exposes every public attribute).
- **Streaming**: the tool loop asks `generate_streaming` when an interface registered a sink (`set_stream_sink`). It sends the same options as `generate` (`num_ctx`, `keep_alive`), so the model is not reloaded. If the stream fails before the first word it falls back to `generate`. A turn that turns out to be a tool call clears what was shown.
- **Safety**: the page is built with DOM calls only (no `innerHTML`, no `eval`). A strict CSP: scripts from the app folder, sockets to 127.0.0.1 only. Files can be read only if the user picked them in the dialog, dropped them, or typed `@file` in the current folder or the home folder. Actions keep the engine's confirmations.

## 3. Layout

### Left panel (Ctrl+B opens and closes it)
- Grandpa mark and name (also starts a new chat), and a collapse button.
- **New chat** (Ctrl+N), **Search** (Ctrl+K), **Projects**, **Memory**.
- **Pinned** chats, then **Recents** (newest first; a chat's project shows as a tag).
- Each chat's menu: rename, pin/unpin, move to project / new project, delete.
- Bottom: the user's avatar initial, title and name ("Mr. Hari Hara Sudhan"), and a menu: Settings, Memory, Show the orb, dark/light, keyboard shortcuts.

### Top bar
- State ring (one colour per state: grey idle, yellow thinking, orange asking, red stopped, blue listening).
- Chat title, with the same menu as in the panel.
- Incognito toggle.

### Empty chat
- "Good morning / afternoon / evening, <title> <name>" with the Grandpa mark.
- The typing box in the middle of the page, with suggestion chips under it.

### Conversation
- The user's messages sit right-aligned in a bubble. Hover shows copy, plus edit on the last one.
- Grandpa's replies are full width, in markdown. Hover shows copy, retry (on the last reply), the time, seconds taken and the model.
- Replies **stream in** as they are written, with a cursor. "Thinking…" shows until the first word arrives.
- Code blocks have a language label, a Copy button and light syntax colours. Tables are rendered.
- Grandpa's questions (yes/no, a choice, a typed answer) appear as cards.
- Notes (failures, file problems) are small; failures are red.

### Typing box
- **＋ menu**: Add files (several, from any folder via the dialog: text, code, PDF, Word, Excel, PowerPoint), Voice typing, Show the orb.
- Drag and drop files onto the window (real paths from pywebview 5+).
- File chips above the text; at most 5 files per message.
- Model menu (Grandpa's own `/model` list, F6). Mic button (voice typing). Send button (an up arrow), which becomes Stop while Grandpa works (Esc does the same).
- A message typed while Grandpa works waits its turn.

## 4. Pages

- **Projects**: a grid of cards (name, instructions preview, number of chats); New project.
- **Project**: its chats, and **instructions** that are sent with the first message of each chat in the project (`set_next_context`). They are not shown as typed text.
- **Memory**: what Grandpa remembers (the same store as `/memory`). You can search, forget one item by its id, or add a note.
- **Settings**:
  - Profile: title, name, email. This is the profile the terminal's `/profile` uses, and the first run asks for it.
  - Appearance: dark, light or system; text size.
  - Chat: start model, Enter sends, stream replies.
  - Data & privacy: export JSON, delete all.
  - Shortcuts.
  - About.
- **Search and commands (Ctrl+K)**: recent and matching chats, plus commands (new chat, new project, projects, memory, switch model, incognito, show the orb, theme, panel, settings).

## 5. Incognito
An incognito chat is never written to storage. Grandpa's conversation is cleared when it starts and when it ends. Things the user explicitly asks Grandpa to remember are still remembered; that is the memory feature working as asked.

## 6. Storage
- Chats, projects, pins and settings: this window's localStorage (`~/.grandpa/app_webview`), on this PC only.
- Profile: `~/.grandpa/config.toml` (`[user] title, username, email`).
- Memory: Grandpa's memory database.

## 7. The orb
- A 40 px ring in a 64 px see-through window. Only the ring is clickable; the rest clicks through.
- Click the ring: a 340×420 chat opens and the ring hides. ✕ closes the chat and the ring comes back. The bar drags the window. *Open app* and *Quit* are icons in the bar.
- Hold **Ctrl+Win** anywhere, speak, and release: Grandpa hears it. The keys are read with `GetAsyncKeyState`, read-only, as in `grandpa bubble`. `--hold-key` picks other keys and `--no-mic` turns talking off.
- The 3D character is **on hold**. The ring is shown unless `--character` is given.

## 8. Differences from the Claude app (deliberate)
| Claude Desktop | Grandpa |
|---|---|
| Cloud models, account, plans | Local models on this PC; no account; profile only |
| Artifacts panel | Not yet (**Planned**) |
| Connectors / MCP | Grandpa's own tools and actions; MCP is Phase 8 (**Planned**) |
| Share chat | Export JSON only (local-first) |
| Thumbs up/down feedback | Not included (nothing is sent anywhere) |
| No floating assistant | The orb, plus hold-to-talk |
| Web search toggle | Grandpa's web search is a tool the model calls |

## 9. Planned
- Edit any earlier message, with branching.
- A right context panel (memory used, tools run, context size).
- "Hey Grandpa" wake word on the orb (a wake engine exists in `voice/wake_engine.py`; to be wired to the orb).
- Images and scanned PDFs (needs a vision model or OCR).
- A tray icon for the app, start on boot, native notifications.

## 10. Tests
- `tests/app/test_app.py`:
  - session messages, attaching (dialog-picked versus typed), documents, the profile, streaming deltas, project instructions, memory deletion only by id
  - the page has no `innerHTML`/`eval` and uses only the project colours
- `tests/app/test_launch.py`: detached launching, one copy of each.
- `tests/runtime/test_ollama_streaming.py`: streaming matches `generate`, the fallback, and tool calls clearing what was shown.
- `tests/ui/test_avatar.py`: the orb's methods, Quit, hold-to-talk, no emoji, a shared icon set.
- `tests/tui/test_tui.py`: terminal streaming, queueing, no emoji.
- Browser end-to-end (Playwright, fake engine): streaming, retry, edit, Ctrl+K, projects with instructions, pinning, light mode.
- Checked on Windows: attaching a file from D:\, a streamed reply, separate programs, the clickable ring.
