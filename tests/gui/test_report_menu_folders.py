# -*- coding: utf-8 -*-
"""2026-10-17 Report-menu rework: every counted run generates its DUT
report immediately; the Report menu items OPEN the output folders
(DUT Report / Event Log / DAQ CSV Data) whose names are modifiable;
the progress bar carries the elapsed run time and the Event Log shows
the run process (started / finished lines)."""
from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from mtkgui import report_paths  # noqa: E402


@pytest.fixture()
def report_home(tmp_path, monkeypatch):
    """Redirect the report root into a tmp dir (env override)."""
    monkeypatch.setenv("MTKGUI_REPORT_HOME", str(tmp_path))
    return tmp_path


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


# ------------------------------------------------------------ paths
def test_default_folders_next_to_program(report_home):
    assert report_paths.dut_folder() == report_home / "DUT Report"
    assert report_paths.event_folder() == report_home / "Event Report"
    # DAQ CSV lives under the SAME root as the DUT reports
    assert report_paths.daq_folder() == \
        report_home / "DUT Report" / "DAQ CSV"


def test_folder_names_roundtrip(report_home):
    report_paths.set_folder_names("My Reports", "My Logs")
    assert report_paths.dut_folder() == report_home / "My Reports"
    assert report_paths.event_folder() == report_home / "My Logs"
    assert report_paths.daq_folder() == \
        report_home / "My Reports" / "DAQ CSV"
    assert (report_home / report_paths.CFG_NAME).is_file()
    # blank names fall back to the defaults, never to an empty path
    report_paths.set_folder_names("  ", "")
    assert report_paths.dut_folder() == report_home / "DUT Report"
    assert report_paths.event_folder() == report_home / "Event Report"


# ------------------------------------------------------------- menu
def _window():
    from mtkgui.main_window import MainWindow
    return MainWindow()


def test_report_menu_opens_folders(qapp, report_home):
    w = _window()
    labels = [a.text() for a in w.report_menu.actions()]
    assert labels[:4] == ["DUT Report", "Event Log", "DAQ CSV Data",
                          "Report Folder…"]
    # the folder openers create the folders on demand
    w._open_daq_csv_folder()
    assert (report_home / "DUT Report" / "DAQ CSV").is_dir()
    w.deleteLater()


# ------------------------------------------------- auto report files
def _finish_session(page):
    from PySide6.QtWidgets import QTableWidgetItem

    def _cell(table, r, c, text):
        it = table.item(r, c)
        if it is None:
            it = QTableWidgetItem()
            table.setItem(r, c, it)
        it.setText(text)

    page.ict_steps = [("test", "DCDC_1V0", "V", "—", "3.2", "3.4")]
    page.ict.setRowCount(1)
    _cell(page.ict, 0, 7, "PASS")
    page.fct_rows = ["All Tests done."]
    page.fct.setRowCount(1)
    _cell(page.fct, 0, 4, "PASS")
    page.result_label.setText("PASS")


def test_counted_run_generates_report_files(qapp, report_home):
    w = _window()
    _finish_session(w.workflow_page)
    w._on_run_report_auto({"counted": True})
    day = report_paths.dut_folder() / __import__("datetime").datetime \
        .now().strftime("%Y-%m-%d")
    pdfs = list(day.glob("DUT_PASS_*.pdf"))
    csvs = list(day.glob("*_*.csv"))
    assert pdfs and csvs, f"missing files under {day}"
    assert pdfs[0].read_bytes()[:4] == b"%PDF"
    # the Event Log shows the process
    log = w.event_log.toPlainText()
    assert "DUT report generated" in log
    w.deleteLater()


def test_uncounted_run_generates_nothing(qapp, report_home):
    w = _window()
    _finish_session(w.workflow_page)
    w._on_run_report_auto({"counted": False})
    assert not report_paths.dut_folder().exists()
    w.deleteLater()


# -------------------------------------------- progress bar + process
def test_progress_bar_carries_elapsed_time(qapp, report_home):
    w = _window()
    w._update_run_progress(2, 10)
    fmt = w.status_progress.format()
    assert fmt.startswith("2/10 (20%)")
    assert "·" in fmt                       # the elapsed section
    assert w._run_started_at is not None
    # the Event Log shows the run process
    assert "Test run started (10 steps)" in w.event_log.toPlainText()
    # idle progress (0 total) must NOT start a run
    w._finish_run_progress()
    assert w._run_started_at is None
    assert "Test run finished · elapsed" in w.event_log.toPlainText()
    w.deleteLater()


def test_finish_without_run_keeps_plain_complete(qapp, report_home):
    """The yaml-build long tasks share the finish handler: without a
    run clock there is no elapsed section and no process line."""
    w = _window()
    w._finish_run_progress()
    assert w.status_progress.format() == "Complete (100%)"
    assert "Test run finished" not in w.event_log.toPlainText()
    w.deleteLater()


# ------------------------------------------------------- DAQ CSV path
def test_daq_csv_lands_under_dut_root(qapp, report_home):
    from mtkgui.test_workflow_page import TestWorkFlowPage
    page = TestWorkFlowPage()
    page.set_rails([("VDD_3V3", "#38bdf8", 3.3, 0.0)])
    path = page._write_csv([[0.0, 0.5, 1.0]])
    assert path.parent == report_home / "DUT Report" / "DAQ CSV"
    assert path.is_file() and path.name.startswith("power_rails")
    page.deleteLater()
