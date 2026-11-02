# -*- coding: utf-8 -*-
"""M51 §3 - Tools menu "Performance Timing Log" switch (offscreen Qt).

The checkbox reflects the SAVED setting, never the running session;
changing it persists the value and always tells the operator that a
restart is required.
"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from mtkgui import startup_timing as st  # noqa: E402
from mtkgui.main_window import MainWindow  # noqa: E402

MainWindow.__test__ = False


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_tools_perf_timing_switch(qapp, tmp_path, monkeypatch):
    store = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    old = st._SETTINGS
    st._SETTINGS = store
    monkeypatch.delenv("MTK_TIMING", raising=False)
    shown: list = []
    monkeypatch.setattr(
        QMessageBox, "information",
        staticmethod(lambda *args, **kwargs: shown.append(args)))
    session_before = st.is_enabled()
    window = MainWindow(role="Supervisor", mode="Real", fixture="ATE")
    try:
        action = window.act_perf_timing
        assert action.text() == "Performance Timing Log"
        assert action.isCheckable()
        # first run (no saved key, no MTK_TIMING=0) -> checked
        assert action.isChecked() is True
        action.setChecked(False)
        assert st.saved_enabled() is False
        assert st._as_bool(store.value(st.ENABLED_KEY)) is False
        # the running session keeps the state it started with
        assert st.is_enabled() == session_before
        assert shown, "restart information dialog was not shown"
        assert "next GUI restart" in shown[-1][2]
        action.setChecked(True)
        assert st.saved_enabled() is True
        assert len(shown) >= 2
    finally:
        window.close()
        window.deleteLater()
        st._SETTINGS = old
