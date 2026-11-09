# -*- coding: utf-8 -*-
"""M96 report folders: every counted run generates its DUT report
immediately; the Report menu items OPEN the output folders (DUT Report /
Event Log) and the folder configuration lives in
Settings > Report Folders… (reports root + Browse, two sub-folder names,
one tree per project).  Settings travel in the work folder, so a
package upgrade keeps them."""
from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from mtkgui import report_paths  # noqa: E402


@pytest.fixture()
def report_home(tmp_path, monkeypatch):
    """Redirect the report root AND the settings file into a tmp dir."""
    monkeypatch.setenv("MTKGUI_REPORT_HOME", str(tmp_path / "reports"))
    monkeypatch.setenv("MTKGUI_WORK_DIR", str(tmp_path / "work"))
    monkeypatch.setenv("MTKGUI_PROJECT", "96317")
    report_paths.set_current_project("")
    return tmp_path / "reports"


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


# ------------------------------------------------------------ paths
def test_default_folders_one_tree_per_project(report_home):
    assert report_paths.dut_folder() == \
        report_home / "96317" / "DUT Report"
    assert report_paths.event_folder() == \
        report_home / "96317" / "Event Report"


def test_env_override_is_the_default_root(report_home):
    """Nothing saved: MTKGUI_REPORT_HOME supplies the root."""
    assert report_paths.report_root() == report_home
    assert report_paths.dut_folder() == report_home / "96317" / "DUT Report"
    assert report_paths.event_folder() == report_home / "96317" / "Event Report"


def test_unsaved_root_defaults_to_the_work_folder(monkeypatch, tmp_path):
    """W2-1: nothing saved and no MTKGUI_REPORT_HOME -> the station work
    folder, so a package re-deploy keeps the reports next to the settings."""
    monkeypatch.delenv("MTKGUI_REPORT_HOME", raising=False)
    monkeypatch.delenv("MTKGUI_PROJECT", raising=False)
    monkeypatch.setenv("MTKGUI_WORK_DIR", str(tmp_path / "work"))
    report_paths.set_current_project("")
    assert report_paths.report_root() == tmp_path / "work"
    assert report_paths.event_folder() == \
        tmp_path / "work" / report_paths.NO_PROJECT / "Event Report"
    assert report_paths.dut_folder() == \
        tmp_path / "work" / report_paths.NO_PROJECT / "DUT Report"


def test_folder_settings_roundtrip(report_home, tmp_path):
    """Root + both names persist into the work folder and take effect."""
    chosen = tmp_path / "chosen root"
    cfg = report_paths.set_folder_settings(str(chosen), "My Reports", "My Logs")
    assert cfg == tmp_path / "work" / report_paths.CFG_NAME
    assert cfg.is_file()
    assert report_paths.dut_folder() == chosen / "96317" / "My Reports"
    assert report_paths.event_folder() == chosen / "96317" / "My Logs"
    # a saved root wins over the environment default (Browse is effective)
    assert report_paths.report_root() == chosen


def test_bad_names_and_blank_root_fall_back(report_home, tmp_path):
    """A typo must never move the output: separators / '..' / blank = default."""
    report_paths.set_folder_settings(str(tmp_path / "x"), "../escape",
                                     "sub/dir")
    assert report_paths.dut_folder().name == report_paths.DEFAULT_DUT
    assert report_paths.event_folder().name == report_paths.DEFAULT_EVENT
    # blank root = unsaved -> back to the environment default
    report_paths.set_folder_settings("", "", "")
    assert report_paths.report_root() == report_home
    assert report_paths.dut_folder() == report_home / "96317" / "DUT Report"


def test_project_key_env_and_loaded_project(report_home, monkeypatch):
    """<PROJECT>: MTKGUI_PROJECT wins, else the loaded project's folder."""
    assert report_paths.project_key() == "96317"          # from the env
    monkeypatch.delenv("MTKGUI_PROJECT")
    assert report_paths.project_key() == report_paths.NO_PROJECT
    report_paths.set_current_project("P002-MTK")
    assert report_paths.project_key() == "P002-MTK"
    assert report_paths.dut_folder() == report_home / "P002-MTK" / "DUT Report"
    # a yaml's project label comes from its folder, not from a generic one
    assert report_paths.project_label_for(
        "/srv/work/projects/96317/plan.yaml") == "96317"
    assert report_paths.project_label_for(
        "/srv/app/config/plans/plan_96317.yaml") == "plan_96317"
    assert report_paths.project_label_for(None) == ""
    report_paths.set_current_project("")


def test_legacy_report_folders_json_is_ignored(report_home, tmp_path):
    """M96: the old beside-the-exe override must not redirect anything."""
    legacy = report_paths.program_dir() / "report_folders.json"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text('{"dut": "My Reports", "event": "My Logs"}',
                      encoding="utf-8")
    try:
        assert report_paths.dut_folder() == report_home / "96317" / "DUT Report"
        assert report_paths.event_folder() == report_home / "96317" / "Event Report"
        for gone in ("folder_names", "set_folder_names", "_names"):
            assert not hasattr(report_paths, gone), gone
    finally:
        legacy.unlink()


# ------------------------------------------------------------- menu
def _window():
    from mtkgui.main_window import MainWindow
    return MainWindow()


