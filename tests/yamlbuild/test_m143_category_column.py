# -*- coding: utf-8 -*-
"""M143: node 02 keeps the Category values readable with real data.

The Category cell is a QComboBox.  A column sized from the header text
alone clipped every value to "Po" / "Ot" once a netlist filled the table,
so the column now reserves the widest category plus the drop-down arrow.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtGui import QFontMetrics  # noqa: E402
from PySide6.QtWidgets import QApplication, QComboBox  # noqa: E402

from mtkgui.gui.yamlbuild.parse_nets_v2 import (  # noqa: E402
    V2_CATEGORIES,
    V2NetRow,
    V2ParseState,
)
from mtkgui.gui.yamlbuild.parse_nets_v2_panel import (  # noqa: E402
    ParseNetsV2Panel,
)

PANEL_WIDTH = 1194  # the width node 02 gets inside a 1216 px dialog


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _state() -> V2ParseState:
    rows = [
        V2NetRow(name="VDD_1V8", category="Power", sub_type="1V8"),
        V2NetRow(name="CLK_24M", category="SE Clock", sub_type="clock_single"),
        V2NetRow(name="GND", category="GND", sub_type="ground"),
        V2NetRow(name="GPIO0", category="Other", sub_type="signal"),
    ]
    return V2ParseState(rows=rows)


def _panel(qapp) -> ParseNetsV2Panel:
    panel = ParseNetsV2Panel()
    panel.resize(PANEL_WIDTH, 560)
    panel.set_state(_state())
    panel.show()
    panel.layout().activate()
    qapp.processEvents()
    panel._fit_columns()
    for _ in range(3):
        qapp.processEvents()  # let the scroll area settle after the widths land
    return panel


def test_category_column_fits_the_combo(qapp):
    """The column must show the longest category plus its arrow.

    The header font varies per platform and per test app, so the test pins a
    plain pixel floor instead of deriving one from the font.
    """
    panel = _panel(qapp)
    try:
        for table in (panel.table, panel.table_other):
            width = table.columnWidth(1)
            combos = table.findChildren(QComboBox)
            assert combos, "the Category column must host a combo box"
            # 80 px holds "SE Clock" in the shipped 10 px header with the
            # drop-down arrow beside it; below that the combo clips the value
            # to its first letter (seen at 66 px on the bench).
            assert width >= 80, (
                f"Category column {width} px cannot show the longest "
                "category plus the drop-down arrow")
    finally:
        panel.deleteLater()


def test_columns_end_flush_with_no_horizontal_bar(qapp):
    panel = _panel(qapp)
    try:
        for table in (panel.table, panel.table_other):
            viewport = table.viewport().width()
            total = sum(table.columnWidth(column)
                        for column in range(table.columnCount()))
            assert total == viewport, (
                f"columns sum to {total} px inside a {viewport} px viewport")
            header = table.horizontalHeader().length()
            assert header <= viewport, (
                f"header needs {header} px inside a {viewport} px viewport")
            assert not table.horizontalScrollBar().isVisible()
    finally:
        panel.deleteLater()


def test_sub_type_column_fits_its_longest_value(qapp):
    """A label column sizes to its widest value, not to its header."""
    panel = _panel(qapp)
    try:
        metrics = QFontMetrics(panel.table.font())
        longest = "clock_single"
        needed = metrics.horizontalAdvance(longest)
        for table in (panel.table, panel.table_other):
            values = [table.item(row, 2).text()
                      for row in range(table.rowCount())
                      if table.item(row, 2) is not None]
            if longest not in values:
                continue
            assert table.columnWidth(2) >= needed, (
                f"Sub-type column {table.columnWidth(2)} px cannot show "
                f"'{longest}' ({needed} px)")
    finally:
        panel.deleteLater()
