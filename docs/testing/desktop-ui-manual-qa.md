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

## Do this step first: O1

**O1 is the one step to do before any other.** It takes one glance and it
decides what everything else you are looking at means.

`grandpa bubble` now opens as a floating orb, and the orb is drawn by one of two
mechanisms. The real one composites per-pixel alpha through Win32 and gives a
glowing ring with no edge. If that is refused -- a remote desktop session, a
software renderer, a driver that declines layered windows -- it falls back to the
same ring on a flat dark disc, which always works and looks worse. Every other
judgement about how the orb looks depends on which one you have, so establish
that first rather than reporting a flat disc as ugly glow.

| # | Do this | Expect |
| --- | --- | --- |
| O1 | Run `grandpa bubble`, look at the orb, then double-tap it and read the status line | A **glowing ring with no visible edge or box**, and the status line contains **`orb: glow`**. If you see a **dark circle** with a hard edge, the status line will say **`orb: flat disc (...)`** — copy that whole bracket to me and treat every later "how does it look" step as describing the fallback. |

### What it should look like, measured

So you can tell "soft on purpose" from "wrong":

- The glow fades to **nothing** before the window's edge. All four corners of
  the orb's square are the desktop exactly — read off the screen, not asserted:
  with the per-pixel path the corners match the backdrop pixel for pixel, where
  the chroma-key approach the survey rejected left 62.4% of the window as a
  solid magenta disc.
- **It will be slightly soft, and that is known.** This display runs at 125%
  scaling and the process is DPI-unaware, so Windows stretches the orb's 72
  pixels to 90 as a bitmap. Measured over a backdrop, the ring's band is 5
  physical pixels at half its peak and its peak is 5 times brighter than the
  glow 4 pixels away — a defined line rather than a smear, but softer-edged
  than a hard-drawn stroke would be. Fixing that means declaring DPI awareness
  for the whole process, which changes the panel's size and every font in it —
  a separate decision, not done here. Report it if it bothers you; do not
  report it as a bug in the glow.


## O. The orb

| # | Do this | Expect |
| --- | --- | --- |
| O2 | Run `grandpa bubble` on a clean machine (no remembered state) | **Only the orb** appears — no panel. It is voice-only until you ask for more. |
| O3 | Watch the orb while the model loads | A **dim neutral ring with a travelling arc**. It must not look ready. |
| O4 | Wait for loading to finish | The ring settles to **neutral white** and begins a **very slow breathe** — one swell about every six seconds. If it looks like a pulse or a throb rather than a slow swell, say so. |
| O5 | Click another window, then look at the orb | It **stays on top** and the other window **keeps the caret**. Type something into that window to be sure. |
| O6 | Hold CTRL+WIN and say a long sentence, loudly then quietly | The ring turns **blue** and its **edge ripples with your voice** — bumps where you were loud, smooth where you were quiet, travelling round as the history scrolls. Not a uniform pulse. If it moves the same way whatever you say, say so: that is the one failure this animation can have. |
| O7 | Release the key | **Yellow with two arcs travelling in opposite directions** while it transcribes and thinks, then **orange with waves radiating outward** while it speaks, then **green with a single ripple** that expands once and settles. |
| O8 | Ask something that fails (unplug the microphone, or hold the key for half a second and release) | The ring **flashes red twice and then holds solid red**. It must not keep flashing. |
| O9 | Ask for something that opens an app — "open notepad" | While the automation is actually running the ring is **purple with segments chasing round the circle**. It is deliberately indeterminate: it never fills from empty to full, because the action layer reports "running" and "finished" and no fraction in between. If you see it fill like a progress bar, say so. |
| O10 | Ask a plain question that runs no automation — "what is the time" | **No purple at all.** Yellow, then the reply. Purple only ever means something ran. |

### The seven, side by side

Each state should be tellable from across the room by colour first and motion
second. The two closest are **success** and **speaking** — both send a ring
outward, and they happen one after the other. They are meant to be separable
because green is not orange and because success ripples *once* while speaking
keeps going. If you cannot tell them apart in use, that is worth knowing.

| state | colour | motion |
| --- | --- | --- |
| standby | neutral white | slow breathe, one swell every 6s |
| listening | blue | the ring's edge follows your voice |
| transcribing / thinking | yellow | two arcs, opposite directions |
| speaking | orange | waves radiating outward |
| working | purple | segments chasing round, never filling |
| done | green | one ripple, then steady |
| error | red | two flashes, then solid |
| loading | dim neutral | one travelling arc |
| unread reply | amber | slow breathe, never times out |


