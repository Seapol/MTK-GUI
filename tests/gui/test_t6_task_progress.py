# -*- coding: utf-8 -*-
"""T6 long-task progress + Event-Log detail tests (GUI layer only).

Covers: staged task_progress / task_log emission from the Yaml Build
page (Excel import / publish), precise failure reasons on the Event
Log, global status-bar progress state machine in MainWindow, and the
short-task no-spam rule (export logs one line, no progress)."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from mtkgui.yaml_build_page import YamlBuildPage  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def page(qapp):
    w = YamlBuildPage()
    yield w
    w.deleteLater()


class Recorder:
    """Collect progress + log emissions in order."""

    def __init__(self, page):
        self.progress = []
        self.log = []
        page.task_progress.connect(
            lambda p, l: self.progress.append((p, l)))
        page.task_log.connect(
            lambda lvl, msg: self.log.append((lvl, msg)))


def _fill_valid_model(page):
    from tests.yamlbuild.conftest import fill_required
    from mtkgui.gui.yamlbuild.model import YamlBuildModel
    page.model = YamlBuildModel()
    page.model.enable_all()
    fill_required(page.model)


# ------------------------------------------------------------ Excel import
def test_import_emits_staged_progress_and_log(page, tmp_path,
                                              monkeypatch):
    """Successful import: start -> stage -> done (100) with Event-Log
    start / done lines."""
    from tests.yamlbuild.test_sync_excel_publish import make_model
    from mtkgui.gui.yamlbuild.excel_io import export_to_excel
    rec = Recorder(page)
    src = make_model()
    xlsx = tmp_path / "plan.xlsx"
    export_to_excel(src, str(xlsx))
    monkeypatch.setattr(
        "mtkgui.yaml_build_page.QFileDialog.getOpenFileName",
        staticmethod(lambda *a, **k: (str(xlsx), "")))
    monkeypatch.setattr(QMessageBox, "information",
                        lambda *a, **k: 0)
    page._import_excel()
    assert rec.progress[0] == (0, "import: reading workbook")
    assert rec.progress[-1][0] == 100
    levels = {lvl for lvl, _ in rec.log}
    assert "INFO" in levels
    assert any("import started" in m for _l, m in rec.log)
    assert any("import done" in m for _l, m in rec.log)


def test_import_failure_logs_row_reasons_and_resets(page, tmp_path,
                                                    monkeypatch):
    """Invalid rows: ERROR lines with the exact reasons, progress
    back to 0, model untouched."""
    import openpyxl
    rec = Recorder(page)

    def semantic():
        """State snapshot without the volatile saved_at timestamp
        (the two snapshots may straddle a second boundary under
        load)."""
        return {k: v for k, v in page.state().items()
                if k != "saved_at"}

    before = semantic()
    xlsx = tmp_path / "bad.xlsx"
    wb = openpyxl.Workbook()
    wb.save(xlsx)                       # empty workbook: invalid rows
    monkeypatch.setattr(
        "mtkgui.yaml_build_page.QFileDialog.getOpenFileName",
        staticmethod(lambda *a, **k: (str(xlsx), "")))
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: 0)
    page._import_excel()
    assert any(lvl == "ERROR" and "import rejected" in msg
               for lvl, msg in rec.log)
    assert rec.progress[-1] == (0, "import: idle")
    assert semantic() == before         # nothing applied


def test_import_no_file_no_progress_noise(page, monkeypatch):
    """Cancelling the dialog emits nothing (no idle churn)."""
    rec = Recorder(page)
    monkeypatch.setattr(
        "mtkgui.yaml_build_page.QFileDialog.getOpenFileName",
        staticmethod(lambda *a, **k: ("", "")))
    page._import_excel()
    assert rec.progress == []
    assert rec.log == []


# ---------------------------------------------------------------- publish
def test_publish_failure_logs_validation_reason(page, monkeypatch):
    """An invalid model blocks the publish with the exact reasons on
    the Event Log (no progress machinery started)."""
    rec = Recorder(page)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: 0)
    page._publish("draft")              # fresh model: validation fails
    assert any(lvl == "ERROR" and "validation" in msg
               for lvl, msg in rec.log)
    assert all(p < 100 for p, _l in rec.progress)


def test_publish_success_staged_progress(page, tmp_path, monkeypatch,
                                         qapp):
    """A valid model publishes: start -> write -> done (100) and the
    project view refreshes."""
    rec = Recorder(page)
    _fill_valid_model(page)
    monkeypatch.setattr(QMessageBox, "information",
                        lambda *a, **k: 0)
    monkeypatch.setattr(
        "mtkgui.yaml_build_page.PLANS_DIR", str(tmp_path / "plans"))
    page._publish("draft")
    assert rec.progress[0][0] == 0
    assert any(p == 50 for p, _ in rec.progress)
    assert rec.progress[-1][0] == 100
    assert any(lvl == "INFO" and "publish done" in msg
               for lvl, msg in rec.log)


def test_publish_failure_at_write_logs_reason(page, tmp_path,
                                              monkeypatch):
    """A write error (PLANS_DIR path is a file, not a directory)
    reports the exact reason and resets the progress to 0."""
    rec = Recorder(page)
    _fill_valid_model(page)
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: 0)
    monkeypatch.setattr(QMessageBox, "information",
                        lambda *a, **k: 0)
    blocker = tmp_path / "blocked"     # a FILE where a dir is required
    blocker.write_text("", encoding="utf-8")
    monkeypatch.setattr("mtkgui.yaml_build_page.PLANS_DIR",
                        str(blocker))
    page._publish("draft")
    assert any(lvl == "ERROR" and "publish failed" in msg
               for lvl, msg in rec.log)
    assert rec.progress[-1] == (0, "publish: idle")


# ------------------------------------------------- short-task no-spam
def test_export_single_log_line_no_progress(page, tmp_path,
                                            monkeypatch):
    """Export is fast: exactly one INFO line, zero progress emissions."""
    from tests.yamlbuild.test_sync_excel_publish import make_model
    rec = Recorder(page)
    page.model = make_model()
    out = tmp_path / "out.xlsx"
    monkeypatch.setattr(
        "mtkgui.yaml_build_page.QFileDialog.getSaveFileName",
        staticmethod(lambda *a, **k: (str(out), "")))
    monkeypatch.setattr(QMessageBox, "information",
                        lambda *a, **k: 0)
    page._export_excel()
    assert rec.progress == []
    assert len(rec.log) == 1
    assert rec.log[0][0] == "INFO" and "export done" in rec.log[0][1]


# --------------------------------------------- global status bar logic
def test_global_task_progress_state_machine(qapp):
    """MainWindow._on_task_progress: 0 starts with label, stages
    update, 100 completes and arms the auto-reset."""
    from mtkgui.main_window import MainWindow
    from PySide6.QtCore import Qt
    mw = MainWindow.__new__(MainWindow)   # headless: only the widgets
    from PySide6.QtWidgets import QProgressBar
    mw.status_progress = QProgressBar()
    mw._progress_reset_pending = False
    MainWindow._on_task_progress(mw, 0, "import: reading workbook")
    assert mw.status_progress.maximum() == 100
    assert mw.status_progress.value() == 0
    assert "import" in mw.status_progress.format()
    MainWindow._on_task_progress(mw, 40, "import: applying")
    assert mw.status_progress.value() == 40
    MainWindow._on_task_progress(mw, 100, "import: done")
    assert mw.status_progress.value() == 100
    assert mw._progress_reset_pending is True
    MainWindow._on_task_progress(mw, 0, "next: task")
    assert mw.status_progress.value() == 0
    assert "next: task" in mw.status_progress.format()
    mw.status_progress.deleteLater()


# --------------------------------------------- design input parse bridge
def test_design_input_parse_progress_signal(qapp, monkeypatch):
    """The Design-Input page mirrors parse progress on the global
    signal (same state machine when wired into the window)."""
    from tests.designinput.test_page import (  # noqa: E402
        NET_SAMPLE,
        SPF_SAMPLE,
    )
    from mtkgui.gui.designinput.page import DesignInputPage
    p = DesignInputPage()
    try:
        seen = []
        p.parse_progress.connect(lambda pct, lbl: seen.append((pct, lbl)))
        import tempfile
        from pathlib import Path
        tmp = Path(tempfile.mkdtemp())
        spf = tmp / "s.spf"
        spf.write_text(SPF_SAMPLE, encoding="utf-8")
        net = tmp / "b.net"
        net.write_text(NET_SAMPLE, encoding="utf-8")
        monkeypatch.setattr(
            "mtkgui.gui.designinput.page.QFileDialog.getOpenFileName",
            staticmethod(lambda *a, **k: (str(spf), "")))
        p._browse_schematic()
        monkeypatch.setattr(
            "mtkgui.gui.designinput.page.QFileDialog.getOpenFileName",
            staticmethod(lambda *a, **k: (str(net), "")))
        p._browse_net()
        p._parse_nets()
        assert seen[0][0] <= 5
        assert seen[-1] == (100, "parse: done")
        assert any(pct == 55 for pct, _lbl in seen)
    finally:
        p.deleteLater()
