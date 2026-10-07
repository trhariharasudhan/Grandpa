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
| 2 | Look at the state line immediately | A grey dot and **"Loading model..."** — not "Ready". The status line underneath says `loading`. |
| 3 | Wait | The dot turns green and reads **"Ready"**. Status line shows the model name and `speech ready`. About 7s for `base.en`, 17s for `small.en`. |
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
| 8 | Click into Notepad first, so the bubble does **not** have focus. Hold SPACE and say "what is the time" | Dot turns red, state **"Recording"** — while Notepad has focus. This is the point of the global key. |
| 9 | Release SPACE | State goes **"Transcribing..."** then **"Thinking..."**, then back to green "Ready". |
| 10 | Read the panes | The grey line shows what it heard in quotes. The reply pane shows Grandpa's answer. |
| 11 | Select the reply text with the mouse | It **selects** and can be copied with Ctrl+C. |
| 12 | Tap SPACE briefly without speaking | Nothing is routed. Status line says it heard nothing usable. No reply appears. |

Holding SPACE will also type spaces into Notepad. That is expected — the key is
read globally and not swallowed. Use `--key ctrl` if that bothers you; a
modifier types nothing.

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
