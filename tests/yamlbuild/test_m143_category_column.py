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
        V2NetRow(name="CLK_24M", category="SE Clock", sub_type="24MHz"),
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

    The header font is a platform metric (the section is pinned to 10 px by
    the sheet's style sheet), so the test asks for the rendered text plus a
    fixed allowance for the arrow rather than the combo's own size hint -
    that hint also carries the style's icon room and is not what the cell
    actually needs.
    """
    panel = _panel(qapp)
    try:
        metrics = QFontMetrics(panel.table.horizontalHeader().font())
        needed = max(metrics.horizontalAdvance(category)
                     for category in V2_CATEGORIES)
        for table in (panel.table, panel.table_other):
            width = table.columnWidth(1)
            combos = table.findChildren(QComboBox)
            assert combos, "the Category column must host a combo box"
            assert width >= needed + 16, (
                f"Category column {width} px cannot show '{max(
                    V2_CATEGORIES, key=len)}' ({needed} px) plus the "
                "drop-down arrow")
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
