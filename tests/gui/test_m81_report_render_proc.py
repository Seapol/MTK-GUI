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
