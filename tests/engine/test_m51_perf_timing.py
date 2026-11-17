# -*- coding: utf-8 -*-
"""M51 full-lifecycle timing log rework - engine-side tests.

Covers: [SLOW] marks + exclusions, settings.json threshold, exception
capture hooks (main / worker thread, chain-safe), the Tools-switch
persistence helpers, the session summary (TOP-N, exclusions, off =
nothing), and the zero-impact OFF fast path.
"""
from __future__ import annotations

import threading
import types
from pathlib import Path

import pytest

from mtkgui import app_paths
from mtkgui import startup_timing as st


class _Clock:
    """Deterministic replacement for ``time.perf_counter``."""

    def __init__(self, *values):
        self.values = list(values) or [0.0]
        self.calls = 0

    def perf_counter(self) -> float:
        self.calls += 1
        return self.values[min(self.calls - 1, len(self.values) - 1)]


@pytest.fixture()
def probe(tmp_path):
    """Temp log; the settings come from the isolated config dir."""
    old = (st._ENABLED, st._LOG, st._T0, st._LAST, st._HEADER_WRITTEN)
    st._ENABLED = True
    st._LOG = tmp_path / "timing.log"
    st._HEADER_WRITTEN = False
    st._T0 = 0.0
    st._LAST = 0.0
    st._stack().clear()
    st._SPANS.clear()
    st._EXCEPTIONS.clear()
    st._SUMMARY_WRITTEN = False
    st.install_exception_hooks()
    yield tmp_path / "timing.log"
    (st._ENABLED, st._LOG, st._T0, st._LAST,
     st._HEADER_WRITTEN) = old
    st._stack().clear()
    st._SPANS.clear()
    st._EXCEPTIONS.clear()
    st.remove_exception_hooks()


def _lines(log: Path) -> list[str]:
    return log.read_text(encoding="utf-8").splitlines()


def _last(log: Path) -> str:
    return _lines(log)[-1]


# ----------------------------------------------------------- 1 [SLOW]
def test_slow_mark_above_threshold(probe, monkeypatch):
    st._HEADER_WRITTEN = True
    monkeypatch.setattr(st, "time", _Clock(1.05))
    st.mark("ui: slow thing")
    assert _last(probe).endswith("ui: slow thing [SLOW 1.050s]")


def test_under_threshold_is_not_marked(probe, monkeypatch):
    app_paths.set_setting(st.SLOW_THRESHOLD_KEY, 1.0)
    st._HEADER_WRITTEN = True
    monkeypatch.setattr(st, "time", _Clock(0.8))
    st.mark("ui: fast thing")
    assert "[SLOW" not in _last(probe)


def test_slow_end_and_threshold_from_settings(probe, monkeypatch):
    app_paths.set_setting(st.SLOW_THRESHOLD_KEY, 0.5)
    st._HEADER_WRITTEN = True
    monkeypatch.setattr(st, "time", _Clock(0.0, 0.8))
    st.begin("io: parse")
    st.end("io: parse")
    assert "[SLOW 0.800s]" in _last(probe)
    # the threshold is re-read per event: raising it changes the verdict
    app_paths.set_setting(st.SLOW_THRESHOLD_KEY, 2.0)
    st._LAST = 0.0
    monkeypatch.setattr(st, "time", _Clock(0.0, 0.8))
    st.begin("io: parse 2")
    st.end("io: parse 2")
    assert "[SLOW" not in _last(probe)


def test_wait_span_is_never_slow(probe, monkeypatch):
    st._HEADER_WRITTEN = True
    monkeypatch.setattr(st, "time", _Clock(0.0, 1.5))
    st.begin("login", category="wait", wait=True)
    st.end("login")
    line = [l for l in _lines(probe) if "END   login" in l][0]
    assert "[WAIT]" in line and "[SLOW" not in line


def test_no_slow_span_is_never_slow(probe, monkeypatch):
    st._HEADER_WRITTEN = True
    monkeypatch.setattr(st, "time", _Clock(0.0, 3.0))
    st.begin("testflow: delay", no_slow=True)
    st.end("testflow: delay")
    assert "[SLOW" not in _last(probe)


# ------------------------------------------------------ 2 exceptions
def test_thread_exception_hook_logs_and_chains(probe):
    seen: list = []
    original_prev = st._PREV_THREAD_EXCEPTHOOK
    st._PREV_THREAD_EXCEPTHOOK = lambda args: seen.append(args)
    try:
        def _boom():
            raise ValueError("boom")

        thread = threading.Thread(target=_boom, name="m51-worker")
        thread.start()
        thread.join()
    finally:
        st._PREV_THREAD_EXCEPTHOOK = original_prev
    line = [l for l in _lines(probe) if "[EXCEPTION]" in l][-1]
    assert "ValueError: boom" in line
    assert "test_m51_perf_timing.py:" in line
    assert seen, "previous threading.excepthook was not chained"


