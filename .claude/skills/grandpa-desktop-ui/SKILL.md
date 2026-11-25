---
name: grandpa-desktop-ui
description: Build and fix Grandpa's on-screen surfaces - the tkinter bubble and orb (BubbleController, injected views, per-pixel-alpha layered window), the shared state palette, the avatar window (pywebview page, loopback WebSocket with per-run token, three.js ring and head, lip-sync, A7 GPU/RAM budget), the UI bridge, and the Windows tray. Use when changing what Grandpa looks like or how it shows state, when a window steals focus, goes blank, drifts off-screen or uses too much GPU, or when adding a new UI surface or state.
---

# GRANDPA desktop UI

Grandpa's UI is small on purpose: a floating bubble/orb, an optional avatar
window, and a tray icon. The design choices were made by measurement and
recorded in `docs/development/desktop-ui-survey.md` and `orb-survey.md`.
Read those before proposing a new toolkit.

## Surfaces

| Surface | Command | Code | Extra |
|---|---|---|---|
| Bubble + orb (tkinter) | `grandpa bubble` | `ui/bubble.py` (behaviour), `ui/tk_view.py` (window), `ui/orb_view.py`, `ui/orb_image.py`, `ui/layered.py` | none (tkinter + pillow) |
| Avatar window | `grandpa avatar` (blocks the terminal) | `ui/avatar_controller.py`, `ui/avatar_server.py`, `ui/avatar_window.py`, `ui/avatar_states.py`, `ui/avatar_character.py`, `ui/avatar_web/` (HTML, JS, vendored three.js) | `avatar` |
| Lip-sync | used by avatar | `ui/lipsync.py` | — |
| Tray | `grandpa tray` | `tray.py`, `cli/tray_cmd.py` | `tray` (pystray) |
| Start with Windows | — | `windows_startup.py` | — |
| Shared colours | — | `ui/palette.py` | — |
| UI ↔ Grandpa seam | — | `ui/bridge.py` (`send`, `transcribe`) | — |

The Tauri/React branch `wip/floating-bubble-final` was surveyed and **not**
adopted. tkinter with an injected renderer won on dependencies, packaging and
testability.

## Design rules (each one came from a bug or a measurement)

1. **Behaviour has no toolkit import.** `BubbleController` drives an injected
   `BubbleView`; `tk_view` takes the tk module as a parameter. Tests exercise
   the controller and open no window. Keep new UI logic in the same shape.
2. **State is shown, never inferred.** `BubbleState`: LOADING, IDLE,
   RECORDING, TRANSCRIBING, THINKING, EXECUTING, SPEAKING, SUCCESS, ERROR.
   EXECUTING comes from the action layer's own announcement, never from
   guessing at text. The avatar page is a renderer only; Python decides state.
3. **One palette.** Every surface reads hues from `ui/palette.py`. Two palettes
   once disagreed about the same state, which made colour meaningless.
4. **Never take focus.** The bubble must not steal keyboard focus from the app
   Captain is using (`tests/ui/test_bubble_never_takes_focus.py`). The orb is a
   Toplevel of the panel's root, not a second `Tk()`.
5. **Never blank, never off-screen.** See `test_nothing_is_blank.py` and
   `test_orb_stays_on_screen.py`; positions are clamped to the work area.
6. **The UI adds no consent gates and removes none.** Text goes through
   `ui/bridge.InProcessBridge`, the same path and confirmations as voice/CLI.
7. **Avatar socket is locked down.** Binds `127.0.0.1`, needs a per-run random
   token in the URL, accepts only `{"type": "send"}` messages up to
   `MAX_INBOUND_TEXT`. Don't widen this without `grandpa-security-governance`.
8. **Performance budget (A7).** `ui/avatar_budget.py`: at most 20% iGPU and
   300 MB RAM (`GPU_BUDGET_PCT`, `RAM_BUDGET_MB`, 3 strikes over 10 s samples).
   Over budget, the 3D head goes and only the ring stays, because the UI shares
   the iGPU with Ollama.
9. **Windows-only rendering stays behind adapters.** `UpdateLayeredWindow` with
   premultiplied BGRA gives a clean glow; `-transparentcolor` left 62% of the
   falloff visible (measured).

## Workflow

1. Reproduce on the controller with a fake view first; write the failing test
   in `tests/ui/`.
2. Change behaviour in the controller, rendering in the view, colours in the
   palette.
3. Run `uv run pytest tests/ui -q` (and `tests/test_tray*` if you touched
   the tray). These run on Linux because the toolkit is injected.
4. Manual check on Windows with the scripts in `docs/testing/desktop-ui-manual-qa.md`
   and `docs/testing/avatar-manual-qa.md`. Say clearly which steps you could
   not run.
5. For anything visible, describe the before/after state per `BubbleState`.

## Adding a new UI state

1. Add it to `BubbleState` (and `avatar_states.py` if the avatar shows it).
2. Give it a hue in `palette.py`; keep hue = kind of activity, brightness and
   motion = progress.
3. Set it from the event source (voice, action layer), never from reply text.
4. Tests: controller transition test + palette test + "nothing is blank".

## Known issues

- `ui/bubble.py`, `ui/avatar_states.py` and `voice/cli_session.py` import
  `enum.StrEnum`, which only exists in Python 3.11+, while `pyproject.toml`
  says `requires-python >= 3.10`. Either raise the floor to 3.11 or add a
  fallback; don't add more 3.11-only imports until that is decided.
- Avatar web assets vendor three.js; update it as a deliberate change with the
  manual QA script, never as a side effect.
