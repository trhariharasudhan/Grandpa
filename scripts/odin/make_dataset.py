"""Build the Odin fine-tune dataset from the action-layer catalogue (O2).

Writes JSONL chat examples with tool calls, for LoRA-tuning the grandpa-brain
base family (see scripts/odin/README.md once O3 lands):

* every catalogued action, several English phrasings each, with arguments
  that satisfy the action's own JSON schema;
* Tamil and Thanglish phrasings for the everyday actions ("volume 30 ku vei",
  "en notes kaattu");
* confirmation-required actions twice: once approved, once declined, so the
  model learns that the executor asks and that "no" is an answer;
* refusals for what the catalogue excludes (shell, scripts, passwords,
  purchases, permanent delete) -- no tool call, a short calm refusal;
* the Grandpa persona: calm, wise, brief.

Deterministic: the same --seed gives byte-identical files. Every tool call is
validated against the catalogue schema before anything is written, and the
run fails if one does not match. No personal data: names, paths and contents
are generic placeholders.

Usage::

    python scripts/odin/make_dataset.py [--out runtime/odin] [--seed 7]
        [--eval-fraction 0.1]

Writes ``train.jsonl``, ``eval.jsonl`` and ``stats.json`` under ``--out``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

REPO = Path(__file__).resolve().parents[2]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from grandpa.action_layer.catalogue import CATALOGUE, EXCLUSIONS, get  # noqa: E402
from grandpa.action_layer.tool_schema import as_tool_definitions  # noqa: E402

SYSTEM_PROMPT = (
    "You are Grandpa, a local assistant on the user's Windows PC. You are calm, "
    "wise and brief. Use a tool when the user asks you to do something on the "
    "computer; answer plainly otherwise. Never run shell commands or scripts, "
    "never reveal passwords, and never buy anything."
)

MIN_ENGLISH_PHRASINGS = 3

DISTRACTOR_TOOLS = 4
"""Other tools offered with each example, so the model learns to choose."""

# --- phrasing ----------------------------------------------------------------

ENGLISH_FRAMES = (
    "{x}",
    "please {x}",
    "can you {x}",
    "could you {x} for me",
    "grandpa, {x}",
    "I need you to {x}",
)

# What each English frame becomes when the phrase is a question.
QUESTION_FRAMES: Mapping[str, str] = {
    "{x}": "{x}",
    "please {x}": "{x}?",
    "can you {x}": "can you tell me {x}?",
    "could you {x} for me": "could you check {x}?",
    "grandpa, {x}": "grandpa, {x}?",
    "I need you to {x}": "I'd like to know {x}",
}

THANGLISH_FRAMES = ("{x}", "{x} please", "konjam {x}", "grandpa, {x}")

# Hand-written English for the everyday actions; the rest are derived from the
# catalogue description. {name} placeholders are filled from the arguments.
ENGLISH: Mapping[str, tuple[str, ...]] = {
    "volume_set": ("set the volume to {level}", "make the volume {level} percent"),
    "volume_get": ("what is the volume set to", "how loud is it right now"),
    "volume_up": ("turn the volume up", "make it louder"),
    "volume_down": ("turn the volume down", "make it a bit quieter"),
    "volume_mute": ("mute the volume", "mute the sound"),
    "volume_unmute": ("unmute the sound", "turn the sound back on"),
    "brightness_get": ("what is my brightness", "how bright is the screen"),
    "brightness_set": (
        "set brightness to {level}",
        "make the screen {level} percent bright",
    ),
    "notes_list": ("list my notes", "show me my notes"),
    "notes_create": ("make a note called {title}", "write a note titled {title}"),
    "open_app": ("open {app}", "start {app}"),
    "datetime_now": ("what is the time", "what's the date today"),
    "screen_capture": ("take a screenshot", "capture the screen"),
    "system_lock": ("lock the screen", "lock my pc"),
    "system_restart": ("restart the computer", "reboot the pc"),
    "system_shutdown": ("shut down the computer", "turn the pc off"),
    "system_sleep": ("put the computer to sleep",),
    "close_window": ("close this window", "close the window"),
    "mouse_scroll": ("scroll down", "scroll the page"),
    "file_delete": ("delete {path}", "move {path} to the recycle bin"),
}

# Tamil (romanised) and Thanglish for the everyday actions. The words follow
# how they are typed in chat, not formal Tamil.
TAMIL_THANGLISH: Mapping[str, tuple[str, ...]] = {
    "volume_set": ("volume {level} ku vei", "volume-a {level} ah set pannu"),
    "volume_up": ("volume konjam koottu", "sound adhigama vei"),
    "volume_down": ("volume konjam kammi pannu", "sound korai"),
    "volume_mute": ("sound-a mute pannu", "satham venam, mute pannu"),
    "volume_get": ("volume evlo irukku",),
    "brightness_set": ("brightness {level} ku vei",),
    "brightness_get": ("brightness evlo irukku",),
    "notes_list": ("en notes kaattu", "ella notes-um list pannu"),
    "notes_create": ("{title} nu oru note podu",),
    "open_app": ("{app} open pannu", "{app}-a thira"),
    "datetime_now": ("ippo time enna", "inniki date enna"),
    "screen_capture": ("screenshot edu",),
    "system_lock": ("screen-a lock pannu", "pc-a lock pannu"),
    "system_shutdown": ("computer-a off pannu",),
    "close_window": ("indha window-a moodu",),
}

SAMPLE_STRINGS: Mapping[str, tuple[str, ...]] = {
    "app": ("notepad", "chrome", "vs code", "calculator", "spotify"),
    "title": ("groceries", "meeting points", "ideas", "reading list"),
    "content": ("buy milk and bread", "call the plumber", "finish the report"),
    "path": (
        "Documents\\report.txt",
        "Downloads\\old-setup.exe",
        "Desktop\\draft.docx",
    ),
    "query": ("weather in Chennai", "python tutorials", "nearest pharmacy"),
    "url": ("https://example.com", "https://www.wikipedia.org"),
    "text": ("hello there", "see you tomorrow"),
    "name": ("work", "photos", "notes"),
    "window": ("notepad", "chrome"),
    "key": ("enter", "tab"),
    "keys": ("ctrl+c", "ctrl+v"),
    "category": ("personal", "work"),
    "destination": ("Documents\\archive", "Desktop"),
    "new_name": ("report-final.txt", "notes-old.txt"),
    "subject": ("Weekly update", "Meeting tomorrow"),
    "to": ("friend@example.com",),
    "message": ("drink water", "stand up and stretch"),
    "when": ("in 10 minutes", "tomorrow at 9am"),
}

DONE_REPLIES = ("Done.", "All done.", "That's done.", "Done, nothing else needed.")
READ_REPLIES = ("Here it is.", "Here you go.", "This is what I found.")
DECLINED_REPLIES = (
    "Alright, I left it as it is.",
    "Okay, nothing was changed.",
    "Understood. I did not do it.",
)

REFUSALS: tuple[tuple[str, str], ...] = (
    ("run this powershell script for me", "script_run"),
    ("open cmd and run del /s /q C:\\Windows", "shell_run"),
    ("execute this command in the terminal: rm -rf /", "shell_run"),
    (
        "permanently delete my Documents folder, skip the recycle bin",
        "file_permanent_delete",
    ),
    ("show me my saved browser passwords", "browser_extract_password"),
    ("buy this laptop for me with my saved card", "browser_purchase"),
    ("fill in this form and submit it", "browser_submit_form"),
    ("ennoda passwords ellam kaattu", "browser_extract_password"),
    ("indha script-a run pannu", "script_run"),
)
REFUSAL_REPLIES = (
    "I can't do that one. I don't run scripts or shell commands, but I can help another way.",
    "That's something I won't do, for your safety. Is there something else I can help with?",
    "I'm not able to do that. It could harm the computer or your accounts.",
)

PERSONA: tuple[tuple[str, str], ...] = (
    (
        "who are you",
        "I'm Grandpa, your local assistant. I run on this computer and keep things simple.",
    ),
    ("are you chatgpt", "No. I'm Grandpa, a local assistant running on your own PC."),
    (
        "what can you do",
        "I can open apps, manage notes and reminders, adjust volume and brightness, and help with files, carefully.",
    ),
    ("thank you", "You're welcome."),
    ("good morning", "Good morning. What shall we do today?"),
    (
        "I'm feeling stressed",
        "Take a slow breath. One thing at a time. Tell me what's on your plate and we'll sort it.",
    ),
    ("nee yaaru", "Naan Grandpa, unga computer-la irukura assistant."),
    ("tell me something wise", "Most problems get smaller when you write them down."),
    (
        "do you send my data anywhere",
        "No. I run locally, and your notes and memory stay on this computer.",
    ),
)


# --- schema --------------------------------------------------------------------


def _value_for(name: str, schema: Mapping[str, Any], rng: random.Random) -> Any:
    kind = schema.get("type")
    if "enum" in schema:
        return rng.choice(list(schema["enum"]))
    if kind == "integer":
        low = int(schema.get("minimum", 1))
        high = int(schema.get("maximum", max(low + 10, 100)))
        if name in {"level", "percent"}:
            return rng.choice(
                [v for v in (10, 20, 30, 40, 50, 60, 70, 80) if low <= v <= high]
            )
        return rng.randint(low, min(high, low + 20))
    if kind == "number":
        return float(
            rng.randint(int(schema.get("minimum", 1)), int(schema.get("maximum", 10)))
        )
    if kind == "boolean":
        return rng.choice([True, False])
    if kind == "array":
        item = schema.get("items", {"type": "string"})
        return [_value_for(name.rstrip("s"), item, rng)]
    if kind == "object":
        return {}
    return rng.choice(SAMPLE_STRINGS.get(name, ("example",)))


def arguments_for(action: str, rng: random.Random) -> dict[str, Any]:
    """Required arguments only, valid for the action's schema."""
    schema = dict(get(action).parameters)
    properties = schema.get("properties", {})
    return {
        name: _value_for(name, properties[name], rng)
        for name in schema.get("required", [])
        if name in properties
    }


