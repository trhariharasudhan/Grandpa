"""Short spoken commands, straight to the action that does them.

Captain's voice test (2026-11-25) found everyday commands that reached the
model instead of an action, and the model then *said* it had done them:
"volume up", "brightness 70", "what's my battery", "what's the weather",
"show my latest download", "create a file called notes". The actions all
exist in the catalogue; nothing routed the words to them. This module does,
before anything else is tried, for a small set of unambiguous shapes. Every
request still goes through the executor with the catalogue's own risk and
confirmation rules -- this only *finds* the action, it never lowers a rule.

It also understands Thanglish verbs ("Notepad open pannu", "volume kammi
pannu") by rewriting them to the English the other routes know, and splits
"open a new tab, go back, refresh the page" into one command each.
"""

from __future__ import annotations

import re
from typing import Any

__all__ = ["normalize_thanglish", "quick_request", "split_commands"]

# --- Thanglish -> English ------------------------------------------------------

_DO = r"(?:pannu|pannunga|pannuga|panu|pannidu|panniru|pannu da|pannu bro|podu|pannuda)"
_MORE = r"(?:jaasthi|jasthi|jaasti|jasti|adhigam|athigam|adhigama|ethu|yethu|yeathu|increase|kootu)"
_LESS = r"(?:kammi|kami|koraiyu|korai|kurai|kuraiyu|kammiya|decrease|eraku|irakku)"
_SOUND = r"(?:volume|sound|saththam|satham)"

_THANGLISH = [
    (re.compile(rf"^{_SOUND}\s+{_MORE}\s*{_DO}?$"), "volume up"),
    (re.compile(rf"^{_SOUND}\s+{_LESS}\s*{_DO}?$"), "volume down"),
    (re.compile(rf"^{_SOUND}\s+(?:off|mute)\s*{_DO}?$"), "mute"),
    (re.compile(rf"^(?:brightness|velicham)\s+{_MORE}\s*{_DO}?$"), "brightness up"),
    (re.compile(rf"^(?:brightness|velicham)\s+{_LESS}\s*{_DO}?$"), "brightness down"),
    (re.compile(rf"^(.+?)\s+(?:open|thira|thiranthu|thiraku)\s*{_DO}$"), r"open \1"),
    (re.compile(r"^(\w+(?:\s\w+)?)\s+(?:open|thira)$"), r"open \1"),
    (re.compile(rf"^(.+?)\s+(?:close|moodu|mudu)\s*{_DO}$"), r"close \1"),
    (re.compile(r"^(\w+(?:\s\w+)?)\s+(?:close|moodu)$"), r"close \1"),
    (re.compile(rf"^(.+?)\s+(?:search|thedu)\s*{_DO}$"), r"search google for \1"),
    (re.compile(rf"^(?:pc|computer|system|laptop)\s+lock\s*{_DO}?$"), "lock my pc"),
    (re.compile(r"^(?:time|neram)\s+(?:enna|ennaa|evlo|yenna)\b.*$"), "what time is it"),
    (re.compile(r"^(?:weather|climate|vaanilai)\s+(?:enna|eppadi|epdi|yenna)\b.*$"), "what is the weather"),
]


def _clean(text: str) -> str:
    text = str(text or "").strip()
    text = re.sub(r"^(?:hey |hi |ok |okay )?grandpa[,!. ]*", "", text, flags=re.I)
    return re.sub(r"[.!?]+$", "", text).strip()


def normalize_thanglish(text: str) -> str:
    """"Notepad open pannu" -> "open notepad"; anything else unchanged."""
    cleaned = _clean(text)
    low = " ".join(cleaned.casefold().split())
    for pattern, replacement in _THANGLISH:
        if pattern.match(low):
            return pattern.sub(replacement, low).strip()
    return text


# --- several commands in one breath ---------------------------------------------

_STARTS = (
    "open", "close", "go back", "go forward", "refresh", "reload", "new tab",
    "volume", "mute", "unmute", "brightness", "search", "lock", "minimize",
    "maximize", "scroll", "play", "pause", "next tab", "close tab",
)


