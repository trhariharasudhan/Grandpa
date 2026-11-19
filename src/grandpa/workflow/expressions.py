"""Variables and conditions for YAML workflows, without ``eval``.

A workflow file is something a person (or later a plugin) hands to Grandpa,
so nothing in it is ever executed as Python. Two small languages cover what a
routine needs:

* **Templates** -- ``{{ vars.city }}``, ``{{ city }}``, ``{{ steps.battery.message }}``
  or ``{{ steps.battery.data.percent }}``. A value that is exactly one template
  keeps its type (a number stays a number); a template inside other text is
  replaced by its text.
* **Conditions** -- ``steps.battery.ok``, ``not steps.battery.ok``,
  ``vars.mode == 'quiet'``, ``steps.vol.data.level < 30``,
  ``steps.read.message contains 'error'``, joined with ``and`` / ``or``
  (``and`` binds tighter; no parentheses).

An unknown name resolves to ``None`` rather than raising, so a condition on a
step that was skipped is simply false.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

__all__ = [
    "ExpressionError",
    "evaluate_condition",
    "references",
    "render",
    "resolve",
]

_TEMPLATE = re.compile(r"\{\{\s*([A-Za-z_][\w.\-]*)\s*\}\}")
_WHOLE_TEMPLATE = re.compile(r"^\s*\{\{\s*([A-Za-z_][\w.\-]*)\s*\}\}\s*$")
_NAME = re.compile(r"^[A-Za-z_][\w.\-]*$")
_OPERATORS = ("not contains", "contains", "==", "!=", "<=", ">=", "<", ">")


class ExpressionError(ValueError):
    """A condition that cannot be parsed."""


def resolve(name: str, context: Mapping[str, Any]) -> Any:
    """Look up a dotted name. ``city`` is shorthand for ``vars.city``."""
    parts = name.split(".")
    if parts[0] not in context and parts[0] in context.get("vars", {}):
        parts = ["vars", *parts]
    value: Any = context
    for part in parts:
        if isinstance(value, Mapping) and part in value:
            value = value[part]
        else:
            return None
    return value


def references(value: Any) -> set[str]:
    """Every dotted name a value's templates refer to."""
    if isinstance(value, str):
        return set(_TEMPLATE.findall(value))
    if isinstance(value, Mapping):
        found: set[str] = set()
        for item in value.values():
            found |= references(item)
        return found
    if isinstance(value, (list, tuple)):
        found = set()
        for item in value:
            found |= references(item)
        return found
    return set()


def render(value: Any, context: Mapping[str, Any]) -> Any:
    """Fill templates in ``value`` (strings, lists and dicts, recursively)."""
    if isinstance(value, str):
        whole = _WHOLE_TEMPLATE.match(value)
        if whole:
            return resolve(whole.group(1), context)
        return _TEMPLATE.sub(lambda m: _as_text(resolve(m.group(1), context)), value)
    if isinstance(value, Mapping):
        return {key: render(item, context) for key, item in value.items()}
    if isinstance(value, list):
        return [render(item, context) for item in value]
    return value


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _operand(token: str, context: Mapping[str, Any]) -> Any:
    token = token.strip()
    if not token:
        raise ExpressionError("missing value")
    if len(token) >= 2 and token[0] == token[-1] and token[0] in "'\"":
        return token[1:-1]
    lowered = token.lower()
    if lowered in {"true", "yes"}:
        return True
    if lowered in {"false", "no"}:
        return False
    if lowered in {"none", "null"}:
        return None
    try:
        return int(token)
    except ValueError:
        pass
    try:
        return float(token)
    except ValueError:
        pass
    whole = _WHOLE_TEMPLATE.match(token)
    if whole:
        return resolve(whole.group(1), context)
    if _NAME.match(token):
        return resolve(token, context)
    raise ExpressionError(f"cannot read {token!r}")


def _compare(left: Any, operator: str, right: Any) -> bool:
    if operator in {"contains", "not contains"}:
        found = left is not None and _as_text(right).lower() in _as_text(left).lower()
        return found if operator == "contains" else not found
    if operator == "==":
        return left == right or _as_text(left) == _as_text(right)
    if operator == "!=":
        return not (left == right or _as_text(left) == _as_text(right))
    try:
        a, b = float(left), float(right)
    except (TypeError, ValueError):
        return False
    return {"<": a < b, ">": a > b, "<=": a <= b, ">=": a >= b}[operator]


def _split_outside_quotes(text: str, word: str) -> list[str]:
    pattern = re.compile(rf"\s+{word}\s+", re.IGNORECASE)
    parts: list[str] = []
    start = 0
    quote = ""
    i = 0
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == quote:
                quote = ""
        elif ch in "'\"":
            quote = ch
        else:
            m = pattern.match(text, i)
            if m:
                parts.append(text[start:i])
                start = i = m.end()
                continue
        i += 1
    parts.append(text[start:])
    return parts


def _single(text: str, context: Mapping[str, Any]) -> bool:
    text = text.strip()
    negate = False
    if re.match(r"^not\s+", text, re.IGNORECASE) and not re.match(
        r"^not\s+contains\b", text, re.IGNORECASE
    ):
        negate = True
        text = re.sub(r"^not\s+", "", text, flags=re.IGNORECASE)
    for operator in _OPERATORS:
        pieces = (
            _split_outside_quotes(text, re.escape(operator))
            if operator[0].isalpha()
            else _split_symbol(text, operator)
        )
        if len(pieces) == 2:
            outcome = _compare(
                _operand(pieces[0], context), operator, _operand(pieces[1], context)
            )
            return not outcome if negate else outcome
        if len(pieces) > 2:
            raise ExpressionError(f"{operator!r} used more than once in {text!r}")
    outcome = bool(_operand(text, context))
    return not outcome if negate else outcome


def _split_symbol(text: str, operator: str) -> list[str]:
    parts: list[str] = []
    start = 0
    quote = ""
    i = 0
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == quote:
                quote = ""
        elif ch in "'\"":
            quote = ch
        elif text.startswith(operator, i):
            # "<" must not match the first half of "<=", and so on.
            nxt = text[i + len(operator) : i + len(operator) + 1]
            prev = text[i - 1 : i] if i else ""
            if operator in {"<", ">"} and nxt == "=":
                i += 1
                continue
            if operator in {"==", "!=", "<=", ">="} or prev not in "<>!=":
                parts.append(text[start:i])
                start = i = i + len(operator)
                continue
        i += 1
    parts.append(text[start:])
    return parts


def evaluate_condition(expression: str, context: Mapping[str, Any]) -> bool:
    """Whether ``expression`` holds. Raises :class:`ExpressionError` if unreadable."""
    expression = (expression or "").strip()
    if not expression:
        return True
    return any(
        all(_single(term, context) for term in _split_outside_quotes(group, "and"))
        for group in _split_outside_quotes(expression, "or")
    )
