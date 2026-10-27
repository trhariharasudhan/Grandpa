"""Shared fixtures — clear all registries and the event bus between tests."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

import grandpa.core.config as _config
from grandpa.core.config import GpuInfo, HardwareInfo
from grandpa.core.events import EventBus, reset_event_bus
from grandpa.core.registry import (
    AgentRegistry,
    CompressionRegistry,
    ConnectorRegistry,
    EngineRegistry,
    MemoryRegistry,
    ModelRegistry,
    RouterPolicyRegistry,
    SkillRegistry,
    SpeechRegistry,
    ToolRegistry,
    TTSRegistry,
)

_TEST_HOME = Path(
    os.environ.get("GRANDPA_TEST_HOME", Path.cwd() / "runtime" / "test-home")
)
_TEST_HOME.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("GRANDPA_HOME", str(_TEST_HOME))
_config.DEFAULT_CONFIG_DIR = _TEST_HOME
_config.DEFAULT_CONFIG_PATH = _TEST_HOME / "config.toml"

_OPTIONAL_ENVIRONMENT_TESTS = {
    "tests/connectors/test_live_smoke.py": (
        "GRANDPA_RUN_LIVE_CONNECTOR_TESTS",
        "live connector smoke test; set GRANDPA_RUN_LIVE_CONNECTOR_TESTS=1 to run",
    ),
    "tests/skills/test_integration_live.py": (
        "GRANDPA_RUN_LIVE_SKILL_TESTS",
        "live skill integration tests require a running inference engine and installed user skills",
    ),
}
_RUST_EXTENSION_AVAILABLE = importlib.util.find_spec("grandpa_rust") is not None
_RELEASE_TEST_PATHS = {
    "tests/test_actions_decomposition.py",
    "tests/test_autonomous_workflows.py",
    "tests/test_browser_control.py",
    "tests/test_desktop_control_services.py",
    "tests/test_intent_router.py",
    "tests/test_local_actions.py",
    "tests/test_native_agent_planner.py",
    "tests/test_pc_control.py",
    "tests/test_pc_control_api.py",
    "tests/test_pc_control_kernel.py",
    "tests/test_plugin_runtime.py",
    "tests/test_release_gate.py",
    "tests/test_services_layer.py",
    "tests/test_skill_runtime.py",
    "tests/test_visual_targeting.py",
    "tests/test_workflow_skill_graph.py",
    "tests/server/test_routes.py",
}


#: Third-party backends that actuate or write the *first* time they are
#: touched, as a side effect of being loaded rather than of being used.
#: ``_warm_lazy_backends`` does that touching once, before any guard arms.
#:
#: ``pyautogui``: importing it imports ``mouseinfo``, which on POSIX runs
#: ``subprocess.Popen(['which', ...])`` at module scope to find a clipboard
#: helper.
#:
#: ``comtypes``/``pycaw``: see ``_WIN_TYPELIBS`` below.
_LAZY_BACKENDS: tuple[str, ...] = ("pyautogui", "comtypes", "pycaw")

#: COM type libraries the product asks comtypes to compile. ``GetModule``
#: generates a Python wrapper per library into ``site-packages/comtypes/gen``
#: and *writes it to disk*, so the first caller pays with a write the guard
#: refuses. Pre-generating them here means the test-time call imports a module
#: that already exists.
#:
#: Identified however ``GetModule`` will actually accept, which is not uniform:
#:
#: * ``UIAutomationCore.dll`` -> ``_944DE083_..._0_1_0.py``, asked for by
#:   ``windows_window_control._uia`` and ``browser_control``. This one accounted
#:   for 13 Windows failures. Resolves by bare filename.
#: * The Speech Object Library -> ``_C866CA3A_..._0_5_4.py``, reached through
#:   pyttsx3's SAPI driver by anything that probes TTS -- ``doctor`` does, which
#:   is why six doctor tests and the audio-denied test failed on it once the UIA
#:   one was fixed. It is given as ``(guid, major, minor)`` because
#:   ``GetModule("sapi.dll")`` raises *"Error loading type library/DLL"*: the
#:   library lives at ``System32\\Speech\\Common\\sapi.dll``, which is not on
#:   the loader path, and hardcoding that absolute path would bind this to one
#:   machine's layout. The registry triple is the same identity the generated
#:   filename encodes, and it resolved where the filename did not. Generated,
#:   not instantiated: a ``SpVoice`` would touch the audio stack, and what is
#:   wanted here is only the file on disk.
#:
#: Add to this list when a new generated module shows up in a write refusal.
_WIN_TYPELIBS: tuple[object, ...] = (
    "UIAutomationCore.dll",
    ("{C866CA3A-32F7-11D2-9602-00C04F8EE628}", 5, 4),
)


def _warm_lazy_backends() -> None:
    """Touch each lazy backend once; pin the ones that are unavailable."""
    import sys

    for name in _LAZY_BACKENDS:
        if sys.modules.get(name, False) is None:
            continue  # already pinned unavailable by an earlier call
        try:
            importlib.import_module(name)
        except (KeyboardInterrupt, SystemExit):
            # "Any failure means unavailable" does not extend to the user
            # asking the run to stop, which is the one BaseException here that
            # is not about the backend.
            raise
        except BaseException:
            # Anything else -- ImportError, a headless DISPLAY error, no audio
            # endpoint, whatever the backend raises on hardware it cannot
            # drive -- means the same thing to every caller: there is no
            # backend. Pin it so later imports fail fast and cheaply instead of
            # re-running module code. setdefault, not assignment: a module that
            # imported fine must not be pinned None by a later step's failure.
            sys.modules.setdefault(name, None)  # type: ignore[arg-type]

    if sys.platform != "win32" or sys.modules.get("comtypes") is None:
        return

    for typelib in _WIN_TYPELIBS:
        try:
            import comtypes.client

            comtypes.client.GetModule(typelib)
        except (KeyboardInterrupt, SystemExit):
            raise
        except BaseException:
            # One missing or unregisterable library must not stop the others:
            # a machine with no speech stack still needs the UIA wrapper. The
            # test that actually wanted it will fail on its own terms, which is
            # more informative than this loop guessing.
            continue


def pytest_configure(config: pytest.Config) -> None:
    """Warm the lazy desktop backends once, before any guard arms.

    Two guards are armed per test and both are right. ``_nothing_actuates``
    replaces ``subprocess.Popen``; ``confine_writes`` refuses a write outside
    the test's scratch space. ``ActuationDenied`` derives from
    ``BaseException`` on purpose, so the product's ``except Exception``
    handlers cannot turn a denial into a friendly sentence nobody reads.

    What that combination cannot tell apart is *the product* doing something
    and *a dependency* doing something while being loaded. Both CI jobs hit it,
    for the same reason, in two different guards:

    * Linux, 5 failures. ``screen_awareness._available_screenshot_backends``
      does ``import pyautogui`` inside ``try/except Exception`` -- exactly how
      a capability probe should be written -- and mouseinfo's module-scope
      ``Popen`` came back as an unswallowable denial. Screen diagnostics,
      screen description, OCR redaction and two pc_control API routes went
      down, none of which actuate anything.
    * Windows, 12 failures. ``comtypes.client.GetModule`` compiles
      UIAutomationCore's type library and writes the result into
      ``site-packages/comtypes/gen`` the first time anyone asks. On a
      developer's machine that happened months ago, so the directory is
      already there and tests never write it; on a fresh runner it is the
      first call that pays, and the write guard refused it -- 8 as ``os.mkdir``
      on the ``gen`` directory and 4 as ``open`` on the generated module.
      That is why these failed only in CI and only on a clean checkout.

    Warming fixes it at the cause and leaves both guards at full strength: the
    side effects happen before any test, and the test-time call then finds a
    cached module and a directory that exists. The alternative was seventeen
    ``real_actions`` and ``real_writes`` markers, which would hand real
    implementations and real write access to tests that need neither, to work
    around a dependency's first-use behaviour. That is how a marker written for
    one reason ends up granting another -- which this conftest's own
    ``_nothing_actuates`` docstring records happening to 395 tests.
    """
    _warm_lazy_backends()


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Classify optional/environment suites, and refuse a file-wide opt-out.

    The scope check comes first and raises: @pytest.mark.real_actions is
    function-scope only. 88 files once carried one between them, covering 1288
    tests, of which 893 did not need it -- and one of the ones that did need
    something wrote to a real home under a reason written for its neighbours. A
    warning would have been read once; this refuses the run.
    """
    from tests.actuation_guard import scope_error_message, scope_violations

    offenders = scope_violations(items)
    if offenders:
        raise pytest.UsageError(scope_error_message(offenders))

    for item in items:
        rel_path = item.path.as_posix()
        if rel_path.startswith(str(Path.cwd()).replace("\\", "/")):
            rel_path = Path(rel_path).relative_to(Path.cwd()).as_posix()
        optional_rule = _OPTIONAL_ENVIRONMENT_TESTS.get(rel_path)
        if optional_rule:
            env_var, reason = optional_rule
            item.add_marker(pytest.mark.integration)
            item.add_marker(pytest.mark.optional)
            item.add_marker(pytest.mark.environment)
            if os.environ.get(env_var) != "1":
                item.add_marker(pytest.mark.skip(reason=reason))
        if rel_path == "tests/core/test_rust_bridge.py" and (
            "TestGetRustModule" in item.nodeid or "TestRustBackedModules" in item.nodeid
        ):
            item.add_marker(pytest.mark.optional)
            item.add_marker(pytest.mark.environment)
            if not _RUST_EXTENSION_AVAILABLE:
                item.add_marker(
                    pytest.mark.skip(reason="grandpa_rust extension is not built")
                )
        if (
            rel_path == "tests/core/test_credentials.py"
            and item.name == "test_file_permissions"
        ):
            item.add_marker(pytest.mark.environment)
            if os.name == "nt":
                item.add_marker(
                    pytest.mark.skip(
                        reason="POSIX chmod mode assertions are not reliable on Windows"
                    )
                )
        if rel_path in _RELEASE_TEST_PATHS:
            item.add_marker(pytest.mark.release)
        marker_names = {marker.name for marker in item.iter_markers()}
        # Tests explicitly marked ``microphone`` drive real audio hardware and
        # block indefinitely on a machine with a sound card. Opt in with
        # GRANDPA_RUN_MICROPHONE_TESTS=1; otherwise treat them as environment
        # tests and skip, so a default ``pytest`` run always terminates.
        if "microphone" in marker_names:
            item.add_marker(pytest.mark.environment)
            if os.environ.get("GRANDPA_RUN_MICROPHONE_TESTS") != "1":
                item.add_marker(
                    pytest.mark.skip(
                        reason=(
                            "requires microphone/audio hardware; set "
                            "GRANDPA_RUN_MICROPHONE_TESTS=1 to run"
                        )
                    )
                )
            continue
        if not marker_names.intersection({"optional", "environment", "slow", "live"}):
            item.add_marker(pytest.mark.core)


