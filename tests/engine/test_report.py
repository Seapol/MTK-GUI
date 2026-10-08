# -*- coding: utf-8 -*-
"""Module B report tests: data model, CSV format, statistics math,
empty-report edge, and the consistency contract (report content ==
the session's Overall Result / table cells)."""
from __future__ import annotations

import csv

import pytest

from mtkgui.engine.report import (
    BatchSummary,
    DutReport,
    ReportItem,
    save_batch_csv,
    save_dut_csv,
)


def _dut(result="PASS", items=None, serial="SN001"):
    return DutReport(serial_no=serial, station_id="STATION-A",
                     user="op", overall_result=result,
                     items=items or [])


# ------------------------------------------------------------- data model
def test_dut_report_csv_rows_header_and_items():
    report = _dut(items=[ReportItem(
        test_name="Static Impedance - 3V3", category="ICT",
        measured="1.8", low="1.5", high="2.1", unit="Ω",
        result="PASS")])
    rows = report.csv_rows()
    assert rows[0][0] == "serial_no" and rows[0][-1] == "result"
    assert len(rows) == 2
    assert rows[1][4] == "Static Impedance - 3V3"
    assert rows[1][11] == "PASS"


def test_csv_file_is_well_formed(tmp_path):
    report = _dut(items=[ReportItem(test_name="t", category="FCT",
                                    result="PASS")])
    path = save_dut_csv(report, tmp_path, batch="B42")
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    assert rows[0][0] == "serial_no"
    assert rows[1][0] == "SN001"
    assert path.parent.name == report.timestamp[:10]  # day archive


def test_batch_summary_statistics_and_ranking():
    mk = lambda sn, result, fails: DutReport(
        serial_no=sn, station_id="S", user="op", overall_result=result,
        items=[ReportItem(test_name=name, category="FCT",
                          result="FAIL" if name in fails else "PASS")
               for name in ("flash", "wifi", "console")])
    summary = BatchSummary(reports=[
        mk("A", "PASS", []),
        mk("B", "FAIL", ["wifi"]),
        mk("C", "FAIL", ["wifi", "wifi"[:0] or "console"]),
    ])
    assert (summary.n_total, summary.n_pass, summary.n_fail) == (3, 1, 2)
    assert summary.yield_pct == 33.3
    ranking = summary.failures_by_item()
    assert ranking[0] == ("wifi", 2)
    assert all(count >= 1 for _name, count in ranking)


def test_batch_csv_has_stats_block(tmp_path):
    summary = BatchSummary(reports=[_dut()])
    path = save_batch_csv(summary, tmp_path)
    rows = list(csv.reader(open(path, encoding="utf-8")))
    flat = [row[0] if row else "" for row in rows]
    assert "n_total" in flat and "yield_pct" in flat
    assert "failed_item" in flat


def test_empty_report_edge():
    """No items / no reports: valid empties, yield 0, no crash."""
    report = _dut()
    assert report.csv_rows() == [list(report.csv_rows()[0])]
    summary = BatchSummary(reports=[])
    assert summary.yield_pct == 0.0 and summary.n_total == 0
    assert summary.failures_by_item() == []
    assert "0" in summary.to_html()


# ------------------------------------------------- session consistency
@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_report_matches_session_overall(qapp):
    """Consistency contract: the report built from a scripted session
    carries the SAME overall verdict the page renders."""
    from mtkgui.test_workflow_page import TestWorkFlowPage
    page = TestWorkFlowPage()
    page.ict_steps = [("test", "Static Impedance - 3V3", "Ω", "—",
                       "—", "—")]
    page.ict.setRowCount(1)
    page.ict.item(0, 7).setText("PASS")
    page.fct_rows = ["All Tests done."]
    page.fct.setRowCount(1)
    page.fct.item(0, 4).setText("PASS")
    page.result_label.setText("Virtual PASS")
    report = DutReport.from_session(page)
    assert report.overall_result == "Virtual PASS"
    assert [i.result for i in report.items] == ["PASS", "PASS"]
    assert [i.category for i in report.items] == ["ICT", "FCT"]
    page.deleteLater()


def test_pending_rows_are_skipped(qapp):
    """Pending / blank rows are NOT reported (never judged)."""
    from mtkgui.test_workflow_page import TestWorkFlowPage
    page = TestWorkFlowPage()
    page.ict_steps = [("test", "t", "V", "—", "—", "—")]
    page.ict.setRowCount(1)
    page.ict.item(0, 7).setText("Pending")
    report = DutReport.from_session(page)
    assert report.items == []
    page.deleteLater()


def test_auto_trigger_captures_counted_products(qapp):
    """B4 §8.3: run_finished(counted) appends to the session batch;
    uncounted runs (stop) do not."""
    from mtkgui.test_workflow_page import TestWorkFlowPage
    page = TestWorkFlowPage()
    window = __import__("mtkgui.main_window",
                        fromlist=["MainWindow"]).MainWindow()
    window._on_run_report_auto({"counted": True})
    window._on_run_report_auto({"counted": False})
    assert len(window._session_reports) == 1
    assert window._last_batch is not None
    page.deleteLater(); window.deleteLater()
