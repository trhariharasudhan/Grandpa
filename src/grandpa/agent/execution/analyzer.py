"""Diagnostic failure parser and root cause classifier for Agent Execution Engine V2."""

from __future__ import annotations

import re
import uuid

from grandpa.agent.execution.models import (
    DiagnosticEvidence,
    DiagnosticResult,
    FailureAnalysis,
)


def analyze_failure(result: DiagnosticResult) -> tuple[FailureAnalysis, list[DiagnosticEvidence]]:
    """Parse output from diagnostic command (ruff, pytest, compileall) to extract file/line details, classify, and generate structured evidence."""
    stdout = result.stdout or ""
    stderr = result.stderr or ""
    full_output = stdout + "\n" + stderr

    evidences: list[DiagnosticEvidence] = []
    analysis_id = str(uuid.uuid4())[:8]

    # Defaults
    failure_type = "unrelated_failure"
    failing_file = None
    failing_line = None
    message = "No clear failure details detected."
    root_cause = "Unknown issue."

    # 1. Environment / Timeout failures
    if result.timeout_triggered:
        evidence = DiagnosticEvidence(
            evidence_id=f"ev_{str(uuid.uuid4())[:6]}",
            command=result.command,
            argv=result.command,
            working_directory=".",
            exit_code=result.exit_code,
            stdout_excerpt=stdout[:500],
            stderr_excerpt=stderr[:500],
            parser="timeout_parser",
            failure_type="timeout",
            confidence=1.0
        )
        evidences.append(evidence)
        return FailureAnalysis(
            analysis_id=analysis_id,
            failure_type="timeout",
            message="The execution exceeded the configured duration boundary.",
            root_cause="Process hung or operation timed out.",
            is_confirmed=True,
            evidence_ids=[evidence.evidence_id]
        ), evidences

    if "command not found" in full_output.lower() or "executable not found" in full_output.lower() or "not recognized as an internal or external command" in full_output.lower():
        evidence = DiagnosticEvidence(
            evidence_id=f"ev_{str(uuid.uuid4())[:6]}",
            command=result.command,
            argv=result.command,
            working_directory=".",
            exit_code=result.exit_code,
            stdout_excerpt=stdout[:500],
            stderr_excerpt=stderr[:500],
            parser="env_parser",
            failure_type="environment_failure",
            confidence=1.0
        )
        evidences.append(evidence)
        return FailureAnalysis(
            analysis_id=analysis_id,
            failure_type="environment_failure",
            message="Required executable or command not found in environment.",
            root_cause="Dependency missing or PATH environment configuration error.",
            is_confirmed=True,
            evidence_ids=[evidence.evidence_id]
        ), evidences

    if "connection refused" in full_output.lower() or "http connection" in full_output.lower() or "server connection failed" in full_output.lower():
        evidence = DiagnosticEvidence(
            evidence_id=f"ev_{str(uuid.uuid4())[:6]}",
            command=result.command,
            argv=result.command,
            working_directory=".",
            exit_code=result.exit_code,
            stdout_excerpt=stdout[:500],
            stderr_excerpt=stderr[:500],
            parser="env_parser",
            failure_type="environment_failure",
            confidence=1.0
        )
        evidences.append(evidence)
        return FailureAnalysis(
            analysis_id=analysis_id,
            failure_type="environment_failure",
            message="Server connection refused.",
            root_cause="External service or background daemon is not running.",
            is_confirmed=True,
            evidence_ids=[evidence.evidence_id]
        ), evidences

    # 2. Parse Compileall / SyntaxError
    # Format: *** Error compiling 'src/grandpa/agent/runtime.py'...
    # Format:   File "src/grandpa/agent/runtime.py", line 123
    # Format:     some syntax error
    # Format: SyntaxError: invalid syntax
    syntax_file_match = re.search(r"File\s+\"([^\"]+)\",\s+line\s+(\d+)", full_output)
    syntax_err_match = re.search(r"(SyntaxError|IndentationError|TabError):\s*(.*)", full_output)
    compile_match = re.search(r"\*\*\*\s+Error compiling\s+'([^']+)'\s*\.\.\.\n(?:.*\n)?([A-Za-z]+Error):\s*(.*)", full_output)

    if compile_match or (syntax_file_match and syntax_err_match):
        if compile_match:
            failing_file = compile_match.group(1)
            failing_line = 1
            err_name = compile_match.group(2)
            message = compile_match.group(3)
        else:
            failing_file = syntax_file_match.group(1)
            failing_line = int(syntax_file_match.group(2))
            err_name = syntax_err_match.group(1)
            message = syntax_err_match.group(2)

        failure_type = "syntax_error"
        if "NameError" in err_name or "ImportError" in err_name:
            failure_type = "import_error"

        evidence = DiagnosticEvidence(
            evidence_id=f"ev_{str(uuid.uuid4())[:6]}",
            command=result.command,
            argv=result.command,
            working_directory=".",
            exit_code=result.exit_code,
            stdout_excerpt=full_output[:1000],
            stderr_excerpt="",
            parser="compileall_parser",
            failure_type=failure_type,
            file_path=failing_file,
            line_number=failing_line,
            confidence=1.0
        )
        evidences.append(evidence)
        return FailureAnalysis(
            analysis_id=analysis_id,
            failure_type=failure_type,
            failing_file=failing_file,
            failing_line=failing_line,
            message=f"{err_name}: {message}",
            root_cause=f"Syntax compilation/parsing failed in '{failing_file}'. Details: {message}",
            is_confirmed=True,
            evidence_ids=[evidence.evidence_id]
        ), evidences

    # 3. Parse Ruff errors
    # Format: src/grandpa/agent/runtime.py:29:41: F821 Undefined name `Any`
    # Format: src/grandpa/agent/runtime.py:29: F821 Undefined name `Any`
    ruff_matches = re.finditer(r"([^\s\n\r:]+):(\d+):(?:\d+:)?\s*([A-Z]\d+\s+.*)", full_output)
    for m in ruff_matches:
        f_file = m.group(1)
        f_line = int(m.group(2))
        msg = m.group(3)

        f_type = "syntax_error"
        if "undefined name" in msg.lower() or "imported but unused" in msg.lower():
            f_type = "import_error"

        evidence = DiagnosticEvidence(
            evidence_id=f"ev_{str(uuid.uuid4())[:6]}",
            command=result.command,
            argv=result.command,
            working_directory=".",
            exit_code=result.exit_code,
            stdout_excerpt=m.group(0),
            stderr_excerpt="",
            parser="ruff_parser",
            failure_type=f_type,
            file_path=f_file,
            line_number=f_line,
            confidence=1.0
        )
        evidences.append(evidence)

    if evidences and "ruff" in "".join(result.command).lower():
        # Ruff failures found
        first_ev = evidences[0]
        return FailureAnalysis(
            analysis_id=analysis_id,
            failure_type=first_ev.failure_type,
            failing_file=first_ev.file_path,
            failing_line=first_ev.line_number,
            message=first_ev.stdout_excerpt,
            root_cause=f"Ruff code quality or styling rule failure in '{first_ev.file_path}': {first_ev.stdout_excerpt}",
            is_confirmed=True,
            evidence_ids=[ev.evidence_id for ev in evidences]
        ), evidences

    # 4. Parse Pytest Traceback
    # Parse Pytest failure blocks to extract FAILED test node and tracebacks
    pytest_failed_node_match = re.search(r"FAILED\s+([^\s:]+)::([^\s\-]+)(?:\s+-\s+(.*))?", full_output)
    pytest_traceback_match = re.search(r"([^:\s\n]+):(\d+):\s+([A-Za-z]+Error(?:\s+.*)?)", full_output)
    pytest_exc_block = re.search(r"\nE\s+([A-Za-z]+Error):\s*(.*)", full_output)

    if pytest_failed_node_match or pytest_traceback_match or pytest_exc_block:
        failing_file = None
        failing_line = None
        msg = "Pytest execution failed."
        f_type = "assertion_failure"

        if pytest_failed_node_match:
            failing_file = pytest_failed_node_match.group(1)
            msg = pytest_failed_node_match.group(3) or "Test node execution failed."

        if pytest_traceback_match:
            # More specific traceback location
            failing_file = pytest_traceback_match.group(1)
            failing_line = int(pytest_traceback_match.group(2))
            msg = pytest_traceback_match.group(3)

        # Fallback file extraction from output if failing_file is not set yet
        if not failing_file:
            py_file_match = re.search(r"([^\s\n\r\"]+\.py)", full_output)
            if py_file_match:
                failing_file = py_file_match.group(1)

        if pytest_exc_block:
            exc_name = pytest_exc_block.group(1)
            exc_msg = pytest_exc_block.group(2)
            msg = f"{exc_name}: {exc_msg}"
            if "AssertionError" in exc_name:
                f_type = "assertion_failure"
            elif "ImportError" in exc_name or "ModuleNotFoundError" in exc_name:
                f_type = "import_error"
            elif "ConnectionRefusedError" in exc_name:
                f_type = "environment_failure"
            else:
                f_type = "product_bug"
        elif "AssertionError" in msg:
            f_type = "assertion_failure"

        evidence = DiagnosticEvidence(
            evidence_id=f"ev_{str(uuid.uuid4())[:6]}",
            command=result.command,
            argv=result.command,
            working_directory=".",
            exit_code=result.exit_code,
            stdout_excerpt=full_output[max(0, full_output.find("FAILURES") if "FAILURES" in full_output else 0):][:1000],
            stderr_excerpt="",
            parser="pytest_parser",
            failure_type=f_type,
            file_path=failing_file,
            line_number=failing_line,
            confidence=1.0
        )
        evidences.append(evidence)

        return FailureAnalysis(
            analysis_id=analysis_id,
            failure_type=f_type,
            failing_file=failing_file,
            failing_line=failing_line,
            message=msg,
            root_cause=f"Pytest assertion or runtime failure: {msg}",
            is_confirmed=True,
            evidence_ids=[evidence.evidence_id]
        ), evidences

    return FailureAnalysis(
        analysis_id=analysis_id,
        failure_type=failure_type,
        message=message,
        root_cause=root_cause,
        is_confirmed=False,
        evidence_ids=[]
    ), evidences