@pytest.fixture(autouse=True)
def _clean_registries() -> None:
    """Ensure each test starts with empty registries and a fresh event bus."""
    ModelRegistry.clear()
    EngineRegistry.clear()
    MemoryRegistry.clear()
    AgentRegistry.clear()
    ToolRegistry.clear()
    RouterPolicyRegistry.clear()
    SpeechRegistry.clear()
    CompressionRegistry.clear()
    ConnectorRegistry.clear()
    TTSRegistry.clear()
    SkillRegistry.clear()
    reset_event_bus()


@pytest.fixture(autouse=True)
def _nothing_actuates(request, monkeypatch) -> None:
    """Replace every catalogued implementation, and the primitives beneath them.

    Default-deny, from the catalogue rather than from a list of the categories
    that have already gone wrong: six times in one session a test changed the
    machine it ran on, and each time the previous fix had been to add that one
    category to a recorder.

    The filesystem is confined too (tests/write_guard.py). The catalogue names
    actions, not tools, so nothing here replaced ``FileWriteTool`` -- and when
    a mutation run removed that tool's own path guard, a test asserting the
    refusal against real absolute paths wrote to a real ``~/.ssh`` and a real
    ``~/.grandpa``. Replacing the one tool would leave the gap; the writes are
    confined instead.

    There are two permissions here, and they are different sizes, so they are
    two markers and a test asks for exactly the one it needs:

        @pytest.mark.real_actions(reason="...")   # run the real implementation
        @pytest.mark.real_writes(reason="...")    # write outside the sandbox

    Each needs its own reason. They used to be one marker, which is how a test
    that legitimately needed a real implementation also got permission to write
    a mocked traceback into a real ``~/.grandpa/server.log``. Of the 395 tests
    that carried the combined marker, five needed the write bound off.
    """
    from tests.actuation_guard import MARKER, deny_everything, reason_for
    from tests.write_guard import WRITE_MARKER, confine_writes

    # own_markers, not get_closest_marker: both markers are function-scope only,
    # so one inherited from a module or a class does not count. See
    # tests/actuation_guard.py's scope_violations for the collection-time refusal.
    own = {mark.name: mark for mark in request.node.own_markers}
    for name in (MARKER, WRITE_MARKER):
        if name in own:
            try:
                reason_for(own[name])
            except ValueError as exc:
                pytest.fail(str(exc))

    if MARKER not in own:
        deny_everything(monkeypatch)
    if WRITE_MARKER not in own:
        confine_writes(monkeypatch)


