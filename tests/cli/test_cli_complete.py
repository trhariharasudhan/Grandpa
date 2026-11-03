"""A name is a name, bars stay quiet, and the advertised commands are real.

Three defects met here, all of them things that passed because nothing asked
the right question:

* A huggingface_hub progress bar was stored as a display name and greeted the
  user on every launch. It has no control characters and fits the length
  limit, which was all ``validate_username`` checked.
* ``quiet_model_downloads()`` was called from three commands and not at CLI
  entry, so onboarding -- which runs before any of them -- was unprotected.
* ``validate_command_registry()`` checks the slash-command table against
  itself, so it cannot notice a command that is advertised and unreachable.
"""

from __future__ import annotations

import inspect
import unicodedata

import pytest

from grandpa.cli import theme
from grandpa.cli.theme import ACCENT, INLINE_CODE, TEXT_ACCENT
from grandpa.profile import MAX_USERNAME_LENGTH, validate_username

# --- what a name is ----------------------------------------------------------

REAL_NAMES = [
    "Hari Hara Sudhan",
    "Marie-Th\u00e9r\u00e8se O'Neill",
    "J. Smith",
    "O\u2019Brien",
    "\u0bb9\u0bb0\u0bbf",  # Tamil, which this product supports
    "Anne-Marie",
    "Zo\u00eb",
    # Digits are legal. Refusing them cost this name and bought nothing: the
    # junk machine output is really made of is refused on its own.
    "user2",
    "R2D2",
]

MACHINE_OUTPUT = [
    "vocabulary.txt: 460kB [00:00, 2.65MB/s]",  # the one that actually got in
    "C:/Users/ASUS/.grandpa",
    # NOT "INFO 2026-11-03 server started": once digits are legal, that is
    # letters, digits, spaces and a hyphen, so no character-class rule can
    # refuse it. Recorded as a known limit on validate_username rather than
    # asserted here, because asserting it would mean pattern-matching content.
    '{"name": "x"}',
    "https://example.com",
    "model.bin: 100%|##########|",
]


@pytest.mark.parametrize("name", REAL_NAMES)
def test_a_real_name_is_accepted(name: str) -> None:
    assert validate_username(name) == " ".join(name.split())


@pytest.mark.parametrize("value", MACHINE_OUTPUT)
def test_machine_output_is_not_a_name(value: str) -> None:
    """The rule is an allowlist of what names are made of.

    A blocklist of progress-bar shapes would be endless; letters, combining
    marks, spaces and ``- ' .`` covers every real name this product has to
    greet and none of these.
    """
    with pytest.raises(ValueError):
        validate_username(value)


def test_the_progress_bar_that_got_in_is_refused_by_name() -> None:
    """Named explicitly, because this is the value from the real config."""
    with pytest.raises(ValueError) as refusal:
        validate_username("vocabulary.txt: 460kB [00:00, 2.65MB/s]")

    message = str(refusal.value)
    assert "cannot contain" in message
    # The refusal has to say what it objected to, or it cannot be acted on.
    assert "'/'" in message or "'0'" in message or "','" in message


def test_a_name_needs_at_least_one_letter() -> None:
    for value in ("...", "---", "' '"):
        with pytest.raises(ValueError):
            validate_username(value)


def test_the_old_checks_still_hold() -> None:
    with pytest.raises(ValueError):
        validate_username("")
    with pytest.raises(ValueError):
        validate_username("a" * (MAX_USERNAME_LENGTH + 1))
    with pytest.raises(ValueError):
        validate_username("bad\u0007name")


def test_combining_marks_are_allowed() -> None:
    """Devanagari and Tamil names are letters plus combining marks.

    Rejecting category M would refuse a large share of this product's users.
    """
    name = "\u0ba4\u0bae\u0bbf\u0bb4\u0bcd"
    assert any(
        unicodedata.category(character).startswith("M") for character in name
    )
    assert validate_username(name) == name


# --- the stored bad value cannot reach the screen ----------------------------


