# Desktop UI: survey and recommendation

Stage 1. No implementation. Everything below was read or measured on
`7a176e80`, 2026-10-06.

## 1. `wip/floating-bubble-final`

A **Tauri 2 + React + TypeScript + Vite** floating window.

| | |
| --- | --- |
| head | `f43639fb` "wip(desktop): premium orb and click-expand investigation" |
| date | 2026-06-20 — **3.5 months old** |
| own commits | 2 (`3bd483ac` 2026-06-19, `f43639fb` 2026-06-20) |
| merge base | `7235d289` 2026-06-17 |
| main ahead by | **226 commits** |
| frontend files on the branch | 118 |

Its own commit messages describe its state: the first is "finalize floating-first
bubble **pending Windows verification**", the second an "investigation". So it was
never verified working on Windows by its author, and nothing since has verified
it.

**Does it run?** Unknown, and the question is close to moot. `cargo` 1.96,
`rustc` 1.96, `node` v24.19 and `npm` 11.17 are all installed, so it could
plausibly be built. But:

**What has changed under it is that main deleted it.** On 2026-07-26, commit
`2cabd560` ("fix: update Grandpa project improvements") removed **112
`frontend/` files**, plus `.github/workflows/desktop.yml` (242 lines) and
`.github/workflows/frontend.yml`. `git ls-files frontend` on main returns zero.
The current CI is five workflows — `autotag`, `ci`, `docs`, `pypi-publish`,
`take-assign` — and none of them builds a desktop app or a frontend.

So resurrecting this branch is not "finishing old work". It reverses a decision
main already made, and the CI that would have proved it is gone too.

## 2. UI-adjacent inventory

| thing | lines | works today? | reachable? | tested |
| --- | --- | --- | --- | --- |
| `src/grandpa/tray.py` | 375 | **No** — needs `pystray`, which is not installed | `grandpa tray` | 24 tests |
| `src/grandpa/cli/interactive_tui.py` | 608 | Yes | via `grandpa chat` and slash commands, not its own command | 18 tests |
| `src/grandpa/cli/launcher.py` | 481 | Yes | `grandpa launcher` | 15 tests |
| `src/grandpa/apps/launcher.py` | 45 | Yes — app launching, not UI | used by `apps`/automation | covered |
| `src/grandpa/automation/locator.py` `_render_tk_overlay` | ~40 | **Yes** | via `automation` highlight actions | injected renderer |
| `frontend/` | — | absent from main | — | — |

Two findings matter more than the table.

**The repo already draws a floating always-on-top window, in tkinter, in
production code.** `_render_tk_overlay` uses `overrideredirect(True)`,
`attributes("-topmost", True)` and `wm_attributes("-transparentcolor", …)` to put
a borderless transparent highlight box over an arbitrary window. That is exactly
the mechanism a bubble needs, and it is already shipping and already works on
this machine.

**The repo already has a proven pattern for testing GUI code without opening a
window.** Two instances:

* `HighlightOverlay(lambda item, _duration: highlights.append(item))` — the
  renderer is injected, so `tests/test_screen_automation_v2.py` exercises the
  highlight path and records calls instead of drawing.
* `start_tray(..., pystray_module=types.SimpleNamespace(Icon=FailingIcon))` —
  the toolkit is injected, so `tests/test_tray.py` gets 24 tests out of a module
  whose dependency is not even installed.

Neither imports its toolkit at test time. That is the constraint the task sets,
and it is already solved here.

`tkinter` appears nowhere else in `src/` or `tests/`, so there is no existing
tkinter test harness — but there is no obstacle either, because the injection
seam is what the tests use, not the toolkit.

## 3. The HTTP surface

**It exists and is substantial. A UI would need no new routes for the core
flow.** 184 routes, 2 of them websockets:

```
POST  /v1/voice/listen        audio in, transcript out
POST  /v1/voice/command       transcript in, routed reply out
POST  /v1/voice/confirm       the confirmation gate
POST  /v1/voice/speak
GET   /v1/voice/history
POST  /v1/chat/completions
WS    /v1/chat/stream         streaming replies
WS    /v1/agents/events
GET   /health, /v1/speech/health, /v1/conversation/status, ...
```

The browser push-to-talk page documented in
`docs/testing/push-to-talk-manual-qa.md` already drives `/v1/voice/listen` and
`/v1/voice/command`, so this surface is not theoretical — it has a working
client.

Auth: `check_bind_safety` refuses a non-loopback bind without an API key, and
loopback needs none. `fastapi` and `uvicorn` are in the `server` extra, not the
base dependency set.

## 4. Technology recommendation

Dependency reality, measured:

| | installed | declared |
| --- | --- | --- |
| `tkinter` | yes (stdlib) | n/a |
| `pillow` | yes | **base dependency** |
| `fastapi` / `uvicorn` | yes | `server` extra |
| `pystray` | **no** | `tray` extra |
| `PySide6` / `PyQt6` | **no** | not declared |
| `jinja2` | **no** | not declared |

Also measured: the `rust/` workspace has 17 crates and **is not imported at
runtime** — `grandpa_rust`, `grandpa._native` and `grandpa_core` are all absent,
and `rust/target/release` holds no artifacts. Rust is a parallel effort, not a
shipping dependency. The shipping surface is Python.

### Recommended: tkinter, with the renderer injected

* **Already in the dependency set** — ships with CPython. Zero new packages. The
  only other thing a bubble needs is `pillow`, which is already a *base*
  dependency, not an extra.
* **Survives packaging** — no wheel, no native DLL to bundle, no second
  toolchain on the build machine. PyInstaller and the existing `pypi-publish`
  flow handle it without a new workflow.