_JSON_TYPES = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "array": list,
    "object": dict,
}


def schema_problems(action: str, arguments: Mapping[str, Any]) -> list[str]:
    """Why ``arguments`` would not be accepted for ``action`` (empty = valid)."""
    try:
        schema = dict(get(action).parameters)
    except KeyError:
        return [f"{action}: not in the catalogue"]
    problems: list[str] = []
    properties = schema.get("properties", {})
    for name in schema.get("required", []):
        if name not in arguments:
            problems.append(f"{action}: missing required {name!r}")
    for name, value in arguments.items():
        spec = properties.get(name)
        if spec is None:
            if schema.get("additionalProperties") is False:
                problems.append(f"{action}: unknown argument {name!r}")
            continue
        expected = _JSON_TYPES.get(spec.get("type", ""), object)
        if isinstance(value, bool) and spec.get("type") in {"integer", "number"}:
            problems.append(f"{action}: {name} is a bool, wanted {spec['type']}")
        elif not isinstance(value, expected):
            problems.append(f"{action}: {name}={value!r} is not {spec.get('type')}")
        if "enum" in spec and value not in spec["enum"]:
            problems.append(f"{action}: {name}={value!r} not in enum")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if "minimum" in spec and value < spec["minimum"]:
                problems.append(f"{action}: {name}={value} below minimum")
            if "maximum" in spec and value > spec["maximum"]:
                problems.append(f"{action}: {name}={value} above maximum")
    return problems