def test_report_menu_labels_and_folders(qapp, report_home):
    w = _window()
    labels = [a.text() for a in w.report_menu.actions()]
    # M96: 'DAQ CSV Data' (duplicate of DUT Report) and the rename dialog
    # are gone; the folder configuration now lives in Settings.
    assert labels[:3] == ["DUT Report", "Event Log", "Statistics"]
    assert "DAQ CSV Data" not in labels
    assert not any(text.startswith("Report Folder") for text in labels)
    assert labels[-1].startswith("SharePoint Upload")
    assert not hasattr(w, "_open_daq_csv_folder")
    assert not hasattr(w, "_open_report_folder_settings")
    settings_labels = [a.text() for a in w.settings_menu.actions()]
    assert any(text.startswith("Report Folders") for text in settings_labels)
    # the folder openers create the folders on demand
    w._open_dut_report_folder()
    assert (report_home / "96317" / "DUT Report").is_dir()
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
    from PySide6.QtTest import QTest
    w = _window()
    _finish_session(w.workflow_page)
    w._on_run_report_auto({"counted": True})
    # the START is announced immediately in the Event Log...
    log = w.event_log.toPlainText()
    assert "DUT report generating" in log
    # ...while the (heavy) rendering is deferred onto the worker thread
    assert not list(report_paths.dut_folder().rglob("*.pdf"))
    # fire the deferred generation (what the singleShot would do) and
    # wait for the worker thread to finish the PDF (the completion log
    # line is emitted after QPrinter flushed the file)
    w._generate_dut_report_files(w._session_reports[-1])
    deadline = 15_000
    while "DUT report generated" not in w.event_log.toPlainText() \
            and deadline > 0:
        QTest.qWait(100)
        deadline -= 100
    # 2026-10-17 identity naming: the report lives in a per-DUT folder
    # whose name carries Part# / Core ID / Batch# / Serial# / timestamp
    pdfs = list(report_paths.dut_folder().rglob("DUT_PASS_*.pdf"))
    csvs = list(report_paths.dut_folder().rglob("DUT_detail_*.csv"))
    assert pdfs and csvs, "missing identity-named report files"
    run_dir = pdfs[0].parent
    assert run_dir.name.startswith("NA_NA_freebatch_DUT_2026")
    assert run_dir == csvs[0].parent          # report + detail csv together
    assert pdfs[0].read_bytes()[:4] == b"%PDF"
    # the Event Log shows the process
    assert "DUT report generated" in w.event_log.toPlainText()
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
def test_daq_csv_lands_in_identity_folder(qapp, report_home):
    """2026-10-17 identity naming: the DAQ capture lives in its own
    identity folder under the DUT Report root - folder AND file name
    carry Part# / Core ID / Batch# / Serial#."""
    from mtkgui.test_workflow_page import TestWorkFlowPage
    page = TestWorkFlowPage()
    page.set_rails([("VDD_3V3", "#38bdf8", 3.3, 0.0)])
    path = page._write_csv([[0.0, 0.5, 1.0]])
    assert path.parent.parent == report_paths.dut_folder()
    # product_info defaults: part/core empty -> NA, batch -> freebatch
    assert path.parent.name.startswith("NA_NA_freebatch_DUT_2026")
    assert path.name.startswith("power_rails_NA_NA_freebatch_DUT_")
    assert path.is_file()
    page.deleteLater()


# ------------------------------------------------- report settings dialog
def test_report_settings_dialog_saves_and_previews(qapp, report_home, tmp_path):
    from mtkgui.gui.report_settings_dialog import ReportFoldersDialog

    dlg = ReportFoldersDialog()
    assert dlg.root_edit.text() == str(report_home)
    assert dlg.dut_edit.text() == report_paths.DEFAULT_DUT
    # the preview shows the resolved absolute paths
    assert dlg.project_label.text() == "96317"
    assert str(report_home / "96317" / "DUT Report") in dlg.preview.text()
    chosen = tmp_path / "browsed"
    dlg.root_edit.setText(str(chosen))          # what Browse fills in
    dlg.dut_edit.setText("Certificates")
    assert str(chosen / "96317" / "Certificates") in dlg.preview.text()
    dlg._save()
    assert dlg.result() == 1                     # accepted
    assert report_paths.dut_folder() == chosen / "96317" / "Certificates"
    assert (report_paths.event_folder()
            == chosen / "96317" / report_paths.DEFAULT_EVENT)
    dlg.deleteLater()


def test_default_root_follows_the_env_then_the_work_folder(monkeypatch, tmp_path):
    """W2-1b: the default root is the env override, else the work folder."""
    monkeypatch.delenv("MTKGUI_REPORT_HOME", raising=False)
    monkeypatch.setenv("MTKGUI_WORK_DIR", str(tmp_path / "work"))
    assert report_paths.default_root() == tmp_path / "work"
    monkeypatch.setenv("MTKGUI_REPORT_HOME", str(tmp_path / "reports"))
    assert report_paths.default_root() == tmp_path / "reports"


def test_blank_root_preview_and_restore_follow_the_default_root(qapp, report_home):
    """W2-1b: a blank root, and 'Restore defaults', point at the default root
    - never at the program directory, which a re-deploy wipes."""
    import json
    from mtkgui.gui.report_settings_dialog import ReportFoldersDialog

    dlg = ReportFoldersDialog()
    dlg.root_edit.clear()
    assert str(report_home) in dlg.preview.text()
    assert str(report_paths.program_dir()) not in dlg.preview.text()
    dlg._restore()
    assert dlg.root_edit.text() == ""            # blank = default, nothing pinned
    assert str(report_home) in dlg.preview.text()
    dlg._save()
    cfg = report_home.parent / "work" / "report_paths.json"
    assert json.loads(cfg.read_text(encoding="utf-8"))["root"] == ""
    assert report_paths.report_root() == report_home
    dlg.deleteLater()
