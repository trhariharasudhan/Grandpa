# Bubble manual QA

Everything a test can assert is already asserted. What is left needs eyes and
ears on a real window, and only you have those. Grouped so you can stop after
any section.

Start it:

```powershell
uv run grandpa voice --list-microphones   # only if you need a device index
uv run grandpa bubble
```

It blocks this terminal until you close it. Open a second terminal if you want
one.

## A. Appearing

| # | Do this | Expect |
| --- | --- | --- |
| 1 | Run `grandpa bubble` | A small dark window near the top-left. **No title bar**, no minimise or close buttons. |
| 2 | Read the top-right of the header | Two chips: **"hold CTRL+WIN"** and **"speech on"**. If the key chip names anything else, say so — it read "hold SPACE" for a whole release once. |
| 3 | Look at the state line immediately | A grey dot and **"Loading model..."** — not "Ready". |
| 4 | Watch the window while it loads | It must stay **responsive**: the meter strip is visible and you can drag the window. It used to freeze solid for the whole load. |
| 5 | Wait | Dot turns green, reads **"Ready"**. Status line shows the model name and `speech ready`. About 7s for `base.en`. |
| 6 | Click another window so the bubble is behind it | The bubble **stays on top**. |

If step 3 ever shows "Ready" before step 5, stop and tell me — that is the bug
the LOADING state exists to prevent.

## B. Not stealing focus

The difference between usable and infuriating.

| # | Do this | Expect |
| --- | --- | --- |
| 7 | Open Notepad, click into it, type | Every character lands **in Notepad**. The bubble does not take the caret. |
| 8 | Click the bubble's text box, type, click back into Notepad, type | The bubble took focus only from your click, and gave it back. |

## C. The held key

**Ctrl+Win**, held together. One hand, no `Fn`.

| # | Do this | Expect |
| --- | --- | --- |
| 9 | Click into Notepad first, so the bubble does **not** have focus. Hold **Ctrl+Win** and say "what is the time" | Dot turns red, state **"Recording"** — while Notepad has focus. This is the point of the global key. |
| 10 | Release both keys | **"Transcribing..."** then **"Thinking..."**, then back to green. |
| 11 | Read the panes | The grey line shows what it heard in quotes. The reply pane shows the answer. |
| 12 | Select the reply text with the mouse | It **selects** and copies with Ctrl+C. |
| 13 | Tap Ctrl+Win briefly without speaking | Nothing is routed. The status names the tap: "That was a 0.0Ns tap — hold CTRL+WIN down while you speak." |
| 14 | Release Ctrl+Win after a hold | The **Start menu must not open**. If it does, tell me and switch to `--key menu`. |

### The swallow — one part must still work alone

| # | Do this | Expect |
| --- | --- | --- |
| 15 | Click the bubble's text box, type `hello`, select it, press **Ctrl+C** | It **copies**. Ctrl alone is not the hold key, so it must reach the box normally. This is the regression the combination risked. |
| 16 | With the box focused, hold **Ctrl+Win** | The box stays **empty** — no character — and recording starts. |
| 17 | Restart with `--key ctrl+space`, focus the box, hold it | Still no space in the box. The swallow is not specific to one key. |

If holding Ctrl+Win does nothing at all — no "saw CTRL+WIN" in the status line —
restart with `--key menu` or `--key f8` and tell me.

## D. The meter

This is the one I most wanted: proof it is hearing you.

| # | Do this | Expect |
| --- | --- | --- |
| 18 | Look at the strip under the state line when idle | A **flat dim line**, not an empty box. |
| 19 | Hold the key and speak normally | Bars **move with your voice**, red, filling maybe half to two-thirds the height. New bars appear on the right. |
| 20 | Hold the key and stay silent | Bars stay **near flat**. This is how you tell "not hearing me" from "heard me, wrong words". |
| 21 | Hold the key and speak loudly | Bars reach **full height** and stop there. |
| 22 | Release | The meter returns to the flat resting line. |

If the bars never move while you are clearly speaking, the microphone is the
problem and not the words — check with `grandpa voice push-to-talk --no-route`.

## E. The spoken reply

| # | Do this | Expect |
| --- | --- | --- |
| 23 | Ask anything by voice or text | The reply **appears as text first**, then is read aloud. State shows **"Speaking..."**, then back to Ready. |
| 24 | While it is speaking, hold Ctrl+Win | Speech **stops mid-sentence** and a new recording starts. |
| 25 | Click **"speech on"** in the header | It reads **"speech off"** and dims. Next reply is text only. |
| 26 | Click it again | Back to "speech on", and replies are spoken again. |
| 27 | Restart with `--no-speak`, ask something | Chip reads "speech off" from the start; reply is text only. |

The reply text must never be missing because speech failed. If you ever see
"not spoken" in the status line, the text should still be there in full.

## F. Text, position, closing

| # | Do this | Expect |
| --- | --- | --- |
| 28 | Click the box, type `what is my voice status`, press Enter | Box clears, "Thinking...", reply appears. Same answer as `grandpa ask`. |
| 29 | Drag the bubble by its top strip to another corner. Press Esc. Run `grandpa bubble` again | It reopens **where you left it**. |
| 30 | Press Esc, or Ctrl+C in the terminal | The window closes and the terminal returns to a prompt. |

## If something is wrong

Both of these mean the pipeline, not the window:

- **"Heard nothing usable"** every time → check the microphone with
  `grandpa voice push-to-talk --no-route`. If that works and the bubble does
  not, it is the bubble.
- **Replies are the wrong words** → that is recognition, not the UI. Measure it
  with `grandpa voice accuracy-test` and compare `--model small.en`.

Tell me the step number and what you saw instead. "Step 19, bars never moved
while I was talking" is enough to act on.
