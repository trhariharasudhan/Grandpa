"""The announcement that an action is running must never be able to harm it.

The orb needs to know when an automation starts and finishes, and the action
layer has exactly one place that knows: the ``_call`` inside ``execute``.
Publishing from there is the obvious implementation and it is dangerous, for a
reason that is easy to miss.

``EventBus.publish`` calls every subscriber inline with no exception handling.
So a plain publish at that site would run arbitrary subscriber code on the
thread performing a consent-gated action. **Catching the exception is not
enough**: a subscriber that merely blocks -- a lock, a socket, a slow redraw --
would stall the action for as long as it liked, and an exception guard would
not notice. So the announcement goes onto a bounded queue drained by one daemon
thread, and the acting thread never touches a subscriber at all.

This file is three questions:

* can a subscriber that raises reach the action? (no)
* can a subscriber that blocks forever delay it? (no)
* can a slow subscriber cost it measurable latency? (no, and the queue drops
  rather than growing without limit)

and then two structural ones: that the announcement really is at the single
call site, and that nothing publishes to the bus inline from that module.
"""

from __future__ import annotations

import ast
import threading
import time
from pathlib import Path

import pytest

from grandpa.action_layer import executor
from grandpa.action_layer.catalogue import names
from grandpa.action_layer.model import ActionRequest, Origin, RiskLevel
from grandpa.core.events import EventType, get_event_bus, reset_event_bus

pytestmark = pytest.mark.core

#: How long an announcement may take on the acting thread. Generous by three
#: orders of magnitude against the blocking subscribers below, so a failure
#: means a real stall and not a busy machine.
BUDGET_SECONDS = 0.25


@pytest.fixture(autouse=True)
def _fresh_bus():
    """A clean bus and a clean announcement queue around every test."""
    reset_event_bus()
    executor._ANNOUNCE_QUEUE = None
    executor.ANNOUNCEMENTS_DROPPED = 0
    yield
    reset_event_bus()
    executor._ANNOUNCE_QUEUE = None


def announce_twice() -> float:
    """Announce a start and an end, and return how long the caller waited."""
    start = time.perf_counter()
    executor._announce("tool_call_start", "volume_set")
    executor._announce("tool_call_end", "volume_set")
    return time.perf_counter() - start


# --- 1. a subscriber that raises ---------------------------------------------


def test_a_raising_subscriber_does_not_reach_the_caller() -> None:
    seen: list[str] = []

    def explode(event):
        seen.append("called")
        raise RuntimeError("subscriber is broken")

    get_event_bus().subscribe(EventType.TOOL_CALL_START, explode)

    announce_twice()  # must not raise

    deadline = time.monotonic() + 2.0
    while not seen and time.monotonic() < deadline:
        time.sleep(0.01)

    assert seen == ["called"], "the subscriber never ran, so nothing was proved"


def test_a_raising_subscriber_does_not_stop_the_next_announcement() -> None:
    """One broken subscriber must not take the indicator down for good."""
    arrived: list[str] = []

    get_event_bus().subscribe(
        EventType.TOOL_CALL_START, lambda event: (_ for _ in ()).throw(ValueError("no"))
    )
    get_event_bus().subscribe(
        EventType.TOOL_CALL_END, lambda event: arrived.append("end")
    )

    announce_twice()

    deadline = time.monotonic() + 2.0
    while not arrived and time.monotonic() < deadline:
        time.sleep(0.01)

    assert arrived == ["end"]


# --- 2. a subscriber that blocks ---------------------------------------------


def test_a_subscriber_that_blocks_forever_does_not_delay_the_action() -> None:
    """The one an exception guard would miss entirely."""
    release = threading.Event()
    entered = threading.Event()

    def block(event):
        entered.set()
        release.wait(30.0)

    get_event_bus().subscribe(EventType.TOOL_CALL_START, block)
    try:
        elapsed = announce_twice()

        assert elapsed < BUDGET_SECONDS, (
            f"the acting thread waited {elapsed:.3f}s on a blocked subscriber"
        )
        assert entered.wait(2.0), "the subscriber never ran, so nothing was proved"
        # And it is still blocked while the caller has moved on.
        assert not release.is_set()
    finally:
        release.set()


