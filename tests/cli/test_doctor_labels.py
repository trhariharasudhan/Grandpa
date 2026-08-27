"""Tests for ``Grandpa doctor`` optional dependency labels."""

from __future__ import annotations

import json
import traceback

from click.testing import CliRunner, Result

from grandpa.cli import cli


def _describe(result: Result) -> str:
    """Render everything known about a CliRunner result.

    All three tests below failed on GitHub's windows-latest runner with
    ``JSONDecodeError: Expecting value: line 1 column 1 (char 0)``, meaning
    ``result.output`` was empty. They pass locally both in isolation and in a
    full-suite run, and two hypotheses have been tested and disproved: an
    unreachable Ollama still yields clean JSON, and forcing
    ``OllamaBackendAdapter.list_models`` to raise ``TimeoutError`` also yields
    clean JSON (exit 0 both times).

    The cause is therefore not established, and this helper exists so the next
    CI run reports it rather than only saying the output would not parse. It
    surfaces the exit code, any exception Click captured with its traceback,
    and the raw output with its repr so whitespace or a stray banner is visible.
    """
    parts = [
        f"exit_code={result.exit_code!r}",
        f"exception={result.exception!r}",
        f"output_len={len(result.output)}",
        f"output_repr={result.output[:2000]!r}",
    ]
    if result.exception is not None and result.exc_info is not None:
        parts.append(
            "traceback=\n" + "".join(traceback.format_exception(*result.exc_info))
        )
    return "\n".join(parts)


def _doctor_json() -> list[dict]:
    """Invoke ``doctor --json`` and return the parsed payload.

    The JSON contract is asserted here rather than weakened: the command must
    exit 0, emit non-empty output, parse as JSON, and yield a list of check
    objects carrying at least ``name`` and ``status``. Each failure mode gets
    its own message so a CI failure identifies which step broke instead of
    surfacing as an opaque decode error at char 0.
    """
    result = CliRunner().invoke(cli, ["doctor", "--json"])

    assert result.exit_code == 0, f"doctor --json exited non-zero.\n{_describe(result)}"
    assert result.output.strip(), (
        f"doctor --json produced no output.\n{_describe(result)}"
    )

    try:
        data = json.loads(result.output)
    except json.JSONDecodeError as exc:
        raise AssertionError(
            f"doctor --json emitted output that is not valid JSON: {exc}\n"
            f"{_describe(result)}"
        ) from exc

    assert isinstance(data, list), (
        f"doctor --json must emit a list of checks, got {type(data).__name__}.\n"
        f"{_describe(result)}"
    )
    assert data, f"doctor --json emitted an empty list.\n{_describe(result)}"
    for entry in data:
        assert "name" in entry and "status" in entry, (
            f"check entry is missing name/status: {entry!r}"
        )
    return data


class TestDoctorOptionalLabels:
    def test_labels_show_description(self) -> None:
        """Doctor output uses unified readiness labels, not raw package names."""
        data = _doctor_json()
        names = [c["name"] for c in data]
        assert "REST API server installed" in names
        assert "Desktop automation backend" in names
        assert "Docker" not in names
        assert "Optional: torch (for learning)" not in names
        assert "Optional: pynvml (GPU monitoring)" not in names

    def test_optional_items_are_non_blocking(self) -> None:
        """Optional environment gaps should be informational, not failures."""
        data = _doctor_json()
        optional_checks = [
            c for c in data if c["status"] in {"info", "skipped", "not_configured"}
        ]
        assert optional_checks
        assert all(c["status"] not in {"fail", "failure"} for c in optional_checks)

    def test_engine_labels_use_descriptive_names(self) -> None:
        """Engine readiness checks should be grouped by engine name."""
        data = _doctor_json()
        names = [c["name"] for c in data]
        assert "Default model" in names
