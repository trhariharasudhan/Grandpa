# Terminal interface

Type `grandpa` (Linux, macOS, or Windows Terminal / Command Prompt) and Grandpa opens full screen: the conversation in the middle, the input box at the bottom, and a status line under it.

## Start it

| System | From the repo folder | From anywhere (after installing the launcher once) |
|---|---|---|
| Windows | `grandpa.cmd` | `powershell -ExecutionPolicy Bypass -File scripts\install_launcher.ps1`, then `grandpa` |
| Linux / macOS | `./grandpa.sh` | `sh scripts/install_launcher.sh`, then `grandpa` |

`grandpa tui -m <model>` starts it with a specific model. Set `GRANDPA_NO_TUI=1` to get the plain line-by-line chat instead. Grandpa falls back to that by itself when the terminal can't run a full-screen app, for example when its output is piped.

## Keys

| Key | What it does |
|---|---|
| Enter | Send |
| Shift+Enter, Alt+Enter, Ctrl+J | New line |
| ↑ / ↓ | Earlier messages (kept between sessions) |
| `/` | Command list; type more letters to narrow it |
| `/memory` then a space | That command's subcommands |
| `@` and a path | Attach a text file (Tab picks from the list) |
| F1 | Keyboard shortcuts |
| F2 | Talk: speak, and your words appear in the input box |
| F3 | Copy Grandpa's last reply |
| F4 | Read replies aloud, on or off |
| F5 | Ask the last message again |
| Ctrl+T | Dark or light theme |
| PgUp / PgDn | Scroll the conversation |
| Esc, Ctrl+C | Cancel the reply that is being written, or answer No |
| Ctrl+L | Clear the screen |
| Ctrl+D | Quit |

## Commands the interface handles itself

These never go to the AI model:

| Command | What it does |
|---|---|
| `/theme`, `/theme dark`, `/theme light` | Switch theme (saved) |
| `/talk` | Same as F2 |
| `/speak on`, `/speak off` | Read replies aloud (saved) |
| `/copy` | Same as F3 |
| `/retry` | Same as F5 |
| `/export` | Save the conversation to `~/.Grandpa/exports/grandpa-chat-<date>-<time>.md` |
| `/keys` | Same as F1 |

Every other command in the list (`/status`, `/memory`, `/notes`, `/apps` and the rest) is Grandpa's normal chat command. A command that needs something from you, such as `/notes search <query>`, fills the box and waits for you to type the rest.

## Attaching files with @

`summarise @README.md` sends the message together with the file's text. Use quotes for names with spaces: `@"my notes.txt"`.

- Only text files. Binary files are refused.
- Only files in the current folder or your home folder.
- Up to 100 KB per file. Anything longer is cut, and Grandpa tells you.

## Talking and listening

- **F2** records one phrase from the microphone and turns it into text with Grandpa's local speech-to-text. The text goes into the input box, so you can check it before pressing Enter. Press F2 again to finish early, or Esc to stop. This needs the voice extra: `uv sync --extra voice`.
- **F4** or `/speak on` makes Grandpa read each reply aloud in its own voice, the same voice the avatar uses (see [avatar-voices.md](avatar-voices.md)). Code blocks are skipped.

## Themes and colours

Both themes use only the project's seven colours: Light Gray `#E5E7EB`, Blue `#168BFF`, Yellow `#FFD21F`, Red `#FF3B45`, Purple `#A855F7`, Green `#22C55E` and Orange `#FF922B`, plus tints and shades of them.

| Role | Dark | Light |
|---|---|---|
| Your messages | `#B0A2E2` (purple) | `#7E40B9` (deeper purple) |
| Grandpa's replies | `#FFE2A4` (yellow) | `#735E0E` (deep yellow) |
| Logo, focused box | Yellow | Deep yellow |
| Errors / success | Red / Green | Darker red / green |

Any colour the chat engine prints (markdown, code highlighting) is mapped onto the nearest colour the theme allows, so nothing outside the seven appears. Every text colour stays readable: at least 4.5:1 contrast on both themes.

## When something goes wrong

- If Grandpa stops with an error, the reason stays on screen. Press Ctrl+D to close.
- In the classic Windows Command Prompt, the interface keeps the console in the right input mode, so mouse movements don't show up as text such as `^[[<35;71;1M`.
- A reply that takes longer than 15 seconds rings the terminal bell when it is done.
