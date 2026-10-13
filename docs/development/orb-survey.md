# Floating orb: survey

A survey, not a build. Everything below that could be measured was measured on
this machine (Windows 11 build 26300, 1920×1080, Python 3.11.9); everything that
is a judgement is labelled as one.

The headline: **tkinter can do this properly, but not the way the existing
window is drawn.** `-transparentcolor` cannot render a glow — tested, not
predicted — and per-pixel alpha can, through `UpdateLayeredWindow` via `ctypes`,
with no new dependency.

---

## 1. Transparency: the finding

### What was tested

Three surfaces, each drawn over a backdrop window the probe creates in a known
dark colour, with the composited result read back off the screen so the answer
is pixels rather than an opinion. A halo shows up as magenta, because the chroma
key is magenta.

| Surface | magenta pixels | exact key pixels |
| --- | --- | --- |
| **A** `-transparentcolor` + anti-aliased glow | **30,210 — 62.4% of the window** | 0 |
| **B** `UpdateLayeredWindow`, per-pixel alpha | **0 — 0.00%** | 0 |

### (a) What `-transparentcolor` actually does

Your reasoning was right, and the magnitude is worse than "a halo". The key
colour itself vanishes correctly — `exact key pixels = 0`. But the glow's
falloff is thousands of pixels that are *near* magenta and not equal to it, and
every one of them stays. The result is a **solid magenta disc** with a faint
blue ring floating in it: 62% of the window.

This is not a tuning problem. A glow is by definition a gradient to the
background, and a chroma key is by definition an equality test. They cannot be
reconciled. The only `-transparentcolor` shape that works is one with hard
edges, where no pixel is ever partially the key colour.

### (b) Per-pixel alpha is reachable

`UpdateLayeredWindow` worked on the first attempt:

```
tk child hwnd=526458, toplevel hwnd=1574804
WS_EX_LAYERED set (was 0x88)
UpdateLayeredWindow returned 1
magenta-ish pixels: 0 (0.00%)
```

