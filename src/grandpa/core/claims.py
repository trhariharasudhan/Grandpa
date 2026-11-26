"""Grandpa never says he did something he did not do.

A small model asked "volume down" without calling the volume tool answers
"Ok, I'm down to 50%" -- and the volume does not move. That is worse than
"I can't": the user stops checking. So a reply from the model is checked
before it is shown: if it *claims* an action (opened, closed, set to 50%,
"is now open", "I will lock your computer") while no action actually ran in
that turn, it is replaced by an honest sentence.

Only the model's own words are checked. Messages from a real action (the
action layer, a local route) report what happened and are never touched.
"""

from __future__ import annotations

import re

_VERBS = (
    r"open(?:ed|ing)?|clos(?:ed|ing)|launch(?:ed|ing)|start(?:ed|ing)|"
    r"set|turn(?:ed|ing)|increas(?:ed|ing)|decreas(?:ed|ing)|rais(?:ed|ing)|"
    r"lower(?:ed|ing)|mut(?:ed|ing)|unmut(?:ed|ing)|lock(?:ed|ing)|block(?:ed|ing)|"
    r"shut(?:ting)? down|shutdown|restart(?:ed|ing)|delet(?:ed|ing)|creat(?:ed|ing)|"
    r"mov(?:ed|ing)|sen[dt](?:ing)?|search(?:ed|ing)|play(?:ed|ing)|chang(?:ed|ing)|"
    r"adjust(?:ed|ing)|dimm(?:ed|ing)|brighten(?:ed|ing)|navigat(?:ed|ing)|"
    r"minimi[sz](?:ed|ing)|maximi[sz](?:ed|ing)|switch(?:ed|ing)|install(?:ed|ing)"
)

_CLAIMS = [
    # "I've opened Chrome", "I have set the volume", "I just closed it"
    rf"\bi(?:'ve| have| just| already|'ve just| have just)\s+(?:{_VERBS})\b",
    # "Ok, I'm up to 100%", "down to 50%", "set to 70 %", "volume is at 30%"
    r"\b(?:up|down|set|changed|adjusted|lowered|raised|reduced)\s+to\s+\d{1,3}\s*(?:%|percent)",
    r"\b(?:volume|brightness|sound)\b[^.?!\n]{0,30}\b(?:is|now)\b[^.?!\n]{0,12}\d{1,3}\s*(?:%|percent)",
    # "Chrome is now open", "the PC is now locked", "Google is now searching"
    rf"\b(?:is|are)\s+now\s+(?:{_VERBS}|open|closed|on|off|muted|locked|playing|running)\b",
    # "Notepad has been opened", "it was closed"
    rf"\b(?:has|have)\s+been\s+(?:{_VERBS})\b",
    # "Understood, I will block your computer", "I'll lock it now", "I am opening"
    r"\bi(?:'ll| will| am going to|'m going to)\s+(?:now\s+)?"
    r"(?:open|close|lock|block|shut|restart|delete|turn|set|mute|launch|search|play|send)\b",
    r"\bi(?:'m| am)\s+(?:now\s+)?(?:opening|closing|locking|blocking|shutting|restarting|"
    r"deleting|setting|muting|launching|searching|playing|sending)\b",
]
_CLAIM = re.compile("|".join(f"(?:{p})" for p in _CLAIMS), re.IGNORECASE)

HONEST = (
    "I did not do that: no action ran. Say it again in a short way "
    '(for example "volume down", "open Chrome", "lock my PC"), or ask what I can do.'
)


def claims_an_action(text: str) -> bool:
    """Does the reply say something was (or is being) done on the PC?"""
    return bool(_CLAIM.search(str(text or "")))


def honest_reply(text: str, *, acted: bool) -> str:
    """The reply as it may be shown: unchanged, or the honest sentence."""
    if acted or not claims_an_action(text):
        return text
    return HONEST


__all__ = ["HONEST", "claims_an_action", "honest_reply"]
