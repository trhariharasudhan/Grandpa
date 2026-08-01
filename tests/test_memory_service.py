"""Integration and CLI tests for MemoryService in Grandpa Memory System V1."""

from __future__ import annotations

import tempfile
from pathlib import Path

import click.testing
import pytest

from grandpa.cli.memory_cmd import memory
from grandpa.memory.models import redact_sensitive
from grandpa.memory.service import MemoryService


@pytest.fixture(autouse=True)
def setup_temp_memory_service():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = Path(tmpdir) / "test_service_memory.db"
        svc = MemoryService.get_instance(db_path=str(db_path))
        yield svc
        MemoryService.reset_instance()


def test_memory_service_remember_recall_search(setup_temp_memory_service: MemoryService) -> None:
    svc = setup_temp_memory_service
    item = svc.remember("Browser Intelligence V1 completed", category="knowledge", key="bi_v1_status")
    assert item.key == "bi_v1_status"
    assert item.content == "Browser Intelligence V1 completed"

    recalled = svc.recall("bi_v1_status")
    assert recalled is not None
    assert recalled.content == "Browser Intelligence V1 completed"

    results = svc.search("Browser Intelligence")
    assert len(results) >= 1
    assert results[0].key == "bi_v1_status"


def test_short_term_memory_session_isolation(setup_temp_memory_service: MemoryService) -> None:
    svc = setup_temp_memory_service
    s_item = svc.remember("Transient user request in session", category="session", key="s_req_1")
    assert s_item.category == "session"

    # Short term memory should exist in session buffer
    session_items = svc.short_term.get_session_memories()
    assert len(session_items) == 1
    assert session_items[0].key == "s_req_1"

    # Persistent DB should not contain unpromoted session item
    assert svc.store.get_by_key("s_req_1") is None

    # Promote to long term
    promoted = svc.short_term.promote("s_req_1", svc.store)
    assert promoted is not None
    assert svc.store.get_by_key("s_req_1") is not None


def test_preferences_memory(setup_temp_memory_service: MemoryService) -> None:
    svc = setup_temp_memory_service
    assert svc.preferences.get_preference("preferred_shell") == "pwsh"

    svc.preferences.set_preference("preferred_shell", "bash")
    assert svc.preferences.get_preference("preferred_shell") == "bash"

    all_prefs = svc.preferences.list_all_preferences()
    assert all_prefs["preferred_shell"] == "bash"
    assert "default_browser" in all_prefs


def test_project_memory(setup_temp_memory_service: MemoryService) -> None:
    svc = setup_temp_memory_service
    svc.projects.update_project_info(
        project_name="Grandpa",
        content="Local AI assistant for Windows automation",
        latest_feature="Memory System V1",
        latest_commit="7967add9",
        next_task="Multi-modal vision engine",
    )

    summary = svc.projects.get_project_summary("Grandpa")
    assert summary is not None
    assert "Windows automation" in summary.content
    assert summary.metadata["latest_feature"] == "Memory System V1"

    proj_list = svc.projects.list_projects()
    assert len(proj_list) == 1
    assert proj_list[0]["project_name"] == "Grandpa"


def test_retrieval_context_formatting(setup_temp_memory_service: MemoryService) -> None:
    svc = setup_temp_memory_service
    svc.remember("Python 3.11 is required for Grandpa", category="knowledge", key="py_ver")

    context = svc.retrieval.get_context_summary(query="Python")
    assert "[MEMORY CONTEXT]" in context
    assert "py_ver" in context
    assert "Python 3.11 is required" in context


def test_sensitive_redaction_helper() -> None:
    text = "The password is secret_pass_123"
    redacted = redact_sensitive(text)
    assert "secret_pass_123" not in redacted
    assert "[REDACTED CONTENT" in redacted


def test_clear_requires_confirmation(setup_temp_memory_service: MemoryService) -> None:
    svc = setup_temp_memory_service
    svc.remember("Test item", key="test_item")
    with pytest.raises(PermissionError, match="Confirmation"):
        svc.clear(confirm=False)

    cleared = svc.clear(confirm=True)
    assert cleared >= 1


def test_cli_memory_commands(setup_temp_memory_service: MemoryService) -> None:
    runner = click.testing.CliRunner()

    # 1. remember
    res = runner.invoke(memory, ["remember", "Browser Intelligence V1 completed", "-k", "bi_v1"])
    assert res.exit_code == 0
    assert "Memory stored successfully!" in res.output

    # 2. list
    res = runner.invoke(memory, ["list"])
    assert res.exit_code == 0
    assert "bi_v1" in res.output

    # 3. search
    res = runner.invoke(memory, ["search", "Browser"])
    assert res.exit_code == 0
    assert "bi_v1" in res.output

    # 4. show
    res = runner.invoke(memory, ["show", "bi_v1"])
    assert res.exit_code == 0
    assert "Browser Intelligence V1 completed" in res.output

    # 5. update
    res = runner.invoke(memory, ["update", "bi_v1", "Browser Intelligence V1 stabilized"])
    assert res.exit_code == 0
    assert "updated successfully" in res.output

    # 6. preferences
    res = runner.invoke(memory, ["preferences"])
    assert res.exit_code == 0
    assert "preferred_shell" in res.output

    res = runner.invoke(memory, ["preferences", "--set", "response_language", "English"])
    assert res.exit_code == 0

    # 7. projects
    res = runner.invoke(memory, ["projects"])
    assert res.exit_code == 0

    # 8. stats (existing command compatibility)
    res = runner.invoke(memory, ["stats"])
    assert res.exit_code == 0
    assert "V1 Memories Count" in res.output

    # 9. delete with -y
    res = runner.invoke(memory, ["delete", "bi_v1", "-y"])
    assert res.exit_code == 0
    assert "deleted" in res.output

    # 10. clear with -y
    res = runner.invoke(memory, ["clear", "-y"])
    assert res.exit_code == 0
    assert "Cleared" in res.output
