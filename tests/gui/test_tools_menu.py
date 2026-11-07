# -*- coding: utf-8 -*-
"""B1 final menu-baseline test: fixed top-level menu order.

M83/C14 deleted the Tools > Set all instruments batch submenu; the run
opens its own instrument rack (see tests/gui/test_m83_rack_on_run.py)."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="module")
def window():
    """One offscreen MainWindow."""
    app = QApplication.instance() or QApplication([])
    from mtkgui.main_window import MainWindow
    window = MainWindow()
    window.show()
    yield window
    window.close()


def test_fixed_menu_order(window):
    """Final standard order: File, View, Settings, Tools, Run, Report,
    Help (rightmost) - item 15 added the top-level Run menu between
    Tools and Report; stable across tab switches."""
    from PySide6.QtWidgets import QApplication
    assert [a.text() for a in window.menuBar().actions()] == \
        ["File", "View", "Settings", "Tools", "Run", "Report", "Help"]
    window.tabs.setCurrentWidget(window.yaml_build_page)
    QApplication.processEvents()
    assert [a.text() for a in window.menuBar().actions()] == \
        ["File", "View", "Settings", "Tools", "Run", "Report", "Help"]
