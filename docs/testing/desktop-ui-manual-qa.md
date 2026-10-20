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
| O1 | Run `grandpa bubble`, look at the orb, then click it and read the status line | A **glowing ring with no visible edge or box**, and the status line contains **`orb: glow`**. If you see a **dark circle** with a hard edge, the status line will say **`orb: flat disc (...)`** — copy that whole bracket to me and treat every later "how does it look" step as describing the fallback. |

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
| O9 | Drag the orb across the screen | It follows the cursor. The panel **must not open** — a drag never counts as a click, and the decision is made on release where the drag is already known. |
| O11 | **Click the orb once** | The panel opens **beside the orb**. One click, not two. |
| O12 | Click once again | The panel goes away. The orb stays. |
| O12a | Click the **empty corner** of the orb's square — well outside the ring | **Nothing happens.** Only the ring and its inside answer a click: 28.1% of the orb's square, which is what stops a stray click opening the panel now that one click is enough. |
| O12b | Press on the ring, move the mouse about five pixels, release | **Nothing opens** and the orb has moved. Five pixels is a drag. |
| O12c | Press on the ring, wobble two or three pixels, release | The panel **opens**. Two pixels is still a click. |
| O14 | Drag the orb to the **far right edge**, then click it | The panel opens to the orb's **left**, fully on screen. Repeat at the bottom edge: it should open **upward**. Nothing should hang off the screen or sit under the taskbar. |
| O15 | Tap once anywhere on the orb's **transparent corner** — the empty-looking square area outside the ring | The tap is **swallowed**: the window behind does not get it. This is known and accepted for now. **Tell me how much it bothers you in practice** — measured at 39% of the orb's square at standby, down from 77% before the window shrank. Making the corners click-through is a second Win32 mechanism and its own decision. |

### They move as one thing

The orb and the panel are two separate native windows — there is no shared
parent — so this is the section where that shows or does not.

| # | Do this | Expect |
| --- | --- | --- |
| M1 | With the panel open, drag the **orb** | **Both** move together, the gap between them unchanged. |
| M2 | With the panel open, drag the panel by its **top strip** | **Both** move together. The orb comes along. |
| M3 | Try to drag from the **text box**, the **speech chip**, the **heard row** or the **status line** | Nothing moves. Only the header strip and the state label are handles. Dragging from the text box should still let you select text. |
| M4 | Drag the pair to a corner, collapse, drag the orb somewhere else, expand | The panel reappears **the same distance and direction from the orb** as before. It must never detach. |
| M5 | Drag them around quickly for a few seconds | No stutter, no gap opening up, no second copy of either window. |
| M6 | Drag the orb hard into each of the four **corners**, and along each edge | It **stops at the edge** with the whole glowing ring still visible. The window itself may hang about nine pixels over -- that is the transparent padding, and it is deliberate, so the ring can sit flush with the edge instead of stopping short of it. Measured at all four corners: the ring lands between 0.6 and 1535.4 across a 1536-wide work area. |
| M7 | With the panel open, push the pair into the **right-hand** corners | The orb keeps its corner and the **panel flips to the orb's left**, wholly on screen. The orb is what you place; the panel finds room. |
| M8 | Drag back from the edge | The panel returns to the side it was on. The flip is not remembered — only borrowed while it is needed. |
| M9 | If you have a second monitor: drag the orb onto it, then into its corners | It clamps to **that** display's edges, not the main one's. Being stranded on the primary screen was the alternative. |


### The microphone is held open

