"""Tests for ``Grandpa doctor`` optional dependency labels."""

from __future__ import annotations

import json
import traceback
from unittest.mock import patch

from click.testing import CliRunner, Result

from grandpa.cli import cli


def _describe(result: Result) -> str:
    """Render everything known about a CliRunner result."""
    parts = [
        f"exit_code={result.exit_code!r}",
        f"exception={result.exception!r}",
        f"stdout_len={len(result.stdout)}",
        f"stdout_repr={result.stdout[:2000]!r}",
        f"stderr_repr={result.stderr[:500]!r}",
    ]
    if result.exception is not None and result.exc_info is not None:
        parts.append(
            "traceback=\n" + "".join(traceback.format_exception(*result.exc_info))
        )
    return "\n".join(parts)


def _doctor_json() -> list[dict]:
    """Invoke ``doctor --json`` and return the payload parsed from stdout.

    Parses ``result.stdout``, not ``result.output``. Click's ``output`` is the
    merged terminal view -- "as the user would see it" -- so it interleaves
    stderr. ``--json`` only ever promises that *stdout* is machine-readable.

    That distinction is the whole bug these tests hit. On GitHub's
    windows-latest runner there is no Ollama, so listing models times out and
    ``ollama_adapter.py:512`` logs a warning. ``setup_logging`` attaches a
    ``logging.StreamHandler()`` with no stream argument, which writes to
    stderr. Reading ``result.output`` therefore produced

        WARNING grandpa.runtime.ollama_adapter: Failed to list models ...
        WARNING grandpa.runtime.ollama_adapter: Failed to list models ...
        [
          {"name": "Python version", ...

    and json.loads failed at char 0. stdout by itself was valid JSON the whole
    time, and `grandpa doctor --json | jq` is unaffected in a real shell
    because stderr does not travel through the pipe. The product was correct;
    the tests were reading the wrong stream. Locally the failure was invisible
    only because Ollama is running, so no warning was emitted.

    The contract is asserted rather than weakened: exit 0, non-empty stdout,
    valid JSON, a list, non-empty, and name/status on every entry.
    """
    result = CliRunner().invoke(cli, ["doctor", "--json"])

    assert result.exit_code == 0, f"doctor --json exited non-zero.\n{_describe(result)}"
    assert result.stdout.strip(), (
        f"doctor --json produced no stdout.\n{_describe(result)}"
    )

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(
            f"doctor --json emitted stdout that is not valid JSON: {exc}\n"
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


class TestDoctorJsonStdoutStaysMachineReadable:
    """``--json`` must keep stdout parseable when a backend is unreachable.

    This is the condition the CI runner is always in and a developer machine
    running Ollama never is, which is why it went unnoticed locally. Diagnostic
    logging belongs on stderr so `grandpa doctor --json | jq` keeps working
    precisely when something is wrong.
    """

    def test_stdout_is_valid_json_when_ollama_is_unreachable(self) -> None:
        import httpx

        from grandpa.cli.log_config import setup_logging

        # Attach the console handler the real CLI installs, otherwise the
        # warning has nowhere to go and the test cannot observe the split.
        setup_logging()

        def refuse(*_args, **_kwargs):
            raise httpx.ConnectError("simulated: no Ollama on this host")

        # Patch inside the adapter's try/except so the real warning at
        # ollama_adapter.py:512 fires. Replacing list_models outright removes
        # the very code that logs, which is how an earlier investigation
        # wrongly cleared this hypothesis.
        with patch("httpx.Client.get", refuse):
            result = CliRunner().invoke(cli, ["doctor", "--json"])

        assert result.exit_code == 0, _describe(result)

        # stdout alone must parse. This is the contract.
        payload = json.loads(result.stdout)
        assert isinstance(payload, list) and payload

        # The warning must be present but confined to stderr.
        assert "Failed to list models" in result.stderr
        assert "WARNING" not in result.stdout
