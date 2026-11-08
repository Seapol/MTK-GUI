# -*- coding: utf-8 -*-
"""M81: the DUT report renders in a CHILD process, with visible progress.

The render holds the GIL in the GUI interpreter, so the progress dialog must
belong to a parent that is not rendering.  These tests drive the real child
(``sys.executable`` + ``main.py`` + ``--render-pdf``) and the real parent-side
client, plus the run gate that stops a second run while a report is still
being generated.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

REPO_ROOT = Path(__file__).resolve().parents[2]
CHILD_TIMEOUT_S = 180.0


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


# --------------------------------------------------------------- fixtures
def _report():
    from mtkgui.engine.report import DutReport, ReportItem
    report = DutReport(serial_no="SN-M81-001", station_id="ST-01",
                       user="tester", overall_result="PASS")
    report.items = [
        ReportItem(test_name=f"TEST_{index}", category="ICT",
                   channel="CH1", measured="1.000", result="PASS")
        for index in range(1, 5)]
    report.console_log = "console line\n" * 80
    return report


def _job(path) -> dict:
    return {"type": "render", "path": str(path),
            "meta": {"part": "P", "core_id": "C", "batch": "B"},
            "report": asdict(_report())}


def _child_argv() -> list[str]:
    argv = [sys.executable]
    if not getattr(sys, "frozen", False):
        argv.append(str(REPO_ROOT / "main.py"))
    argv.append("--render-pdf")
    return argv


def _child_env() -> dict:
    env = dict(os.environ)
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    return env


def _run_child(jobs: list[dict], timeout: float = CHILD_TIMEOUT_S):
    """Feed the jobs to one child (stdin closes it) and return its lines."""
    payload = "".join(json.dumps(job) + "\n" for job in jobs)
    proc = subprocess.run(_child_argv(), input=payload, capture_output=True,
                          text=True, timeout=timeout, cwd=str(REPO_ROOT),
                          env=_child_env())
    assert proc.returncode == 0, proc.stderr
    lines = [json.loads(line) for line in proc.stdout.splitlines()
             if line.strip()]
    return lines, proc


# -------------------------------------------------------------------- C1
def test_render_pdf_on_page_callback_reports_every_page(tmp_path, qapp):
    from mtkgui.gui import dut_pdf

    html, images, chart_spec = dut_pdf.report_pdf_payload(_report(), {})
    if chart_spec:
        images[dut_pdf.CHART_RESOURCE] = dut_pdf.paint_rails_chart(*chart_spec)
    seen = []
    dut_pdf._render_pdf(html, images, tmp_path / "callback.pdf",
                        font_scale=dut_pdf.screen_font_scale(),
                        on_page=lambda done, total: seen.append((done, total)))
    assert seen, "the page callback must fire"
    total = seen[0][1]
    assert seen[0][0] == 0                     # total announced first
    assert [done for done, _total in seen[1:]] == list(range(1, total + 1))
    assert all(count == total for _done, count in seen)


def test_render_child_reports_pages_and_writes_pdf(tmp_path):
    out = tmp_path / "child.pdf"
    lines, _proc = _run_child([_job(out)])
    assert lines[0] == {"t": "ready"}
    pages = [line for line in lines if line.get("t") == "page"]
    assert pages, "the child must report its pages"
    total = pages[-1]["total"]
    assert all(page["total"] == total for page in pages)
    assert [page["done"] for page in pages] == list(range(0, total + 1))
    done = lines[-1]
    assert done["t"] == "done"
    assert done["path"] == str(out)
    assert out.is_file() and out.stat().st_size > 0


def test_render_child_returns_error_line_without_exiting(tmp_path):
    broken = {"type": "render", "path": str(tmp_path / "broken.pdf"),
              "meta": {}, "report": {"items": "not-a-list"}}
    good = _job(tmp_path / "after_error.pdf")
    lines, _proc = _run_child([broken, good])
    assert lines[0] == {"t": "ready"}
    assert lines[1]["t"] == "error"
    assert "TypeError" in lines[1]["msg"]
    # the child stayed alive for the next job
    assert any(line.get("t") == "done"
               and line.get("path") == str(tmp_path / "after_error.pdf")
               for line in lines)
    assert (tmp_path / "after_error.pdf").is_file()


# -------------------------------------------------------------------- C2
def _pump(app, predicate, timeout_s: float) -> bool:
    """Spin the event loop until *predicate* is true or the timeout expires."""
    import time

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.005)
    app.processEvents()
    return predicate()


def _long_report():
    report = _report()
    report.console_log = ("A" * 78 + "\n") * 1500      # ~120 000 chars
    return report


def test_render_client_times_out_and_recovers(tmp_path, qapp):
    from mtkgui.gui.render_client import ReportRenderClient

    client = ReportRenderClient()
    client._timer.setInterval(50)      # test knob - do not wait a minute
    events = []
    client.failed.connect(lambda msg: events.append(("failed", msg)))
    client.finished.connect(lambda path: events.append(("finished", path)))
    try:
        assert client.render(asdict(_long_report()), {},
                             tmp_path / "timed_out.pdf")
        assert _pump(qapp, lambda: bool(events), 20.0), "no timeout reported"
        assert events[0] == ("failed", "DUT report renderer timed out after 60 s")
        assert client.busy is False
        # the next job spawns a fresh child; the interval is back to normal
        client._timer.setInterval(60_000)
        client.render(asdict(_report()), {}, tmp_path / "recovered.pdf")
        assert _pump(qapp, lambda: len(events) == 2, 30.0), "no recovery"
        assert events[1] == ("finished", str(tmp_path / "recovered.pdf"))
        assert (tmp_path / "recovered.pdf").is_file()
    finally:
        client.shutdown()


def test_client_render_keeps_main_thread_stall_under_200ms(
        tmp_path, qapp):
    import time

    from PySide6.QtCore import QTimer

    from mtkgui.gui.render_client import ReportRenderClient

    ticks: list[float] = []
    heart = QTimer()
    heart.setInterval(10)
    heart.timeout.connect(lambda: ticks.append(time.monotonic()))
    heart.start()

    client = ReportRenderClient()
    done: list[str] = []
    client.finished.connect(done.append)
    try:
        client.render(asdict(_long_report()), {},
                      tmp_path / "responsive.pdf")
        assert _pump(qapp, lambda: bool(done), 60.0), "render did not finish"
    finally:
        heart.stop()
        client.shutdown()
    assert done[0] == str(tmp_path / "responsive.pdf")
    assert (tmp_path / "responsive.pdf").is_file()
    gaps = [later - earlier for earlier, later in zip(ticks, ticks[1:])]
    assert gaps, "the heartbeat never ticked"
    assert max(gaps) < 0.200, f"main thread stalled {max(gaps) * 1000:.0f} ms"


# -------------------------------------------------------------------- C3
def test_generate_dut_report_uses_child_process_not_a_thread(
        tmp_path, qapp, monkeypatch):
    from types import SimpleNamespace

    from mtkgui.gui import dut_pdf
    from mtkgui.main_window import MainWindow

    calls = {"render": [], "stage": [], "begin": 0, "log": []}
    page = SimpleNamespace(
        product_info=lambda: {"part": "P", "core_id": "C", "batch": "B"},
        rail_csv_path=None,
        last_report_artifact="",
        report_artifact_pending=False,
        begin_report=lambda: calls.__setitem__(
            "begin", calls["begin"] + 1))
    fake = SimpleNamespace(
        workflow_page=page,
        _report_jobs=set(),
        _report_workers=set(),
        _report_bridge=SimpleNamespace(
            stage=lambda pct, label: calls["stage"].append((pct, label))),
        _render_client=SimpleNamespace(
            render=lambda *args: calls["render"].append(args) or True),
        _append_event_log=lambda *args, **kwargs: calls["log"].append(args),
        _on_dut_pdf_done=lambda *args: None,
        _on_dut_pdf_failed=lambda *args: None,
    )
    created = []
    monkeypatch.setattr(dut_pdf, "PdfRenderWorker",
                        lambda *args, **kwargs: created.append(args))

    MainWindow._generate_dut_report_files(fake, _report())
    assert calls["begin"] == 1
    assert fake._report_workers == set()
    assert created == [], "a worker thread must not be created any more"
    assert calls["render"], "the child client must receive the job"
    report_dict, meta, path = calls["render"][0]
    assert report_dict["serial_no"] == "SN-M81-001"
    assert len(report_dict["items"]) == 4
    assert meta["part"] == "P"
    assert path.endswith(".pdf")
    assert any("DUT report: rendering" in str(entry)
               for entry in calls["log"])


# -------------------------------------------------------------------- C4
def test_report_busy_blocks_start_run(qapp, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from mtkgui.test_workflow_page import TestWorkFlowPage

    shown, logged = [], []
    monkeypatch.setattr(QMessageBox, "information",
                        lambda *args, **kwargs: shown.append(args) or 0)
    page = TestWorkFlowPage()
    monkeypatch.setattr(page, "_log", lambda text: logged.append(text))
    try:
        page.begin_report()
        assert page.report_busy is True
        assert page.btn_run.isEnabled() is False
        page.start_run()
        assert shown, "Run must warn instead of starting"
        assert shown[0][1] == "DUT Report Still Rendering"
        assert shown[0][2] == (
            "The previous DUT report is still being generated.\n"
            "Wait for it to finish before starting the next run.")
        assert logged == ["Run blocked: previous DUT report is still "
                          "rendering"]
        assert page.run_state != "running"
    finally:
        page.end_report()
        page.deleteLater()


def test_report_busy_releases_after_finish(qapp):
    from mtkgui.test_workflow_page import TestWorkFlowPage

    page = TestWorkFlowPage()
    try:
        page.begin_report()
        assert page.btn_run.isEnabled() is False
        page.end_report()
        assert page.report_busy is False
        assert page.btn_run.isEnabled() is True
        # a run that is still in progress keeps the button disabled
        page.run_state = "running"
        page.begin_report()
        page.end_report()
        assert page.btn_run.isEnabled() is False
        page.run_state = "idle"
        page.btn_run.setEnabled(True)
    finally:
        page.deleteLater()
