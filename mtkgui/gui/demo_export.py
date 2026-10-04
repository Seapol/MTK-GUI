# -*- coding: utf-8 -*-
"""P2-9 report export demo (headless-safe, rc=0 on success).

Closed loop: P2-5 metrics + records -> standardized HTML (header/
KPI/anomaly/trend thumbnails/batch table/detail/footer with hash) ->
PDF via QPdfWriter -> batch summary multi-export -> provenance hash
stability.  Exit 0 = all checkpoints passed.
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from mtkgui.engine.metrics import MetricsEngine, TestRecord  # noqa: E402
from mtkgui.engine.results import StepStatus  # noqa: E402
from mtkgui.gui.export_page import ExportPage  # noqa: E402
from mtkgui.gui.report_export import export_pdf, sparkline  # noqa: E402

T0 = datetime(2026, 10, 4, 9, 0, 0)


def rec(name, status, dur, measured=None, batch="B001",
        ts=None, kind=None):
    return TestRecord(name=name, status=status, duration_s=dur,
                      measured=measured, ts=ts or T0, batch=batch,
                      station="S1", failure_kind=kind)


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    eng = MetricsEngine()
    for i, m in enumerate((3.31, 3.32, 3.30)):
        eng.add(rec("PWR 3V3 Voltage", StepStatus.PASS, 1.0, m,
                    ts=T0 + timedelta(minutes=10 * i)))
    eng.add(rec("PWR 3V3 Voltage", StepStatus.FAIL, 1.4, 3.9,
                ts=T0 + timedelta(minutes=40)))
    eng.add(rec("Fixture Check", StepStatus.ERROR, 5.0,
                ts=T0 + timedelta(minutes=50)))
    for i, m in enumerate((3.30, 3.31)):
        eng.add(rec("PWR 3V3 Voltage", StepStatus.PASS, 1.0, m,
                    batch="B002",
                    ts=T0 + timedelta(hours=5, minutes=10 * i)))

    tmp = Path(tempfile.mkdtemp(prefix="p2_9_demo_"))
    page = ExportPage(eng, out_dir=tmp)
    page.interactive = False
    page.meta = {"part_number": "FRDM-IMX93", "version": "v2.0.0",
                 "revision": "1.0"}
    page.cpk_case, page.cpk_lsl, page.cpk_usl = \
        "PWR 3V3 Voltage", 3.267, 3.333
    page.refresh()

    html = page._html
    # 1. standardized sections present
    for need in ("量产测试成品报告", "FRDM-IMX93", "指标摘要", "真实良率",
                 "异常统计", "不良 TOP", "良率趋势缩略图", "<svg",
                 "CpK 趋势缩略图", "批次汇总对比", "测试明细",
                 "溯源哈希", " Fixture Check", "PWR 3V3 Voltage"):
        assert need in html, need
    assert "ERROR" in html and "FAIL" in html, "statuses rendered"
    # 2. provenance hash embedded (header 16 chars == footer prefix)
    import re
    hashes = re.findall(r"[0-9a-f]{64}", html)
    assert len(set(hashes)) == 1 and hashes[0][:16] in html, \
        "trace hash consistent header/footer"

    # 3. one-click exports
    h = page.export_html()
    assert h and h.is_file() and h.suffix == ".html"
    assert h.read_text(encoding="utf-8") == html, "lossless export"
    p = page.export_pdf_file()
    assert p and p.is_file() and p.suffix == ".pdf"
    raw = p.read_bytes()
    assert raw[:5] == b"%PDF-" and len(raw) > 2000, "valid PDF"
    assert b"%%EOF" in raw[-2048:], "PDF complete"

    # 4. batch summary multi-export (B001/B002 + merged SUMMARY)
    outs = page.export_batch_summary()
    assert outs and len(outs) == 3, outs
    b1 = outs[0].read_text(encoding="utf-8")
    assert "B001" in b1 and "批次: <b>B001</b>" in b1, "batch scoped"
    summary = outs[-1].read_text(encoding="utf-8")
    assert "批次汇总对比" in summary and "B002" in summary

    # 5. sparkline: stable output, too-few points -> fallback text
    assert sparkline([1, 2, 3, 4]) == sparkline([1, 2, 3, 4])
    assert "暂无趋势数据" in sparkline([5]), "insufficient samples"

    # 6. preview / zoom / find surface
    page.zoom(1); page.zoom(-1); page.zoom(0)
    assert page.zoom_label.text() == "100%", "zoom reset"
    page.find_box.setText("Fixture")
    page.find_next()                       # must not crash headless
    fired = []
    page.report_exported.connect(fired.append)
    page.export_html()
    assert len(fired) == 1, "export signal fired"

    print("[P2-9 export demo] commercial report OK — standardized "
          "HTML sections, trace hash, PDF export, batch summary "
          "multi-export, sparkline, preview zoom/find all validated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