### Drag and double-tap — the part most likely to annoy you

These share one mouse button, so they are worth a minute each.

| # | Do this | Expect |
| --- | --- | --- |
| O9 | Drag the orb across the screen | It follows the cursor. The panel **must not open** — a drag never toggles. |
| O10 | Drag the orb a long way, let go, then immediately tap once | Nothing opens. A drag then a tap is not a double-tap. |
| O11 | Double-tap the orb | The panel opens **beside the orb**. |
| O12 | Double-tap again | The panel goes away. The orb stays. |
| O13 | Try to double-tap **slowly** — about a second between taps | Nothing happens. The threshold is Windows' own double-click time, read from your settings rather than hardcoded, so if this feels wrong for you it is worth saying: someone with a tremor may have raised it deliberately. |
| O14 | Drag the orb to the **far right edge**, then double-tap | The panel opens to the orb's **left**, fully on screen. Repeat at the bottom edge: it should open **upward**. Nothing should hang off the screen or sit under the taskbar. |
| O15 | Tap once anywhere on the orb's **transparent corner** — the empty-looking square area outside the ring | The tap is **swallowed**: the window behind does not get it. This is known and accepted for now. **Tell me how much it bothers you in practice** — measured at 39% of the orb's square at standby, down from 77% before the window shrank. Making the corners click-through is a second Win32 mechanism and its own decision. |

### Collapsed is voice-only, and the panel remembers

| # | Do this | Expect |
| --- | --- | --- |
| O16 | With the panel open, ask something. Double-tap to collapse. Double-tap to open it again | The **same question and reply are still there**. Collapsing hides the panel, it does not throw the conversation away — speech is not reviewable, so this is the only place to read a reply afterwards. |
| O17 | Collapse the orb, drag it somewhere new, press Esc to close, run `grandpa bubble` again | It reopens **collapsed, where you left the orb**. |
| O18 | Open the panel, close with Esc, run `grandpa bubble` again | It reopens **with the panel open**. Which state it was in is remembered. |

### The unread ring

| # | Do this | Expect |
| --- | --- | --- |
| O19 | Open the panel, click **"speech on"** so it reads **"speech off"**, collapse to the orb | Just the orb, still blue. |
| O20 | Hold CTRL+WIN, ask a question, and wait | The ring turns **amber** and keeps a slow pulse. Nothing was spoken and nothing is on screen, so the amber is the only sign a reply arrived. |
| O21 | Leave it amber and go and do something else for several minutes | It is **still amber**. It must never time out — a notification that clears itself is one you can miss entirely. |
| O22 | Double-tap to open the panel | The reply is there and the ring goes back to **blue**. It has been read. |
| O23 | Turn speech back on, collapse, and ask something | **No amber ring.** You heard it, so there is nothing unread. |
| O24 | Collapse, ask something that fails | The ring is **red**, not amber. Red says more than "unread" does, so it is not replaced. |


## A. The panel — appearing

| # | Do this | Expect |
| --- | --- | --- |
| 1 | Double-tap the orb | A small dark window beside it. **No title bar**, no minimise or close buttons. |
| 2 | Read the top-right of the header | Two chips: **"hold CTRL+WIN"** and **"speech on"**. If the key chip names anything else, say so — it read "hold SPACE" for a whole release once. |
| 3 | Look at the state line immediately (double-tap the orb as soon as it appears) | A grey dot and **"Loading model..."** — not "Ready". |
| 4 | Watch the window while it loads | It must stay **responsive**: the meter strip is visible and you can drag the window. It used to freeze solid for the whole load. |
| 5 | Wait | Dot turns **neutral white**, reads **"Standby"** — not "Ready". Status line shows the model name, `speech ready`, and which orb painter is live. About 7s for `base.en`. |
| 6 | Click another window so the bubble is behind it | The bubble **stays on top**. |

If step 3 ever shows "Ready" before step 5, stop and tell me — that is the bug
the LOADING state exists to prevent.


## B. Nothing should be blank

Reported: "the text box is an empty dark strip above the status line. I had to
ask what it was for." Auditing the rest of the window found three more of the
same fault, so this section checks all of them before anything happens.