@pytest.fixture(autouse=True)
def _host_state_is_stated(request, monkeypatch) -> None:
    """Pin the live foreground window, and clear the action cooldown.

    Thirteen tests failed on a documentation-only tree because
    ``desktop_context.active_window_is_protected()`` reads the *real* foreground
    window title and matches it against "sign in", "login", "password", "bank",
    "checkout" and others. Chrome's window title follows its active tab, so a
    sign-in page with focus was enough. The same tree passed on either side of
    that run, and all the affected tests passed in isolation.

    The protected-window feature is correct -- it is what stops the assistant
    typing into a password prompt -- so it is not weakened here. What is fixed is
    tests inheriting their answer from whatever the developer has open.

    A test that needs the real machine asks for it, with a reason, exactly as the
    other two guards work:

        @pytest.mark.real_host_state(reason="...")

    The cooldown timestamp is reset for the same class of reason: it is module
    state, wall-clock based, and survives a test.
    """
    from tests.host_state import MARKER as HOST_MARKER
    from tests.host_state import pin_host_state, reason_for, reset_action_cooldown

    own = {mark.name: mark for mark in request.node.own_markers}
    if HOST_MARKER in own:
        try:
            reason_for(own[HOST_MARKER])
        except ValueError as exc:
            pytest.fail(str(exc))
        return

    pin_host_state(monkeypatch)
    reset_action_cooldown(monkeypatch)


