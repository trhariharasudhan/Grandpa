"""A7: the performance gate -- 20% iGPU, 300 MB, and the fall back to the ring.

No real process is measured and no PowerShell runs: psutil and the counter
call are replaced by fakes, because what is tested is the arithmetic and the
decision. The real numbers come from Captain's PC (`grandpa avatar
--perf-log` while Ollama generates). The page's own slow-frame check is
checked as written and was exercised in headless Chromium for the PR.
"""

from __future__ import annotations

import json
import re
import time
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from grandpa.cli.avatar_cmd import avatar, budget_watch, build
from grandpa.ui.avatar_budget import (
    GPU_BUDGET_PCT,
    RAM_BUDGET_MB,
    STRIKES,
    Budget,
    BudgetWatch,
    Sample,
    gpu_pct,
    parse_gpu_counters,
    ram_mb,
    sample_window,
    window_processes,
)
from grandpa.ui.avatar_controller import RING_ONLY_NOTE, AvatarController
from grandpa.ui.avatar_states import ChatMessage, ModeMessage, encode
from grandpa.ui.avatar_window import WEB_DIR

pytestmark = pytest.mark.core

MIB = 1024 * 1024


def test_the_budget_is_the_spec() -> None:
    assert (GPU_BUDGET_PCT, RAM_BUDGET_MB) == (20.0, 300.0)


# --- samples ----------------------------------------------------------------------


def test_a_sample_says_what_is_over() -> None:
    budget = Budget()
    assert Sample(ram_mb=120, gpu_pct=8).over(budget) == []
    assert Sample(ram_mb=120, gpu_pct=27.4).over(budget) == ["GPU 27% > 20%"]
    assert Sample(ram_mb=420, gpu_pct=None).over(budget) == ["RAM 420 MB > 300 MB"]
    assert Sample().over(budget) == [] and not Sample().measured


class FakeProc:
    def __init__(self, pid, name, uss=None, rss=0, gone=False):
        self.pid, self._name, self._uss, self._rss, self._gone = (
            pid,
            name,
            uss,
            rss,
            gone,
        )

    def name(self):
        if self._gone:
            raise ProcessLookupError
        return self._name

    def memory_full_info(self):
        if self._uss is None:
            raise PermissionError
        return SimpleNamespace(uss=self._uss)

    def memory_info(self):
        if self._gone:
            raise ProcessLookupError
        return SimpleNamespace(rss=self._rss)


def fake_psutil(children):
    me = SimpleNamespace(children=lambda recursive: children)
    return SimpleNamespace(Process=lambda pid=None: me)


def test_only_the_webview_processes_are_the_window() -> None:
    kids = [
        FakeProc(10, "msedgewebview2.exe"),
        FakeProc(11, "chrome.exe"),  # a program Grandpa opened: not the avatar
        FakeProc(12, "msedgewebview2"),
        FakeProc(13, "x", gone=True),
    ]
    found = window_processes(psutil_module=fake_psutil(kids))
    assert [p.pid for p in found] == [10, 12]


def test_ram_prefers_private_memory_and_falls_back_to_working_set() -> None:
    procs = [
        FakeProc(1, "a", uss=100 * MIB, rss=300 * MIB),
        FakeProc(2, "b", uss=None, rss=50 * MIB),
        FakeProc(3, "c", gone=True),
    ]
    assert ram_mb(procs) == pytest.approx(150.0)
    assert ram_mb([]) is None


COUNTERS = """\
pid_10_luid_0x0_0x1_phys_0_eng_0_engtype_3d=12.5
pid_10_luid_0x0_0x1_phys_0_eng_1_engtype_3d=1,5
pid_99_luid_0x0_0x1_phys_0_eng_0_engtype_3d=80
pid_12_luid_0x0_0x1_phys_0_eng_0_engtype_3d=not-a-number
"""


def test_gpu_counters_are_summed_for_the_window_only() -> None:
    assert parse_gpu_counters(COUNTERS, [10, 12]) == pytest.approx(14.0)
    assert parse_gpu_counters(COUNTERS, [7]) == 0.0  # counters read, not using the GPU
    assert parse_gpu_counters("", [10]) is None
    assert parse_gpu_counters(COUNTERS, []) is None


def test_gpu_is_read_with_one_powershell_call_on_windows_only() -> None:
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(returncode=0, stdout=COUNTERS)

    assert gpu_pct([10], run=run, platform="win32") == pytest.approx(14.0)
    assert calls[0][0] == "powershell" and "GPU Engine" in calls[0][-1]
    assert gpu_pct([10], run=run, platform="linux") is None
    assert gpu_pct([], run=run, platform="win32") is None
    assert len(calls) == 1


def test_a_failed_counter_read_is_unknown_not_zero() -> None:
    def fails(*_a, **_k):
        return SimpleNamespace(returncode=1, stdout="")

    def raises(*_a, **_k):
        raise FileNotFoundError("powershell")

    assert gpu_pct([10], run=fails, platform="win32") is None
    assert gpu_pct([10], run=raises, platform="win32") is None


def test_a_window_sample_reads_ram_and_gpu() -> None:
    kids = [FakeProc(10, "msedgewebview2.exe", uss=80 * MIB)]

    def run(*_a, **_k):
        return SimpleNamespace(returncode=0, stdout=COUNTERS)

    sample = sample_window(psutil_module=fake_psutil(kids), run=run)
    assert sample.ram_mb == pytest.approx(80.0)
    assert sample.gpu_pct is None or sample.gpu_pct == pytest.approx(14.0)


# --- the watch --------------------------------------------------------------------


def _watch(**kwargs):
    fired = []
    watch = BudgetWatch(lambda: Sample(), fired.append, **kwargs)
    return watch, fired


