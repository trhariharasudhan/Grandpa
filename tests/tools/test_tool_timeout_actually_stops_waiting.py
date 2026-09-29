"""A tool timeout has to stop waiting, not just rename the result.

The executor ran each call as::

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(tool.execute, **params)
        result = future.result(timeout=timeout)

``future.result(timeout=...)`` raising does not stop the work, and the ``with``
block's exit calls ``shutdown(wait=True)`` -- so the executor waited for the tool
to finish *anyway*, and only then reported "timed out after 30s". The timeout
limited nothing; it relabelled the answer after paying full price for it.

That stayed invisible while every tool's budget was 30 seconds. Raising the
budget for model calls to the engine's own 900 made it visible: one run of the
suite spent eighteen and a half minutes inside a single unrelated teardown,
waiting for an abandoned call that the executor had already given up on.

Abandoning the call was tried, in this same change, and reverted. It works for a
tool that only reads and breaks one that does not: with abandonment in place, an
over-running ``repl`` execution carried on running ``exec()``, kept hold of the
memory database, and ``tests/security/test_agent_plan_cannot_be_named_into_a_write.py``
blocked on sqlite until pytest killed it at 300 seconds. The stack dump named
both halves at once -- the abandoned ``repl.py:315 exec(...)`` thread and the
test waiting in ``MemoryIntelligenceStore.sync()``.

So abandonment is only safe for a tool that holds no shared state, and knowing
which is which means each tool saying so -- the same shape as
``BaseTool.requires``. That is what ``BaseTool.abandon_on_timeout`` now is: a
declaration, defaulting to False, that a tool opts out of with a reason. Only
``llm`` has opted in so far; ``scan_chunks``, which spends its budget in the same
kind of model call, has not, because it holds a live sqlite connection across it.

These tests were ``xfail(strict=True)`` while that was unbuilt. They are now
plain tests, in both directions: a tool that may be abandoned returns at its
budget and leaves its worker running on a daemon thread, and a tool that may not
is waited out, says so in the result rather than claiming a timeout it did not
apply, and leaves nothing in flight to wedge the next caller.
"""

from __future__ import annotations

import threading
import time

import pytest

from grandpa.core.types import ToolCall, ToolResult
from grandpa.tools._stubs import BaseTool, ToolExecutor, ToolSpec

pytestmark = pytest.mark.core


class _Blocking(BaseTool):
    """Sleeps far longer than its budget, and says when it finally stopped."""

    tool_id = "blocking_tool"

    def __init__(
        self, seconds: float, budget: float, *, abandonable: bool = True
    ) -> None:
        self._seconds = seconds
        self._budget = budget
        self.abandon_on_timeout = abandonable
        self.finished = threading.Event()

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="blocking_tool",
            description="Blocks.",
            timeout_seconds=self._budget,
        )

    def execute(self, **params) -> ToolResult:
        time.sleep(self._seconds)
        self.finished.set()
        return ToolResult(tool_name="blocking_tool", content="late", success=True)


def test_the_executor_returns_at_the_budget_not_at_the_end() -> None:
    """The fix, stated as a stopwatch.

    Budget 0.5s against a call that takes 4s, on a tool that may be abandoned.
    It must return at the budget. Before this change it returned after the full
    4 seconds with a message claiming it had timed out at 0.5.
    """
    # Kept small on purpose. While the executor waited for every call, this
    # test's cost *was* the sleep, paid on every run of the suite: a first draft
    # slept for 6 and 30 seconds and taxed the suite 36 seconds to describe a
    # defect. The abandonable case no longer pays it, but the non-abandonable
    # tests below still do, so the sleeps stay short.
    tool = _Blocking(seconds=4.0, budget=0.5)
    executor = ToolExecutor([tool])

    started = time.time()
    result = executor.execute(ToolCall(id="1", name="blocking_tool", arguments="{}"))
    elapsed = time.time() - started

    assert result.success is False
    assert "timed out" in result.content
    assert elapsed < 2.0, (
        f"the executor waited {elapsed:.1f}s for a call it had given up on at "
        f"0.5s; a timeout that still waits is not a timeout"
    )
    # And the abandoned work is still running -- which is why its thread must be
    # a daemon rather than something a teardown will join.
    assert not tool.finished.is_set()