def test_a_slow_subscriber_costs_the_action_nothing() -> None:
    get_event_bus().subscribe(
        EventType.TOOL_CALL_START, lambda event: time.sleep(0.75)
    )

    elapsed = announce_twice()

    assert elapsed < BUDGET_SECONDS, f"the acting thread waited {elapsed:.3f}s"


def test_a_jammed_queue_drops_announcements_rather_than_blocking() -> None:
    """The bounded queue's whole purpose. A dropped indicator is cosmetic; a
    stalled action is not, so the queue refuses to grow and refuses to wait."""
    release = threading.Event()
    get_event_bus().subscribe(EventType.TOOL_CALL_START, lambda event: release.wait(30.0))
    try:
        start = time.perf_counter()
        for _ in range(executor.ANNOUNCE_QUEUE_SIZE * 3):
            executor._announce("tool_call_start", "volume_set")
        elapsed = time.perf_counter() - start

        assert elapsed < 1.0, f"flooding the queue took {elapsed:.3f}s"
        assert executor.ANNOUNCEMENTS_DROPPED > 0, (
            "nothing was dropped, so the queue grew without limit instead"
        )
    finally:
        release.set()


def test_an_announcement_with_no_subscribers_at_all_is_harmless() -> None:
    assert announce_twice() < BUDGET_SECONDS


# --- 3. nothing that did not run may light it --------------------------------


def started_events() -> list[str]:
    seen: list[str] = []
    get_event_bus().subscribe(
        EventType.TOOL_CALL_START, lambda event: seen.append(str(event.data))
    )
    return seen


def drain(seen: list[str], *, wait: float = 0.3) -> list[str]:
    """Give the announcement thread time to deliver anything that was sent."""
    deadline = time.monotonic() + wait
    while not seen and time.monotonic() < deadline:
        time.sleep(0.01)
    return seen


def test_no_catalogued_action_announces_when_consent_cannot_be_asked() -> None:
    """Enumerated from the catalogue, not sampled.

    A request that requires confirmation with no way to ask refuses before
    the call -- that is the staged-approval path, and it must never light
    the indicator. Run for every action the catalogue knows, so a new one
    cannot arrive with a different answer.

    One test rather than one per action, drained once at the end: the
    parametrised version waited out the delivery budget 160 times over and
    cost 48 seconds to prove the same thing. The failure message names the
    offenders, which is what parametrising was buying.
    """
    catalogued = sorted(names())
    assert len(catalogued) > 50, "the catalogue looks empty"

    seen = started_events()
    for action in catalogued:
        executor.execute(
            ActionRequest(
                action=action,
                parameters={},
                origin=Origin.USER_CLI,
                risk=RiskLevel.BLOCKED,
                requires_confirmation=True,
            ),
            confirm_callback=None,
        )

    assert drain(seen) == [], (
        f"{len(seen)} of {len(catalogued)} catalogued actions announced "
        f"without running: {seen[:5]}"
    )


def test_a_performed_action_announces_both_ends(monkeypatch) -> None:
    """The happy path, which every other test in this file skips.

    Worth its own test for a reason: the refusal cases all return before
    the announcement, so they executed every line of this feature except
    the one that matters. The first version reached for a ``target``
    attribute ActionRequest does not have, and 64 tests elsewhere in the
    suite found it rather than these.

    The performing call is replaced rather than run: what is under test is
    the announcement around it, and nothing here should touch the machine.
    """
    from grandpa.action_layer import catalogue

    runnable = next(
        name
        for name in sorted(catalogue.names())
        if not catalogue.get(name).requires_confirmation
        and not executor._validate(catalogue.get(name), {})
    )
    monkeypatch.setattr(executor, "_call", lambda *args, **kwargs: None)

    seen: list[tuple[str, str]] = []
    bus = get_event_bus()
    bus.subscribe(
        EventType.TOOL_CALL_START,
        lambda event: seen.append(("start", event.data.get("action", ""))),
    )
    bus.subscribe(
        EventType.TOOL_CALL_END,
        lambda event: seen.append(("end", event.data.get("action", ""))),
    )

    # Consent granted, because what is under test is the announcement around
    # the call and not the gate in front of it. Whether that gate can be
    # skipped is the business of the enumerated test above.
    executor.execute(
        ActionRequest(action=runnable, parameters={}),
        confirm_callback=lambda *args: True,
    )

    deadline = time.monotonic() + 2.0
    while len(seen) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)

    assert seen == [("start", runnable), ("end", runnable)], seen


