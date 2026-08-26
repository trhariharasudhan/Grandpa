"""Tests for the shell_exec tool.

Python's ``subprocess`` is the single authoritative implementation. These tests
exercise it directly and pin the four guarantees a Rust-first branch used to
drop silently: timeout enforcement, environment sanitisation, output
truncation, and truthful return codes.

Commands are written portably. Anything beyond a bare ``echo`` runs through
``sys.executable -c`` so the same assertion holds on cmd.exe and on POSIX
shells; a handful of shell-syntax-specific cases are parameterised per platform.
"""

from __future__ import annotations

import importlib
import os
import sys

import pytest

from grandpa.tools.shell_exec import (
    _MAX_OUTPUT_BYTES,
    _MAX_TIMEOUT,
    ShellExecTool,
)

IS_WINDOWS = sys.platform == "win32"


def _py(code: str) -> str:
    """A shell command running *code* under the current interpreter.

    Quoted so it survives both cmd.exe and POSIX shells: the code itself uses
    no double quotes, so wrapping in double quotes is safe on both.
    """
    return f'"{sys.executable}" -c "{code}"'


def _echo_env(var: str) -> str:
    """A shell command echoing environment variable *var* using shell syntax."""
    return f"echo %{var}%" if IS_WINDOWS else f"echo ${var}"


class TestShellExecTool:
    def test_not_registered_via_tools_package_import(self):
        import grandpa.tools as tools_pkg
        from grandpa.core.registry import ToolRegistry

        sys.modules.pop("grandpa.tools.shell_exec", None)
        importlib.reload(tools_pkg)

        assert not ToolRegistry.contains("shell_exec")

    def test_spec(self):
        tool = ShellExecTool()
        assert tool.spec.name == "shell_exec"
        assert tool.spec.category == "system"
        assert tool.spec.requires_confirmation is True
        assert tool.spec.timeout_seconds == 60.0
        assert "code:execute" in tool.spec.required_capabilities
        assert "command" in tool.spec.parameters["properties"]
        assert "command" in tool.spec.parameters["required"]

    def test_tool_id(self):
        assert ShellExecTool().tool_id == "shell_exec"

    def test_to_openai_function(self):
        fn = ShellExecTool().to_openai_function()
        assert fn["type"] == "function"
        assert fn["function"]["name"] == "shell_exec"
        assert "command" in fn["function"]["parameters"]["properties"]

    def test_no_command(self):
        result = ShellExecTool().execute(command="")
        assert result.success is False
        assert "No command" in result.content

    def test_no_command_param(self):
        result = ShellExecTool().execute()
        assert result.success is False
        assert "No command" in result.content

    # -- output capture ---------------------------------------------------

    def test_simple_stdout(self):
        result = ShellExecTool().execute(command=_py("print('hello')"))
        assert result.success is True
        assert "hello" in result.content
        assert "=== STDOUT ===" in result.content

    def test_capture_stderr(self):
        result = ShellExecTool().execute(
            command=_py("import sys; sys.stderr.write('error_msg')"),
        )
        assert "error_msg" in result.content
        assert "=== STDERR ===" in result.content

    def test_no_output(self):
        result = ShellExecTool().execute(command=_py("pass"))
        assert result.success is True
        assert result.content == "(no output)"


class TestReturnCodeIsTruthful:
    """A non-zero exit must be reported as a failure with its real code.

    The removed Rust branch hardcoded ``returncode: 0, success: True`` for every
    invocation, so a command that failed was indistinguishable from one that
    succeeded.
    """

    def test_zero_returncode_is_success(self):
        result = ShellExecTool().execute(command=_py("pass"))
        assert result.success is True
        assert result.metadata["returncode"] == 0

    def test_nonzero_returncode_is_failure(self):
        result = ShellExecTool().execute(command=_py("raise SystemExit(42)"))
        assert result.success is False
        assert result.metadata["returncode"] == 42

    def test_nonzero_returncode_still_returns_output(self):
        result = ShellExecTool().execute(
            command=_py("import sys; print('partial'); sys.exit(3)"),
        )
        assert result.success is False
        assert result.metadata["returncode"] == 3
        assert "partial" in result.content


class TestTimeoutIsEnforced:
    """``timeout`` must actually bound execution.

    The removed Rust branch called ``Command::output()``, which blocks with no
    deadline, while still reporting ``timeout_used`` in metadata.
    """

    def test_timeout_terminates_long_command(self):
        result = ShellExecTool().execute(
            command=_py("import time; time.sleep(30)"),
            timeout=1,
        )
        assert result.success is False
        assert "timed out" in result.content.lower()
        assert result.metadata["returncode"] == -1
        assert result.metadata["timeout_used"] == 1

    def test_timeout_capped_at_max(self):
        result = ShellExecTool().execute(command=_py("pass"), timeout=999)
        assert result.metadata["timeout_used"] == _MAX_TIMEOUT

    def test_timeout_floored_at_one(self):
        result = ShellExecTool().execute(command=_py("pass"), timeout=0)
        assert result.metadata["timeout_used"] == 1

    def test_default_timeout_metadata(self):
        result = ShellExecTool().execute(command=_py("pass"))
        assert result.metadata["timeout_used"] == 30

    @pytest.mark.parametrize("bad", ["abc", None, [], {}])
    def test_invalid_timeout_falls_back_to_default(self, bad):
        result = ShellExecTool().execute(command=_py("pass"), timeout=bad)
        assert result.metadata["timeout_used"] == 30