* **Testable under the guard, by a pattern this repo already uses twice** — a
  `FloatingBubble` taking an injected widget factory tests exactly as
  `HighlightOverlay` and `start_tray` do: no window, no microphone, no speaker,
  no new fixture.
* **Maintainable by one developer** — one module, no build step, no
  `node_modules`, no Rust, no second test runner.
* **Capability is proven here, not assumed** — borderless, always-on-top and
  transparent already work in `_render_tk_overlay` on this machine.

The honest cost: tkinter looks dated. No native rounded corners, no acrylic blur,
plain widget text. For a small bubble holding a record indicator, a text entry, a
status line and a reply pane, that is a real but acceptable loss — and it is the
loss the "premium orb" branch was trying to avoid, at the price of three
toolchains.

### Rejected: Tauri + React (resurrecting the wip branch)

**Disqualified on testability, before anything else.** A Tauri window cannot be
exercised from pytest. The React layer could be tested with vitest, but that is a
second suite outside the audio guard and the default-deny fixture — and holding
under those is the stated constraint, not a preference.

Beyond that: main deleted 112 files and both CI workflows for this stack; the
branch is 226 commits behind and was never Windows-verified by its author; and it
asks one developer to maintain Python, Rust and Node to own a single window.

### Rejected: PySide6 / Qt

Not disqualified — `QT_QPA_PLATFORM=offscreen` with `pytest-qt` is a real
headless path, which is more than Tauri offers. Rejected on cost: a new ~100 MB
dependency that is neither installed nor declared, LGPL/commercial licensing to
reason about for a shipped product, and an offscreen platform plugin that is
less reliable on Windows than on Linux. For three controls in a small window it
buys appearance and nothing structural.

### Rejected as the primary: a local page served by the existing server

Testable (`TestClient`), nearly free (the routes exist), and already proven by
the browser push-to-talk page. But **a browser tab cannot be always-on-top**,
and "floating desktop assistant" is the requirement. Hosting the page in a
chromeless top-most window means Electron, Tauri or pywebview — which is the
rejected option again, wearing a hat.

This remains the right answer for the **Pironman and phone** cases on the
roadmap, and it is already built for them.

## 5. Smallest useful version

The guess in the task is close to right. One substantive disagreement, on
evidence.

**A push-to-talk *button* is the wrong primitive.** `WindowsKeyProbe` reads
`GetAsyncKeyState`, which is global — hold-to-talk already works while another
window has focus, which is why `grandpa voice push-to-talk` is usable at all.
A button requires clicking the bubble, which means the pointer and focus are on
the bubble rather than on the window being dictated into. The daily-usable
primitive is a **global hotkey plus a visible recording indicator**; a button is
a secondary affordance for discoverability, not the mechanism.

Two consequences that follow from the same reasoning:

* **the bubble must never steal focus.** `-topmost` without `focus_force`, and
  the text entry takes focus only on an explicit click. A floating window that
  grabs keystrokes is worse than no window.
* **the status line must show model readiness.** Loading `base.en` takes about
  7s and `small.en` about 17s. A UI that looks ready while the model is still
  loading repeats, at the UI level, the exact bug that made two accuracy runs
  unusable last task.

### In

1. Borderless always-on-top bubble, draggable, position remembered between runs.
2. Global hold-to-talk hotkey, reusing `WindowsKeyProbe` and
   `PushToTalkSession` unchanged.
3. State indicator: idle / recording / transcribing / thinking.
4. Text entry that routes exactly as `grandpa ask` does.
5. Status line: active model, whether speech is ready, last error.
6. A reply pane with selectable text.

### Explicitly deferred

* **OS toast notifications** — on the MVP list, needs its own mechanism, not
  needed daily.
* **Quick actions** — every actuation path has a consent gate; which actions and
  how they ask is a design task of its own.
* **Tray icon integration** — `pystray` is not installed, and `tray.py` does not
  run today.
* **Settings UI** — `config.toml` is adequate and already documented.
* **Conversation history browsing** — `/v1/voice/history` exists; the UI does
  not need it to be useful.
* **Themes, animation, the "premium orb"** — the thing the stale branch spent
  its last commit on.
* **Anything running on the Pironman or a phone** — served by the existing HTTP
  surface and the browser page.

## 6. In-process or over the local API

**Recommend in-process**, behind a one-method seam.

The bubble is a Python process. Importing `VoiceCommandProcessor` and
`PushToTalkSession` is a direct call: no serialization, no port, no auth
decision, no second process to supervise, and the same objects the CLI already
exercises in the suite.

**What the API path would cost**

* `grandpa serve` must be running and supervised — a second process whose
  death the UI has to detect and explain.
* `fastapi` and `uvicorn` move from the optional `server` extra into the UI's
  hard requirements.
* An auth decision. Loopback needs no key, so the realistic choice is
  loopback-only — which is no more secure than in-process while adding a
  listening port to the attack surface.
* Every interaction pays HTTP round-trip latency and needs a server-down path.

**Why the roadmap argument does not change the answer.** Running on the Pironman
or a phone is real, but it does not require the *desktop bubble* to speak HTTP.
The server already exposes the whole voice API, and the browser page is already
a working remote client. Building the local bubble on HTTP to serve a case that
HTTP already serves pays for it twice.

**The hedge, which is cheap.** Put the UI's calls behind a small protocol — one
`send(text) -> reply` and one `transcribe(audio) -> text` — with an in-process
implementation now. An HTTP implementation can be added later without touching
the UI. That is one interface, not an architecture, and it is the only
concession the remote case needs.
