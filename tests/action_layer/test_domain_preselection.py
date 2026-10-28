"""Picking a domain from the request, because the model will not fetch one.

``load_tools`` was meant to make a deferred domain cost one round trip rather
than being unreachable. Measured on grandpa-brain through the tool loop, six
goals x three attempts: every goal needing a deferred domain failed and every
goal CORE could answer passed -- 6/15, against the 15/15 recorded one day
before tiering existed. Prompting was not the untried fix: the loop's system
prompt already names the meta-tool and its subjects, and the tool's own
description already says "do not say you are unable until you have looked".

``load_tools`` did fire in 1 of those 18 runs, and that run failed as well: it
loaded the notes tools and then ended the turn on "Let me list your saved notes
for you" without calling ``notes_list``. So the round trip is not merely
skipped, it is where the follow-through is lost.

So the request picks the domain before the first model call. These tests hold
the two properties that make that safe, and they are deliberately not "the
goal completed" -- a goal can complete for the wrong reason, which is how the
first three versions of this matcher looked fine.
"""

from __future__ import annotations

import json

from grandpa.action_layer.catalogue import (
    _SELECTION_ALIASES,
    CORE_DOMAINS,
    DOMAINS,
    candidate_domains,
    loadable_domains,
)
from grandpa.action_layer.tool_schema import (
    core_tool_definitions,
    tool_definitions_for,
)


def _cost(domains: tuple[str, ...]) -> int:
    """Prompt tokens beyond core, by the estimator warn_if_cold uses."""
    core = len(json.dumps(core_tool_definitions())) // 4
    return len(json.dumps(tool_definitions_for(list(domains)))) // 4 - core


# --- the substring trap ------------------------------------------------------


def test_notepad_does_not_load_the_notes_domain() -> None:
    """"Notepad" contains "note", and that is a 904-token mistake.

    A substring matcher sends "open Notepad and type hello" to notes, pays for
    twelve notes tools the goal will never call, and the goal still passes --
    because open_app is in CORE. The score would be green and the mechanism
    wrong, so this asserts the mechanism.
    """
    chosen = candidate_domains("Open Notepad and type hello there.")

    assert "notes" not in chosen, (
        f"'Notepad' matched the notes domain: {chosen}. Matching must be on "
        "whole words, and any prefix rule must run one way only -- the "
        "request's word may begin a catalogue word, never the reverse."
    )
    assert "input" in chosen, (
        f"typing needs the input domain (keyboard_type), got {chosen}"
    )


# --- a request core can answer must pay nothing ------------------------------


def test_a_core_request_preloads_nothing() -> None:
    """Where the cold start is won.

    Sending the whole catalogue costs ~11,480 tokens beyond core, which is the
    sixteen-minute cold start tiering exists to avoid. Pre-selection is only
    affordable because it stays silent for requests already in front of the
    model. An earlier version let description words accumulate and "what time
    is it" started buying diagnostics and memory for +1292 tokens.
    """
    for request in (
        "What time is it?",
        "Turn the volume up.",
        "What is my volume set to?",
        "Hello, how are you?",
    ):
        chosen = candidate_domains(request)
        assert chosen == (), (
            f"{request!r} selected {chosen} (+{_cost(chosen)} tokens) when "
            "core already answers it"
        )


def test_a_deferred_request_selects_its_own_domain() -> None:
    """The goals that measured 0/3, by the domain each one needs."""
    for request, wanted in (
        ("List my notes.", "notes"),
        ("Describe what is on my screen right now.", "diagnostics"),
        ("What is my screen brightness set to?", "brightness"),
        ("What is in my clipboard?", "clipboard"),
        ("What is on my calendar tomorrow?", "calendar"),
        ("Remind me to call mum at six.", "reminders"),
        (
            "Create a file called notes.txt, write a word in it, then read it "
            "back to me.",
            "files",
        ),
    ):
        chosen = candidate_domains(request)
        assert wanted in chosen, f"{request!r} selected {chosen}, wanted {wanted}"


# --- the hand-written part cannot rot quietly --------------------------------


