# -*- coding: utf-8 -*-
"""M104b: File + Report menu keyboard shortcuts."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtGui import QKeySequence  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def window(qapp, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "mtkgui.yaml_build_page.save_project_state",
        lambda key, state: True)
    from mtkgui.main_window import MainWindow
    MainWindow.__test__ = False
    w = MainWindow(role="Supervisor", mode="Real", fixture="ATE")
    yield w
    w.close()
    w.deleteLater()


def test_file_menu_shortcuts(window):
    assert window.act_load_yaml.shortcut().toString() == "Ctrl+O"
    assert window.act_save_yaml.shortcut().toString() == "Ctrl+S"
    assert window.act_save_yaml_as.shortcut().toString() == "Ctrl+Shift+S"


def test_report_menu_shortcuts(window):
    assert window.act_dut_report.shortcut().toString() == "Ctrl+Shift+D"
    assert window.act_report_event_log.shortcut().toString() == \
        "Ctrl+Shift+E"
    assert window.act_statistics.shortcut().toString() == "Ctrl+Shift+T"
    # the shortcuts point at the intended slots
    assert window.act_dut_report.text() == "DUT Report"
    assert window.act_report_event_log.text() == "Event Log Folder…"
    assert window.act_statistics.text() == "Statistics"
    assert window.act_dut_report.shortcut() == QKeySequence("Ctrl+Shift+D")