class TestEnvironmentIsSanitised:
    """The child must receive the curated environment, not the parent's.

    The removed Rust branch inherited the full parent environment, so any secret
    in the agent's own environment was readable by an executed command.
    """

    def test_arbitrary_env_var_is_not_inherited(self, monkeypatch):
        monkeypatch.setenv("GRANDPA_TEST_SECRET_12345", "leaked")
        result = ShellExecTool().execute(
            command=_py(
                "import os; print(os.environ.get("
                "'GRANDPA_TEST_SECRET_12345', 'ABSENT'))"
            ),
        )
        assert result.success is True
        assert "leaked" not in result.content
        assert "ABSENT" in result.content

    def test_env_passthrough_allows_named_var(self, monkeypatch):
        monkeypatch.setenv("GRANDPA_TEST_PASSTHROUGH_67890", "allowed_value")
        result = ShellExecTool().execute(
            command=_py(
                "import os; print(os.environ.get("
                "'GRANDPA_TEST_PASSTHROUGH_67890', 'ABSENT'))"
            ),
            env_passthrough=["GRANDPA_TEST_PASSTHROUGH_67890"],
        )
        assert result.success is True
        assert "allowed_value" in result.content

    def test_env_passthrough_of_unset_var_is_not_an_error(self):
        result = ShellExecTool().execute(
            command=_py("pass"),
            env_passthrough=["GRANDPA_DEFINITELY_UNSET_VAR_XYZ"],
        )
        assert result.success is True

    def test_path_is_preserved(self):
        result = ShellExecTool().execute(
            command=_py("import os; print('PATH' in os.environ)"),
        )
        assert "True" in result.content

    @pytest.mark.skipif(IS_WINDOWS, reason="POSIX shell variable syntax")
    def test_shell_expansion_does_not_leak_secret_posix(self, monkeypatch):
        monkeypatch.setenv("GRANDPA_TEST_SHELL_SECRET", "leaked")
        result = ShellExecTool().execute(
            command=_echo_env("GRANDPA_TEST_SHELL_SECRET"),
        )
        assert "leaked" not in result.content


class TestOutputTruncation:
    """Output beyond the cap must be truncated.

    The removed Rust branch returned whatever the command produced, so a command
    emitting hundreds of megabytes flowed straight into a model prompt.
    """

    def test_large_stdout_is_truncated(self):
        result = ShellExecTool().execute(
            command=_py(f"print('A' * {_MAX_OUTPUT_BYTES * 2})"),
            timeout=60,
        )
        assert "stdout truncated" in result.content
        assert len(result.content) < _MAX_OUTPUT_BYTES * 2

    def test_large_stderr_is_truncated(self):
        result = ShellExecTool().execute(
            command=_py(f"import sys; sys.stderr.write('B' * {_MAX_OUTPUT_BYTES * 2})"),
            timeout=60,
        )
        assert "stderr truncated" in result.content


class TestWorkingDir:
    def test_working_dir_is_used(self, tmp_path):
        result = ShellExecTool().execute(
            command=_py("import os; print(os.getcwd())"),
            working_dir=str(tmp_path),
        )
        assert result.success is True
        assert result.metadata["working_dir"] == str(tmp_path)
        assert str(tmp_path.resolve()).lower() in result.content.lower()

    def test_working_dir_not_exists(self):
        result = ShellExecTool().execute(
            command="echo hi",
            working_dir=os.path.join(os.sep, "nonexistent", "path"),
        )
        assert result.success is False
        assert "does not exist" in result.content

    def test_working_dir_not_directory(self, tmp_path):
        f = tmp_path / "file.txt"
        f.write_text("data", encoding="utf-8")
        result = ShellExecTool().execute(command="echo hi", working_dir=str(f))
        assert result.success is False
        assert "not a directory" in result.content


class TestNoRustDelegation:
    """shell_exec must not consult the Rust backend at all.

    Regression guard for the removed Rust-first branch. Even a working
    ``grandpa_rust`` must not change how a shell command is executed, because
    the two implementations did not share timeout, environment, truncation, or
    return-code semantics.
    """

    def test_rust_module_is_never_requested(self, monkeypatch):
        calls: list[str] = []

        def _fail() -> None:
            calls.append("get_rust_module")
            raise AssertionError(
                "shell_exec must not delegate to the Rust backend",
            )

        monkeypatch.setattr(
            "grandpa._rust_bridge.get_rust_module",
            _fail,
        )
        result = ShellExecTool().execute(command=_py("print('ok')"))

        assert calls == []
        assert result.success is True
        assert "ok" in result.content

    def test_source_contains_no_rust_reference(self):
        import inspect

        import grandpa.tools.shell_exec as mod

        source = inspect.getsource(mod.ShellExecTool.execute)
        assert "get_rust_module" not in source
        assert "_rust" not in source


class TestRustBridgeContract:
    """``_rust_bridge`` must describe the backend it actually has."""

    def test_rust_available_reflects_reality(self):
        import importlib.util

        from grandpa import _rust_bridge

        expected = importlib.util.find_spec("grandpa_rust") is not None
        assert _rust_bridge.RUST_AVAILABLE is expected
        assert _rust_bridge.rust_available() is expected

    def test_docstring_does_not_claim_rust_is_mandatory(self):
        from grandpa import _rust_bridge

        doc = (_rust_bridge.__doc__ or "").lower()
        assert "optional" in doc
        assert "mandatory" not in doc.split("previously documented")[0]
