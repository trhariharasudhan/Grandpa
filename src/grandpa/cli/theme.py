from contextlib import contextmanager
from datetime import datetime

from rich.align import Align
from rich.console import Console, Group, RenderableType
from rich.text import Text
from rich.theme import Theme

from grandpa.cli.slash_commands import command_groups, picker_group_items

# --- the palette ------------------------------------------------------------
#
# The orb's seven state colours, so a colour means the same thing in the
# terminal as it does in the panel. Roles are assigned below; nothing outside
# this module should carry a hex literal.
#
# A tint mixes a base toward white and a shade mixes it toward the background.
# The brief defined only the tint direction, 0% = base and 100% = white, but a
# white-ward ramp can only make a colour brighter -- and the list markers have
# to read QUIETER than body text. So shade() is the other half, and the dim
# structural roles are shades rather than tints.
#
# Every value below is the measured one. Floors: 4.5:1 for anything carrying
# meaning, 3:1 for dim structure, against all three grounds the CLI draws on.
#
#   name         hex       #0c0c0c   #1e1e1e   #181818   worst
#   Light Gray   #F2F3F5   17.62:1   15.02:1   15.99:1   15.02:1
#   Blue         #8AC5FF   10.72:1    9.14:1    9.73:1    9.14:1
#   Yellow       #FFE88F   16.01:1   13.65:1   14.54:1   13.65:1
#   Red          #FF9DA2    9.87:1    8.41:1    8.96:1    8.41:1
#   Purple       #D4AAFB   10.19:1    8.69:1    9.25:1    8.69:1
#   Green        #90E2AE   12.74:1   10.86:1   11.56:1   10.86:1
#   Orange       #FFC895   12.99:1   11.07:1   11.79:1   11.07:1
#
# Pale on dark passes comfortably: the worst of all seven is 8.41:1, nearly
# double the 4.5:1 floor. No role needs the ramp to reach contrast any more --
# the saturated bases did, Purple at 4.21:1, and these do not.
#
# CAN A PERSON TELL THEM APART? That is the real question at 50%, where
# everything is pale and red, orange and yellow crowd together. Measured as
# CIEDE2000, not hex distance -- two colours 100 apart in RGB can be
# indistinguishable while two 40 apart are obvious. All 21 pairs, closest
# first:
#
#   Yellow  vs Orange  15.13     <- the closest pair in the whole set
#   Light   vs Blue    22.28
#   Light   vs Orange  22.48
#   Red     vs Orange  23.44     <- error vs warning
#   Blue    vs Purple  23.93
#   ... every remaining pair is above 24, up to Yellow vs Purple at 54.91
#
# Convention: below 2.3 is the just-noticeable difference, 2.3-5 is visible
# only side by side, 5-10 is workable apart, above 10 is unambiguous. A
# terminal shows these on separate lines minutes apart, never adjacent, so the
# bar is the upper end -- and the WORST pair in the set is 15.13. Error against
# warning is 23.44, more than double the threshold. The crowding does not
# materialise, so no tint was adjusted to work around it.

# The seven at tint 50% -- the soft shades, not the saturated bases. The bases
# stay in the orb, where they are correct; nothing in the CLI uses them.
LIGHT_GRAY = "#F2F3F5"
BLUE = "#8AC5FF"
YELLOW = "#FFE88F"
RED = "#FF9DA2"
PURPLE = "#D4AAFB"
GREEN = "#90E2AE"
ORANGE = "#FFC895"

PALETTE = {
    "light_gray": LIGHT_GRAY,
    "blue": BLUE,
    "yellow": YELLOW,
    "red": RED,
    "purple": PURPLE,
    "green": GREEN,
    "orange": ORANGE,
}