| # | Do this | Expect |
| --- | --- | --- |
| P1 | Run `grandpa bubble` and read the first line it prints | It says the microphone is held open. Windows shows its microphone-in-use indicator for as long as the bubble runs — that is deliberate and it is telling the truth. |
| P2 | Look at the orb | A small **second ring inside the main one**. That is the mark saying the stream is live. It is an overlay on whatever state is showing, not a state of its own, so it is there in standby, while listening, while speaking — always. |
| P3 | Press CTRL+WIN and **start talking immediately**, without the usual beat first | The first word is there. This is the whole point: opening the stream used to take 245ms on average and up to 361ms, all of it after the key was noticed, so up to 392ms of speech was never recorded. It is 30ms now, and 300ms of what you said *before* the key went down is kept too. |
| P4 | Run `grandpa bubble --no-live-mic` | No mark on the orb, no mention in the first line, and the microphone indicator appears only while you hold the key. Behaviour is exactly what it was: press, wait a beat, then speak. |
| P5 | Set `voice.live_microphone = false` with `grandpa config set` and run `grandpa bubble` | Same as P4. The flag and the key both work; the flag wins for one run. |
| P6 | With the bubble running, **unplug the microphone** or disconnect a Bluetooth headset | The mark goes out and the status line stops saying it is held open. The next hold refuses quickly rather than hanging. Reconnect and restart the bubble to get it back — reopening the stream mid-session is not done, and if you want that, say so. |


### Collapsed is voice-only, and the panel remembers

| # | Do this | Expect |
| --- | --- | --- |
| O16 | With the panel open, ask something. Collapse. Open it again | The **same question and reply are still there**. Collapsing hides the panel, it does not throw the conversation away — speech is not reviewable, so this is the only place to read a reply afterwards. |
| O16a | Collapse to the orb and ask **three** things without opening the panel, then open it | All three are there: the newest in the two big panes, the two before it as single dimmed lines above. It used to keep one, so the first two simply vanished. |
| O16b | Ask a fourth | The oldest drops off. Three is the limit, deliberately — this is a short exchange, not a chat log. |
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

The panel is 520x512 now and reads as a conversation: a header with the
product's name, bubbles on alternating sides, and an action row under the
reply.

| # | Do this | Expect |
| --- | --- | --- |
| 1 | Click the orb | A dark window beside it, about 520 wide. **No title bar**, no minimise, no maximise. |
| 2 | Read the header, left to right | A small **ring** in the state's colour, **"GRANDPA"** over **"Personal AI Assistant"**, then on the right a **"speech on"** chip, a coloured dot with the state's word, and an **x** to close. |
| 3 | Read the line under the text box | **"Enter to send · hold CTRL+WIN to talk"**. If it names a different key, say so — it read "hold SPACE" for a whole release once. There is deliberately **no** "Shift + Enter for a new line": the box is single-line, so that line would be a lie. |
| 4 | Look at the state line immediately (click the orb as soon as it appears) | A grey dot and **"Loading model..."** — not "Ready". |
| 5 | Watch the window while it loads | It must stay **responsive**: the meter strip is visible and you can drag the window by its header. It used to freeze solid for the whole load. |
| 6 | Wait | Dot turns **neutral white**, reads **"Standby"** — not "Ready". The header's ring turns white too. Status line shows the model name, `speech ready`, and which orb painter is live. About 7s for `base.en`. |
| 7 | Click another window so the bubble is behind it | The bubble **stays on top**. |
| 8 | Drag the window | It moves only when you grab the **header**, the state word or the state dot. The bubbles, the buttons, the box and the status line are not handles. |

If step 4 ever shows "Ready" before step 6, stop and tell me — that is the bug
the LOADING state exists to prevent.

### The corners are square, and that is known

The panel draws itself a rounded border inside a square window, because a
borderless tk toplevel gets no rounding from Windows 11's compositor —
measured, the corner pixel is panel-coloured at radius 0.

**It still reads as square, and that is measured too.** The border is drawn on
a canvas that fills the window, and the content frame sits on top of it:
opaque, square, inset by three pixels. So all you can see of a 14-pixel round
is three pixels of straight line at each edge and a nick at each corner. Read
off the top-left 50x50 at 125%: eight rows of the arc are missing as shipped,
and unpacking the content makes every row but the outermost show border — so
the arc is drawn and simply covered.

Rounding it properly needs the window itself rounded, which is `SetWindowRgn`
or a layered panel: a second Win32 mechanism and its own decision. Do not
report square corners as a bug. **Do** report it if the three-pixel edge looks
like a glitch rather than a border.


