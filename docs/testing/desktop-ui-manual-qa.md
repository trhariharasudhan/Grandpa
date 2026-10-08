# Bubble manual QA

Fifteen checks. Everything a test can assert is already asserted; what is left
needs eyes on a real window, and only you have one.

Start it:

```powershell
uv run grandpa voice --list-microphones   # only if you need a device index
uv run grandpa bubble
```

It blocks this terminal until you close it. Open a second terminal if you want
one.

## Appearing

| # | Do this | Expect |
| --- | --- | --- |
| 1 | Run `grandpa bubble` | A small dark window appears near the top-left. **No title bar**, no minimise or close buttons. |
| 1a | Read the top-right of the header | It says **"hold F9"**. It read "hold SPACE" in the previous build, which is the label this round fixed; if it names any other key, say so. |
| 2 | Look at the state line immediately | A grey dot and **"Loading model..."** — not "Ready". The status line underneath says `loading`. |
| 3 | Wait | The dot turns green and reads **"Ready"**. Status line shows the model name and `speech ready`. About 7s for `base.en`, 17s for `small.en`. |
| 3a | While it is still loading, hold F9 | The status line says it **saw F9** and that the model is still loading. It must not stay silent — silence is what made a held key look like a dead key. |
| 4 | Click another window so the bubble is behind it | The bubble **stays visible on top**. |

If step 2 ever shows "Ready" before step 3, stop and tell me — that is the
failure the LOADING state exists to prevent, and a test is supposed to make it
impossible.

## Not stealing focus

This is the one I most want checked, because it is the difference between usable
and infuriating.

| # | Do this | Expect |
| --- | --- | --- |
| 5 | Open Notepad, click into it, start typing | Every character lands **in Notepad**. The bubble does not take the caret. |
| 6 | While still typing in Notepad, watch the bubble | It stays on top and does nothing. No flicker, no focus ring. |
| 7 | Click the bubble's text box, type, then click back into Notepad and type | The bubble took focus only from your click, and gave it back. |

## The held key

| # | Do this | Expect |
| --- | --- | --- |
| 8 | Click into Notepad first, so the bubble does **not** have focus. Hold **F9** and say "what is the time" | Dot turns red, state **"Recording"** — while Notepad has focus. This is the point of the global key. |
| 9 | Release F9 | State goes **"Transcribing..."** then **"Thinking..."**, then back to green "Ready". |
| 10 | Read the panes | The grey line shows what it heard in quotes. The reply pane shows Grandpa's answer. |
| 11 | Select the reply text with the mouse | It **selects** and can be copied with Ctrl+C. |
| 12 | Tap F9 briefly without speaking | Nothing is routed. The status line names the tap: "That was a 0.0Ns tap — hold F9 down while you speak." No reply appears. |

**F9 types nothing**, in Notepad or in the bubble's own text box. SPACE shipped
first and did both, which is what this round fixed. `--key` still takes `space`
through `f10` and the bubble swallows whichever you pick, but a printable key
will still type into *other* windows, and `--key ctrl` fires on every Ctrl+C you
press.

| # | Do this | Expect |
| --- | --- | --- |
| 8a | Click the bubble's text box, then hold F9 | The box stays **empty** — no character appears — and recording starts. This is the reported bug; if a character appears, say so. |
| 8b | With the box focused, hold SPACE after restarting with `--key space` | Same: no space in the box. The swallow is not specific to F9. |

If F9 does nothing at all — no "saw F9" in the status line — your F-row probably
needs `Fn`. Restart with `--key f8` or `--key shift` and tell me.

## Text, position, closing

| # | Do this | Expect |
| --- | --- | --- |
| 13 | Click the text box, type `what is my voice status`, press Enter | Box clears, state goes "Thinking...", reply appears. Same answer you would get from `grandpa ask`. |
| 14 | Drag the bubble by its top strip to another corner. Press Esc. Run `grandpa bubble` again | It reopens **where you left it**. |
| 15 | Press Esc, or Ctrl+C in the terminal | The window closes and the terminal returns to a prompt. |

## If something is wrong

Both of these mean the pipeline, not the window:

- **"Heard nothing usable"** every time → check the microphone with
  `grandpa voice push-to-talk --no-route`. If that works and the bubble does
  not, it is the bubble.
- **Replies are wrong words** → that is recognition, not the UI. Measure it with
  `grandpa voice accuracy-test` and compare against `--model small.en`.

Tell me the step number that failed and what you saw instead. "Step 6, the
bubble flickered and Notepad lost the caret" is enough to act on.
