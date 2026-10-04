# -*- coding: utf-8 -*-
"""P2-9 report export tests (headless offscreen)."""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from mtkgui.engine.metrics import MetricsEngine, TestRecord
from mtkgui.engine.results import StepStatus
from mtkgui.gui.export_page import ExportPage
from mtkgui.gui.report_export import (build_html_report, doc_hash,
                                      export_pdf, sparkline)

T0 = datetime(2026, 10, 4, 9, 0, 0)


def rec(name, status, dur, measured=None, batch="B1", ts=None):
    return TestRecord(name=name, status=status, duration_s=dur,
                      measured=measured, ts=ts or T0, batch=batch,
                      station="S1")


@pytest.fixture()
def env():
    eng = MetricsEngine()
    eng.add(rec("A", StepStatus.PASS, 1.0, 5.0))
    eng.add(rec("A", StepStatus.PASS, 1.1, 5.1))
    eng.add(rec("B", StepStatus.FAIL, 1.2, 9.9))
    eng.add(rec("C", StepStatus.PASS, 1.0, 5.0, batch="B2"))
    app = QApplication.instance() or QApplication([])
    import tempfile
    page = ExportPage(eng, out_dir=tempfile.mkdtemp(prefix="p2_9_"))
    page.interactive = False
    return eng, page


def test_sparkline_svg_and_fallback():
    svg = sparkline([1, 3, 2, 5, 4])
    assert svg.startswith("<svg") and 'points="' in svg
    assert svg == sparkline([1, 3, 2, 5, 4]), "deterministic"
    assert "暂无趋势数据" in sparkline([1])
    assert "暂无趋势数据" in sparkline([])


def test_doc_hash_stable_and_sensitive():
    a = doc_hash({"x": 1})
    assert a == doc_hash({"x": 1}) and a != doc_hash({"x": 2})
    assert len(a) == 64


def test_html_sections_complete(env):
    eng, page = env
    html = page._html
    for need in ("指标摘要", "真实良率", "异常统计", "不良 TOP",
                 "良率趋势缩略图", "批次汇总对比", "测试明细",
                 "溯源哈希"):
        assert need in html, need
    assert "B" in html and "9.9" in html, "fail detail rendered"


def test_trace_hash_in_header_and_footer(env):
    eng, page = env
    import re
    hashes = re.findall(r"[0-9a-f]{64}", page._html)
    assert len(set(hashes)) == 1, "same hash stamped twice"
    assert hashes[0][:16] in page._html, "short form in header"


def test_pdf_export_valid(env):
    eng, page = env
    import tempfile
    out = Path(tempfile.mkdtemp(prefix="p2_9_pdf_")) / "r.pdf"
    export_pdf(page._html, out)
    raw = out.read_bytes()
    assert raw[:5] == b"%PDF-" and b"%%EOF" in raw[-2048:]
    assert len(raw) > 2000, "real content, not blank"


def test_export_html_and_signal(env):
    eng, page = env
    fired = []
    page.report_exported.connect(fired.append)
    p = page.export_html()
    assert p.is_file()
    assert p.read_text(encoding="utf-8") == page._html
    assert len(fired) == 1 and fired[0] == str(p)


def test_batch_summary_export_multi(env):
    eng, page = env
    outs = page.export_batch_summary()
    names = [p.name for p in outs]
    assert any("B1_" in n for n in names), names
    assert any("B2_" in n for n in names)
    assert any("SUMMARY" in n for n in names)
    b1 = outs[0].read_text(encoding="utf-8")
    assert "批次: <b>B1</b>" in b1, "per-batch scoping"


def test_preview_zoom_find(env):
    eng, page = env
    page.zoom(1)
    assert page.zoom_label.text() == "110%"
    page.zoom(0)
    assert page.zoom_label.text() == "100%"
    page.find_box.setText("nothing-matches-xyz")
    page.find_next()          # must not crash
    page.find_box.setText("")
    page.find_next()