## B. Nothing should be blank

Reported: "the text box is an empty dark strip above the status line. I had to
ask what it was for." Auditing the rest of the window found three more of the
same fault, so this section checks all of them before anything happens.

| # | Do this | Expect |
| --- | --- | --- |
| A1 | Look at the box at the bottom, before typing anything | It has a **visible edge** and reads **"Message Grandpa..."** in grey, with **"Enter to send · hold ... to talk"** on the line beneath. It should look like something you type in. |
| A2 | Look at the middle of the window, before anything has been said | A faint **ring**, **"No messages yet"**, and **"Hold ... to talk, or type below"**. Not a blank dark rectangle, and **not** two empty bubbles — the bubbles are not there until there is something in them. |
| A3 | Ask it something, then look again | The empty state is **gone**, replaced by your message in a **blue bubble on the right** and the reply in a **grey bubble on the left**, each with a small line under it saying who said it and when. |
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
| B1 | Hold the key and say something it gets wrong | The **blue bubble on the right** shows the wrong text, and the line under it reads **"you · hh:mm · sent · click to correct"**. |
| B2 | Click the blue bubble | The wrong text appears **in the box at the bottom**, ready to edit. The caret does not move there on its own — the window never takes focus. |
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

## I. The action row: copy, read, stop

Three buttons under the reply. They appear once there is a reply to act on and
not before.

| # | Do this | Expect |
| --- | --- | --- |
| I1 | Ask something, then look under the grey bubble | Three small outlined buttons: **copy**, **read**, **stop**. |
| I2 | Click **copy**, then paste somewhere | The reply's text, exactly. Nothing is gated and nothing asks you: this is a button on your own screen, and selecting the reply and pressing Ctrl+C already did the same thing. |
| I3 | Click **copy** twice, then paste | The reply **once**, not twice. |
| I4 | Turn speech off (the chip), ask something, then click **read** | It speaks the reply **anyway**. The chip governs whether replies are spoken automatically; clicking read is not automatic. |
| I5 | While it is speaking, click **stop** | It stops **mid-sentence**, within about a word. If you have to wait for the sentence to finish, say so — the stop is deliberately not queued behind the speech. |
| I6 | Click **stop** while it is *thinking* rather than speaking | **Nothing happens, and that is correct.** Stop stops speaking, not generating. Routing is one blocking call with no cancellation; stopping it is a separate piece of work and is not built. Report it if you want it, do not report it as broken. |
| I7 | Click the **x** in the header | The panel closes, the same as pressing Escape. |
| I8 | Ask something and watch that spot while it thinks | The three buttons are replaced by a **Thinking · · ·** pill in the same place, and come back when the reply lands. They share the slot deliberately: measured, a pill packed as its own row got one pixel of height on a full panel — present to every test, invisible to you, and invisible exactly when you are waiting for it. |

## J. The panel at the screen edges

The panel got 120 pixels wider, which moves the point at which it has to flip
to the orb's other side.

| # | Do this | Expect |
| --- | --- | --- |
| J1 | Drag the orb hard into each of the four corners in turn | The **orb** reaches each corner — its ring sits flush with the edge. The **panel** stays wholly on screen, flipping to the orb's left on the right-hand side. |
| J2 | Drag back from the right-hand edge | The panel returns to the orb's **right**, where it was. A flip must not be permanent. |
| J3 | Drag the panel somewhere of your own, then move the orb a little | The panel keeps **your** offset, not the default one — until keeping it would push it off screen. |

Measured on this machine at each corner, 1536x864 work area, panel 520x512:
the panel's rect was `(51, 0, 571, 512)` top-left, `(965, 0, 1485, 512)`
top-right, `(51, 352, 571, 864)` bottom-left, `(965, 352, 1485, 864)`
bottom-right — inside the work area at all four, flipped to the orb's left on
the right-hand side, with the orb's visible ring flush at `0.6` and `1535.4`.

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