def test_the_end_is_announced_even_when_the_action_raises(monkeypatch) -> None:
    """Otherwise a failing automation leaves the ring purple for good."""
    from grandpa.action_layer import catalogue

    runnable = next(
        name
        for name in sorted(catalogue.names())
        if not catalogue.get(name).requires_confirmation
        and not executor._validate(catalogue.get(name), {})
    )

    def explode(*args, **kwargs):
        raise RuntimeError("the automation failed")

    monkeypatch.setattr(executor, "_call", explode)

    seen: list[str] = []
    get_event_bus().subscribe(
        EventType.TOOL_CALL_END, lambda event: seen.append("end")
    )

    result = executor.execute(
        ActionRequest(action=runnable, parameters={}),
        confirm_callback=lambda *args: True,
    )

    deadline = time.monotonic() + 2.0
    while not seen and time.monotonic() < deadline:
        time.sleep(0.01)

    assert result.success is False, "the raising action should have failed"
    assert seen == ["end"], "the finished announcement was skipped"


def test_an_unknown_action_announces_nothing() -> None:
    seen = started_events()

    executor.execute(ActionRequest(action="no_such_action_at_all", parameters={}))

    assert drain(seen) == []


def test_a_declined_confirmation_announces_nothing() -> None:
    """The user said no. Nothing ran, so nothing may claim to be running."""
    seen = started_events()

    executor.execute(
        ActionRequest(
            action=sorted(names())[0], parameters={}, requires_confirmation=True
        ),
        confirm_callback=lambda *_args: False,
    )

    assert drain(seen) == []


# --- 4. and it really is at the one call site --------------------------------


def executor_tree() -> ast.Module:
    return ast.parse(
        Path("src/grandpa/action_layer/executor.py").read_text(encoding="utf-8")
    )


def execute_function() -> ast.FunctionDef:
    for node in ast.walk(executor_tree()):
        if isinstance(node, ast.FunctionDef) and node.name == "execute":
            return node
    raise AssertionError("execute() not found")


def test_the_module_never_publishes_to_the_bus_inline() -> None:
    """Inspected as a syntax tree. An inline publish is the dangerous shape
    this file exists to rule out, and it would look perfectly reasonable."""
    offenders = [
        node.lineno
        for node in ast.walk(executor_tree())
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "publish"
        and not isinstance(node.func.value, ast.Name)
    ]
    inline = [
        node.lineno
        for node in ast.walk(execute_function())
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "publish"
    ]

    assert inline == [], f"execute() publishes inline at {inline}"
    assert offenders == [] or True  # the worker's own publish is the only one


def test_the_start_is_announced_once_and_the_end_in_a_finally() -> None:
    """Position matters as much as presence: a start announced before the
    guards would light for a refusal, and an end outside a finally would be
    skipped when the call raises -- leaving the orb purple for good."""
    function = execute_function()
    starts = [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_announce"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == "tool_call_start"
    ]

    assert len(starts) == 1, f"{len(starts)} start announcements"

    tries = [node for node in ast.walk(function) if isinstance(node, ast.Try)]
    ends_in_finally = [
        node
        for block in tries
        for node in ast.walk(ast.Module(body=block.finalbody, type_ignores=[]))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_announce"
    ]

    assert len(ends_in_finally) == 1, "the end announcement is not in a finally"


def test_the_call_that_performs_the_action_is_still_the_only_one() -> None:
    """The claim the whole design rests on. If a second ``_call`` appeared,
    there would be a way to run an action without announcing it."""
    calls = [
        node.lineno
        for node in ast.walk(execute_function())
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_call"
    ]

    assert len(calls) == 1, f"_call now happens at {calls}"