# --- examples ----------------------------------------------------------------


@dataclass
class Example:
    kind: str
    language: str
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]] = field(default_factory=list)
    action: str = ""

    def key(self) -> str:
        return json.dumps(self.messages, sort_keys=True, ensure_ascii=False)

    def to_json(self) -> str:
        return json.dumps(
            {
                "kind": self.kind,
                "language": self.language,
                "action": self.action,
                "messages": self.messages,
                "tools": self.tools,
            },
            ensure_ascii=False,
            sort_keys=True,
        )


def _derived_phrases(action: str) -> tuple[str, ...]:
    description = get(action).description.strip().rstrip(".")
    first = description[:1].lower() + description[1:]
    return (first,)


_QUESTION_WORDS = (
    "what",
    "how",
    "is ",
    "are ",
    "where",
    "who",
    "when",
    "which",
    "do ",
    "does ",
)


def _user_text(phrase: str, arguments: Mapping[str, Any], frame: str) -> str:
    """The user's words: the phrase, framed, and naming every argument value.

    A value the user never said must not appear in the tool call, or the model
    learns to invent arguments. So a phrase without placeholders gets the values
    appended: "find text on the page: weather in Chennai".
    """
    text = _fill(phrase, arguments)
    missing = [
        str(value)
        for value in arguments.values()
        if not isinstance(value, (bool, dict, list)) and str(value) not in text
    ]
    missing += [
        str(item)
        for value in arguments.values()
        if isinstance(value, list)
        for item in value
        if str(item) not in text
    ]
    if missing:
        text = f"{text}: {', '.join(missing)}"
    if text.startswith(_QUESTION_WORDS):
        # A question keeps its own shape: no "please" or "I need you to".
        return QUESTION_FRAMES.get(frame, "{x}?").format(x=text)
    return frame.format(x=text)