def _rgb(colour: str) -> tuple[int, int, int]:
    raw = colour.lstrip("#")
    return tuple(int(raw[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _hex(values: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{max(0, min(255, round(v))):02x}" for v in values)


def tint(colour: str, percent: float) -> str:
    """Mix *colour* toward white. 0 returns the base, 100 returns white."""
    r, g, b = _rgb(colour)
    factor = percent / 100.0
    return _hex((r + (255 - r) * factor, g + (255 - g) * factor, b + (255 - b) * factor))


def shade(colour: str, percent: float) -> str:
    """Mix *colour* toward black. 0 returns the base, 100 returns black.

    The quiet half of the ramp. Dim structure needs less contrast than body
    text, and tinting toward white can only add contrast.
    """
    r, g, b = _rgb(colour)
    factor = 1.0 - percent / 100.0
    return _hex((r * factor, g * factor, b * factor))


# --- roles ------------------------------------------------------------------
#
# Each role names what the colour MEANS, so a reader changing one does not
# have to guess what else relies on it. Colour is never the only signal: every
# warning, error and confirmation carries words that say the same thing.

STRUCTURE = LIGHT_GRAY
"""#F2F3F5, worst 15.02:1 -- body text, rules, labels, structural furniture."""

INLINE_CODE = shade(LIGHT_GRAY, 20)
"""#c2c2c4, worst 9.37:1 -- literal strings inside a reply. A grey weight.

THE CONFLICT, named rather than hidden: all seven colours have a job, and
inline code appears inside Grandpa's own prose, so there is no role it can
never sit beside. Sharing with Green would make a literal look like a
success; with Blue, like something executing. Either turns a quoted string
into a status.

So it takes a grey weight instead of a colour, which also says the right
thing: a literal is not a state, and backticks mean "this is text", not
"look at me". It is the third grey, and all three are perceptually distinct --
dE00 11.17 from body and 14.02 from the dim markers, both above the
unambiguous threshold. Rich's default here is bold cyan on a black background,
which is why it previously read as emphasis.
"""

STRUCTURE_DIM = shade(LIGHT_GRAY, 40)
"""#919293, worst 5.35:1 -- list numbers, bullets, dim labels.

The markers were Rich's default cyan, which made structure look like content
and fought the text beside it. A shade rather than a tint, because quieter is
what was needed and a white-ward ramp can only brighten. dE00 24.93 from body
and 14.02 from inline code, so the three greys do not blur into each other.
Shade 50% (#797a7a, 3.87:1) was the lowest clearing the 3:1 floor and was not
taken -- markers you have to squint at are a different bug.
"""

ASSISTANT = YELLOW
"""#FFE88F, worst 13.65:1 -- Grandpa's own name and label."""

ACCENT = YELLOW
VOICE = YELLOW
"""The logo, and voice.

A DELIBERATE SHARE, and the only one on this colour: all three are Grandpa
himself. His label in the transcript, the logo at startup, and the chrome of a
spoken session are the same thing wearing different clothes, so giving them
one colour is the palette being consistent rather than running out.
"""

ERROR = RED
"""#FF9DA2, worst 8.41:1 -- errors."""

WARNING = ORANGE
"""#FFC895, worst 11.07:1 -- warnings.

The pair the pale palette was supposed to break. Measured, error against
warning is dE00 23.44 -- more than double the unambiguous threshold, and the
fourth-closest pair of twenty-one rather than the closest. They are
distinguishable, so Orange is used as it stands.

Yellow is the conventional warning colour and is unavailable here, being
Grandpa's label. Orange is the next nearest in meaning and sits 15.13 from
Yellow, which is still unambiguous.
"""

SUCCESS = GREEN
"""#90E2AE, worst 10.86:1 -- success and confirmations."""

THINKING = BLUE
ACTION = BLUE
"""#8AC5FF, worst 9.14:1 -- the spinner and thinking pill, and tool execution.

Thinking needed a new colour because Yellow is now Grandpa's label. Blue is
the choice because it reads as work in progress rather than as a verdict, and
because it is 22.28 from body text and 23.93 from the user's prompt purple --
the two things it will most often appear beside.

A DELIBERATE SHARE with tool execution: both mean "Grandpa is working on it",
they are sequential rather than simultaneous -- the spinner is replaced by the
action line -- and nothing is lost by them agreeing.
"""

TEXT_ACCENT = PURPLE
"""#D4AAFB, worst 8.69:1 -- the user's own name in the prompt.

Distinct from ASSISTANT's yellow by dE00 54.91, the largest separation in the
whole set, which is right: whose turn it is should be the least ambiguous
thing on the screen.
"""

PICKER_TEXT = STRUCTURE
"""#F2F3F5 -- the selected row's text in the command picker.

Was tint 100%, pure white, which is outside the seven. Light Gray 50% is the
palette's own lightest value and measures 17.23:1 on the picker background.
"""

PICKER_BG = shade(LIGHT_GRAY, 90)
"""#171717 -- the picker's own background, near-black by design.

Not a text colour, so no contrast floor applies to it; the floors apply to
what is drawn ON it, which is why #181818 is one of the three grounds every
role above is measured against.
"""

PICKER_INVERSE = shade(LIGHT_GRAY, 93)
"""#101010 -- text on an ACCENT-filled row, where the fill is the bright one.

Measured against ACCENT rather than against a dark ground, because that is
what it sits on: 11.26:1.
"""

# #5fb3b3 is gone. It was the one colour from outside the palette, kept while
# the saturated bases were in use because nothing in them was cyan and both
# candidates that cleared contrast already meant something else. At tint 50%
# the argument changes: INLINE_CODE is a grey weight now, defined with the
# other two greys above, so every colour in the CLI comes from the seven.
DEFAULT_USERNAME = "Username"
ASSISTANT_NAME = "Grandpa"

CHAT_THEME = Theme(
    {
        # Rich's default for inline code is bold cyan on a BLACK background.
        # The box and the bold made a literal string read as emphasis, in the
        # same register as the blue name in the prompt -- two different things
        # saying "look at me". A muted cyan with no background and no bold
        # reads as "this is a literal", which is what backticks mean.
        #
        # Measured rather than eyeballed, as WCAG contrast against the two dark
        # backgrounds this is actually read on:
        #
        #                              #0c0c0c   #1e1e1e
        #   rich default cyan          15.60:1   13.30:1   (too loud)
        #   INLINE_CODE #5fb3b3         8.00:1    6.82:1   (AA is 4.50:1)
        #
        # It stays well clear of the thinking yellow, which it must not
        # resemble, and of the blue that now means Grandpa's own label.
        "markdown.code": INLINE_CODE,
        # The list markers. Rich's defaults are standard cyan for both the
        # number and the whole list, which read as blue beside the body text
        # and made the 1 2 3 4 5 of a names reply compete with the names. A
        # marker is structure: it says where an item begins and carries no
        # meaning of its own, so it belongs on the quiet end of the ramp.
        #
        # The bullet also loses its bold for the same reason.
        "markdown.item.number": STRUCTURE_DIM,
        "markdown.item.bullet": STRUCTURE_DIM,
        "markdown.list": STRUCTURE_DIM,
    }
)
"""Console theme for conversational surfaces.

Inline code and the list markers. Fenced blocks keep Rich's own highlighting,
which goes through ``Syntax`` and is not these styles.
"""

CHAT_STARTUP_TEXT = (
    "Chat Assistant\nType your message and press Enter.\nType exit or quit to leave."
)

VOICE_STARTUP_TEXT = 'Voice Assistant\nSay "stop listening" to exit.'

FAREWELL_TEXT = "Goodbye! I’ll be here when you need me."

GRANDPA_LOGO = r"""
  ██████╗ ██████╗  █████╗ ███╗   ██╗██████╗ ██████╗  █████╗
 ██╔════╝ ██╔══██╗██╔══██╗████╗  ██║██╔══██╗██╔══██╗██╔══██╗
 ██║  ███╗██████╔╝███████║██╔██╗ ██║██║  ██║██████╔╝███████║
 ██║   ██║██╔══██╗██╔══██║██║╚██╗██║██║  ██║██╔═══╝ ██╔══██║
 ╚██████╔╝██║  ██║██║  ██║██║ ╚████║██████╔╝██║     ██║  ██║
  ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═══╝╚═════╝ ╚═╝     ╚═╝  ╚═╝
"""


LEFT_INDENT = "  "
TWO_COLUMN_MIN_WIDTH = 108
SECTION_RULE = "────────────────"


def _greeting() -> str:
    hour = datetime.now().hour

    if hour < 12:
        return "Good Morning"
    if hour < 17:
        return "Good Afternoon"
    return "Good Evening"


def _logo() -> str:
    lines = GRANDPA_LOGO.strip("\n").splitlines()
    width = max(len(line) for line in lines)
    return "\n".join(line.ljust(width) for line in lines)


def _indent(text: str) -> str:
    return "\n".join(
        f"{LEFT_INDENT}{line}" if line else "" for line in text.splitlines()
    )


def _section(title: str, body: str) -> Text:
    return Text.from_markup(
        f"[bold {TEXT_ACCENT}]{title}[/bold {TEXT_ACCENT}]\n"
        f"[dim]{SECTION_RULE}[/dim]\n\n"
        f"{body}"
    )


def _build_left_panel(engine: str, model: str, agent: str) -> RenderableType:
    return Group(
        Align.center(Text.from_markup(f"[bold {ACCENT}]{_logo()}[/bold {ACCENT}]"))
    )


def _build_right_panel() -> RenderableType:
    return Text("")


def render_chat_home(
    console: Console,
    engine: str,
    model: str,
    agent: str,
) -> None:
    """Render the legacy chat home without the former full-screen panel."""
    console.print()
    render_logo_borderless(console)
    console.print()
    console.print(CHAT_STARTUP_TEXT)


def render_logo(console: Console) -> None:
    """Render the canonical Grandpa logo without a surrounding panel."""

    console.print(Text(_logo(), style=f"bold {ACCENT}"))


def render_logo_borderless(console: Console) -> None:
    """Backward-compatible alias for the canonical logo renderer."""

    render_logo(console)


def render_help(console: Console) -> None:
    console.print(f"[bold {ACCENT}]Grandpa Command Center[/bold {ACCENT}]")
    console.print()
    console.print(help_commands_text())
    console.print()
    console.print("[dim]More: /help tools  /help advanced  /help all[/dim]")


def help_commands_text(view: str = "default") -> str:
    groups = command_groups(view)
    heading = {
        "default": "Beginner commands",
        "tools": "/help tools - Local tools and integrations",
        "advanced": "/help advanced - Settings and advanced controls",
        "all": "/help all - Complete slash command reference",
        "commands": "/help commands - Shows beginner-friendly slash commands.",
    }.get(view, "Beginner commands")
    lines = [heading]
    for category, commands in groups.items():
        lines.extend(("", category))
        for command in commands:
            if view in {"default", "commands"} and command.name == "/tools":
                lines.extend(
                    f"{item.command:<22} {item.description}"
                    for item in picker_group_items("Tools")
                )
                continue
            display_name = command.name
            if view == "tools":
                display_name = f"/tools {command.name.lstrip('/')}"
            elif view == "advanced":
                display_name = f"/settings {command.name.lstrip('/')}"
            lines.append(f"{display_name:<22} {command.description}")
    return "\n".join(lines)


def help_examples_text() -> str:
    return (
        "/help examples - Shows natural language examples you can type.\n\n"
        "Memory:\n"
        "  show my memories\n\n"
        "Reminders:\n"
        "  what reminders do I have\n"
        "  remind me in 30 minutes to drink water\n\n"
        "Desktop:\n"
        "  open Chrome\n\n"
        "Browser:\n"
        "  search YouTube for Python\n\n"
        "Daily Life:\n"
        "  order biryani"
    )


def help_modules_text() -> str:
    return (
        "/help modules - Explains what each Grandpa module is for.\n\n"
        "Memory      Saved facts, preferences, and profile details\n"
        "Reminders   One-shot reminders and reminder listing\n"
        "Desktop     Computer/app/window control\n"
        "Browser     Web navigation/search\n"
        "Files       Local file search/actions\n"
        "Voice       Local speech input, wake word, and spoken responses\n"
        "Coding      Developer assistant\n"
        "Automation  Workflows/routines\n"
        "Order       Future daily-life ordering"
    )


def help_shortcuts_text() -> str:
    return (
        "/help shortcuts - Shows keyboard controls for the slash picker.\n\n"
        "Left/Right  Move between top-level commands\n"
        "Up/Down     Move through preview options\n"
        "Enter       Select highlighted option\n"
        "Ctrl+C/Esc  Cancel if supported"
    )


def _command_group(title: str, commands: list[str]) -> str:
    lines = [f"[bold {TEXT_ACCENT}]{title}[/bold {TEXT_ACCENT}]"]
    lines.extend(f"[{TEXT_ACCENT}]{command}[/{TEXT_ACCENT}]" for command in commands)
    return "\n".join(lines)


def resolve_username(config=None) -> str:
    """Resolve a safe terminal display name from the active config.

    Validated, not merely trimmed. This collapsed whitespace and truncated,
    which a progress bar stored as a display name passed intact -- so the
    greeting was repaired by ``profile_from_config``'s ``_safe_username``
    while the chat prompt label, which comes through here, still printed the
    bar. Two readers of one field disagreeing about whether it was usable.
    """
    from grandpa.profile import _safe_username

    configured = getattr(getattr(config, "user", None), "username", "")
    if not str(configured or "").strip():
        return DEFAULT_USERNAME
    return _safe_username(configured)[:40] or DEFAULT_USERNAME


def user_prompt(username: str = DEFAULT_USERNAME) -> str:
    """Return the shared interactive user prompt."""

    normalized = " ".join(str(username).split()).strip()[:40]
    return f"{normalized or DEFAULT_USERNAME} > "


def render_user_message(
    console: Console,
    content: str,
    *,
    username: str = DEFAULT_USERNAME,
) -> None:
    """Render submitted user input into the permanent chat transcript."""

    normalized = " ".join(str(username).split()).strip()[:40] or DEFAULT_USERNAME
    label = Text(f"{normalized} >", style=f"bold {TEXT_ACCENT}")
    console.print(Text.assemble(label, " ", content))


def render_assistant_prefix(console: Console) -> None:
    """Render the stable Grandpa response prefix."""

    # ASSISTANT, not ACCENT. The palette gives Blue one job -- Grandpa's own
    # name and label -- and this is that label. It was the logo yellow, which
    # made the assistant prefix and the thinking spinner the same colour.
    console.print(Text(f"{ASSISTANT_NAME} >", style=f"bold {ASSISTANT}"), end=" ")


def render_assistant_response(console: Console, content) -> None:
    """Render a prefixed Grandpa response."""

    render_assistant_prefix(console)
    console.print(content)


def render_status_message(console: Console, content) -> None:
    """Render an informational status or system message without assistant prefix."""

    if isinstance(content, str):
        console.print(f"[dim]{content}[/dim]")
    elif hasattr(content, "style"):
        content.style = "dim"
        console.print(content)
    else:
        console.print(content)


def enable_vt_mode() -> bool:
    """Enable Virtual Terminal Processing on Windows to support ANSI escape sequences."""
    import sys

    if sys.platform != "win32":
        return True
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        hOut = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        if hOut == -1 or hOut is None:
            return False

        dwMode = wintypes.DWORD()
        if not kernel32.GetConsoleMode(hOut, ctypes.byref(dwMode)):
            return False

        # ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
        dwMode.value |= 0x0004
        if not kernel32.SetConsoleMode(hOut, dwMode):
            return False
        return True
    except Exception:
        return False


@contextmanager
def alternate_screen(enabled: bool = True):
    """Enter and exit terminal alternate screen buffer using VT100/ANSI escape sequences."""
    if not enabled:
        yield
        return

    # Check if stdout and stderr are TTYs
    is_tty = False
    try:
        import sys

        is_tty = sys.stdout.isatty() and sys.stderr.isatty()
    except Exception:
        pass

    if is_tty:
        # Enable VT mode on Windows to support ANSI sequences
        import sys

        if sys.platform == "win32":
            enable_vt_mode()

        # Enter alternate screen buffer and move cursor to home
        sys.stdout.write("\x1b[?1049h\x1b[H")
        sys.stdout.flush()
        try:
            yield
        finally:
            # Exit alternate screen buffer, restore cursor shape/visibility, and reset styles
            try:
                sys.stdout.write("\x1b[?1049l\x1b[?25h\x1b[0m")
                sys.stdout.flush()
            except Exception:
                pass
    else:
        # Fallback to standard terminal output
        yield
