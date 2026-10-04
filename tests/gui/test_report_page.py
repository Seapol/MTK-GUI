# -*- coding: utf-8 -*-
"""P2-6 visual report dashboard unit tests (headless offscreen)."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from mtkgui.engine.failures import FailureKind
from mtkgui.engine.metrics import MetricsEngine, TestRecord
from mtkgui.engine.results import StepStatus
from mtkgui.gui.charts import BarChart, LineChart, PieChart
from mtkgui.gui.report_page import ReportPage

T0 = datetime(2026, 10, 4, 9, 0, 0)


def rec(name, status, dur=1.0, measured=None, batch="B1", ts=T0,
        kind=None):
    return TestRecord(name=name, status=status, duration_s=dur,
                      measured=measured, ts=ts, batch=batch,
                      station="S1", failure_kind=kind)


@pytest.fixture()
def env():
    eng = MetricsEngine()
    eng.records.extend([
        rec("A", StepStatus.PASS, 2.0, 5.0),
        rec("A", StepStatus.PASS, 2.2, 5.1,
            ts=T0 + timedelta(minutes=30)),
        rec("B", StepStatus.FAIL, 4.0, 9.0, ts=T0 + timedelta(minutes=10)),
        rec("C", StepStatus.ERROR, 3.0, kind=FailureKind.RESOURCE,
            ts=T0 + timedelta(minutes=20)),
        rec("A", StepStatus.PASS, 1.0, 5.0, batch="B2",
            ts=T0 + timedelta(hours=6)),
        rec("A", StepStatus.PASS, 1.1, 5.0, batch="B2",
            ts=T0 + timedelta(hours=6, minutes=10)),
    ])
    page = ReportPage(eng)
    page.interactive = False
    return page, eng


# ------------------------------------------------------------ charts
def test_line_chart_series_management():
    chart = LineChart("t")
    chart.set_series("s1", [("a", 1.0), ("b", 2.0)])
    assert chart.point_count("s1") == 2 and chart.point_count() == 2
    chart.add_series("s2", [("a", 3.0)])
    assert chart.point_count() == 3
    chart.set_series("s1", [])  # replace not append
    assert chart.point_count("s1") == 0 and chart.point_count() == 1


def test_bar_chart_highlight():
    chart = BarChart("t")
    chart.set_data([("slow", 9.0), ("fast", 1.0)], highlight="slow")
    assert chart.bar_count() == 2 and chart._highlight == "slow"
    chart.set_data([])
    assert chart.bar_count() == 0


def test_pie_chart_zero_slices_dropped():
    chart = PieChart("t")
    chart.set_data([("A", 3.0), ("B", 0.0)])
    assert chart.slice_count() == 1, "zero-value slices removed"
    chart.set_data([])
    assert chart.slice_count() == 0


def test_charts_paint_offscreen(qapp):
    from PySide6.QtGui import QImage
    widgets = [LineChart("l"), BarChart("b"), PieChart("p")]
    widgets[0].set_series("s", [("a", 1.0), ("b", 2.0)])
    widgets[1].set_data([("x", 1.0)])
    widgets[2].set_data([("x", 1.0)])
    for w in widgets:
        img = QImage(200, 150, QImage.Format.Format_ARGB32)
        w.resize(200, 150)
        w.render(img)
        assert not img.isNull()


# ------------------------------------------------------------- page
def test_page_initial_refresh_and_signal(env):
    page, _eng = env
    assert page.report_refreshed is not None
    # fixture page refreshed once in __init__: 5 in-scope records
    assert page.batch_combo.count() == 3  # 全部 + B1 + B2


def test_page_yield_trend_buckets(env):
    page, _eng = env
    page.refresh()
    pts = page.yield_chart._series.get("yield", [])
    assert pts, "yield trend has points"
    assert all(0.0 <= v <= 1.0 for _l, v in pts), "yield in [0,1]"


def test_page_cycle_bottleneck_highlight(env):
    page, _eng = env
    page.refresh()
    assert page.cycle_chart._highlight == "B", \
        "slowest case highlighted"
    items = dict(page.cycle_chart._items)
    assert items["B"] >= items["A"], "bars sorted by duration"


def test_page_defect_top_and_pie(env):
    page, _eng = env
    page.refresh()
    assert page.defect_chart._items[0][0] == "B"
    shares = dict(page.pie_chart._items)
    assert shares.get("产品不良") == 1.0
    assert shares.get("RESOURCE") == 1.0


def test_page_cpk_trend_requires_config(env):
    page, _eng = env
    page.refresh()
    assert page.cpk_chart.point_count() == 0, "unconfigured -> empty"
    page.cpk_case, page.cpk_lsl, page.cpk_usl = "A", 4.5, 5.5
    page.refresh()
    pts = dict(page.cpk_chart._series["cpk"])
    assert set(pts) == {"B1"}, \
        "B2 zero-dispersion (inf) trend point excluded"


def test_page_batch_compare_table(env):
    page, _eng = env
    page.refresh()
    assert page.batch_table.rowCount() == 2
    rows = {page.batch_table.item(r, 0).text():
            (page.batch_table.item(r, 1).text(),
             page.batch_table.item(r, 3).text())
            for r in range(2)}
    assert rows["B2"][0] == "100.00%"
    assert rows["B1"][1] == "4"


def test_page_filters_and_reset(env):
    page, eng = env
    fired = []
    page.report_refreshed.connect(fired.append)
    page.batch_combo.setCurrentText("B2")
    page.refresh()
    assert all(r.batch == "B2" for r in page._filtered())
    page.batch_combo.setCurrentText("全部")
    page.shift_combo.setCurrentText("night")
    page.refresh()
    assert page._filtered() == [], "no night records"
    # live data linkage: add a night record -> filter now matches
    eng.add(rec("N", StepStatus.PASS, 1.0, batch="B3",
                ts=datetime(2026, 10, 4, 23, 0)))
    page.refresh()
    assert len(page._filtered()) == 1
    page.reset()
    assert page.batch_combo.currentText() == "全部"
    assert page.shift_combo.currentText() == "全部"
    assert len(page._filtered()) == 7


def test_page_detail_view_headless(env):
    page, _eng = env
    page.show_detail()
    text = page.detail.toPlainText()
    assert "A" in text and "PASS" in text, "raw records listed"
    assert page.interactive is False, "no modal in headless mode"


def test_page_auto_refresh_toggle(env):
    page, eng = env
    assert not page.timer.isActive()
    page.auto_btn.setChecked(True)
    assert page.timer.isActive()
    assert "开" in page.auto_btn.text()
    eng.add(rec("A", StepStatus.PASS, 1.0, batch="B9"))
    page.timer.timeout.emit()
    assert page.batch_table.rowCount() == 3, "B9 appears after tick"
    page.auto_btn.setChecked(False)
    assert not page.timer.isActive()


def test_shell_registers_real_report_page(qapp):
    from mtkgui.gui.shell import MainWindow
    win = MainWindow(baseline_version="test")
    win.mount_default_routes()
    assert "reports" in win.route_keys
    win.navigate("reports")
    assert "reports" in win.cached_pages
    from mtkgui.gui.report_page import ReportPage
    assert isinstance(win._pages["reports"], ReportPage)
    assert win.metrics_engine is not None
