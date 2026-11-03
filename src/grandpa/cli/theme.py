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
#   base         hex       #0c0c0c   #1e1e1e   #181818   worst
#   Light Gray   #E5E7EB   15.80:1   13.47:1   14.34:1   13.47:1
#   Blue         #168BFF    5.75:1    4.90:1    5.22:1    4.90:1
#   Yellow       #FFD21F   13.50:1   11.50:1   12.25:1   11.50:1
#   Red          #FF3B45    5.56:1    4.73:1    5.04:1    4.73:1
#   Purple       #A855F7    4.94:1    4.21:1    4.49:1    4.21:1
#   Green        #22C55E    8.58:1    7.32:1    7.79:1    7.32:1
#   Orange       #FF922B    8.75:1    7.46:1    7.95:1    7.46:1
#
# Six of the seven clear 4.5:1 unmodified. Purple is the exception at 4.21:1,
# so the role that uses it takes tint 5%.

LIGHT_GRAY = "#E5E7EB"
BLUE = "#168BFF"
YELLOW = "#FFD21F"
RED = "#FF3B45"
PURPLE = "#A855F7"
GREEN = "#22C55E"
ORANGE = "#FF922B"

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
"""Body text and structural furniture: rules, labels, the user's prompt."""

STRUCTURE_DIM = shade(LIGHT_GRAY, 40)
"""#898b8d, worst 4.88:1 -- list numbers, bullets, dim labels.

The numbered markers in a reply were Blue, which made structure look like
content and fought the text beside it. A shade rather than a tint, because
quieter is what was needed: 4.88:1 against body text's 13.47:1 reads as
clearly subordinate while still clearing the 4.5:1 floor, never mind the 3:1
one asked for. Shade 50% (#727476, 3.55:1) was the lowest that clears 3:1 and
was not taken -- markers you have to squint at are a different bug.
"""

ASSISTANT = BLUE
"""Grandpa's own name and label. 4.90:1 at tint 0%."""

THINKING = YELLOW
"""The spinner, the thinking pill, and warnings. 11.50:1."""

WARNING = YELLOW
ERROR = RED
"""Errors. 4.73:1."""

ACTION = tint(PURPLE, 5)
"""#ac5ef7, 4.52:1 -- tool and action execution.

The only role needing the ramp: Purple's base is 4.21:1, under the floor.
"""

SUCCESS = GREEN
"""Success and confirmations. 7.32:1."""

VOICE = ORANGE
"""Voice and speaking. 7.46:1."""

ACCENT = YELLOW
"""The logo and borders.

Branding rather than state, and it shares Yellow with thinking/warnings --
stated plainly because it is the one place a colour carries two meanings. It
is tolerable because the logo only ever appears at startup and a warning
always carries words; if the two ever appear together, the words disambiguate.
"""

TEXT_ACCENT = STRUCTURE
"""The user's name in the prompt.

Light Gray, per the palette: the prompt is structure, not content. This was
#818cf8 -- a blue chosen in the previous task to clear AA, which it did at
5.59:1. It is retired rather than kept: the palette has one blue and it means
Grandpa's label, so a second blue for the user's name would make the strongest
signal in the terminal ambiguous.
"""

PICKER_TEXT = tint(LIGHT_GRAY, 100)
"""#ffffff -- the selected row's text in the command picker. Tint 100%."""

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

INLINE_CODE = "#5fb3b3"
"""KEPT, and it is the one colour not from the palette.

Checked against every base before deciding. Green clears 4.5:1 at 7.32:1 and
Blue at 4.90:1, and both are already spoken for -- Green means success, Blue
means Grandpa -- so either would make a literal string look like a state.
Nothing else in the seven is in the cyan range at all. #5fb3b3 measures
8.00:1 / 6.82:1 / 7.26:1, so it clears the floor on its own merits and stays
distinct from both.
"""

# TEXT_ACCENT was #6244c5, which measured 2.94:1 on #0c0c0c and 2.50:1 on
# #1e1e1e -- below even WCAG's 3:1 large-text floor, and the least readable
# thing on the screen. It is the user's own name, so it has to be legible.
#
# #818cf8 was picked on measurement against four constraints, not by eye:
#
#                        #0c0c0c   #1e1e1e   hue   vs INLINE_CODE
#   #6244c5 (was)         2.94:1    2.50:1   254         112
#   #818cf8               6.56:1    5.59:1   234          86
#
# AA for body text is 4.50:1, so it clears both grounds with margin. Hue 234
# keeps it indigo-blue and closest of the passing candidates to the old 254,
# so the prompt still looks like itself. It stays clear of INLINE_CODE, which
# it must not be confused with, and of ACCENT, the orb's thinking amber.
#
# #a5b4fc passed with more headroom (9.81:1 / 8.36:1) and was not taken: it
# drifts paler and reads less like the original.
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