The mechanism: get the toplevel `HWND` (`GetParent` of `root.winfo_id()`, since
`winfo_id` returns tk's child window), add `WS_EX_LAYERED`, build a premultiplied
BGRA DIB section, and call `UpdateLayeredWindow` with `ULW_ALPHA`.

**No new dependency.** `pillow>=12.1.1` and `numpy>=1.24` are already declared in
`pyproject.toml` and already imported across `src/` (`screen/capture.py`,
`screen/ocr.py`, `connectors/embeddings.py`). `ctypes` is standard library. The
glow is rendered by PIL — supersampled ring, stacked Gaussian blurs — which is
also the only way to get a smooth gradient at all, since tk's Canvas has no
blur and no anti-aliased stroke.

One trap worth recording: every GDI signature must be declared with `argtypes`.
ctypes defaults an undeclared argument to `c_int`, and a 64-bit `HBITMAP` does
not fit — `OverflowError: int too long to convert`. It happened to work in the
first probe because those handles were small that run, which is exactly how a
Win32 binding fails intermittently on someone else's machine.

### (c) Does it break the testing constraint?

**It improves it.** The orb becomes a pure function:

```
state + phase + level  ->  RGBA image
```

That is testable with no window, no display and no toolkit — assert on pixels,
on the alpha channel, on the colour for a given state. The existing injected
renderer tests a *recorded call log*; this can be tested on its actual output,
which is strictly stronger.

What changes is the division of labour. Today tk paints the window. With
per-pixel alpha, **tk no longer paints the orb at all** — it owns the window and
the events, and the pixels arrive by blit. So the seam is:

| Piece | Where | Testable |
| --- | --- | --- |
| `orb_image(state, phase, level) -> Image` | pure function | yes, on pixels |
| `blit(hwnd, image, x, y)` | one ctypes call | injected, asserted on call |
| window, drag, double-tap | tk, as now | as now, via the recorder |

The panel is unaffected and keeps its current renderer. One window gains a
second drawing path; nothing existing changes.

### (d) The fallbacks, and what they look like

- **Hard-edged ring, no glow.** `-transparentcolor` renders this correctly, and
  it is not the reference you showed me. A flat blue annulus on the desktop
  reads as a sticker, not a light source.
- **Opaque dark disc with the glow painted on.** Works everywhere, needs no
  Win32, and looks like a dark coaster with a ring on it. The glow falls off
  into the disc's own dark grey and then stops at a visible circular edge. On a
  dark desktop it is passable; on anything else the disc is obvious.

Both are real options and both discard the thing that makes the reference look
like the reference, which is that the light has no boundary.

### Recommendation

**Per-pixel alpha via `UpdateLayeredWindow`, with the opaque disc as a
documented fallback** when `UpdateLayeredWindow` fails or the platform is not
Windows. Not because it is the ambitious option — because the cheap option was
measured and it produces a magenta disc.

This is Windows-only. So is the hold key (`GetAsyncKeyState`), the toast
notifier, and the tray, so the orb is not the thing that makes this app
Windows-only.

**No new toolkit.** Qt and Tauri were rejected before for reasons that still
hold, and nothing here needs them: the measured result is the reference image,
from libraries already in the dependency list.

---

## 2. Drag versus double-tap

Windows already publishes the user's own answer, so inventing a threshold would
be worse than reading one:

| Setting | This machine |
| --- | --- |
| `GetDoubleClickTime()` | **500 ms** |
| `SM_CXDOUBLECLK` × `SM_CYDOUBLECLK` | **4 × 4 px** |
| `SM_CXDRAG` × `SM_CYDRAG` | **4 × 4 px** |

**The rule.** On button-down, record position and time. On button-up: it is a
**tap** if the pointer never moved more than `SM_CXDRAG`/`SM_CYDRAG` from where
it went down; otherwise it was a **drag** and the orb has already moved. Two
taps are a **double-tap** if the second button-up is within
`GetDoubleClickTime()` of the first and within the double-click slop of it.

Two details that matter:

- **Drag starts on exceeding the threshold, not on button-down.** Otherwise
  every tap nudges the orb by a pixel or two, and a jittery hand can never tap.
- **A drag cancels the pending tap.** Moving 6 px and returning to the start
  still counts as a drag, because the maximum distance is what is tracked, not
  the final one.

Read these from `GetSystemMetrics` at startup rather than hardcoding 4 and 500 —
they are accessibility settings, and someone with a tremor may have raised them
deliberately.

---

## 3. Collapsed behaviour

### Your instinct is right, with one addition

Collapsed *is* voice-only mode. The evidence supports it: TTS resolves to
pyttsx3 and doctor reports it Ready, replies are spoken by default, holding the
key already interrupts speech, and the 2.25 s per-call engine probe was fixed
last round so speaking starts promptly. Hold the key, speak, hear the answer,
never open the panel. That is the whole point of a collapsed orb.

The addition: **the panel must retain the last exchange**, so expanding after a
spoken reply shows what was said rather than an empty pane. Speech is not
reviewable — you cannot re-read it, and "what was that number again?" has no
answer if the text was never kept. The panel already holds `heard` and `reply`;
collapsing must not clear them.

### What if speech is off and a reply arrives collapsed

This is the case that must not swallow an answer, and there are three candidate
behaviours:

| Option | Cost |
| --- | --- |
| Auto-expand the panel | The window grows under the pointer while you are typing in something else. The one thing this UI has never done is take over. |
| Refuse to collapse when speech is off | Punishes a setting with a missing feature. |
| **An unread state on the ring** | One more state on a thing that already shows state. |

**Recommendation: the unread state** — the amber ring in the sheet. It is
distinct from all five others, and crucially it **does not time out**: the ring
stays amber until the panel is opened, so a reply cannot be missed by looking
away. Expanding clears it.

That also covers a case you did not ask about: speech *on* but the reply was
spoken while you were out of the room. Setting unread whenever a reply lands
collapsed — spoken or not — costs nothing and closes that too.

---

## 4. Panel placement

**Anchored to the orb, flipping at the edges, not the panel's remembered
position.**

The orb is the thing the user just double-tapped and is looking at; a panel that
opens 600 px away on the other side of the screen reads as a different window.
The remembered position belongs to the orb now — that is the thing being
dragged.

Placement: prefer right-and-below the orb with a 12 px gap; flip to the other
side of each axis when the panel would leave the **work area** (not the screen —
`SPI_GETWORKAREA`, so the taskbar is excluded); clamp only if flipping also
fails.

Measured for a 96 px orb and the current 400×324 panel:

| Orb at | Panel lands | |
| --- | --- | --- |
| top-left (20, 20) | (128, 20) | fits |
| top-right (1804, 20) | (1392, 20) | flipped left |
| bottom-left (20, 964) | (128, 736) | flipped up |
| bottom-right (1804, 964) | (1392, 736) | flipped both |
| centre (912, 492) | (1020, 492) | fits |

Every corner resolves by flipping alone; clamping never fires at this screen
size, because 400×324 fits twice over in 1920×1080. Clamping is still written,
because a 1366×768 laptop with a side-docked taskbar is a smaller work area than
this one.

Note: `SPI_GETWORKAREA` returned the full 1920×1080 here, so the taskbar is
auto-hidden on this machine. The code should still use the work area — it is
correct on machines where the taskbar is pinned, and this one is the lucky case.

---

## 5. Animation cost, measured

| Operation | Median |
| --- | --- |
| Generate one frame from scratch (PIL, ×4 supersample) | **5.9 ms** |
| Generate one frame (×1, no supersample) | 3.6 ms |
| **Blit a pre-generated frame (`UpdateLayeredWindow`)** | **0.28 ms** (p95 0.97 ms) |
| Build a 24-frame pulse cycle, once | 0.21 s, **4.4 MB** held |
| Cycle a pre-rendered frame | 0.33 ms |

Generating every frame live would cost 5.9 ms and cap at ~170 fps in theory, but
it burns a core for an idle decoration. **Pre-render the pulse once, then
cycle.** At that point the per-frame cost is a memcpy and a blit:

| Rate | Budget | Used | Share of one core |
| --- | --- | --- | --- |
| 10 fps | 100 ms | 0.28 ms | **0.3%** |
| 15 fps | 66.7 ms | 0.28 ms | 0.4% |
| 20 fps | 50 ms | 0.28 ms | **0.6%** |
| 30 fps | 33.3 ms | 0.28 ms | 0.8% |

**20 fps, 24 frames, 4.4 MB.** A breath cycle is slow — a 3-second period is 60
frames of motion from 24 pre-rendered ones by holding each ~2 ticks.

**Idle must cost nothing, and can.** A still orb is blitted once; Windows then
composites the layered window itself with no further work from the process. So
the rule is: **do not schedule the tick when the state is not animating.** Start
the timer on entering an animated state, cancel it on leaving. An idle breath is
a choice, not a requirement — if the orb is truly idle, stop at a fixed frame and
spend 0%.

That is the opposite of the existing `pump`, which re-arms unconditionally; the
orb's tick must be cancellable, or a decorative window will burn 0.6% of a core
forever.

---

## 6. The six states

A mapping onto the controller's existing states, not new machinery. Rendered in
`orb-states.png`.

| State | Visual |
| --- | --- |
| **loading** | Dim grey ring with one brighter arc sweeping slowly round it — the only state that is grey, so "not ready" is obvious without reading anything. |
| **idle** | Soft blue ring, low glow, optionally breathing very slowly; the resting state the reference is built around. |
| **listening** | Bright cyan, ring visibly thicker and the glow up to twice as strong, **driven by the microphone level the meter already produces** — so the orb is a level meter while collapsed. |
| **thinking** | Violet, with a short arc travelling round a dimmed ring: indeterminate motion, clearly different from listening's steady swell. |
| **speaking** | Warm green, a steady confident pulse at a slower rhythm than listening, so the two are not confused at a glance. |
| **error** | Red ring, one bright flash, then holding dim red until something clears it — the only state that stays wrong-looking. |
| *(proposed)* **unread** | Amber, steady, never times out: a reply arrived while collapsed. Clears on expanding. |

The listening state is the one worth most: `controller.note_level()` already
receives per-chunk RMS and `normalise_level()` already maps it to 0–1. The orb
can consume exactly what the meter consumes, so "is it hearing me" is answered
while collapsed, which is the question the meter was built for.

---

## 7. What I would not build

- **A chroma-keyed glow.** Measured at 62% magenta. It is the cheap option and
  it does not work.
- **A new toolkit.** Qt or Tauri would give per-pixel alpha for free, and cost a
  second UI stack, a packaging story and a rewrite of a panel that works. The
  measured result above is the reference image, from dependencies already
  declared.
- **Live frame generation.** 5.9 ms per frame to animate a decoration, when
  0.28 ms of blitting gets the same picture.
- **An always-on idle animation.** Pretty, and it costs 0.6% of a core forever
  for a thing nobody is looking at. Breathe when there is something to say;
  hold still otherwise. This should be a setting, defaulting to still.
- **Auto-expanding on a reply.** The one promise this window has kept all along
  is that it never takes over. An unread ring says the same thing and asks
  permission.
- **A second remembered position.** One position, belonging to the orb. The
  panel is anchored to it.
- **Click-through / hit-testing on the glow.** A layered window takes clicks on
  its whole rectangle by default, so the transparent corners would swallow
  clicks meant for what is behind. Fixable with `WM_NCHITTEST` or by checking
  alpha at the pointer, but it is a second Win32 mechanism and it should be its
  own decision, not smuggled into the first build.

### The honest risk

`UpdateLayeredWindow` means the orb's pixels no longer come from tk. If that
call fails on another machine — a remote desktop session, a software renderer, a
driver that declines layered windows — there must be a fallback that is tested,
not hoped for. The opaque-disc version is that fallback, and it should be
written at the same time rather than promised.