def split_commands(text: str) -> list[str] | None:
    """"Open a new tab, go back, refresh the page" -> three commands.

    Only when every part starts like a command; ordinary sentences with
    commas ("Hello Grandpa, how are you") are left alone.
    """
    cleaned = _clean(text)
    parts = [p.strip() for p in re.split(r"\s*(?:,|;|\band then\b|\bthen\b)\s*", cleaned) if p.strip()]
    # Not on a bare "and": "open Chrome and search for X" is one goal, which
    # the planner runs step by step (it waits for Chrome before searching).
    if len(parts) < 2:
        return None
    lowered = [p.casefold() for p in parts]
    if not all(any(p.startswith(s) for s in _STARTS) for p in lowered):
        return None
    if len(parts) > 5:
        return None
    return parts


# --- the quick routes -----------------------------------------------------------------

_VOL_UP = re.compile(
    r"^(?:(?:turn|crank|bring|put)\s+(?:the\s+)?(?:volume|sound)\s+up|"
    r"(?:increase|raise|boost)\s+(?:the\s+)?(?:volume|sound)|"
    r"(?:volume|sound)\s+(?:up|higher|louder|increase)|louder|make it louder)$"
)
_VOL_DOWN = re.compile(
    r"^(?:(?:turn|bring|put)\s+(?:the\s+)?(?:volume|sound)\s+down|"
    r"(?:decrease|lower|reduce|drop)\s+(?:the\s+)?(?:volume|sound)|"
    r"(?:volume|sound)\s+(?:down|lower|softer|decrease)|softer|quieter|make it quieter)$"
)
_UNMUTE = re.compile(r"^(?:unmute|un mute)(?:\s+(?:the\s+)?(?:volume|sound|pc|computer))?$")
_BRIGHT_SET = re.compile(
    r"^(?:(?:set|change|make|put)\s+(?:the\s+)?)?(?:screen\s+)?brightness\s*(?:to|at|=)?\s*(\d{1,3})\s*(?:%|percent)?$"
)
_BRIGHT_UP = re.compile(
    r"^(?:(?:increase|raise)\s+(?:the\s+)?(?:screen\s+)?brightness|(?:screen\s+)?brightness\s+up|brighter|make it brighter)$"
)
_BRIGHT_DOWN = re.compile(
    r"^(?:(?:decrease|lower|reduce|dim)\s+(?:the\s+)?(?:screen\s+)?brightness|(?:screen\s+)?brightness\s+down|dimmer|dim the screen)$"
)
_BATTERY = re.compile(
    r"^(?:what(?:'s| is)\s+)?(?:my\s+|the\s+)?(?:battery|charge)(?:\s+(?:level|status|percentage|percent|left))?"
    r"|^how much (?:battery|charge)(?: is left| do i have)?|^battery\b"
)
_WEATHER = re.compile(
    r"^(?:what(?:'s| is)\s+|how(?:'s| is)\s+|tell me\s+)?(?:the\s+)?(?:weather|temperature|climate)"
    r"(?:\s+(?:like|now|today|outside|right now))*(?:\s+(?:in|at|for)\s+([a-z][a-z .'-]{1,40}?))?"
    r"(?:\s+(?:today|now|right now))?$"
)
_WEATHER_IS = re.compile(r"^is it (?:raining|going to rain|hot|cold)(?: today| now)?(?:\s+in\s+([a-z][a-z .'-]{1,40}))?$")
_LATEST_DOWNLOAD = re.compile(
    r"^(?:show|what(?:'s| is)|tell me|open)?\s*(?:me\s+)?(?:my\s+|the\s+)?(?:latest|last|newest|most recent|recent)\s+download(?:ed file)?s?$"
)
_CREATE_FILE = re.compile(
    r"^(?:create|make|new)\s+(?:a\s+)?(?:new\s+)?(?:text\s+)?(file|folder)\s+(?:called|named|name)?\s*(.+)$"
)
#: Who holds a role *now* changes after any model was trained, so it is looked
#: up, never guessed ("Who is the CM of Tamil Nadu?" -> the small model said it
#: could not provide that).
_ROLE = (
    r"cm|chief minister|pm|prime minister|president|vice president|governor|ceo|"
    r"founder|chairman|chairperson|captain|coach|mayor|minister|speaker|chief justice|"
    r"head coach|leader of the opposition|collector|mla|mp"
)
_CURRENT_FACT = re.compile(
    rf"^(?:who(?:'s| is| are| was elected)|tell me who is)\s+(?:the\s+)?"
    rf"(?:current\s+|present\s+|new\s+|sitting\s+)?(?:{_ROLE})\b.*$"
    r"|^(?:what(?:'s| is| are)\s+the\s+)?(?:latest|today'?s?|recent)\s+news\b.*$"
    r"|^(?:what(?:'s| is)\s+)?(?:the\s+)?(?:price|rate)\s+of\s+.+\s+(?:today|now)$"
)
_EXPAND = {r"\bcm\b": "chief minister", r"\bpm\b": "prime minister"}

