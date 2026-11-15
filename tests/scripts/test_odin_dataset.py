"""O2: the Odin fine-tune dataset is complete, valid, deterministic and clean."""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

from grandpa.action_layer.catalogue import CATALOGUE, EXCLUSIONS, get

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "odin" / "make_dataset.py"
SPEC = importlib.util.spec_from_file_location("odin_make_dataset", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
make = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = make
SPEC.loader.exec_module(make)


@pytest.fixture(scope="module")
def examples():
    return make.build_examples(seed=7)


def _calls(example):
    return [
        call["function"]
        for message in example.messages
        for call in message.get("tool_calls", []) or []
    ]


def test_every_catalogued_action_is_covered(examples) -> None:
    covered = {e.action for e in examples if e.action}
    assert covered == {spec.name for spec in CATALOGUE}


def test_every_action_has_several_phrasings(examples) -> None:
    users: dict[str, set[str]] = {}
    for e in examples:
        if e.action:
            users.setdefault(e.action, set()).add(e.messages[1]["content"])
    thin = {action: len(texts) for action, texts in users.items() if len(texts) < 2}
    assert not thin, thin


def test_every_tool_call_matches_the_catalogue_schema(examples) -> None:
    assert make.validate(examples) == []


def test_the_validator_catches_a_bad_call() -> None:
    assert make.schema_problems("volume_set", {"level": 150})
    assert make.schema_problems("volume_set", {})
    assert make.schema_problems("volume_set", {"level": 30, "extra": 1})
    assert make.schema_problems("not_an_action", {})
    assert make.schema_problems("volume_set", {"level": 30}) == []


def test_argument_values_appear_in_what_the_user_said(examples) -> None:
    for e in examples:
        user = e.messages[1]["content"]
        for call in _calls(e):
            for value in call["arguments"].values():
                if isinstance(value, (str, int)) and not isinstance(value, bool):
                    assert str(value) in user, (user, call)


def test_tamil_and_thanglish_phrasings_are_present(examples) -> None:
    texts = {e.messages[1]["content"] for e in examples if e.language == "ta"}
    assert any("volume" in t and "ku vei" in t for t in texts)
    assert any("en notes kaattu" in t for t in texts)
    assert len(texts) >= 30


def test_confirmable_actions_have_a_yes_and_a_no(examples) -> None:
    kinds: dict[str, set[str]] = {}
    for e in examples:
        kinds.setdefault(e.action, set()).add(e.kind)
    for spec in CATALOGUE:
        if spec.requires_confirmation:
            assert {"confirm_yes", "confirm_no"} <= kinds[spec.name], spec.name
        else:
            assert "tool" in kinds[spec.name], spec.name


def test_a_declined_confirmation_is_answered_without_claiming_success(examples) -> None:
    for e in (x for x in examples if x.kind == "confirm_no"):
        tool = next(m for m in e.messages if m["role"] == "tool")
        assert json.loads(tool["content"])["error"] == "confirmation_declined"
        assert not e.messages[-1]["content"].lower().startswith("done")


def test_refusals_make_no_tool_call_and_name_excluded_things(examples) -> None:
    refusals = [e for e in examples if e.kind == "refusal"]
    assert refusals
    for e in refusals:
        assert not _calls(e)
    assert all(name in EXCLUSIONS for _, name in make.REFUSALS)


def test_the_persona_is_brief(examples) -> None:
    for e in (x for x in examples if x.kind == "persona"):
        assert len(e.messages[-1]["content"]) <= 200


def test_each_example_offers_its_tool_among_others(examples) -> None:
    for e in (x for x in examples if x.action):
        names = {t["function"]["name"] for t in e.tools}
        assert e.action in names and len(names) > 1


def test_deterministic_for_a_seed(tmp_path: Path) -> None:
    first = make.build_examples(seed=7)
    second = make.build_examples(seed=7)
    assert [e.to_json() for e in first] == [e.to_json() for e in second]
    other = make.build_examples(seed=8)
    assert [e.to_json() for e in first] != [e.to_json() for e in other]


def test_held_out_split_is_disjoint_and_non_empty(examples) -> None:
    train, held = make.split(examples, seed=7, eval_fraction=0.1)
    assert held and train
    assert not {e.key() for e in train} & {e.key() for e in held}
    assert len(train) + len(held) == len(examples)


def test_main_writes_the_files(tmp_path: Path) -> None:
    assert make.main(["--out", str(tmp_path), "--seed", "7"]) == 0
    stats = json.loads((tmp_path / "stats.json").read_text(encoding="utf-8"))
    assert stats["actions_covered"] == len(CATALOGUE)
    rows = (tmp_path / "train.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(rows) == stats["train"]
    first = json.loads(rows[0])
    assert {"messages", "tools", "kind", "language", "action"} <= set(first)


_PERSONAL = re.compile(r"hari|sudhan|captain|@gmail\.com|C:\\\\Users", re.IGNORECASE)


def test_no_personal_data(examples) -> None:
    for e in examples:
        assert not _PERSONAL.search(e.to_json()), e.to_json()[:200]


def test_get_is_the_catalogue_get() -> None:
    assert make.get is get
