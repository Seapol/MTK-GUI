# -*- coding: utf-8 -*-
"""M51 §3 / M125 - Tools menu performance timing entries (offscreen Qt).

M125 changed the contract: the probe is ON by default during
development, and the Tools toggle applies to the RUNNING session
immediately (no "restart required" dialog).  A second entry opens the
live view of the same log.
"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from mtkgui import app_paths  # noqa: E402
from mtkgui import startup_timing as st  # noqa: E402
from mtkgui.main_window import MainWindow  # noqa: E402

MainWindow.__test__ = False


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_tools_perf_timing_switch(qapp, monkeypatch):
    monkeypatch.delenv("MTK_TIMING", raising=False)
    shown: list = []
    monkeypatch.setattr(
        QMessageBox, "information",
        staticmethod(lambda *args, **kwargs: shown.append(args)))
    window = MainWindow(role="Supervisor", mode="Real", fixture="ATE")
    try:
        action = window.act_perf_timing
        assert action.isCheckable()
        assert action.text() == "Record performance timing (this session)"
        # M125: development default is ON, and the box mirrors the
        # RUNNING session, not just the saved preference
        assert action.isChecked() is True
        assert st.is_enabled() is True
        # M125: the toggle applies NOW - no restart notice at all
        action.setChecked(False)
        assert st.is_enabled() is False
        assert st.saved_enabled() is False
        assert app_paths.get_setting(st.ENABLED_KEY) is False
        action.setChecked(True)
        assert st.is_enabled() is True
        assert st.saved_enabled() is True
        assert shown == [], "M125 removed the restart dialog"
    finally:
        window.close()
        window.deleteLater()


def test_tools_show_perf_log_action(qapp):
    window = MainWindow(role="Supervisor", mode="Real", fixture="ATE")
    try:
        assert window.act_show_perf_log.text() == \
            "Show Performance Timing Log…"
        window.act_show_perf_log.trigger()
        dlg = getattr(window, "_perf_log_dialog", None)
        assert dlg is not None and dlg.isVisible()
        # same singleton on a second trigger - one window, not two
        window.act_show_perf_log.trigger()
        assert getattr(window, "_perf_log_dialog", None) is dlg
        dlg.close()
    finally:
        window.close()
        window.deleteLater()