_PC = r"(?:my\s+|the\s+|this\s+)?(?:pc|computer|laptop|system|machine)"
_POWER = (
    (re.compile(rf"^lock\s+(?:{_PC}|(?:my\s+|the\s+)?screen)$"), "system_lock"),
    (re.compile(rf"^(?:put\s+{_PC}\s+to\s+sleep|sleep\s+{_PC})$"), "system_sleep"),
    (re.compile(rf"^(?:restart|reboot)\s+{_PC}$"), "system_restart"),
    (re.compile(rf"^(?:shut\s*down|turn\s+off|power\s+off|switch\s+off)\s+{_PC}$"), "system_shutdown"),
)
_REMINDERS_TODAY = re.compile(r"^(?:what|which|show|list)\s+(?:are\s+)?(?:my\s+)?reminders?(?:\s+(?:do i have\s+)?today)?$|^what reminders do i have(?: today)?$")


def _request(name: str, parameters: dict[str, Any]):
    from grandpa.action_layer.catalogue import get
    from grandpa.action_layer.model import ActionRequest, Origin

    spec = get(name)
    return ActionRequest(
        name,
        parameters,
        origin=Origin.USER_CHAT,
        risk=spec.risk,
        requires_confirmation=spec.requires_confirmation,
    )


def _current_brightness() -> int | None:
    try:
        import screen_brightness_control as sbc  # type: ignore

        value = sbc.get_brightness()
        value = value[0] if isinstance(value, (list, tuple)) else value
        return int(value)
    except Exception:  # noqa: BLE001 - no reading, no relative change
        return None


def _desktop():
    """The real Desktop (OneDrive moves it on many PCs)."""
    from pathlib import Path

    try:
        from grandpa.files.paths import resolve_alias

        found = resolve_alias("desktop")
        if found is not None:
            return Path(found)
    except Exception:  # noqa: BLE001
        pass
    return Path("~/Desktop").expanduser()


def _file_name(raw: str, kind: str) -> str:
    name = raw.strip().strip("'\"").strip()
    name = re.sub(r"\s+(?:on|in)\s+(?:my\s+|the\s+)?desktop$", "", name)
    name = re.sub(r"[^\w .()-]", "", name).strip()
    if kind == "file" and name and "." not in name:
        name = name.replace(" ", "-") + ".txt"
    return name


def quick_request(text: str):
    """An :class:`ActionRequest` for a short, unambiguous command, else ``None``."""
    low = " ".join(_clean(text).casefold().split())
    if not low or len(low) > 80:
        return None
    if _VOL_UP.match(low):
        return _request("volume_up", {})
    if _VOL_DOWN.match(low):
        return _request("volume_down", {})
    if _UNMUTE.match(low):
        return _request("volume_unmute", {})
    found = _BRIGHT_SET.match(low)
    if found:
        return _request("brightness_set", {"level": max(0, min(100, int(found.group(1))))})
    if _BRIGHT_UP.match(low) or _BRIGHT_DOWN.match(low):
        current = _current_brightness()
        if current is None:
            return None
        step = 20 if _BRIGHT_UP.match(low) else -20
        return _request("brightness_set", {"level": max(5, min(100, current + step))})
    if _BATTERY.match(low):
        return _request("battery_status", {})
    found = _WEATHER.match(low) or _WEATHER_IS.match(low)
    if found:
        city = (found.group(1) or "").strip()
        return _request("weather_now", {"city": city.title()} if city else {})
    if _LATEST_DOWNLOAD.match(low):
        return _request("downloads_latest", {})
    found = _CREATE_FILE.match(low)
    if found:
        kind = found.group(1)
        name = _file_name(found.group(2), kind)
        if name:
            return _request("file_create", {"path": str(_desktop() / name), "kind": kind})
    if _REMINDERS_TODAY.match(low):
        return _request("reminders_today", {})
    if _CURRENT_FACT.match(low):
        query = low.rstrip("?")
        for short, full in _EXPAND.items():
            query = re.sub(short, full, query)
        return _request("web_search", {"query": query})
    # Power: found here so "restart my computer" is never read as an app to
    # restart. Each keeps its catalogue rule -- a yes/no is always asked.
    for pattern, action in _POWER:
        if pattern.match(low):
            return _request(action, {})
    return None
