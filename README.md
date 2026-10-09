# Grandpa

Grandpa is a privacy-focused local Windows AI assistant designed to control
applications, windows, files, keyboard, mouse, screen interactions, and system
operations through natural-language voice and CLI commands.

The primary runtime is Python. Ollama provides local language-model inference,
and every desktop action passes through Grandpa's permission, confirmation, and
audit layers. There is no bundled web dashboard, desktop shell, browser
extension, mobile client, or third-party plugin runtime.

## Quick Start on Windows

Install Python 3.10 or newer, [uv](https://docs.astral.sh/uv/), and
[Ollama](https://ollama.com/), then run:

```powershell
git clone https://github.com/trhariharasudhan/Grandpa.git
cd Grandpa
uv sync --extra voice --extra screen --extra server
ollama pull qwen3:8b
uv run grandpa doctor
uv run grandpa chat
```

The default model is `grandpa-brain:latest` (Qwen3 8B), which needs about 6 GB
of usable memory. On a smaller machine Grandpa recommends
`grandpa-mini:latest` instead — see
[docs/development/model-names.md](docs/development/model-names.md) for the
tiers, why the default is what it is, and which roles can call tools.

Start Ollama first if it is not already running:

```powershell
ollama serve
```

## Core Commands

```powershell
uv run grandpa --help
uv run grandpa doctor
uv run grandpa chat
uv run grandpa bubble               # floating desktop assistant (blocks the terminal)
uv run grandpa voice push-to-talk   # hold Ctrl+Win to talk -- start here
uv run grandpa voice                # hands-free, detects speech itself
uv run grandpa voice-operator
uv run grandpa status
uv run grandpa start
uv run grandpa stop
uv run grandpa automation --help
uv run grandpa screen active
uv run grandpa screen describe --active-window
uv run grandpa apps scan
uv run grandpa projects list
uv run grandpa reminders add "remind me in 30 minutes to drink water"
uv run grandpa oops "what just broke"   # log a problem with its context
```

## When something breaks

```powershell
uv run grandpa oops "voice did not hear me"
```

One command, one sentence. It records what you typed plus the context that
makes the problem diagnosable, so you do not have to go and find it:

| Recorded | Why that field |
| --- | --- |
| the last command you ran | "it broke" nearly always means the command before this one |
| the last capture's `speech_window_rms`, `noise_floor`, `max_chunk_rms`, voiced seconds | these four settled the voice-detection argument. A capture reported as "rms 176, never crossed 180" had speech chunks averaging 289 — the whole-buffer figure was the misleading one |
| how long the key was held, and which gate emptied the transcript | "heard nothing" has four distinct causes and they look identical from outside |
| the speech model, LLM model and configured TTS backend | two of the three have diverged from what actually ran |
| `scheduler.enabled` | a reminder that never fired is usually this, not a bug |
| version, platform, Python | identical work on this machine has varied 105× in wall time, and one bug was POSIX-only |
| the last error you were shown | |

```powershell
uv run grandpa oops --list              # what you have logged
uv run grandpa oops --list --context    # with every field
uv run grandpa oops --export            # one file to hand over
```

Everything stays on this machine, under `GRANDPA_HOME`. Your note goes through
the same redaction the screen pipeline uses, so pasting a transcript in will
not leak a password, key or card number. It deliberately collects nothing
slow — no `doctor` run, no model load — so it answers instantly.

It also will not fail. Every field is collected independently, the note is
stored even if every collector breaks, and if the file cannot be written the
note is printed so you still have it.

## Reminders

```powershell
uv run grandpa reminders add "call amma" --in 10m     # the easy way
uv run grandpa reminders list        # one-shot and recurring, in one answer
uv run grandpa reminders run-due     # deliver anything due now
uv run grandpa reminders watch       # keep delivering; blocks this terminal
```

**Use `--in`.** It takes the message exactly as written, so there is no phrasing
to remember: `--in 10m`, `--in 90s`, `--in 2h30m`, `--in 1d`.

The phrase form still works but has a shape you have to know — a "remind me"
prefix, spelled-out units, and "tomorrow" before a clock time:

| Phrase | |
| --- | --- |
| `remind me in 30 minutes to drink water` | works |
| `remind me to call amma in 2 minutes` | works |
| `remind me tomorrow at 7 PM to call amma` | works |
| `call amma in 2 minutes` | **no** — needs the "remind me" prefix |
| `remind me in 2m to call amma` | **no** — no `2m` shorthand |
| `remind me in 90 seconds to call amma` | **no** — no seconds unit |
| `remind me at 5pm to call amma` | **no** — "at &lt;time&gt;" needs "tomorrow" |

### Check that delivery works

Two commands. The first creates a reminder a minute out, the second waits for
it:

```powershell
uv run grandpa reminders add "delivery test" --in 1m
uv run grandpa reminders watch --interval 10
```

Within about a minute the watcher prints `[reminder] delivery test` and
`Delivered rem_...`, then keeps waiting until you press Ctrl+C. The same line
is appended to `reminders-delivered.log` under `GRANDPA_HOME`, so you can
confirm it afterwards even if you were not looking.

**The scheduler is off by default** and stays off: it is a background thread,
and starting one inside every CLI command — including `grandpa --help` — costs
every invocation for a feature most of them do not use.

**Nothing is lost by it being off.** A reminder is delivered whenever it is
next checked, however late, with how late it is in the text ("call Arjun  (3
hours late)"). It used to be marked *failed* after ten minutes and never
delivered, which on a default install meant every reminder was silently lost.
Delivery is also written to `reminders-delivered.log` under `GRANDPA_HOME`, so
a reminder that fired while you were not watching a terminal is still there.

`grandpa scheduler start` is a different thing — it polls scheduled *tasks* and
never reads reminders. Use `reminders watch`, or
`grandpa config set scheduler.enabled true` to have it always on.

## Desktop Bubble

```powershell
uv run grandpa bubble
```

A small borderless window that stays on top: hold **Ctrl+Win** anywhere to talk,
watch the level meter while you speak, and the reply appears and is read aloud.
Type in the box to ask the same thing silently. **It blocks the terminal** — it
owns the window loop — so open a second one if you need it.

The key is read globally, so the bubble hears a hold while another window has
focus, and it never takes focus itself: you can type into Notepad with the
bubble visible and every character lands in Notepad. The microphone is refused
while the model is still loading, and the status says so rather than claiming to
be ready.

**The meter.** While the key is held, the strip under the state line shows what
the microphone is actually picking up — one bar per 0.1s chunk, about three
seconds of history. It is the fastest way to tell "it is not hearing me" from
"it heard me and got the words wrong", which are different problems with
different fixes.

**The reply is spoken as well as shown.** The text appears first and stays;
speech is in addition, never instead. Click **speech on/off** in the header to
mute it, `--no-speak` to start muted, and holding the key cuts a reply off
mid-sentence and starts a new one. If no speech engine works the text is
unaffected and the status line says it was not spoken.

**Why Ctrl+Win and not a single key.** A global read means the key also reaches
whatever window has focus. A printable key therefore types into it — SPACE
shipped first and put a space in the bubble's own text box. A lone modifier
types nothing but fires on the shortcuts you actually use: `--key ctrl` would
start a recording on every Ctrl+C. F9 avoided both and worked, but needs `Fn` on
this laptop, which is awkward to hold while speaking.

A combination solves it, because the test is "all of these at once" and that is
a chord nothing else claims: Ctrl+C never satisfies Ctrl+Win. Both keys are on
the bottom row and reachable with one hand. Rejected: `ctrl+shift` (Windows uses
it to switch keyboard layout), `ctrl+alt` (that *is* right-Alt on AltGr
layouts), `alt+space` (opens the window menu), `win+shift` and `win+alt`
(prefixes of live Windows shortcuts).

`--key` takes any combination of `space`, `ctrl`, `shift`, `alt`, `win`, `rwin`,
`menu`, `f8`, `f9`, `f10` — joined with `+`, as in `--key ctrl+shift` — and the
bubble swallows whichever you pick so it never lands in its own text box. One
part of a combination pressed alone still works normally, so Ctrl+C keeps
copying. `--position X,Y` to place it, `--model small.en` for a different model.
It remembers where you dragged it.

If holding Ctrl+Win does nothing, or if releasing it opens the Start menu, try
`--key menu` or `--key f8` — both are inert single keys — and tell me which.

`docs/testing/desktop-ui-manual-qa.md` is the fifteen-step check for whether it
actually behaves.

## Voice Assistant

Install the local speech stack:

```powershell
uv sync --extra voice
uv run grandpa voice --diagnose
```

**Start with push-to-talk.** Hold Ctrl+Win, speak, release:

```powershell
uv run grandpa voice push-to-talk
```

This is the recommended way in, and the one to come back to if anything goes
wrong. You decide when the utterance starts and ends, so there is no speech
detection to get wrong: no level threshold, no adaptive noise floor, no silence
timeout. `--key menu` or `--key f8` if Ctrl+Win is awkward, `--no-route` to
see the transcript without acting on it.

A combination rather than a single key because the key is read globally: it
reaches whatever has focus, so a printable key types into it and fills the
terminal while you hold it, and a lone modifier fires on every Ctrl+C you
press. Ctrl+Win is satisfied by neither. All three commands that take a held
key share this default.

Hands-free mode detects speech by itself:

```powershell
uv run grandpa voice
```

It has to decide when you started talking, from the audio level against a
threshold derived from a noise floor it estimates as it goes. On a quiet
microphone that works; on others it has needed tuning, and push-to-talk is the
answer while it does. If hands-free gives you "I could not understand" on speech
you know was clear, try push-to-talk on the same microphone — if that works, the
audio is fine and the detection is at fault.

Grandpa records short phrases only while local voice mode is active, transcribes
them with faster-whisper, routes the text through the same safety layer used by
the CLI, and speaks responses through Windows SAPI when available. Voice mode
does not permit raw shell execution or bypass action confirmation.

### Measuring recognition accuracy

If the words come back wrong, measure before changing anything:

```powershell
uv run grandpa voice accuracy-test
```

It shows three phrases, you hold Ctrl+Win and read each one, and it scores what
came back against what it asked for — a word error rate, plus the signal-to-noise
ratio of each recording so a bad microphone can be told from a bad model. Run it
before and after a change and the two numbers are comparable.

Three, not ten, because a run nobody finishes measures nothing. `--count 0`
reads the whole list of ten; `--count 1` is a single phrase. A run you stop
partway still reports, and says it is not comparable and why — it will not
hand you a word error rate computed from nothing.

```powershell
uv run grandpa voice accuracy-test --json > before.json
uv run grandpa voice accuracy-test --model small.en --json > after.json
```

Roughly: **WER below 0.10** is working, **0.10–0.25** is usable with errors,
**above 0.25** needs attention. If the median SNR is below 10 dB the recording is
the limit — move closer to the microphone before trying a larger model.

If the recording is fine and the words are still wrong, the model is the only
lever that measurably helps — a 35% relative reduction in word errors for about
2.85× the decode time:

```toml
[speech]
model = "small.en"
```

`docs/user-guide/voice-runtime.md` has the measured table, including three
things that do *not* help: multilingual models, `distil-small.en`, and
`beam_size`.

### Measuring memory recall

```powershell
uv run grandpa memory recall-test
```

Stores a dozen facts, asks for each one back twice — once reusing the stored
wording, once deliberately avoiding it — and reports how often the right fact
comes back. Half a second, against a throwaway database, so it never touches
your real memory.

Two numbers because they mean different things. The default backend is SQLite
FTS5 with BM25, which matches keywords, so a direct question failing is a
defect while a paraphrase failing is what a keyword index does. Measured today:

| Questions | recall@1 | recall@3 |
| --- | --- | --- |
| direct wording | 100% | 100% |
| paraphrased | 25% | 33% |

So memory reliably finds a fact when you use its words, and usually does not
when you do not. It never returns *nothing* — it returns the closest keyword
match, which for "what vehicle do I drive" is "I am allergic to peanuts",
because the query terms are OR-joined and both share the word "I".
`--misses` lists every question that failed; `--json` compares two runs.

### Names and words the model will not know

Whisper decodes what it has seen before, so an uncommon name becomes a common
one — "Hari" becomes "Harry". Add your own words to bias it:

```toml
[voice]
vocabulary = ["Hari Hara Sudhan", "Arjun", "Tiruchirappalli"]
```

in `~/.grandpa/config.toml`, or `GRANDPA_VOICE_VOCABULARY="Hari,Arjun"` for one
run. These are added to the application names Grandpa already biases toward; set
`vocabulary_replaces_defaults = true` to use only your own.

Useful diagnostics:

```powershell
uv run grandpa voice --list-microphones
uv run grandpa voice --list-voices
uv run grandpa voice microphone-test
uv run grandpa voice --model tiny.en --device cpu
```

`microphone-test` records one supervised phrase and prints every decoding number
behind it, which is the fastest way to tell a microphone problem from a
recognition problem.

## Windows Automation

Grandpa supports permission-aware application discovery, window control,
keyboard and mouse automation, screen element location, screenshots, OCR,
files, folders, processes, and selected system operations.

Low-risk actions such as focusing a window or reading the screen may run
directly. Destructive, authentication-related, payment-related, or system power
actions require confirmation or are blocked. Grandpa never treats model output
as permission.

Examples:

```text
Open VS Code.
Focus Chrome.
Read the active window.
Find the Save button.
Scroll down.
Type hello in Notepad.
Show my Downloads.
What processes are using the most memory?
```

## Screen Understanding

Install optional capture support and verify OCR:

```powershell
uv sync --extra screen
uv run grandpa screen diagnose
uv run grandpa screen monitors
uv run grandpa screen active
uv run grandpa screen read --active-window
uv run grandpa screen describe --active-window
```

Screenshots remain in memory unless a save option is explicitly requested.
Grandpa redacts likely passwords, tokens, OTPs, payment-card numbers, private
keys, and authorization data before displaying or logging recognized text.
Secure desktops and protected windows are not bypassed.

## Local API

The optional FastAPI server is retained for local integrations and
OpenAI-compatible clients:

```powershell
uv sync --extra server
uv run grandpa serve --host 127.0.0.1 --port 8000
```

The server binds to loopback by default and is authenticated by default: on
first run it generates an API key, prints it, and stores it in
`~/.grandpa/config.toml`. Pass it as `Authorization: Bearer <key>`, or override
it with `GRANDPA_API_KEY`. Use `--no-auth` only where every local process is
trusted. Browser origins are not enabled by default; configure CORS explicitly
only for a trusted local client.

## Development

```powershell
uv sync --extra dev --extra server --extra voice --extra screen
uv run --with pytest python -m pytest
uv run --with ruff ruff check src tests
cargo test --manifest-path rust/Cargo.toml
git diff --check
```

## Troubleshooting

- **Ollama unavailable:** run `ollama serve`, then `uv run grandpa doctor`.
- **Model missing:** run `ollama pull <model-name>` and verify with `ollama list`.
- **Microphone unavailable:** check Windows microphone privacy settings and run
  `uv run grandpa voice --list-microphones`.
- **OCR unavailable:** install Tesseract OCR and place `tesseract.exe` on
  `PATH`, or set `GRANDPA_TESSERACT_CMD`.
- **Server stopped:** use `uv run grandpa start` and `uv run grandpa status`.
- **Windows notifications unavailable:** reminders still work without the
  optional toast-notification dependency — they are written to
  `reminders-delivered.log` under `GRANDPA_HOME`.
- **A reminder did not arrive:** the scheduler is off by default. Run
  `uv run grandpa reminders run-due` to deliver it now, or
  `uv run grandpa reminders watch` to keep delivering. Nothing is lost by
  waiting.
- **Anything else:** `uv run grandpa oops "what happened"` records it with
  the context, and `--export` gives one file to hand over.

## Focused Roadmap

1. Reliable voice-command pipeline
2. Accurate intent parsing
3. Windows application control
4. Screen understanding
5. Mouse and keyboard automation
6. File and folder management
7. Safe system operations
8. Context-aware multi-step automation
9. Local AI performance improvements
10. Voice feedback and error recovery
11. Permission controls and audit logs
12. Comprehensive Windows regression testing

## Documentation

- [Installation](docs/getting-started/installation.md)
- [Quick start](docs/getting-started/quickstart.md)
- [Repository structure](docs/development/repo-structure.md)
- [Roadmap](docs/development/roadmap.md)
- [Security](docs/user-guide/security.md)

## Origins and Attribution

Grandpa is a derivative work of [OpenJarvis](https://github.com/open-jarvis),
an Apache-2.0 project by The OpenJarvis Authors, which is itself derived in
part from IPW (Intelligence-per-Watt). This repository retains the upstream
commit history: work up to 2026-05-22 is the OpenJarvis contributors'; Grandpa
was established on 2026-05-23 and has since been substantially rewritten around
a Windows-first local assistant, where OpenJarvis was a general agent and
inference platform.

Copyright and attribution for both works are recorded in [LICENSE](LICENSE) and
[NOTICE](NOTICE). Third-party components, including the vendored FFmpeg build
used by the optional voice runtime, are listed in [NOTICE](NOTICE).

## License

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