@pytest.fixture
def protected_window(monkeypatch) -> None:
    """Re-pin the foreground window as a sensitive one.

    For the tests that assert the refusal. Named so a test asks for the case
    rather than inventing a title and hoping it matches the keyword list.
    """
    from tests.host_state import PROTECTED_PROCESS, pin_host_state

    pin_host_state(monkeypatch, PROTECTED_PROCESS)


@pytest.fixture(scope="session")
def _approval_store_root(tmp_path_factory) -> Path:
    """One directory for every test's approval store.

    A directory per test cost about as much as all the suite's other fixture
    setup put together: creating one under the temp root got slower the more
    the run had already created, ending above ten seconds each. One directory
    and a file name per test is the same isolation for a single mkdir.
    """
    return tmp_path_factory.mktemp("approval-stores")


@pytest.fixture(autouse=True)
def _private_approval_store(monkeypatch, _approval_store_root: Path) -> None:
    """Give each test its own approval store.

    Every action waiting for a yes -- a code approval or a deferred one -- lives
    in pc_control's store. Shared across tests, a "yes" in one test could
    resolve an action another test staged and left pending. A test that sets
    its own path keeps it.

    The file itself is not created here: sqlite makes it when a test first
    opens the store, so a test that never touches approvals writes nothing.
    """
    if not os.environ.get("GRANDPA_PC_CONTROL_DB"):
        path = _approval_store_root / f"approvals-{uuid4().hex}.db"
        monkeypatch.setenv("GRANDPA_PC_CONTROL_DB", str(path))


