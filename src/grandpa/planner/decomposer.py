"""Deterministic-first goal decomposition with an optional local-model fallback."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from grandpa.planner.action_catalog import public_catalog
from grandpa.planner.models import (
    Goal,
    PlannerLimits,
    PlanStep,
    RecoveryPolicy,
    RetryPolicy,
    StepDependency,
    StepVerification,
)

ModelPlanner = Callable[[str, list[dict[str, Any]], int], dict[str, Any] | str]


class GoalDecompositionError(ValueError):
    """Raised when a goal cannot be decomposed without guessing."""


#: Fragments shared by the "open <app> and <clause>" patterns, so every one of
#: them accepts the same verbs, the same connectors and the same shape of name.
_OPEN = r"(?:open|launch|start)"
_CONNECTOR = r"(?:and|then)"
_NAME = r"[\w .+-]+?"


class DeterministicDecomposer:
    """Recognize bounded multi-step patterns while preserving literal payloads."""

    def decompose(self, goal: Goal, limits: PlannerLimits) -> list[PlanStep] | None:
        text = goal.text.strip()
        normalized = goal.normalized
        if not text:
            return None

        match = re.fullmatch(
            r"(?:open|launch|start)\s+(?P<app>[\w .+-]+?)\s+(?:and|then)\s+search(?:\s+(?P<provider>google|bing|duckduckgo))?\s*(?:for\s+)?(?P<query>.+)",
            normalized,
        )
        app = _app_name(match.group("app")) if match else None
        if match and app is not None:
            query = _literal_slice(text, match.start("query"), match.end("query"))
            return _chain(
                (
                    "launch_application",
                    f"Open {app.title()}",
                    {"app": app},
                    "application_window_exists",
                ),
                (
                    "wait_for_window",
                    f"Wait for {app.title()}",
                    {"app": app},
                    "application_window_exists",
                ),
                (
                    "focus_window",
                    f"Focus {app.title()}",
                    {"app": app},
                    "application_window_focused",
                ),
                (
                    "browser_search",
                    f"Search for {query}",
                    {"query": query, "provider": match.group("provider") or "google"},
                    "browser_results_visible",
                ),
            )

        match = _match_notepad_close_goal(text)
        if match:
            payload = match.group("payload").strip().strip('"')
            outcome = match.group("outcome").casefold().replace("’", "'")
            choice = "cancel" if "cancel" in outcome else "discard"
            verification = "document_open" if choice == "cancel" else "document_closed"
            return _chain(
                (
                    "launch_application",
                    "Open a fresh Notepad document",
                    {"app": "notepad", "new_instance": True},
                    "application_window_exists",
                ),
                (
                    "wait_for_window",
                    "Wait for Notepad",
                    {"app": "notepad"},
                    "application_window_exists",
                ),
                (
                    "focus_window",
                    "Focus Notepad",
                    {"app": "notepad"},
                    "application_window_focused",
                ),
                (
                    "type_text",
                    "Type the requested literal text",
                    {"text": payload, "window": "notepad"},
                    "typed_text_present",
                ),
                ("close_window", "Close Notepad", {"app": "notepad"}, "dialog_present"),
                (
                    "invoke_verified_dialog_action",
                    "Cancel the verified close dialog"
                    if choice == "cancel"
                    else "Choose Don't Save in the verified dialog",
                    {"choice": choice},
                    verification,
                ),
            )

        match = re.fullmatch(
            r"(?:open|launch|start)\s+settings\s+(?:and|then)\s+(?:go|navigate)\s+to\s+(.+)",
            normalized,
        )
        if match:
            target = match.group(1).strip()
            return _chain(
                (
                    "launch_application",
                    "Open Settings",
                    {"app": "settings"},
                    "application_window_exists",
                ),
                (
                    "wait_for_window",
                    "Wait for Settings",
                    {"app": "settings"},
                    "application_window_exists",
                ),
                (
                    "find_element",
                    f"Find {target}",
                    {"name": target, "actionable": True},
                    "element_visible",
                ),
                (
                    "click_element",
                    f"Open {target}",
                    {"name": target, "window": "settings"},
                    "text_visible",
                ),
            )

        match = re.fullmatch(
            r"(?:open|launch|start)\s+(?:vs ?code|visual studio code)\s+(?:and|then)\s+open\s+(?:the\s+)?(.+?)(?:\s+project|\s+repo(?:sitory)?)?",
            normalized,
        )
        if match:
            project = match.group(1).strip()
            return _chain(
                (
                    "launch_application",
                    f"Open {project} in VS Code",
                    {"app": "vscode", "project_path": project},
                    "application_window_exists",
                ),
                (
                    "wait_for_window",
                    "Wait for VS Code",
                    {"app": "vscode"},
                    "application_window_exists",
                ),
                (
                    "focus_window",
                    "Focus VS Code",
                    {"app": "vscode"},
                    "application_window_focused",
                ),
            )

        match = re.fullmatch(
            r"(?:open|launch|start)\s+calculator\s+(?:and|then)\s+calculate\s+(.+)",
            normalized,
        )
        if match:
            expression = _safe_expression(match.group(1))
            if expression is None:
                return None
            expected_result = _calculator_result(expression)
            if expected_result is None:
                return None
            return _chain(
                (
                    "launch_application",
                    "Open Calculator",
                    {"app": "calculator"},
                    "application_window_exists",
                ),
                (
                    "wait_for_window",
                    "Wait for Calculator",
                    {"app": "calculator"},
                    "application_window_exists",
                ),
                (
                    "focus_window",
                    "Focus Calculator",
                    {"app": "calculator"},
                    "application_window_focused",
                ),
                (
                    "input_calculator_expression",
                    f"Enter {expression}",
                    {"expression": expression},
                    "calculator_expression_visible",
                ),
                (
                    "invoke_calculator_equals",
                    "Calculate and verify the result",
                    {"expected_result": expected_result},
                    "calculator_result",
                ),
            )

        match = re.fullmatch(
            r"scroll\s+(up|down)\s+until\s+(?:the\s+)?(.+?)(?:\s+appears)?", normalized
        )
        if match:
            return _chain(
                (
                    "scroll_until",
                    f"Scroll until {match.group(2)} appears",
                    {
                        "direction": match.group(1),
                        "name": match.group(2),
                        "max_attempts": limits.max_scroll_attempts,
                    },
                    "element_visible",
                )
            )

        match = re.fullmatch(
            r"find\s+(?:the\s+)?(.+?)\s+(?:and|then)\s+click(?:\s+it)?", normalized
        )
        if match:
            target = match.group(1).removesuffix(" button").strip()
            return _chain(
                (
                    "find_element",
                    f"Find {target}",
                    {"name": target, "actionable": True},
                    "element_visible",
                ),
                (
                    "click_element",
                    f"Click {target}",
                    {"name": target},
                    "target_state_changed",
                ),
            )

        # Multi-step Browser Intelligence goal: Open/Find official <topic> and summarize/read <section>
        match = re.fullmatch(
            r"(?:open|find|search for|locate)\s+(?:official\s+)?(.+?)\s*(?:docs|documentation|site|page)?\s+(?:and|then)\s+(?:summarize|read|extract)\s+(?:the\s+)?(installation|requirements|pricing|specs|faq|code)\s*(?:section|steps)?",
            normalized,
        )
        if match:
            topic = match.group(1).strip()
            sec = match.group(2).strip()
            return _chain(
                (
                    "browser_navigate_smart",
                    f"Open official {topic} docs",
                    {"target": f"official {topic} docs"},
                    "execution_success",
                ),
                (
                    "browser_extract_content",
                    f"Extract {sec} section",
                    {"section": sec},
                    "execution_success",
                ),
                (
                    "browser_summarize",
                    f"Summarize {sec} section",
                    {"type": sec},
                    "execution_success",
                ),
            )

        match = re.fullmatch(r"research\s+(.+)", normalized)
        if match:
            topic = match.group(1).strip()
            return _chain(
                (
                    "browser_research",
                    f"Research {topic}",
                    {"topic": topic},
                    "execution_success",
                ),
            )

        match = re.fullmatch(r"compare\s+(.+?)\s+(?:vs|and|with)\s+(.+)", normalized)
        if match:
            item_a = match.group(1).strip()
            item_b = match.group(2).strip()
            return _chain(
                (
                    "browser_compare",
                    f"Compare {item_a} and {item_b}",
                    {"item_a": item_a, "item_b": item_b},
                    "execution_success",
                ),
            )

        match = re.fullmatch(r"(?:open|find)\s+official\s+(.+)", normalized)
        if match:
            target = match.group(1).strip()
            return _chain(
                (
                    "browser_navigate_smart",
                    f"Find official {target}",
                    {"target": f"official {target}"},
                    "execution_success",
                ),
            )

        match = re.fullmatch(
            r"(?:summarize|read)\s+(?:the\s+)?(?:current\s+)?page(?:\s+as\s+(short|detailed|bullet|technical|installation|requirements))?",
            normalized,
        )
        if match:
            stype = match.group(1) or "short"
            return _chain(
                (
                    "browser_summarize",
                    f"Summarize page ({stype})",
                    {"type": stype},
                    "execution_success",
                ),
            )

        match = re.fullmatch(
            r"(?:extract|read)\s+(installation|requirements|pricing|specs|faq|code)\s*(?:from\s+page)?",
            normalized,
        )
        if match:
            sec = match.group(1)
            return _chain(
                (
                    "browser_extract_content",
                    f"Extract {sec} section",
                    {"section": sec},
                    "execution_success",
                ),
            )

        # "open <app> and go to <site> and search for <query>". Ordered before
        # the two-clause navigation pattern below, whose destination would
        # otherwise swallow "github and search for fastapi" whole.
        match = re.fullmatch(
            rf"{_OPEN}\s+(?P<app>{_NAME})\s+{_CONNECTOR}\s+(?:go|navigate)\s+to\s+"
            rf"(?P<dest>{_NAME})\s+{_CONNECTOR}\s+search"
            r"(?:\s+(?P<provider>google|bing|duckduckgo))?\s*(?:for\s+)?(?P<query>.+)",
            normalized,
        )
        if match:
            app = _app_name(match.group("app"))
            dest = _clause_free(match.group("dest"))
            if app is not None and dest is not None:
                query = _literal_slice(text, match.start("query"), match.end("query"))
                return _chain(
                    *_open_and_focus(app),
                    ("navigate_url", f"Go to {dest}", {"url": dest}, "URL_matches"),
                    (
                        "browser_search",
                        f"Search for {query}",
                        {
                            "query": query,
                            "provider": match.group("provider") or "google",
                        },
                        "browser_results_visible",
                    ),
                )

        # "open <app> and go to <site>". The destination is passed through as
        # spoken: navigate_url hands it to the browser command handler, which
        # already resolves both bare site names ("gmail") and literal URLs, so
        # there is no URL to invent here.
        match = re.fullmatch(
            rf"{_OPEN}\s+(?P<app>{_NAME})\s+{_CONNECTOR}\s+"
            rf"(?:go|navigate)\s+to\s+(?P<dest>.+)",
            normalized,
        )
        if match:
            app = _app_name(match.group("app"))
            dest = _clause_free(match.group("dest"))
            if app is not None and dest is not None:
                return _chain(
                    *_open_and_focus(app),
                    ("navigate_url", f"Go to {dest}", {"url": dest}, "URL_matches"),
                )

        # "open <app> and type <text>". The payload is terminal and taken from
        # the original text, so its capitalisation survives and a connector
        # inside it ("type salt and pepper") stays part of what gets typed
        # rather than being read as another clause.
        match = re.fullmatch(
            rf"{_OPEN}\s+(?P<app>{_NAME})\s+{_CONNECTOR}\s+type\s+(?P<payload>.+)",
            normalized,
        )
        if match:
            app = _app_name(match.group("app"))
            if app is not None:
                payload = _literal_slice(
                    text, match.start("payload"), match.end("payload")
                )
                return _chain(
                    *_open_and_focus(app),
                    (
                        "type_text",
                        "Type the requested literal text",
                        {"text": payload, "window": app},
                        "typed_text_present",
                    ),
                )

        return _single_step(normalized)


class LocalModelDecomposer:
    """Request strict JSON from an injected or configured local model."""

    def __init__(self, planner: ModelPlanner | None = None) -> None:
        self._planner = planner
        self.model_name: str | None = None

    def decompose(self, goal: Goal, limits: PlannerLimits) -> list[PlanStep] | None:
        planner = self._planner or self._configured_planner()
        if planner is None:
            return None
        try:
            raw = planner(goal.text, public_catalog(), limits.max_steps)
            if isinstance(raw, str):
                raw = json.loads(raw)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise GoalDecompositionError(
                "The local model did not return valid planner JSON."
            ) from exc
        if not isinstance(raw, dict) or not isinstance(raw.get("steps"), list):
            raise GoalDecompositionError(
                "The local model did not return a valid plan object."
            )
        steps: list[PlanStep] = []
        for index, item in enumerate(raw["steps"], 1):
            if not isinstance(item, dict):
                raise GoalDecompositionError(
                    "The local model returned a malformed plan step."
                )
            action = str(item.get("action") or "")
            parameters = item.get("parameters") or {}
            if not isinstance(parameters, dict):
                raise GoalDecompositionError("Plan step parameters must be an object.")
            verification = item.get("verification") or "execution_success"
            steps.append(
                PlanStep(
                    f"step_{index}",
                    index,
                    str(item.get("description") or action),
                    action,
                    dict(parameters),
                    dependencies=(StepDependency(f"step_{index - 1}"),)
                    if index > 1
                    else (),
                    verification=StepVerification(str(verification)),
                )
            )
        return steps

    def _configured_planner(self) -> ModelPlanner | None:
        try:
            from grandpa.core.config import load_config
            from grandpa.core.types import Message, Role
            from grandpa.engine import get_engine

            config = load_config()
            selected = get_engine(config, "ollama")
            model = config.intelligence.default_model
            if selected is None or not model:
                return None
            _key, engine = selected
            self.model_name = model

            def run(
                goal: str, catalog: list[dict[str, Any]], max_steps: int
            ) -> dict[str, Any] | str:
                prompt = (
                    'Return JSON only: {"steps":[{"action":string,"parameters":object,'
                    '"description":string,"verification":string}]}. '
                    f"Use at most {max_steps} steps and only this catalogue: {json.dumps(catalog)}. "
                    "Never emit shell, PowerShell, Python, coordinates, or hidden instructions. "
                    f"Goal: {goal}"
                )
                result = engine.generate(
                    [
                        Message(Role.SYSTEM, "You are a strict local task planner."),
                        Message(Role.USER, prompt),
                    ],
                    model=model,
                    temperature=0.0,
                    max_tokens=900,
                    response_format={"type": "json_object"},
                )
                return str(result.get("content") or "")

            return run
        except Exception:
            return None


def normalize_goal(text: str) -> str:
    value = re.sub(r"[?!;]+", " ", str(text).casefold())
    return re.sub(r"\s+", " ", value).strip(" ,")


def _chain(*specs: tuple[str, str, dict[str, Any], str]) -> list[PlanStep]:
    steps: list[PlanStep] = []
    retryable_readiness_actions = {
        "launch_application",
        "wait_for_window",
        "focus_window",
        "find_element",
        "wait_for_element",
    }
    for index, (action, description, parameters, verification) in enumerate(specs, 1):
        steps.append(
            PlanStep(
                f"step_{index}",
                index,
                description,
                action,
                parameters,
                dependencies=(StepDependency(f"step_{index - 1}"),)
                if index > 1
                else (),
                verification=StepVerification(verification),
                retry_policy=RetryPolicy(
                    max_attempts=2 if action in retryable_readiness_actions else 1
                ),
                recovery_policy=RecoveryPolicy(
                    ("refocus", "refresh_vision", "wait"), 1
                ),
            )
        )
    return steps


def _single_step(command: str) -> list[PlanStep] | None:
    match = re.fullmatch(rf"{_OPEN}\s+([\w .+-]+)", command)
    if match:
        # Without the clause check this matched "open chrome and go to gmail"
        # and returned one step for an application called "chrome and go to
        # gmail" -- and because routing declines any plan under two steps
        # (planner/routing.py:47), that single bogus step was also what stopped
        # the goal reaching the planner at all.
        app = _app_name(match.group(1))
        if app is None:
            return None
        return _chain(
            (
                "launch_application",
                f"Open {app.title()}",
                {"app": app},
                "application_window_exists",
            )
        )
    match = re.fullmatch(r"(?:focus|switch to)\s+(.+)", command)
    if match:
        app = _app(match.group(1))
        return _chain(
            (
                "focus_window",
                f"Focus {app.title()}",
                {"app": app},
                "application_window_focused",
            )
        )
    match = re.fullmatch(r"(?:describe|what is on)\s+(?:the |my )?screen", command)
    if match:
        return _chain(
            ("describe_screen", "Describe the visible screen", {}, "execution_success")
        )
    return None


def _open_and_focus(app: str) -> tuple[tuple[str, str, dict[str, Any], str], ...]:
    """The launch-wait-focus preamble every "open <app> and ..." goal shares."""
    return (
        (
            "launch_application",
            f"Open {app.title()}",
            {"app": app},
            "application_window_exists",
        ),
        (
            "wait_for_window",
            f"Wait for {app.title()}",
            {"app": app},
            "application_window_exists",
        ),
        (
            "focus_window",
            f"Focus {app.title()}",
            {"app": app},
            "application_window_focused",
        ),
    )


#: Words that begin a new clause rather than continue a name. A goal is a
#: sequence of clauses, so text containing one of these is never a single
#: application or destination -- "chrome and go to gmail" is two instructions,
#: not an application called "chrome and go to gmail".
#:
#: Matched on word boundaries so ordinary names survive: "command prompt"
#: contains the letters of "and" but not the word.
_CLAUSE_WORDS = re.compile(r"\b(?:and|then|go to|navigate to)\b")


def _clause_free(value: str) -> str | None:
    """Return *value* stripped, or None when it is really several clauses.

    Returning None makes the pattern decline. That matters more than it looks:
    a decomposer that guesses here produces a plan to launch an application
    named "chrome and go to gmail", which cannot exist, so the user is told
    their command succeeded while nothing happens. Declining sends the goal on
    to the next resolver, and if nothing claims it the operator says so.
    """
    name = value.strip()
    if not name or _CLAUSE_WORDS.search(name):
        return None
    return name


def _app_name(value: str) -> str | None:
    """The application a clause names, or None when the text is not one."""
    name = _clause_free(value)
    return None if name is None else _app(name)


def _app(value: str) -> str:
    normalized = value.strip().casefold()
    return {
        "visual studio code": "vscode",
        "vs code": "vscode",
        "google chrome": "chrome",
    }.get(normalized, normalized)


def _safe_expression(value: str) -> str | None:
    normalized = (
        value.casefold()
        .replace("multiplied by", "*")
        .replace("times", "*")
        .replace("divided by", "/")
        .replace("plus", "+")
        .replace("minus", "-")
    )
    normalized = re.sub(r"(?<=\d)\s*[x×]\s*(?=\d)", "*", normalized)
    normalized = re.sub(r"\s+", "", normalized)
    return normalized if re.fullmatch(r"[0-9().+*/-]{1,100}", normalized) else None


def _calculator_result(expression: str) -> str | None:
    try:
        from grandpa.tools.calculator import safe_eval

        value = float(safe_eval(expression))
    except (ArithmeticError, TypeError, ValueError):
        return None
    if not (-1e100 < value < 1e100):
        return None
    return str(int(value)) if value.is_integer() else format(value, ".12g")


def _match_notepad_close_goal(text: str):
    return re.fullmatch(
        r"(?:open|launch|start)\s+notepad\s*,?\s*type\s+"
        r"(?P<payload>.+?)(?:\s*,\s*|\s+)"
        r"(?:(?:then|and|after that|finally)\s+)?close(?:\s+it)?"
        r"(?P<outcome>\s+and\s+cancel|\s+without\s+saving|"
        r"\s*,?\s*(?:and\s+)?(?:don't|dont|do not)\s+save|"
        r"\s*(?:and\s+)?discard\s+changes)\s*",
        text,
        flags=re.I,
    )


def _literal_slice(original: str, start: int, end: int) -> str:
    # Normalization preserves the useful suffix for supported search patterns.
    suffix_length = end - start
    return original.strip()[-suffix_length:].strip() or original.strip()


__all__ = [
    "DeterministicDecomposer",
    "GoalDecompositionError",
    "LocalModelDecomposer",
    "normalize_goal",
]
