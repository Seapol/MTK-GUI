# -*- coding: utf-8 -*-
"""M10-FIX2 - GUI polish regressions (F1..F7).

Offscreen Qt only: dialog sizes, default table column widths, the
console port combo policy, block-card minimums and the first-click tab
switch.  Rendering itself is verified manually (P2 checklist).
"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from mtkgui.gui.sharepoint_upload_dialog import (  # noqa: E402
    SharePointUploadDialog,
)
from mtkgui.gui.yamlbuild.block_flow import BlockCard  # noqa: E402
from mtkgui.gui.yamlbuild.blocks import BlockConfigDialog  # noqa: E402
from mtkgui.gui.yamlbuild.parse_nets import ParseNetsPanel  # noqa: E402
from mtkgui.main_window import MainWindow  # noqa: E402
from mtkgui.permissions import ROLE_SUPERVISOR  # noqa: E402
from mtkgui.widgets.multi_console import ChannelRow  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


# ------------------------------------------------------------------ F2
def test_parsed_nets_default_column_widths(qapp):
    panel = ParseNetsPanel()
    try:
        assert [panel.table.columnWidth(i) for i in range(6)] == \
            [180, 240, 90, 90, 90, 90]
        assert panel.table.columnWidth(6) >= 100
        assert [panel.table_filtered.columnWidth(i) for i in range(2)] == \
            [300, 300]
        assert panel.table_filtered.columnWidth(2) >= 100
        # the empty-state header has no blank band on the right
        assert panel.table.horizontalHeader().stretchLastSection() is True
        assert panel.table_filtered.horizontalHeader().stretchLastSection() \
            is True
        # the empty table is sizeable, not force-stretched by a star column
        assert panel.table.horizontalHeader().sectionResizeMode(0) \
            == panel.table.horizontalHeader().ResizeMode.Interactive
    finally:
        panel.deleteLater()


# ------------------------------------------------------------------ F1
def test_parse_nets_dialog_initial_size(qapp):
    dlg = BlockConfigDialog("parse_ict", {})
    try:
        assert (dlg.width(), dlg.height()) == (1060, 780)
        assert dlg.property("_dlg_enlarged") is True
        assert dlg.nets_panel.table.minimumHeight() <= 120
        assert dlg.nets_panel.table.sizePolicy().verticalPolicy() \
            == dlg.nets_panel.table.sizePolicy().Policy.Expanding
        assert dlg.nets_panel.table_filtered.maximumHeight() <= 200
    finally:
        dlg.deleteLater()


# ------------------------------------------------------------------ F3
def test_design_input_dialog_is_compact(qapp):
    dlg = BlockConfigDialog("design_input", {})
    try:
        assert (dlg.width(), dlg.height()) == (600, 540)
        assert dlg.property("_dlg_enlarged") is True
        assert dlg.minimumWidth() == 560
    finally:
        dlg.deleteLater()


# ------------------------------------------------------------------ F4
def test_sharepoint_dialog_is_bounded(qapp, tmp_path):
    dlg = SharePointUploadDialog(
        None, virtual=True, config_path=tmp_path / "cfg.json",
        state_dir=tmp_path / "state")
    try:
        assert (dlg.width(), dlg.height()) == (720, 560)
        assert (dlg.maximumWidth(), dlg.maximumHeight()) == (720, 680)
        # long status lines wrap instead of inflating the size hint
        assert dlg.conn_status.wordWrap() is True
        assert dlg.signin_status.wordWrap() is True
    finally:
        dlg.deleteLater()


# ------------------------------------------------------------------ F5
def test_serial_port_combo_takes_the_row_slack(qapp):
    from PySide6.QtWidgets import QSizePolicy
    row = ChannelRow("ch1", "serial", "COM1", "#4caf50", {})
    try:
        assert row.combo_port.minimumWidth() >= 180
        assert row.combo_port.sizePolicy().horizontalPolicy() \
            == QSizePolicy.Policy.Expanding
        assert row.combo_baud.maximumWidth() == 100
        row.resize(900, 40)
        row.show()
        qapp.processEvents()
        assert row.combo_port.width() > 180
    finally:
        row.deleteLater()


# ------------------------------------------------------------------ F6
def test_block_cards_have_a_readable_minimum(qapp):
    from mtkgui.gui.yamlbuild.block_flow import WORKFLOW_DISPLAY_STAGES
    card = BlockCard(WORKFLOW_DISPLAY_STAGES[0], 0)
    try:
        assert card.minimumWidth() >= 120
    finally:
        card.deleteLater()


# ------------------------------------------------------------------ F7
def test_each_tab_switches_on_the_first_click(qapp):
    window = MainWindow(role=ROLE_SUPERVISOR)
    try:
        window.show()
        qapp.processEvents()
        bar = window.tabs.tabBar()
        pages = [window.workflow_page, window.equipment_page,
                 window.yaml_build_page]
        order = [2, 1, 0, 2]
        for index in order:
            if not bar.isTabVisible(index):
                continue
            QTest.mouseClick(bar, Qt.MouseButton.LeftButton,
                             pos=bar.tabRect(index).center())
            qapp.processEvents()
            assert window.tabs.currentIndex() == index
            assert window.tabs.currentWidget() is pages[index]
        # clicking the current tab is a harmless no-op
        window._on_tab_clicked(window.tabs.currentIndex())
        assert window.tabs.currentWidget() is pages[window.tabs.currentIndex()]
    finally:
        window.close()
        window.deleteLater()
