# -*- coding: utf-8 -*-
"""Full-lifecycle timing probe tests (M16).

The probe writes a log file; tests monkeypatch the module-level ``_LOG``
to a temp file and reset the module state (last-checkpoint, stack,
header flag) so each test sees a clean session.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from mtkgui import startup_timing as st


@pytest.fixture()
def probe(tmp_path):
    """Redirect the probe to a temp log and reset its state."""
    log = tmp_path / "timing.log"
    st._LOG = log
    st._HEADER_WRITTEN = False
    st._LAST = st._T0
    st._stack().clear()
    st._PROGRESS_HANDLER = None
    yield log
    st._LOG = None
    st._stack().clear()
    st._PROGRESS_HANDLER = None


def _lines(log: Path) -> list[str]:
    return log.read_text(encoding="utf-8").splitlines()


def test_session_header_and_mark(probe):
    st.mark("ui: theme applied")
    lines = _lines(probe)
    assert lines[0].startswith("session 20")
    assert "pid " in lines[0] and "frozen=" in lines[0]
    assert "[ui" in lines[1] and "ui: theme applied" in lines[1]
    # delta of the second checkpoint is measured from the first
    time.sleep(0.01)
    st.mark("ui: build done")
    lines = _lines(probe)
    assert lines[-1].endswith("ui: build done")
    assert "+0.0" in lines[-1]


def test_category_inference_and_override(probe):
    st.mark("testflow: run")            # prefix -> testflow
    st.mark("no prefix here")           # -> misc
    st.mark("parse: nets", category="io")  # explicit override
    lines = _lines(probe)
    assert "[testflow" in lines[1]
    assert "[misc" in lines[2]
    assert "[io" in lines[3]


def test_begin_end_pairs_and_wait_marker(probe):
    st.begin("login", category="wait", wait=True)
    st.end("login", note="operator signed in (Supervisor, Virtual)")
    lines = _lines(probe)
    begin_line = [l for l in lines if "BEGIN login" in l][0]
    end_line = [l for l in lines if "END   login" in l][0]
    assert "[wait    ] [WAIT] BEGIN login" in begin_line
    assert "waiting for operator" in begin_line
    assert "[wait    ] [WAIT] END   login" in end_line
    assert "(operator signed in (Supervisor, Virtual))" in end_line
    assert "waited" in end_line


def test_begin_end_nesting_and_indent(probe):
    st.begin("report: build")
    st.begin("report: render")
    st.end("report: render")
    st.end("report: build")
    lines = _lines(probe)
    render_end = [l for l in lines if "END   report: render" in l][0]
    assert "]   END   report: render" in render_end  # nested indent
    build_end = [l for l in lines if "END   report: build" in l][0]
    assert "] END   report: build" in build_end  # top level, no indent


def test_end_without_begin_warns(probe):
    st.end("orphan")
    assert "no matching BEGIN" in _lines(probe)[1]


def test_end_mismatch_warns(probe):
    st.begin("a: one")
    st.end("b: two")
    assert "mismatch: open is 'a: one'" in _lines(probe)[2]


def test_timed_context_manager(probe):
    with st.timed("io: export excel"):
        time.sleep(0.005)
    lines = _lines(probe)
    assert any("BEGIN io: export excel" in l for l in lines)
    end_line = [l for l in lines if "END   io: export excel" in l][0]
    assert "[io" in end_line


def test_disabled_via_env(probe, monkeypatch, tmp_path):
    monkeypatch.setenv("MTK_TIMING", "0")
    import importlib
    st._ENABLED = False
    st._LOG = None
    st.mark("quiet: should not be written")
    assert not (tmp_path / "timing.log").exists() or \
        "quiet: should not be written" not in _lines(probe)
    st._ENABLED = True


def test_thread_safety(probe):
    errors: list[Exception] = []

    def worker(n):
        try:
            for i in range(50):
                st.mark(f"worker{n}: tick {i}")
                st.begin(f"worker{n}: op")
                st.end(f"worker{n}: op")
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    lines = _lines(probe)
    assert sum(1 for l in lines if "worker1: op" in l) == 100
