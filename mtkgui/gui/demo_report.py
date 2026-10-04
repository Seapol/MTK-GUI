# -*- coding: utf-8 -*-
"""P2-6 visual report & trend dashboard demo (headless-safe, rc=0).

Closed loop offscreen: P2-5 MetricsEngine records -> yield trend line,
cycle-time bars with bottleneck highlight, CpK per-batch trend, defect
TOP bars, failure classification pie, batch comparison table, filter/
refresh/reset/detail/auto-refresh.  Exit 0 = all checkpoints passed.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from mtkgui.engine.failures import FailureKind  # noqa: E402
from mtkgui.engine.metrics import MetricsEngine, TestRecord  # noqa: E402
from mtkgui.engine.results import StepStatus  # noqa: E402
from mtkgui.gui.report_page import ReportPage  # noqa: E402

T0 = datetime(2026, 10, 4, 9, 0, 0)


def rec(name, status, dur, measured=None, batch="B001", ts=None,
        kind=None):
    return TestRecord(name=name, status=status, duration_s=dur,
                      measured=measured,
                      ts=ts or T0, batch=batch, station="S1",
                      failure_kind=kind)


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    eng = MetricsEngine()

    # batch B001: three DUTs spread over the morning; one real FAIL,
    # one equipment fault (RESOURCE), one timeout
    for i, m in enumerate((3.31, 3.32, 3.30)):
        eng.add(rec("PWR 3V3 Voltage", StepStatus.PASS, 1.0 + 0.1 * i, m,
                    ts=T0 + timedelta(minutes=10 * i)))
    eng.add(rec("PWR 1V8 Voltage", StepStatus.PASS, 0.9, 1.79,
                ts=T0 + timedelta(minutes=5)))
    eng.add(rec("PWR 1V8 Voltage", StepStatus.PASS, 0.8, 1.80,
                ts=T0 + timedelta(minutes=25)))
    eng.add(rec("PWR 3V3 Voltage", StepStatus.FAIL, 1.4, 3.9,
                ts=T0 + timedelta(minutes=40)))
    eng.add(rec("Fixture Check", StepStatus.ERROR, 5.0, None,
                kind=FailureKind.RESOURCE,
                ts=T0 + timedelta(minutes=50)))
    eng.add(rec("PWR 1V8 Voltage", StepStatus.FAIL, 6.0, None,
                kind=FailureKind.TIMEOUT, ts=T0 + timedelta(minutes=60)))
    # batch B002 (afternoon): all pass
    for i, m in enumerate((3.30, 3.31)):
        eng.add(rec("PWR 3V3 Voltage", StepStatus.PASS, 1.0, m,
                    batch="B002",
                    ts=T0 + timedelta(hours=5, minutes=10 * i)))
    eng.add(rec("PWR 1V8 Voltage", StepStatus.PASS, 0.9, 1.80,
                batch="B002", ts=T0 + timedelta(hours=5, minutes=15)))

    page = ReportPage(eng)
    page.interactive = False
    page.cpk_case, page.cpk_lsl, page.cpk_usl = \
        "PWR 3V3 Voltage", 3.267, 3.333
    fired = []
    page.report_refreshed.connect(lambda n: fired.append(n))

    # 1. full refresh renders every chart
    page.refresh()
    assert fired and fired[-1] == 11, fired
    # yield trend: two time buckets (morning / afternoon) with data
    assert 0 < page.yield_chart.point_count() <= 6, "yield trend points"
    assert page.yield_chart.point_count("yield") >= 2
    # cycle bars: per-case means, bottleneck highlighted
    assert page.cycle_chart.bar_count() >= 2
    assert page.cycle_chart._highlight is not None
    assert page.cycle_chart._highlight == "Fixture Check", \
        "slowest case highlighted (equipment stall 5s)"
    # CpK trend per batch: B001 penalized by 3.9 V outlier, B002 clean
    pts = page.cpk_chart._series["cpk"]
    by_batch = dict(pts)
    assert set(by_batch) == {"B001", "B002"}, by_batch
    assert by_batch["B001"] < by_batch["B002"], "stability trend differs"
    # defect TOP: the real FAIL case ranked first
    assert page.defect_chart._items[0][0] == "PWR 3V3 Voltage"
    assert page.defect_chart._highlight == "PWR 3V3 Voltage"
    # pie: 1 product fail + RESOURCE + TIMEOUT classes
    shares = dict(page.pie_chart._items)
    assert shares.get("产品不良") == 1.0, shares
    assert shares.get("RESOURCE") == 1.0 and shares.get("TIMEOUT") == 1.0
    assert page.pie_chart.slice_count() == 3
    # batch comparison table: both batches with KPIs
    assert page.batch_table.rowCount() == 2
    header = [page.batch_table.horizontalHeaderItem(i).text()
              for i in range(4)]
    assert header == ["批次", "良率", "平均工时s", "测试数"]
    rows = {page.batch_table.item(r, 0).text():
            page.batch_table.item(r, 1).text()
            for r in range(page.batch_table.rowCount())}
    assert rows["B002"] == "100.00%", "clean batch yield"
    assert rows["B001"].endswith("%") and rows["B001"] != "100.00%"

    # 2. charts actually paint (QPainter path exercised offscreen)
    for chart in (page.yield_chart, page.cycle_chart, page.cpk_chart,
                  page.defect_chart, page.pie_chart):
        img = QImage(320, 240, QImage.Format.Format_ARGB32)
        chart.resize(320, 240)
        chart.render(img)
        assert not img.isNull(), f"{type(chart).__name__} renders"

    # 3. filter: batch combo isolates B002
    page.batch_combo.setCurrentText("B002")
    page.refresh()
    assert fired[-1] == 3, "B002 in-scope count"
    rows_b2 = page._filtered()
    assert all(r.batch == "B002" for r in rows_b2)
    # shift filter: all B002 rows are day-shift (14:00+)
    page.shift_combo.setCurrentText("night")
    page.refresh()
    assert fired[-1] == 0, "no night rows in this dataset"
    page.shift_combo.setCurrentText("day")

    # 4. reset restores 全部
    page.reset()
    assert page.batch_combo.currentText() == "全部"
    assert page.shift_combo.currentText() == "全部"
    assert fired[-1] == 11, "reset restores full dataset"

    # 5. detail view (headless: in-page text only)
    page.show_detail()
    assert "PWR 3V3 Voltage" in page.detail.toPlainText(), \
        "detail lists raw records"

    # 6. auto-refresh toggle + live data linkage
    assert not page.timer.isActive()
    page.auto_btn.setChecked(True)
    assert page.timer.isActive(), "auto refresh started"
    eng.add(rec("PWR 3V3 Voltage", StepStatus.PASS, 1.0, 3.31,
                batch="B003", ts=T0 + timedelta(hours=8)))
    page.timer.timeout.emit()          # simulate the 5s tick
    assert fired[-1] == 12, "new record counted after auto tick"
    assert page.batch_table.rowCount() == 3, "B003 appears in table"
    page.auto_btn.setChecked(False)
    assert not page.timer.isActive()

    print("[P2-6 report demo] visual report dashboard OK — yield trend, "
          "cycle-time bars with bottleneck highlight, per-batch CpK "
          "trend, defect TOP bars, classification pie, batch comparison "
          "table, filter/refresh/reset/detail/auto-refresh all validated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