def test_it_falls_back_only_after_strikes_in_a_row() -> None:
    watch, fired = _watch()
    hot = Sample(ram_mb=100, gpu_pct=35)
    for _ in range(STRIKES - 1):
        assert not watch.check(hot)
    assert not watch.check(Sample(ram_mb=100, gpu_pct=5))  # a good sample resets
    for _ in range(STRIKES - 1):
        watch.check(hot)
    assert fired == []
    assert watch.check(hot)
    assert fired == [["GPU 35% > 20%"]]


def test_it_falls_back_once_and_unknown_samples_count_neither_way() -> None:
    watch, fired = _watch(strikes=2)
    hot = Sample(ram_mb=500)
    watch.check(hot)
    watch.check(Sample())  # unreadable: no reset, no strike
    watch.check(hot)
    watch.check(hot)
    watch.check(hot)
    assert fired == [["RAM 500 MB > 300 MB"]]


def test_a_sampler_that_raises_does_not_stop_the_watch() -> None:
    def boom():
        raise RuntimeError("psutil broke")

    watch = BudgetWatch(boom, lambda _r: None)
    assert watch.step() is False


def test_the_watch_thread_samples_and_stops() -> None:
    samples = []
    watch = BudgetWatch(
        lambda: Sample(ram_mb=50),
        lambda _r: None,
        on_sample=samples.append,
        interval=0.01,
    )
    watch.start()
    deadline = time.monotonic() + 2
    while not samples and time.monotonic() < deadline:
        time.sleep(0.01)
    watch.stop()
    assert samples and samples[0].ram_mb == 50


# --- the controller and the command -------------------------------------------------


class Bridge:
    def send(self, text):
        return SimpleNamespace(text="ok", status="ok", failed=False, kind=None)


def test_ring_only_is_sent_said_and_kept_for_new_pages() -> None:
    published = []
    controller = AvatarController(bridge=Bridge(), publish=published.append)

    assert controller.ring_only("GPU 27% > 20%")
    assert not controller.ring_only("again")  # once per run

    mode = ModeMessage(character=False, reason="GPU 27% > 20%")
    assert published[0] == mode
    assert published[1] == ChatMessage("grandpa", f"{RING_ONLY_NOTE} (GPU 27% > 20%)")
    assert len(published) == 2
    assert controller.snapshot()[0] == mode
    assert json.loads(encode(mode)) == {
        "type": "mode",
        "v": 1,
        "character": False,
        "reason": "GPU 27% > 20%",
    }


def test_a_normal_snapshot_has_no_mode() -> None:
    controller = AvatarController(bridge=Bridge(), publish=lambda _m: None)
    assert not any(isinstance(m, ModeMessage) for m in controller.snapshot())


def test_the_command_watch_falls_back_and_logs() -> None:
    lines = []
    controller = AvatarController(bridge=Bridge(), publish=lambda _m: None)
    watch = budget_watch(
        controller,
        lines.append,
        perf_log=True,
        sample=lambda: Sample(ram_mb=120, gpu_pct=31),
    )
    for _ in range(STRIKES):
        watch.step()
    assert not controller.mode.character
    assert lines[0] == "avatar window: RAM 120 MB, GPU 31.0%"
    assert (
        lines[-1] == "Over budget (GPU 31% > 20%): showing only the ring from now on."
    )


def test_no_budget_only_logs() -> None:
    lines = []
    controller = AvatarController(bridge=Bridge(), publish=lambda _m: None)
    watch = budget_watch(
        controller,
        lines.append,
        perf_log=True,
        fall_back=False,
        sample=lambda: Sample(gpu_pct=90),
    )
    for _ in range(STRIKES + 1):
        watch.step()
    assert controller.mode.character
    assert all(line.startswith("avatar window:") for line in lines)


def test_the_options_are_there() -> None:
    result = CliRunner().invoke(avatar, ["--help"])
    assert result.exit_code == 0
    for option in ("--orb-only", "--no-budget", "--perf-log"):
        assert option in result.output


websockets = pytest.importorskip("websockets")


def test_a_page_that_connects_after_the_fallback_gets_the_mode_first() -> None:
    from websockets.sync.client import connect

    controller, server = build(Bridge())
    controller.ring_only("RAM 420 MB > 300 MB")
    server.start()
    try:
        with connect(server.url, open_timeout=3) as ws:
            first = json.loads(ws.recv(timeout=3))
    finally:
        server.stop()
    assert first["type"] == "mode" and first["character"] is False


# --- the page ---------------------------------------------------------------------

CHARACTER = (WEB_DIR / "character.js").read_text(encoding="utf-8")
AVATAR = (WEB_DIR / "avatar.js").read_text(encoding="utf-8")


def test_the_page_passes_the_mode_to_the_character() -> None:
    assert 'msg.type === "mode"' in AVATAR
    assert '"grandpa:mode"' in AVATAR and '"grandpa:mode"' in CHARACTER
    assert "window.__grandpaMode" in CHARACTER


def test_the_page_judges_its_own_frames_and_retires_for_good() -> None:
    slow = float(re.search(r"const SLOW_FRAME_MS = (\d+);", CHARACTER).group(1))
    after = int(re.search(r"const SLOW_AFTER_FRAMES = (\d+);", CHARACTER).group(1))
    # slower than the 20 fps "waiting" cap, so a capped page never trips it
    assert slow > 1000 / 20 and after >= 60
    assert "if (retired) return;" in CHARACTER
    assert "retired || !(buffer instanceof ArrayBuffer)" in CHARACTER  # no model load
    assert "setTimeout(destroy, MORPH_MS + 50)" in CHARACTER  # morphs out, then frees