def test_both_readers_of_the_name_agree() -> None:
    """The greeting was repaired while the prompt label was not.

    ``profile_from_config`` ran the stored value through ``_safe_username``;
    ``resolve_username`` only trimmed it. So the welcome line said "Username"
    and the chat prompt still said "vocabulary.txt: 460kB ...".
    """

    class _User:
        username = "vocabulary.txt: 460kB [00:00, 2.65MB/s]"
        title = "Mr."
        onboarding_completed = True

    class _Config:
        user = _User()

    from grandpa.profile import DEFAULT_USERNAME

    assert theme.resolve_username(_Config()) == DEFAULT_USERNAME


def test_a_real_name_survives_resolution() -> None:
    class _User:
        username = "Hari Hara Sudhan"
        title = "Mr."
        onboarding_completed = True

    class _Config:
        user = _User()

    assert theme.resolve_username(_Config()) == "Hari Hara Sudhan"


def test_onboarding_reruns_when_the_stored_name_is_unusable() -> None:
    """A completed onboarding is not the same as a usable profile."""
    from grandpa.profile import ensure_profile

    source = inspect.getsource(ensure_profile)

    assert "validate_username" in source, (
        "ensure_profile must notice a stored name it cannot use"
    )
    assert "grandpa profile edit" in source, (
        "the user had to be told the config path; the repair command must be "
        "named where the problem is reported"
    )


# --- library output cannot reach a prompt ------------------------------------


def test_progress_bars_are_silenced_at_cli_entry() -> None:
    """Three doors were guarded and the building had more.

    quiet_model_downloads() was correct and called from bubble_cmd, voice_cmd
    and ui/bridge. Onboarding runs before all three.
    """
    from grandpa.cli import cli

    source = inspect.getsource(cli.callback)

    assert "quiet_model_downloads" in source
    # Before the first thing that can print, or it is decoration.
    assert source.index("quiet_model_downloads") < source.index("ensure_object")


def test_the_silencer_sets_both_switches() -> None:
    from grandpa.voice.accuracy import quiet_model_downloads

    source = inspect.getsource(quiet_model_downloads)

    assert "HF_HUB_DISABLE_PROGRESS_BARS" in source
    assert "disable_progress_bars" in source


# --- every advertised command is reachable -----------------------------------


def _acts(name: str) -> bool:
    """Whether typing ``name`` does something other than describe itself.

    Three legs: the registry dispatcher, namespace expansion onto a dispatched
    command, and chat_cmd's own route branches. Deliberately NOT counting
    ``_handle_module_slash_command``, which renders a help card for anything in
    the table -- if that counted, every advertised command would pass and the
    guard would assert nothing.
    """
    from pathlib import Path

    from grandpa.cli.chat_cmd import expand_namespaced_command
    from grandpa.cli.interactive_tui import INTERACTIVE_COMMANDS

    dispatched = set()
    for command in INTERACTIVE_COMMANDS.commands:
        dispatched.add(command.name)
        dispatched.update(command.aliases)

    chat_source = Path("src/grandpa/cli/chat_cmd.py").read_text(encoding="utf-8")
    expanded = (expand_namespaced_command(name) or name).split()[0]
    return (
        expanded in dispatched
        or name in dispatched
        or f'"{name}"' in chat_source
        or f"'{name}'" in chat_source
    )


def test_every_local_slash_command_either_acts_or_is_a_real_namespace() -> None:
    """``validate_command_registry`` checks the table against itself.

    It cannot see whether anything dispatches, so a command could be
    advertised as Available and do nothing but print its own name back.

    Two shapes are legitimate. A command that acts. And a namespace whose
    bare form shows its menu -- as /memory and /voice do -- provided its
    subcommands actually act. ``/settings`` and ``/tools`` are the second
    shape: bare they print a card, and ``/settings config`` and
    ``/tools gmail`` reach real handlers.

    What this forbids is the third shape: advertised, Available, and leading
    nowhere in any form.
    """
    import grandpa.cli.slash_commands as slash

    hollow = []
    for command in slash.SLASH_COMMANDS:
        if command.routing != "local":
            continue
        if _acts(command.name):
            continue
        # The subcommands are stored whole -- "/settings config", not
        # "/config" -- so they have to be expanded before being asked about.
        # Taking split()[0] yields the namespace again and proves nothing.
        from grandpa.cli.chat_cmd import expand_namespaced_command

        subcommands = [
            (expand_namespaced_command(sub) or sub).split()[0]
            for sub in command.subcommands
            if sub.startswith("/")
        ]
        if subcommands and all(_acts(sub) for sub in subcommands):
            continue
        hollow.append(command.name)

    assert hollow == [], (
        f"advertised as local, and nothing they offer leads anywhere: "
        f"{hollow}. A command that does nothing should be deleted, not listed."
    )