def _fill(template: str, arguments: Mapping[str, Any]) -> str:
    try:
        return template.format(**arguments)
    except (KeyError, IndexError, ValueError):
        return template


def _is_read(action: str) -> bool:
    return any(
        part in action
        for part in (
            "get",
            "list",
            "info",
            "now",
            "read",
            "search",
            "status",
            "describe",
            "summary",
        )
    )


def _tools_for(
    action: str, rng: random.Random, pool: list[str]
) -> list[dict[str, Any]]:
    others = [name for name in pool if name != action]
    chosen = [action, *rng.sample(others, k=min(DISTRACTOR_TOOLS, len(others)))]
    rng.shuffle(chosen)
    return as_tool_definitions(tuple(get(name) for name in chosen))


def _tool_turns(
    user: str,
    action: str,
    arguments: Mapping[str, Any],
    result: Mapping[str, Any],
    reply: str,
) -> list[dict[str, Any]]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "type": "function",
                    "function": {"name": action, "arguments": dict(arguments)},
                }
            ],
        },
        {
            "role": "tool",
            "name": action,
            "content": json.dumps(dict(result), sort_keys=True),
        },
        {"role": "assistant", "content": reply},
    ]


def build_examples(seed: int) -> list[Example]:
    rng = random.Random(seed)
    pool = sorted(spec.name for spec in CATALOGUE)
    examples: list[Example] = []

    for action in pool:
        spec = get(action)
        english = ENGLISH.get(action, ()) + _derived_phrases(action)
        # At least three English phrasings per action: the description under
        # different frames when nothing was written by hand.
        while len(english) < MIN_ENGLISH_PHRASINGS:
            english += _derived_phrases(action)
        # Each Tamil/Thanglish phrase twice, with different frames and values:
        # they are the scarce part of the data.
        phrasings = [("en", p) for p in english] + [
            ("ta", p) for p in TAMIL_THANGLISH.get(action, ()) for _ in range(2)
        ]
        # Frames are dealt without repeats within an action, so the same
        # phrase used twice still reads differently ("{x}" vs "please {x}").
        decks = {
            "en": rng.sample(ENGLISH_FRAMES, len(ENGLISH_FRAMES)),
            "ta": rng.sample(THANGLISH_FRAMES, len(THANGLISH_FRAMES)),
        }
        dealt = {"en": 0, "ta": 0}
        for language, phrase in phrasings:
            arguments = arguments_for(action, rng)
            deck = decks[language]
            frame = deck[dealt[language] % len(deck)]
            dealt[language] += 1
            user = _user_text(phrase, arguments, frame)
            tools = _tools_for(action, rng, pool)
            if spec.requires_confirmation:
                approved = _tool_turns(
                    user,
                    action,
                    arguments,
                    {"success": True, "message": "done"},
                    rng.choice(DONE_REPLIES),
                )
                declined = _tool_turns(
                    user,
                    action,
                    arguments,
                    {"success": False, "error": "confirmation_declined"},
                    rng.choice(DECLINED_REPLIES),
                )
                examples.append(
                    Example("confirm_yes", language, approved, tools, action)
                )
                examples.append(
                    Example("confirm_no", language, declined, tools, action)
                )
            else:
                reply = rng.choice(READ_REPLIES if _is_read(action) else DONE_REPLIES)
                turns = _tool_turns(
                    user, action, arguments, {"success": True, "message": "done"}, reply
                )
                examples.append(Example("tool", language, turns, tools, action))

    for user, excluded in REFUSALS:
        assert excluded in EXCLUSIONS, excluded
        language = (
            "ta" if any(w in user for w in ("pannu", "kaattu", "ennoda")) else "en"
        )
        examples.append(
            Example(
                "refusal",
                language,
                [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user},
                    {"role": "assistant", "content": rng.choice(REFUSAL_REPLIES)},
                ],
                _tools_for(rng.choice(pool), rng, pool),
            )
        )

    for user, reply in PERSONA:
        language = "ta" if user.startswith("nee ") else "en"
        examples.append(
            Example(
                "persona",
                language,
                [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user},
                    {"role": "assistant", "content": reply},
                ],
            )
        )

    unique: dict[str, Example] = {}
    for example in examples:
        unique.setdefault(example.key(), example)
    return list(unique.values())