def test_main_thread_hook_logs(probe):
    import sys
    try:
        raise RuntimeError("main boom")
    except RuntimeError:
        exc = sys.exc_info()
    original_prev = st._PREV_SYS_EXCEPTHOOK
    st._PREV_SYS_EXCEPTHOOK = None      # keep pytest-qt's hook out of it
    try:
        st._sys_excepthook(*exc)
    finally:
        st._PREV_SYS_EXCEPTHOOK = original_prev
    line = [l for l in _lines(probe) if "[EXCEPTION]" in l][-1]
    assert "RuntimeError: main boom" in line
    assert "test_m51_perf_timing.py:" in line


def test_exception_hook_silent_when_off(probe):
    st._ENABLED = False
    st._log_exception(ValueError, ValueError("quiet"), None)
    text = probe.read_text(encoding="utf-8") if probe.exists() else ""
    assert "[EXCEPTION]" not in text


# --------------------------------------------------------- 3 switch
def test_saved_enabled_defaults_to_factory_off(monkeypatch):
    """v2/C3: no saved value -> the factory default is OFF."""
    monkeypatch.delenv("MTK_TIMING", raising=False)
    assert st.saved_enabled() is False
    st.save_enabled(True)
    assert st.saved_enabled() is True
    # the value is in settings.json, not in the environment
    assert app_paths.get_setting(st.ENABLED_KEY) is True
    st.save_enabled(False)
    assert st.saved_enabled() is False


def test_session_state_does_not_follow_saved_setting(probe):
    before = st.is_enabled()
    st.save_enabled(not before)
    assert st.is_enabled() == before


# ---------------------------------------------------------- 4 summary
def test_summary_top_n_and_exceptions(probe):
    st._SPANS.extend([
        (18.412, "ui", "theme applied"),
        (9.021, "testflow", "FCT sequence run: step 12"),
        (3.0, "io", "export excel")])
    st._SPANS.extend(
        (1.0 + i, "io", f"extra span {i}") for i in range(12))
    st._EXCEPTIONS.append(("01:20:44.123", "ValueError: boom", "file.py:123"))
    app_paths.set_setting(st.SLOW_THRESHOLD_KEY, 0.35)
    st.write_session_summary()
    text = probe.read_text(encoding="utf-8")
    assert "====== session summary ======" in text
    assert "slowest steps (threshold 0.3s):" in text
    assert "18.412s" in text and "theme applied" in text
    assert "step 12" in text
    # TOP-10 only: the SUMMARY_TOP constant caps the list
    numbered = [ln for ln in text.splitlines()
                if ln.strip()[:3].strip().rstrip(".").isdigit()]
    assert len(numbered) == 10
    assert "exceptions (1):" in text
    assert "01:20:44.123  ValueError: boom  (file.py:123)" in text
    assert "====== end summary ======" in text
    # once-only: a second call appends nothing
    st.write_session_summary()
    assert text.count("====== session summary ======") == 1


def test_summary_excludes_wait_and_no_slow(probe, monkeypatch):
    st._HEADER_WRITTEN = True
    monkeypatch.setattr(st, "time", _Clock(0.0, 12.0, 0.0, 12.0))
    st.begin("login", wait=True)
    st.end("login")
    st.begin("testflow: delay", no_slow=True)
    st.end("testflow: delay")
    st.write_session_summary()
    text = probe.read_text(encoding="utf-8")
    assert "login" not in text.split("====== session summary ======")[-1]
    assert "testflow: delay" not in text.split("====== session summary")[-1]


def test_summary_not_written_when_session_off(probe):
    st._ENABLED = False
    st._SPANS.append((5.0, "ui", "hidden"))
    st.write_session_summary()
    text = probe.read_text(encoding="utf-8") if probe.exists() else ""
    assert "session summary" not in text


def test_summary_survives_malformed_state(probe):
    st._SPANS.append("malformed")
    st.write_session_summary()      # must not raise
    assert st._SUMMARY_WRITTEN is True


# --------------------------------------------------------- 5 zero OFF
def test_off_is_a_hard_no_op(probe, monkeypatch):
    st._ENABLED = False
    clock = _Clock()
    monkeypatch.setattr(st, "time", clock)
    st.mark("ui: nothing")
    st.begin("io: nothing")
    st.end("io: nothing")
    with st.timed("io: context"):
        pass
    assert clock.calls == 0
    assert not probe.exists()
    assert st._SPANS == []
    assert st._EXCEPTIONS == []


def test_off_installs_no_hooks():
    st.remove_exception_hooks()
    st._ENABLED = False
    st.install_exception_hooks()
    assert st._HOOKS_INSTALLED is False
    st._ENABLED = True
    st.install_exception_hooks()        # restore for the rest of the run
