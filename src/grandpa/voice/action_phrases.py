"""Natural phrasings for PC-control actions that already exist.

This is a lookup table, not a parser framework. It maps things a person
plausibly says onto action types ``pc_control`` already implements, and returns
the existing :class:`~grandpa.voice.operator.VoiceOperatorIntent` so nothing
downstream changes shape. There is no new intent model, no new dispatch, and no
execution here -- resolution only.

Why it exists at all: several actions were implemented and classified in
``pc_control`` but had no phrasing that reached them. ``volume_down``,
``clipboard_read`` and ``clipboard_clear`` were unreachable by voice entirely,
and ``brightness_set``/``brightness_get`` had no phrasing either, while
``volume_up`` answered only to the exact words "volume up". The actuators were
never the gap; the vocabulary was.

Deliberately absent:

* Relative brightness. ``execute_brightness``
  (desktop/control/power.py:113) takes an absolute 0-100 level and there is no
  brightness_up/brightness_down action, so "make the screen brighter" has
  nothing to reach. Mapping it to a guessed step would invent behaviour the
  actuator does not have.
* Screenshots. ``pc_control`` classifies no screenshot action.

Both are left unsupported on purpose. Adding either means adding an action
type first, which is a separate decision.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Pattern


@dataclass(frozen=True)
class ResolvedAction:
    """An action type and its target, resolved from a phrase."""

    action_type: str
    target: str = ""
    args: dict[str, Any] | None = None


#: Phrases that map to an action with no argument. Matched against the
#: normalised transcript, whole-string, so "mute" resolves but "mute" inside a
#: longer sentence does not accidentally fire.
_EXACT_PHRASES: dict[str, ResolvedAction] = {}


def _register(action_type: str, *phrases: str, target: str = "") -> None:
    for phrase in phrases:
        _EXACT_PHRASES[phrase] = ResolvedAction(action_type, target)


# -- volume: volume_up / volume_down / volume_mute / volume_unmute exist ------
_register(
    "volume_up",
    "volume up",
    "turn up the volume",
    "turn the volume up",
    "increase volume",
    "increase the volume",
    "raise the volume",
    "make it louder",
    "louder",
)
_register(
    "volume_down",
    "volume down",
    "turn down the volume",
    "turn the volume down",
    "decrease volume",
    "decrease the volume",
    "lower the volume",
    "make it quieter",
    "quieter",
)
_register(
    "volume_mute",
    "mute",
    "mute the computer",
    "mute the sound",
    "mute the volume",
    "turn off the sound",
    "silence the computer",
)
_register(
    "volume_unmute",
    "unmute",
    "unmute the computer",
    "unmute the sound",
    "turn the sound back on",
    "turn on the sound",
)

# -- clipboard: clipboard_read / clipboard_clear exist -----------------------
_register(
    "clipboard_read",
    "read the clipboard",
    "read clipboard",
    "what is on the clipboard",
    "what is in the clipboard",
    "show the clipboard",
)
_register(
    "clipboard_clear",
    "clear the clipboard",
    "clear clipboard",
    "empty the clipboard",
)

# -- brightness: only the absolute query; see module docstring ---------------
_register(
    "brightness_get",
    "what is the brightness",
    "what's the brightness",
    "check the brightness",
    "get the brightness",
)

# -- windows: the existing window actions ------------------------------------
_register(
    "maximize_window",
    "make this window full screen",
    "make the window full screen",
    "full screen this window",
    target="active",
)


def _numeric_setter(
    action_type: str, pattern: Pattern[str]
) -> Callable[[str], ResolvedAction | None]:
    """Build a resolver for 'set <thing> to N' phrasings."""

    def _resolve(command: str) -> ResolvedAction | None:
        match = pattern.fullmatch(command)
        if match is None:
            return None
        value = max(0, min(100, int(match.group("value"))))
        return ResolvedAction(action_type, str(value), {"level": value})

    return _resolve


_PATTERN_RESOLVERS: tuple[Callable[[str], ResolvedAction | None], ...] = (
    _numeric_setter(
        "volume_set",
        re.compile(
            r"(?:set|change|put)\s+(?:the\s+)?volume\s+(?:to\s+)?(?P<value>\d{1,3})\s*(?:percent|%)?"
        ),
    ),
    _numeric_setter(
        "brightness_set",
        re.compile(
            r"(?:set|change|put)\s+(?:the\s+)?brightness\s+(?:to\s+)?(?P<value>\d{1,3})\s*(?:percent|%)?"
        ),
    ),
)


#: Domains only. A bare word is an application name, not a site, so a TLD has
#: to be recognised before a phrase is treated as a URL.
_KNOWN_TLDS = (
    "com",
    "org",
    "net",
    "io",
    "dev",
    "co",
    "uk",
    "edu",
    "gov",
    "ai",
    "app",
    "me",
)

#: A URL spoken aloud must open a browser, not be looked up as an application.
#: Without this, "open google.com" resolved to ``open_app`` with the target
#: "google com" and failed with "application not found".
#:
#: The pattern matches the *normalised* transcript, which is what this module
#: receives: ``normalize_voice_operator_transcript`` strips punctuation, so
#: "google.com" arrives as "google com" and "https://google.com" as
#: "https //google com". Matching the spoken shape is also what an STT
#: transcript of "google dot com" looks like.
_URL_PATTERN = re.compile(
    r"(?:open|go\s+to|navigate\s+to|browse\s+to|visit)\s+"
    r"(?:https?\s*//\s*)?"
    r"(?:www\s+)?"
    r"(?P<host>[a-z0-9][a-z0-9-]*(?:\s+(?:dot\s+)?[a-z0-9-]+)*)"
    r"\s+(?:dot\s+)?(?P<tld>" + "|".join(_KNOWN_TLDS) + r")"
    r"(?P<path>\s+\S+)?"
)


def _resolve_url(command: str) -> ResolvedAction | None:
    match = _URL_PATTERN.fullmatch(command)
    if match is None:
        return None
    host_words = [word for word in match.group("host").split() if word.lower() != "dot"]
    if not host_words:
        return None
    host = ".".join(host_words)
    url = f"{host}.{match.group('tld')}"
    path = (match.group("path") or "").strip()
    if path:
        url = f"{url}/{path.lstrip('/')}"
    return ResolvedAction("browser_open", url)


def resolve_action_phrase(command: str) -> ResolvedAction | None:
    """Resolve *command* to an existing action, or ``None`` to fall through.

    Returning ``None`` is the normal case: this table only claims phrasings it
    recognises, leaving everything else to the existing parser chain.
    """
    normalised = " ".join(str(command or "").strip().lower().split())
    if not normalised:
        return None

    exact = _EXACT_PHRASES.get(normalised)
    if exact is not None:
        return exact

    url = _resolve_url(normalised)
    if url is not None:
        return url

    for resolver in _PATTERN_RESOLVERS:
        resolved = resolver(normalised)
        if resolved is not None:
            return resolved
    return None


__all__ = ["ResolvedAction", "resolve_action_phrase"]