| # | Do this | Expect |
| --- | --- | --- |
| A1 | Look at the box at the bottom, before typing anything | It has a **visible edge** and reads **"Type a message and press Enter"** in grey. It should look like something you type in. |
| A2 | Look at the large pane in the middle | It says **"Replies appear here"** and tells you the two ways to ask. It should not be a blank dark rectangle. |
| A3 | Look above it | A **"heard"** caption and **"nothing heard yet"**. |
| A4 | Look at the bottom line | A status, not blank. |
| A5 | Click into the box | The placeholder **disappears** so you type into an empty box. |
| A6 | Click away without typing | The placeholder **comes back**. |
| A7 | Click into the box and press Enter without typing | **Nothing is sent.** The placeholder is not a message. |

If any of these is blank, say which — that is the fault this section exists for.

## C. Correcting what it misheard

Reported: "I said 'hello grandpa good morning' and it heard 'An event by Good
Morning.'" The reply was right and the transcript was wrong, and the only
remedy was saying all of it again.

| # | Do this | Expect |
| --- | --- | --- |
| B1 | Hold the key and say something it gets wrong | The **heard** row shows the wrong text, and its caption changes to **"heard — click to correct and resend"**. |
| B2 | Click the heard row | The wrong text appears **in the box at the bottom**, ready to edit. The caret does not move there on its own — the window never takes focus. |
| B3 | Fix the wrong word and press Enter | It is sent as if typed. The reply should now make sense. |
| B4 | Click the heard row before anything has been heard | Nothing happens. |

## D. Not stealing focus

The difference between usable and infuriating.

| # | Do this | Expect |
| --- | --- | --- |
| 7 | Open Notepad, click into it, type | Every character lands **in Notepad**. The bubble does not take the caret. |
| 8 | Click the bubble's text box, type, click back into Notepad, type | The bubble took focus only from your click, and gave it back. |

## E. The held key

**Ctrl+Win**, held together. One hand, no `Fn`.

| # | Do this | Expect |
| --- | --- | --- |
| 9 | Click into Notepad first, so the bubble does **not** have focus. Hold **Ctrl+Win** and say "what is the time" | Dot turns red, state **"Recording"** — while Notepad has focus. This is the point of the global key. |
| 10 | Release both keys | **"Transcribing..."** then **"Thinking..."**, then back to green. |
| 11 | Read the two rows | **heard** shows what it heard, in quotes, with a blue edge beside it. **reply** shows the answer, in its own pane below. The point is telling a misheard sentence from a misunderstood one at a glance. |
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

## F. The meter

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

## G. The spoken reply

| # | Do this | Expect |
| --- | --- | --- |
| 23 | Ask anything by voice or text | The reply **appears as text first**, then is read aloud. State shows **"Speaking..."**, then back to Ready. |
| 24 | While it is speaking, hold Ctrl+Win | Speech **stops mid-sentence** and a new recording starts. |
| 25 | Click **"speech on"** in the header | It reads **"speech off"** and dims. Next reply is text only. |
| 26 | Click it again | Back to "speech on", and replies are spoken again. |
| 27 | Restart with `--no-speak`, ask something | Chip reads "speech off" from the start; reply is text only. |

The reply text must never be missing because speech failed. If you ever see
"not spoken" in the status line, the text should still be there in full.

## H. Text, position, closing

| # | Do this | Expect |
| --- | --- | --- |
| 28 | Click the box, type `what is my voice status`, press Enter | Box clears, "Thinking...", reply appears. Same answer as `grandpa ask`. |
| 29 | Drag the panel by its top strip to another corner, collapse, and expand again | The panel comes back **beside the orb**, not where you dragged it. The orb is the thing you place; the panel follows it. Say so if that is the wrong way round for you. |
| 30 | Press Esc with the panel open, or Ctrl+C in the terminal | Both windows close and the terminal returns to a prompt. |
| 31 | Collapse to the orb, click the orb once, press Esc | It closes. Esc needs one of the windows to have been clicked first, because neither ever takes focus on its own. Ctrl+C in the terminal always works. |

## If something is wrong

Both of these mean the pipeline, not the window:

- **"Heard nothing usable"** every time → check the microphone with
  `grandpa voice push-to-talk --no-route`. If that works and the bubble does
  not, it is the bubble.
- **Replies are the wrong words** → that is recognition, not the UI. Measure it
  with `grandpa voice accuracy-test` and compare `--model small.en`.

- **The orb is a flat dark circle** → that is the fallback, not a bug in the
  look. O1 tells you, and the status line says why in brackets.

Tell me the step number and what you saw instead. "Step 19, bars never moved
while I was talking" is enough to act on.