# ---------------------------------------------------------------------------
# Hardware fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def nvidia_gpu() -> GpuInfo:
    """NVIDIA A100 GPU fixture."""
    return GpuInfo(vendor="nvidia", name="NVIDIA A100-SXM4-80GB", vram_gb=80.0, count=1)


@pytest.fixture
def nvidia_consumer_gpu() -> GpuInfo:
    """NVIDIA consumer GPU fixture."""
    return GpuInfo(
        vendor="nvidia",
        name="NVIDIA GeForce RTX 4090",
        vram_gb=24.0,
        count=1,
    )


@pytest.fixture
def nvidia_multi_gpu() -> GpuInfo:
    """NVIDIA multi-GPU fixture."""
    return GpuInfo(vendor="nvidia", name="NVIDIA H100", vram_gb=80.0, count=4)


@pytest.fixture
def amd_gpu() -> GpuInfo:
    """AMD MI300X GPU fixture."""
    return GpuInfo(vendor="amd", name="AMD Instinct MI300X", vram_gb=192.0, count=1)


@pytest.fixture
def apple_gpu() -> GpuInfo:
    """Apple Silicon GPU fixture."""
    return GpuInfo(vendor="apple", name="Apple M4 Max", vram_gb=128.0, count=1)


@pytest.fixture
def hardware_nvidia(nvidia_gpu: GpuInfo) -> HardwareInfo:
    """Full NVIDIA hardware profile."""
    return HardwareInfo(
        platform="linux",
        cpu_brand="AMD EPYC 7763",
        cpu_count=64,
        ram_gb=512.0,
        gpu=nvidia_gpu,
    )


@pytest.fixture
def hardware_nvidia_consumer(nvidia_consumer_gpu: GpuInfo) -> HardwareInfo:
    """Consumer NVIDIA hardware profile."""
    return HardwareInfo(
        platform="linux",
        cpu_brand="Intel Core i9-14900K",
        cpu_count=24,
        ram_gb=64.0,
        gpu=nvidia_consumer_gpu,
    )


@pytest.fixture
def hardware_amd(amd_gpu: GpuInfo) -> HardwareInfo:
    """Full AMD hardware profile."""
    return HardwareInfo(
        platform="linux",
        cpu_brand="AMD EPYC 9654",
        cpu_count=96,
        ram_gb=768.0,
        gpu=amd_gpu,
    )


@pytest.fixture
def hardware_apple(apple_gpu: GpuInfo) -> HardwareInfo:
    """Apple Silicon hardware profile."""
    return HardwareInfo(
        platform="darwin",
        cpu_brand="Apple M4 Max",
        cpu_count=16,
        ram_gb=128.0,
        gpu=apple_gpu,
    )


@pytest.fixture
def hardware_cpu_only() -> HardwareInfo:
    """CPU-only hardware profile (no GPU)."""
    return HardwareInfo(
        platform="linux",
        cpu_brand="Intel Xeon E5-2686 v4",
        cpu_count=8,
        ram_gb=32.0,
        gpu=None,
    )


# ---------------------------------------------------------------------------
# Engine availability fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def has_ollama() -> bool:
    """Check if Ollama is running locally."""
    try:
        import httpx

        resp = httpx.get("http://localhost:11434/api/tags", timeout=2.0)
        return resp.status_code == 200
    except Exception:
        return False


@pytest.fixture
def has_vllm() -> bool:
    """Check if vLLM is running locally."""
    try:
        import httpx

        resp = httpx.get("http://localhost:8000/v1/models", timeout=2.0)
        return resp.status_code == 200
    except Exception:
        return False