def test_the_namespace_subcommands_actually_act() -> None:
    """Named explicitly, because the namespaces are what a bare audit misses.

    A dispatcher-only check reports /settings and /tools as broken; a check
    that counts help cards reports everything as fine. Neither is the
    question. The question is whether the subcommands they advertise work.
    """
    from grandpa.cli.chat_cmd import expand_namespaced_command

    for namespace, expected in (
        ("/settings config", "/config"),
        ("/settings permissions", "/permissions"),
        ("/settings engine", "/engine"),
        ("/settings compact", "/compact"),
        ("/settings whoami", "/whoami"),
        ("/tools gmail", "/gmail"),
        ("/tools notes", "/notes"),
        ("/tools files", "/files"),
    ):
        assert expand_namespaced_command(namespace) == expected
        assert _acts(expected), f"{namespace} expands to {expected}, which is dead"


def test_help_all_names_every_command_it_can() -> None:
    """The list the chat offers has to be true.

    Only the /quit alias is absent, which is deliberate -- it is scoped as an
    alias of /exit rather than a command of its own.
    """
    import grandpa.cli.slash_commands as slash
    from grandpa.cli.chat_cmd import _handle_help_slash_command

    text = _handle_help_slash_command("/help all") or ""
    missing = sorted(
        command.name
        for command in slash.SLASH_COMMANDS
        if command.name not in text and getattr(command, "scope", "") != "alias"
    )

    assert missing == [], f"/help all does not mention {missing}"


# --- the name colour is legible ----------------------------------------------


def _contrast(one: str, two: str) -> float:
    def channel(value: float) -> float:
        value /= 255.0
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4

    def luminance(colour: str) -> float:
        raw = colour.lstrip("#")
        r, g, b = (int(raw[i : i + 2], 16) for i in (0, 2, 4))
        return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)

    a, b = luminance(one), luminance(two)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


@pytest.mark.parametrize("background", ["#0c0c0c", "#1e1e1e", "#181818"])
def test_the_name_colour_clears_aa(background: str) -> None:
    """It was #6244c5: 2.94:1 and 2.50:1, under even the 3:1 large-text floor.

    #181818 is in the list because the command picker draws the name on that
    background, and a colour fixed for two grounds and broken on a third is
    not fixed.
    """
    ratio = _contrast(TEXT_ACCENT, background)

    assert ratio >= 4.5, f"{TEXT_ACCENT} on {background} is only {ratio:.2f}:1"


def test_the_name_colour_is_still_blue_and_distinct() -> None:
    import colorsys

    raw = TEXT_ACCENT.lstrip("#")
    r, g, b = (int(raw[i : i + 2], 16) / 255.0 for i in (0, 2, 4))
    hue = colorsys.rgb_to_hls(r, g, b)[0] * 360.0

    assert 200 <= hue <= 250, f"{TEXT_ACCENT} is hue {hue:.0f}, not blue"
    assert TEXT_ACCENT != INLINE_CODE
    assert TEXT_ACCENT != ACCENT


def test_the_name_colour_has_one_source() -> None:
    """It was written out three times, so raising contrast meant finding all
    three. A fourth would have been missed."""
    from grandpa.cli import input_ui

    assert input_ui.USER_PROMPT_COLOR == TEXT_ACCENT
    assert input_ui.PICKER_COMMAND_COLOR == TEXT_ACCENT
