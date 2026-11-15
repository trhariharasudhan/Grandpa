# Avatar manual QA

Everything a test can assert is already asserted (`tests/ui/test_avatar*.py`,
`tests/ui/test_lipsync.py`). What is left needs eyes, ears and a microphone on
the real window, and only you have those. Grouped so you can stop after any
section. Tick each row, and for any row that fails open an issue with the row
number (for example "A6-T3 failed: ...").

Start it:

```powershell
cd D:\Grandpa
git pull
uv sync --extra avatar --extra tray
uv run grandpa avatar
```

The first lines printed say which head is used (placeholder or your
`grandpa.glb`), whether the voice is on, and whether Talk and the tray are on.

## Presence: ring, head, morph

| # | Do this | Expect |
| --- | --- | --- |
| A6-P1 | Look at the window after start | A small glowing **ring**, on top of other windows, no white box. |
| A6-P2 | Drag the ring with the left mouse button | The window moves with the mouse. It does **not** open the panel. |
| A6-P3 | Click the ring (no drag) | The chat panel opens. Click again: it closes. |
| A6-P4 | Type `what time is it` and press Send | The ring grows into Grandpa's head in under a second, then back to the ring when he is done. |

## Expressions per state

| # | Do this | Expect |
| --- | --- | --- |
| A6-E1 | Ask `what time is it` and watch his face while the ring says *Thinking...* | A thoughtful look: one eyebrow higher than the other (your model: its `think` shape key). |
| A6-E2 | Watch while he says the answer aloud | A gentle smile while his mouth moves with the words. |
| A6-E3 | Ask `lock the screen` | He asks first. Brows clearly **raised** while the Yes/No buttons show. Click **No**: nothing is locked. |
| A6-E4 | Ask `set volume to 30` and watch while it runs | Ring label *Working...* with the action name; a focused face (brows slightly down). |
| A6-E5 | Watch the face change between states | It **eases** over about a fifth of a second; it never jumps. |

## Click-to-talk

| # | Do this | Expect |
| --- | --- | --- |
| A6-T1 | Open the panel, click **Talk**, say `what time is it`, then stop | The button reads *Listening...* and glows blue; the ring turns blue. After you stop, your words show as your line and he answers. |
| A6-T2 | Click **Talk** and say nothing for 10 seconds | He says "I did not catch that..." and goes back to standby. Nothing is run. |
| A6-T3 | Click **Talk** and say `lock the screen` | He **asks first**, exactly as when typed. Click **No**: nothing is locked. |
| A6-T4 | With the panel closed, **right-click** the ring (or his head) | Same as A6-T1, without opening the panel. A right-click never opens or closes the panel. |
| A6-T5 | Run `uv run grandpa avatar --no-mic` and click **Talk** | He says talking is off; the microphone is not used. |
| A6-T6 | Unplug or disable the microphone, click **Talk** | A red line "I could not use the microphone: ..." and the error colour; the window keeps working for typed text. |

## Tray toggle

| # | Do this | Expect |
| --- | --- | --- |
| A6-Y1 | Find the Grandpa icon near the clock (check the `^` overflow) | It is there. Hover: "Grandpa". |
| A6-Y2 | Left-click the icon | The window hides. Left-click again: it comes back where it was. |
| A6-Y3 | Right-click the icon | Menu shows **Hide Grandpa** (or **Show Grandpa** when hidden) and **Quit Grandpa**. |
| A6-Y4 | Click **Quit Grandpa** | The window closes, the icon goes, and the terminal returns to the prompt. |
| A6-Y5 | Run `uv run grandpa avatar --no-tray` | No tray icon; everything else works. Without the tray extra installed, the start-up line says how to install it. |

## Budget (quick look; A7 measures it properly)

| # | Do this | Expect |
| --- | --- | --- |
| A6-B1 | Task Manager > Performance > GPU while idle (ring only) | iGPU use low (A2's target: at most 15%). |
| A6-B2 | Hide the window from the tray and wait 10 seconds | GPU use for the window should drop to about zero (the page stops drawing when WebView2 reports it hidden). Not verified yet: if it does not drop, say so in an issue; A7 will handle it. |