@pytest.fixture
def has_llamacpp() -> bool:
    """Check if llama.cpp server is running locally."""
    try:
        import httpx

        resp = httpx.get("http://localhost:8080/v1/models", timeout=2.0)
        return resp.status_code == 200
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Cloud API key fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def has_openai_key() -> bool:
    """Check if OPENAI_API_KEY is set."""
    return bool(os.environ.get("OPENAI_API_KEY"))


@pytest.fixture
def has_anthropic_key() -> bool:
    """Check if ANTHROPIC_API_KEY is set."""
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


@pytest.fixture
def has_gemini_key() -> bool:
    """Check if GEMINI_API_KEY or GOOGLE_API_KEY is set."""
    return bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))


# ---------------------------------------------------------------------------
# Mock engine factory
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_engine():
    """Factory for mock InferenceEngine instances."""

    def _factory(
        engine_id: str = "mock",
        model_response: str = "Hello!",
        tool_calls: list | None = None,
        models: list[str] | None = None,
    ) -> MagicMock:
        engine = MagicMock()
        engine.engine_id = engine_id
        engine.health.return_value = True
        engine.list_models.return_value = models or ["test-model"]

        result = {
            "content": model_response,
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            "model": "test-model",
            "finish_reason": "stop",
        }
        if tool_calls:
            result["tool_calls"] = tool_calls
            result["finish_reason"] = "tool_calls"
        engine.generate.return_value = result
        return engine

    return _factory


@pytest.fixture
def event_bus() -> EventBus:
    """Fresh EventBus with history recording enabled."""
    return EventBus(record_history=True)


# ---------------------------------------------------------------------------
# What this run proved, recorded from inside pytest
# ---------------------------------------------------------------------------
# Three commits in this project were made on a failing suite, and one of them
# (2df79819) only because the exit status passed through `tail` on its way to an
# `&&`. These two hooks write the result from inside the pytest process, where
# no pipe exists yet; scripts/commit_verification.py reads the file and the
# commit-msg hook refuses the commit. See tests/verification_plugin.py.
from tests.verification_plugin import (  # noqa: E402
    pytest_runtest_logreport,
    pytest_sessionfinish,
    pytest_sessionstart,
)

__all__ = [
    "pytest_runtest_logreport",
    "pytest_sessionfinish",
    # sessionstart too: a run that is killed writes nothing at finish, so the
    # guard fell back to an older record and the absence was invisible. The
    # start record is what makes an interrupted run refusable.
    "pytest_sessionstart",
]


# ---------------------------------------------------------------------------
# Which test left a sqlite connection open
# ---------------------------------------------------------------------------
# Off unless GRANDPA_TRACK_SQLITE=1. See tests/sqlite_tracker.py for the three
# stalls this exists to explain -- one of which came with a stack dump showing a
# test blocked on `conn.execute` waiting for a lock somebody else held.
from tests import sqlite_tracker  # noqa: E402

sqlite_tracker.install()


@pytest.fixture(autouse=True)
def _track_sqlite_connections(request):
    """Attribute every connection to the test that opened it.

    Reports rather than fails: the first run of this found leaks in code that
    has always leaked them, and turning the suite red on discovery would have
    buried the stall this is for.
    """
    if os.environ.get(sqlite_tracker.ENV_VAR) != "1":
        yield
        return
    nodeid = request.node.nodeid
    # Anything mid-transaction before this test has even started belongs to
    # somebody else, and is what will block this test if it tries to write.
    inherited = sqlite_tracker.TRACKER.in_transaction()
    if inherited:
        print(
            f"\n[sqlite] {nodeid} starts with {len(inherited)} connection(s) "
            f"already in a transaction, held by earlier tests:\n"
            + sqlite_tracker.describe(inherited)
        )
    sqlite_tracker.TRACKER.current_nodeid = nodeid
    yield
    sqlite_tracker.TRACKER.forget_dead()
    leaked = sqlite_tracker.TRACKER.open_for(nodeid)
    if leaked:
        for record in leaked:
            sqlite_tracker.TRACKER.leaks.append(
                (nodeid, record.database, record.opened_at)
            )
        print(
            f"\n[sqlite] {nodeid} left {len(leaked)} connection(s) open:\n"
            + sqlite_tracker.describe(leaked)
        )