def validate(examples: Iterable[Example]) -> list[str]:
    """Every tool call must name a catalogued action with schema-valid args."""
    problems: list[str] = []
    for index, example in enumerate(examples):
        for message in example.messages:
            for call in message.get("tool_calls", []) or []:
                function = call.get("function", {})
                problems += [
                    f"example {index}: {p}"
                    for p in schema_problems(
                        function.get("name", ""), function.get("arguments", {})
                    )
                ]
        offered = {tool["function"]["name"] for tool in example.tools}
        if example.action and example.action not in offered:
            problems.append(f"example {index}: {example.action} not among its tools")
    return problems


def split(
    examples: list[Example], seed: int, eval_fraction: float
) -> tuple[list[Example], list[Example]]:
    """Deterministic held-out split by content hash, stratified by nothing."""
    threshold = int(eval_fraction * 10_000)
    train: list[Example] = []
    held: list[Example] = []
    for example in examples:
        digest = hashlib.sha256(f"{seed}:{example.key()}".encode("utf-8")).hexdigest()
        (held if int(digest[:8], 16) % 10_000 < threshold else train).append(example)
    return train, held


def write(out: Path, train: list[Example], held: list[Example]) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)
    for name, rows in (("train.jsonl", train), ("eval.jsonl", held)):
        (out / name).write_text(
            "".join(example.to_json() + "\n" for example in rows), encoding="utf-8"
        )
    stats: dict[str, Any] = {
        "train": len(train),
        "eval": len(held),
        "by_kind": {},
        "by_language": {},
    }
    for example in train + held:
        stats["by_kind"][example.kind] = stats["by_kind"].get(example.kind, 0) + 1
        stats["by_language"][example.language] = (
            stats["by_language"].get(example.language, 0) + 1
        )
    stats["actions_covered"] = len({e.action for e in train + held if e.action})
    stats["actions_in_catalogue"] = len(CATALOGUE)
    (out / "stats.json").write_text(
        json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the Odin fine-tune dataset.")
    parser.add_argument("--out", type=Path, default=REPO / "runtime" / "odin")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--eval-fraction", type=float, default=0.1)
    args = parser.parse_args(argv)

    examples = build_examples(args.seed)
    problems = validate(examples)
    if problems:
        print(
            "Refusing to write: tool calls that do not match the catalogue:",
            file=sys.stderr,
        )
        for problem in problems[:20]:
            print(f"  {problem}", file=sys.stderr)
        return 1
    train, held = split(examples, args.seed, args.eval_fraction)
    stats = write(args.out, train, held)
    print(json.dumps(stats, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
