"""One place the UI's state colours live.

Before this there were two palettes that disagreed: the orb drew idle blue while
the panel's dot drew idle green, and the panel's "thinking" was blue where the
orb's was violet. Two surfaces describing the same state in different colours is
worse than either palette alone, because the colour stops meaning anything.

So the hues are here, named, and both surfaces read them. Hue says *what kind of
thing is happening*; brightness, the travelling arc and the pulse say how far
along it is. That division is why two states may share a hue without being
confusable -- see ``orb_image.ORB_STYLES``.

Nothing here imports a toolkit or an image library, so the panel can read the
palette without pulling in PIL and the orb can read it without pulling in tk.
"""

from __future__ import annotations

#: Neutral. "Nothing to tell you about your request" -- standby.
NEUTRAL_WHITE = "#E5E7EB"

#: Model loading. Dimmer than standby and carrying a travelling arc, which is
#: what says "not ready yet" without claiming to be working on anything the
#: user asked for.
NEUTRAL_DIM_LOADING = "#787E8C"

#: Listening. Blue while the microphone is capturing.
BLUE_LISTENING = "#168BFF"

#: Processing. Indeterminate work the user is waiting on: turning audio into
#: words, and generating a reply.
YELLOW_PROCESSING = "#FFD21F"

#: A genuine failure, which persists until the next thing happens.
RED_ERROR = "#FF3B45"

#: An operation completed. Persists like the error colour does, so a glance
#: tells you the last automation worked.
GREEN_SUCCESS = "#22C55E"

#: Speaking aloud.
ORANGE_SPEAKING = "#FF922B"

#: A reply nobody heard and nobody has read. Deliberately the one colour
#: outside the state table: unread is an overlay on a state, not a state, and it
#: must not look like activity. It is safe this close to ORANGE_SPEAKING
#: because the two cannot occur together -- unread requires that the reply was
#: *not* spoken, and speaking requires that one is being spoken.
AMBER_UNREAD = "#FFBE5A"

#: Reserved and deliberately unmapped. The spec that defined this palette asked
#: for a purple "Executing / Automation" state. There is a real moment -- the
#: span inside ``grandpa.local.router.handle_local_action`` -- but it is not one
#: place: there are several execution sites interleaved with branches that
#: return *without* running anything (a staged approval, a dry run, a refusal).
#: Lighting purple from any of those would mean a ring that says "running" for
#: something that never ran. The information is not lost: GREEN_SUCCESS already
#: says an automation completed. What purple would add is only its duration.
#: ``tests/ui/test_orb_palette.py`` asserts no state uses this.
PURPLE_EXECUTING_RESERVED = "#A855F7"

#: State name -> hex. The state names are ``BubbleState`` values, plus
#: ``unread``, which is the overlay flag.
#:
#: ``transcribing`` and ``thinking`` share a hue on purpose: both are
#: indeterminate processing and the difference is not actionable from across a
#: room. They are told apart, where it matters, by the panel's own words.
RING_COLOURS: dict[str, str] = {
    "loading": NEUTRAL_DIM_LOADING,
    "idle": NEUTRAL_WHITE,
    "recording": BLUE_LISTENING,
    "transcribing": YELLOW_PROCESSING,
    "thinking": YELLOW_PROCESSING,
    "speaking": ORANGE_SPEAKING,
    "success": GREEN_SUCCESS,
    "error": RED_ERROR,
    "unread": AMBER_UNREAD,
}


def rgb(colour: str) -> tuple[int, int, int]:
    """``"#E5E7EB"`` -> ``(229, 231, 235)``.

    The orb draws with integer channels and the panel configures tk with hex
    strings, so one of the two has to convert. Doing it here keeps a second
    copy of the numbers from existing.
    """
    text = colour.strip().lstrip("#")
    if len(text) == 3:
        text = "".join(character * 2 for character in text)
    if len(text) != 6:
        raise ValueError(f"not a six-digit hex colour: {colour!r}")
    return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)


def ring_colour(state: str, *, unread: bool = False) -> str:
    """The hex for a state. ``unread`` wins, because it is the thing unseen."""
    if unread:
        return RING_COLOURS["unread"]
    return RING_COLOURS.get(str(state), RING_COLOURS["idle"])


def ring_rgb(state: str, *, unread: bool = False) -> tuple[int, int, int]:
    return rgb(ring_colour(state, unread=unread))


__all__ = [
    "AMBER_UNREAD",
    "NEUTRAL_DIM_LOADING",
    "BLUE_LISTENING",
    "GREEN_SUCCESS",
    "NEUTRAL_WHITE",
    "ORANGE_SPEAKING",
    "PURPLE_EXECUTING_RESERVED",
    "RED_ERROR",
    "RING_COLOURS",
    "YELLOW_PROCESSING",
    "rgb",
    "ring_colour",
    "ring_rgb",
]
