# -*- coding: utf-8 -*-
"""M83 C13: the FCT Watchdog dialog explains itself."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QDialog,
    QLabel,
    QWidget,
)

from mtkgui.main_window import (  # noqa: E402
    FctWatchdogDialog,
    MainWindow,
    load_fct_watchdog_s,
    save_fct_watchdog_s,
)
from mtkgui.gui.yamlbuild import dialog_layout as dlayout  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _texts(dlg) -> str:
    return "\n".join(label.text() for label in dlg.findChildren(QLabel))


def test_m83_watchdog_dialog_shows_explanation_block(qapp):
    dlg = FctWatchdogDialog(8.0)
    text = _texts(dlg)
    assert "What it does" in text
    assert "Why it exists" in text
    assert "What it never affects" in text
    assert "Where it lives" in text
    assert "Operator message dialogs" in text
    dlg.deleteLater()


def test_m83_watchdog_dialog_zero_shows_off(qapp):
    dlg = FctWatchdogDialog(0.0)
    text = _texts(dlg)
    assert "Off — every step waits for its own Timeout" in text
    dlg.deleteLater()


def test_m83_watchdog_preview_updates_with_value(qapp):
    dlg = FctWatchdogDialog(8.0)
    assert "fails after about 8 s" in dlg.preview.text()
    dlg.spin.setValue(30.0)
    assert "fails after about 30 s" in dlg.preview.text()
    dlg.spin.setValue(0.0)
    assert dlg.preview.text().startswith("Off —")
    dlg.deleteLater()


def test_m83_watchdog_dialog_persists_value(qapp, monkeypatch, tmp_path):
    store = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    monkeypatch.setattr(
        "mtkgui.main_window.save_fct_watchdog_s",
        lambda value: save_fct_watchdog_s(value, store))
    monkeypatch.setattr(FctWatchdogDialog, "exec",
                        lambda self: QDialog.DialogCode.Accepted)
    monkeypatch.setattr(FctWatchdogDialog, "value", lambda self: 30.0)
    win = QWidget()
    win.workflow_page = SimpleNamespace(fct_watchdog_s=8.0)
    logs: list = []
    win._append_event_log = logs.append
    MainWindow._configure_fct_watchdog(win)
    assert win.workflow_page.fct_watchdog_s == 30.0
    assert load_fct_watchdog_s(store) == 30.0
    assert any("[Tools] FCT Watchdog: 30s (applies to the next run)"
               in line for line in logs)
    win.deleteLater()


def test_m83_watchdog_dialog_width_matches_form_tier(qapp):
    dlg = FctWatchdogDialog(8.0)
    assert dlg.minimumWidth() == dlg.maximumWidth() == dlayout.WIDTH_FORM
    dlg.deleteLater()
