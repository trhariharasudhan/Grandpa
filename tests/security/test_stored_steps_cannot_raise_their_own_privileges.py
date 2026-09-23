"""A saved step supplies values. It does not choose what it may do.

``db_query`` takes ``read_only``, which defaults to ``True`` and confines the
statement to SELECT-shaped SQL. Pass ``read_only=False`` and DROP, DELETE,
UPDATE and TRUNCATE are available, against any SQLite file or PostgreSQL URL
the same call names -- and ``db_query`` is not confirmation-gated, so nothing
asks.

A manifest step's ``arguments_template`` is stored content. It runs when the
skill is next invoked, with nobody reading it. So the answer to "may a saved
skill or manifest ever set ``read_only=False``" is no: not because a write is
always wrong, but because the thing deciding is a file, and a file cannot be
asked whether it meant it. An interactive caller passing ``read_only=False``
is untouched -- this only governs the path where the argument came out of
storage.

It is the same rule the saved-skill fix established for ``_pc_action``, applied
to the other half of the system: there, stored params could not name the
action; here, they cannot name the privilege.
"""

from __future__ import annotations

from grandpa.skills.executor import (
    PRIVILEGE_ARGUMENTS,
    _without_privilege_arguments,
)

DESTRUCTIVE = {
    "query": "DROP TABLE users",
    "db_path": "notes.db",
    "read_only": False,
}


def test_a_stored_step_cannot_turn_read_only_off() -> None:
    cleaned = _without_privilege_arguments("db_query", DESTRUCTIVE)

    assert cleaned["read_only"] is True
    # The rest of the call is left alone: this forces a privilege, it does not
    # rewrite the request. db_query then refuses the statement itself.
    assert cleaned["query"] == "DROP TABLE users"
    assert cleaned["db_path"] == "notes.db"


def test_the_forced_value_is_what_db_query_then_refuses() -> None:
    """End to end: the forcing is only useful if the tool acts on it."""
    from grandpa.tools.db_query import DatabaseQueryTool

    cleaned = _without_privilege_arguments("db_query", DESTRUCTIVE)
    result = DatabaseQueryTool().execute(**cleaned)

    assert result.success is False
    assert "read-only" in result.content


def test_an_interactive_caller_is_not_governed_by_this() -> None:
    """The rule is about stored content, not about the argument existing."""
    assert PRIVILEGE_ARGUMENTS["db_query"] == {"read_only": True}
    # Nothing here touches DatabaseQueryTool's own signature: a caller that is
    # present can still pass read_only=False, and db_query will honour it.
    from grandpa.tools.db_query import DatabaseQueryTool

    spec = DatabaseQueryTool().spec
    assert "read_only" in spec.parameters["properties"]


def test_tools_with_no_privilege_arguments_pass_through_untouched() -> None:
    arguments = {"thought": "something", "read_only": False}

    assert _without_privilege_arguments("think", arguments) == arguments


def test_a_step_that_omits_the_argument_still_gets_the_safe_value() -> None:
    """Forcing, not defaulting: absence must not be a way around it."""
    cleaned = _without_privilege_arguments("db_query", {"query": "DELETE FROM t"})

    assert cleaned["read_only"] is True


def test_the_executor_applies_it_to_every_step() -> None:
    """Pins the wiring, not just the helper.

    Without this, deleting the call in SkillExecutor.run would leave every
    test above passing while the rule reached nothing.
    """
    import inspect

    from grandpa.skills.executor import SkillExecutor

    source = inspect.getsource(SkillExecutor.run)

    assert "_without_privilege_arguments(step.tool_name, rendered)" in source