def test_the_abandoned_worker_cannot_hold_the_process_open() -> None:
    """A non-daemon worker would be joined at interpreter exit, so the wait moves."""
    # Two seconds, not thirty: see the note in the test above. This tool is
    # abandonable, so the sleep outlives the test rather than being waited for.
    tool = _Blocking(seconds=2.0, budget=0.3)
    executor = ToolExecutor([tool])

    executor.execute(ToolCall(id="1", name="blocking_tool", arguments="{}"))

    workers = [
        thread
        for thread in threading.enumerate()
        if "blocking_tool" in thread.name or "tool-" in thread.name
    ]
    assert workers, "expected to find the abandoned worker still running"
    assert all(thread.daemon for thread in workers), (
        "an abandoned tool call is on a non-daemon thread, so Python will wait "
        "for it at exit and the timeout is still not a timeout"
    )


def test_a_tool_that_cannot_be_abandoned_is_waited_for_and_says_so() -> None:
    """The other half of the deal, and the reason the default is False.

    A tool holding shared state cannot be dropped: the abandoned `repl`
    execution that kept running `exec()` held the memory database and wedged the
    next test. So it is waited for -- and the message says what actually
    happened rather than claiming a timeout that was not applied.
    """
    tool = _Blocking(seconds=2.0, budget=0.3, abandonable=False)
    executor = ToolExecutor([tool])

    started = time.time()
    result = executor.execute(ToolCall(id="1", name="blocking_tool", arguments="{}"))
    elapsed = time.time() - started

    assert result.success is False
    assert "could not be abandoned" in result.content
    assert "ran to completion" in result.content
    # Waited for the whole call, and the call finished before we returned --
    # which is the property that keeps the next caller unwedged.
    assert elapsed >= 1.8, elapsed
    assert tool.finished.is_set(), (
        "returned before the call finished, so its work is still in flight"
    )


def test_a_non_abandonable_tool_does_not_wedge_the_next_call() -> None:
    """What the repl/sqlite stall looked like, asserted as a sequence.

    The first call overruns and is waited out; the second must then run at its
    own pace rather than queueing behind live work from the first.
    """
    slow = _Blocking(seconds=1.5, budget=0.2, abandonable=False)
    executor = ToolExecutor([slow])
    executor.execute(ToolCall(id="1", name="blocking_tool", arguments="{}"))

    started = time.time()
    again = executor.execute(ToolCall(id="2", name="blocking_tool", arguments="{}"))
    elapsed = time.time() - started

    assert again.success is False
    # The second call costs its own duration, not its own plus the first's.
    assert elapsed < 3.0, elapsed


def test_a_fast_tool_still_returns_its_own_result() -> None:
    """The ordinary path must be untouched."""

    class _Fast(BaseTool):
        tool_id = "fast"

        @property
        def spec(self) -> ToolSpec:
            return ToolSpec(name="fast", description="Fast.", timeout_seconds=5.0)

        def execute(self, **params) -> ToolResult:
            return ToolResult(tool_name="fast", content="quick", success=True)

    executor = ToolExecutor([_Fast()])

    result = executor.execute(ToolCall(id="1", name="fast", arguments="{}"))

    assert result.success and result.content == "quick"


def test_an_ordinary_error_is_still_reported_as_one() -> None:
    class _Broken(BaseTool):
        tool_id = "broken"

        @property
        def spec(self) -> ToolSpec:
            return ToolSpec(name="broken", description="Raises.")

        def execute(self, **params) -> ToolResult:
            raise ValueError("no good")

    executor = ToolExecutor([_Broken()])

    result = executor.execute(ToolCall(id="1", name="broken", arguments="{}"))

    assert result.success is False
    assert "no good" in result.content


def test_a_base_exception_still_escapes() -> None:
    """The actuation guard raises BaseException on purpose.

    ``ActuationDenied`` derives from BaseException so that no ``except
    Exception`` turns a denial into a friendly sentence. Running the call on a
    thread must not swallow it either -- a guard nobody can see is no guard.
    """

    class _Denied(BaseException):
        pass

    class _Actuates(BaseTool):
        tool_id = "actuates"

        @property
        def spec(self) -> ToolSpec:
            return ToolSpec(name="actuates", description="Denied.")

        def execute(self, **params) -> ToolResult:
            raise _Denied("nothing actuates in a test")

    executor = ToolExecutor([_Actuates()])

    with pytest.raises(_Denied):
        executor.execute(ToolCall(id="1", name="actuates", arguments="{}"))
