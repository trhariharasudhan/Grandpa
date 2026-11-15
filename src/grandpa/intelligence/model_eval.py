"""Compare Odin models on Grandpa's own work (O4): ``grandpa models eval <tag>``.

Two measurements, both against any Ollama tag:

* **Held-out split** of the O2 dataset (``runtime/odin/eval.jsonl``, or built
  in memory from the catalogue when that file is missing). Each example's
  system + user turn goes to the model once, with the example's tools, and
  the first reply is scored: did it call the expected tool, with the expected
  arguments, and did it make no call at all when it should refuse.
* **The five-goal tool-use benchmark** from docs/development/model-names.md:
  raise the volume, read the volume, open Notepad and type, a three-step file
  chain, describe the screen. Each goal runs through the real action-layer
  loop, with the executor replaced by a recorder, so **nothing on the machine
  is touched**; a goal passes when the expected actions were called in order.

It reports tool-call accuracy, argument accuracy, refusal correctness and
latency. It never changes the default model: with ``--baseline`` it prints a
recommendation and the command a person would run to switch.
"""

from __future__ import annotations

import importlib.util
import json
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence
from unittest import mock

REPO = Path(__file__).resolve().parents[3]
DEFAULT_EVAL_PATH = REPO / "runtime" / "odin" / "eval.jsonl"
DATASET_SCRIPT = REPO / "scripts" / "odin" / "make_dataset.py"


@dataclass(frozen=True)
class Goal:
    goal: str
    expected: tuple[str, ...]


BENCHMARK: tuple[Goal, ...] = (
    Goal("turn the volume up", ("volume_up",)),
    Goal("what is my volume set to", ("volume_get",)),
    Goal("open Notepad and type hello", ("open_app", "keyboard_type")),
    Goal(
        "create a file called plan.txt on the Desktop, copy it to Documents, "
        "then read the copy",
        ("file_create", "file_copy", "file_read"),
    ),
    Goal("describe what is on my screen", ("screen_describe",)),
)
"""The five goals of the measured comparison in model-names.md (Brain 15/15,
Mini 0/15). Expected actions are matched as an ordered subsequence: a model
that also checks something first still passes."""


@dataclass
class EvalReport:
    model: str
    examples: int = 0
    tool_expected: int = 0
    tool_correct: int = 0
    args_checked: int = 0
    args_correct: int = 0
    refusals: int = 0
    refusals_correct: int = 0
    goals: int = 0
    goals_passed: int = 0
    latencies: list[float] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    goal_results: list[dict[str, Any]] = field(default_factory=list)

    @staticmethod
    def _rate(hit: int, total: int) -> float | None:
        return round(hit / total, 3) if total else None

    @property
    def tool_accuracy(self) -> float | None:
        return self._rate(self.tool_correct, self.tool_expected)

    @property
    def argument_accuracy(self) -> float | None:
        return self._rate(self.args_correct, self.args_checked)

    @property
    def refusal_correctness(self) -> float | None:
        return self._rate(self.refusals_correct, self.refusals)

    @property
    def benchmark_rate(self) -> float | None:
        return self._rate(self.goals_passed, self.goals)

    @property
    def latency_median_s(self) -> float | None:
        return round(statistics.median(self.latencies), 2) if self.latencies else None

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("latencies")
        data.update(
            tool_accuracy=self.tool_accuracy,
            argument_accuracy=self.argument_accuracy,
            refusal_correctness=self.refusal_correctness,
            benchmark_rate=self.benchmark_rate,
            latency_median_s=self.latency_median_s,
        )
        return data


# --- the held-out split ------------------------------------------------------