def test_every_alias_names_a_real_loadable_domain() -> None:
    """The alias list is tiny and deliberate; it is also the only part not
    derived from the catalogue, so it is the only part that can go stale
    silently. Every mail action is named gmail_*, which is why "email" needs
    an entry at all."""
    loadable = set(loadable_domains())
    for word, domain in _SELECTION_ALIASES.items():
        assert domain in loadable, (
            f"alias {word!r} points at {domain!r}, which is not a loadable "
            f"domain. Loadable: {sorted(loadable)}"
        )
        assert domain not in CORE_DOMAINS, (
            f"alias {word!r} points at the core domain {domain!r}, which is "
            "already sent whole"
        )


def test_selection_never_offers_a_core_domain() -> None:
    """Loading a core domain spends a round trip on tools already sent.
    ``loadable_domains`` excludes them; selection must not reintroduce them."""
    for request in (
        "open spotify",
        "close chrome",
        "mute the sound",
        "what is the time",
        "open my documents folder",
    ):
        assert not set(candidate_domains(request)) & set(CORE_DOMAINS)


def test_selection_is_bounded() -> None:
    """At most two domains, and only when the second is nearly as strong.

    An early version returned a runner-up for almost every request -- browser,
    at +1669 tokens, on half of them. Unbounded breadth turns a targeted
    pre-load back into the catalogue it replaced.
    """
    for request in (
        "List my notes.",
        "Scroll down the page and check my email and read my calendar and "
        "describe my screen and tell me my brightness.",
    ):
        chosen = candidate_domains(request)
        assert len(chosen) <= 2, f"{request!r} selected {chosen}"
        assert len(set(chosen)) == len(chosen), f"duplicates in {chosen}"


def test_every_selectable_domain_is_reachable_by_its_own_name() -> None:
    """A domain nothing can select is a domain back behind load_tools.

    Derivation is the guard: the vocabulary is built from DOMAINS, so a new
    subject arrives selectable. This fails if one is added whose name no
    request could match.
    """
    unreachable = [
        domain
        for domain in loadable_domains()
        if domain not in candidate_domains(f"{domain} please", limit=2)
    ]
    assert unreachable == [], (
        f"these domains cannot be selected by name: {unreachable}. They are "
        "reachable only if the model calls load_tools, which it measurably "
        "does not."
    )


def test_a_singular_request_reaches_a_plural_domain() -> None:
    """Found by a failing test, not by reading the code.

    "delete my note" did not match the notes domain at all. "note" is four
    characters, too short for the prefix rule, so the whole score came from
    "delete" -- a word calendar, downloads and files share equally. The
    singular of every plural domain was unreachable, and the request landed on
    whichever domain happened to sort first.
    """
    for request, wanted in (
        ("delete my note", "notes"),
        ("read that file", "files"),
        ("set a reminder", "reminders"),
    ):
        assert wanted in candidate_domains(request), (
            f"{request!r} selected {candidate_domains(request)}, wanted {wanted}"
        )


def test_one_shared_verb_does_not_buy_a_second_domain() -> None:
    """The runner-up needs more than a verb everything has.

    Measured: "delete my note" scored notes 5, calendar 4, downloads 4, files
    4 -- all four on "delete". A ratio test alone kept calendar, at +785
    tokens for tools the request would never call. A real pair scores like
    "what is my screen brightness set to": diagnostics 17, brightness 16.
    """
    chosen = candidate_domains("delete my note")
    assert chosen == ("notes",), f"expected notes alone, got {chosen}"

    pair = candidate_domains("What is my screen brightness set to?")
    assert "brightness" in pair, (
        f"a genuinely spanning request should keep both, got {pair}"
    )


def test_a_selected_domain_actually_adds_its_tools() -> None:
    """Selection has to change the tool list, not just a variable."""
    chosen = candidate_domains("List my notes.")
    assert chosen == ("notes",)

    names = {
        definition["function"]["name"]
        for definition in tool_definitions_for(list(chosen))
    }
    assert "notes_list" in names
    assert set(DOMAINS["notes"]).issubset(names)
    assert _cost(chosen) > 0