def load_eval_rows(path: Path | None = None) -> list[dict[str, Any]]:
    """The O2 held-out split: from disk, or rebuilt from the catalogue."""
    target = path or DEFAULT_EVAL_PATH
    if target.is_file():
        return [
            json.loads(line)
            for line in target.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    spec = importlib.util.spec_from_file_location("odin_make_dataset", DATASET_SCRIPT)
    if spec is None or spec.loader is None:  # pragma: no cover - repo layout
        raise FileNotFoundError(f"{target} not found and {DATASET_SCRIPT} missing")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(spec.name, module)
    spec.loader.exec_module(module)
    examples = module.build_examples(seed=7)
    _, held = module.split(examples, seed=7, eval_fraction=0.1)
    return [json.loads(example.to_json()) for example in held]


def _messages(rows: Sequence[Mapping[str, Any]]) -> list[Any]:
    from grandpa.core.types import Message, Role

    roles = {"system": Role.SYSTEM, "user": Role.USER}
    return [
        Message(role=roles[row["role"]], content=str(row.get("content") or ""))
        for row in rows
        if row.get("role") in roles
    ]


def _expected_call(row: Mapping[str, Any]) -> tuple[str, dict[str, Any]] | None:
    for message in row.get("messages", []):
        for call in message.get("tool_calls", []) or []:
            function = call.get("function", {})
            return str(function.get("name", "")), dict(function.get("arguments") or {})
    return None


def _parsed(arguments: Any) -> dict[str, Any]:
    if isinstance(arguments, Mapping):
        return dict(arguments)
    try:
        value = json.loads(arguments or "{}")
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _same_arguments(got: Mapping[str, Any], want: Mapping[str, Any]) -> bool:
    """Equal after the coercions a model fairly makes: "30" vs 30, case."""

    def norm(value: Any) -> str:
        return str(value).strip().lower()

    return {k: norm(v) for k, v in got.items() if k in want} == {
        k: norm(v) for k, v in want.items()
    }


def score_split(
    report: EvalReport,
    rows: Iterable[Mapping[str, Any]],
    *,
    engine: Any,
    model: str,
    clock: Callable[[], float] = time.perf_counter,
) -> None:
    for row in rows:
        expected = _expected_call(row)
        if row.get("kind") == "persona":
            continue
        report.examples += 1
        started = clock()
        try:
            response = engine.generate(
                _messages(row["messages"][:2]),
                model=model,
                tools=row.get("tools") or None,
                temperature=0.0,
            )
        except Exception as exc:  # a model error is a wrong answer, and noted
            report.errors.append(f"{row['messages'][1]['content']!r}: {exc}")
            response = {}
        report.latencies.append(clock() - started)
        calls = list((response or {}).get("tool_calls") or [])
        if row.get("kind") == "refusal":
            report.refusals += 1
            report.refusals_correct += not calls
            continue
        if expected is None:
            continue
        name, arguments = expected
        report.tool_expected += 1
        first = calls[0] if calls else {}
        if str(first.get("name") or "") == name:
            report.tool_correct += 1
            report.args_checked += 1
            report.args_correct += _same_arguments(
                _parsed(first.get("arguments")), arguments
            )


# --- the five-goal benchmark ---------------------------------------------------


def _ordered_subsequence(called: Sequence[str], expected: Sequence[str]) -> bool:
    remaining = iter(called)
    return all(any(name == want for name in remaining) for want in expected)


def run_benchmark(
    report: EvalReport,
    *,
    engine: Any,
    model: str,
    goals: Sequence[Goal] = BENCHMARK,
    clock: Callable[[], float] = time.perf_counter,
) -> None:
    """Each goal through the real loop with a recording executor: no actuation."""
    from grandpa.action_layer import loop
    from grandpa.action_layer.model import ActionResult

    for goal in goals:
        called: list[str] = []

        def record(request, confirm_callback=None, _called=called):
            _called.append(request.action)
            return ActionResult.ok(f"{request.action} recorded (eval: not run)")

        started = clock()
        try:
            with mock.patch.object(loop, "execute", record):
                loop.run(goal.goal, engine=engine, model=model, step_limit=6)
            error = ""
        except Exception as exc:
            error = str(exc)
        report.latencies.append(clock() - started)
        passed = not error and _ordered_subsequence(called, goal.expected)
        report.goals += 1
        report.goals_passed += passed
        report.goal_results.append(
            {
                "goal": goal.goal,
                "expected": list(goal.expected),
                "called": called,
                "passed": passed,
                "error": error,
            }
        )


def evaluate(
    model: str,
    *,
    engine: Any,
    rows: Iterable[Mapping[str, Any]] | None = None,
    limit: int | None = None,
    benchmark: bool = True,
) -> EvalReport:
    report = EvalReport(model=model)
    data = list(rows if rows is not None else load_eval_rows())
    if limit is not None:
        data = data[: max(0, limit)]
    score_split(report, data, engine=engine, model=model)
    if benchmark:
        run_benchmark(report, engine=engine, model=model)
    return report


# --- recommendation ------------------------------------------------------------


def recommend(candidate: EvalReport, baseline: EvalReport) -> str:
    """A sentence for a person. Never acted on by this module."""

    def score(report: EvalReport) -> float:
        parts = [
            report.tool_accuracy,
            report.argument_accuracy,
            report.refusal_correctness,
            report.benchmark_rate,
        ]
        known = [p for p in parts if p is not None]
        return sum(known) / len(known) if known else 0.0

    a, b = score(candidate), score(baseline)
    if (
        candidate.refusal_correctness is not None
        and baseline.refusal_correctness is not None
    ):
        if candidate.refusal_correctness < baseline.refusal_correctness:
            return (
                f"Keep {baseline.model}: {candidate.model} refuses less reliably "
                f"({candidate.refusal_correctness:.0%} vs {baseline.refusal_correctness:.0%})."
            )
    if a > b + 0.02:
        return (
            f"{candidate.model} scores better ({a:.0%} vs {b:.0%}). If you want it as "
            f"the default: grandpa config set intelligence.default_model {candidate.model}"
        )
    if b > a + 0.02:
        return f"Keep {baseline.model}: it scores better ({b:.0%} vs {a:.0%})."
    return f"No clear difference ({a:.0%} vs {b:.0%}); keep {baseline.model}."


__all__ = [
    "BENCHMARK",
    "EvalReport",
    "Goal",
    "evaluate",
    "load_eval_rows",
    "recommend",
    "run_benchmark",
    "score_split",
]
