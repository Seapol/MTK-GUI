# -*- coding: utf-8 -*-
"""M0 Overall-Flow stage table layout tests: column widths on the
0-1000 grid, Status >= "Pending..." text width, centered headers,
right-edge auto-fit (mock, offscreen)."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QFontMetrics  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QHeaderView,
)

from mtkgui.test_workflow_page import TestWorkFlowPage  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def page(qapp):
    w = TestWorkFlowPage()
    w.resize(760, 900)
    yield w
    w.deleteLater()


def test_column_widths_on_grid(page):
    """# ~30 / Stage ~90 / EN ~50 / Status ~200 / Duration >= 200
    (the M0 0-1000 grid)."""
    t = page.overall
    assert t.columnWidth(0) == 30                    # #
    assert t.columnWidth(1) == 90                    # Stage (compact)
    assert t.columnWidth(2) == 50                    # EN
    assert t.columnWidth(3) == 200                   # Status (wide)
    assert t.columnWidth(4) >= 200                   # Duration


def test_status_column_fits_pending_text(page):
    """Status column width >= the rendered width of 'Pending...' at
    the default font - no 'Pendi...' truncation."""
    t = page.overall
    fm = QFontMetrics(t.font())
    text_w = fm.horizontalAdvance("Pending...")
    assert t.columnWidth(3) >= text_w + 12          # cell padding headroom
    assert t.columnWidth(3) >= 200


def test_resize_modes_fixed_last_stretches(page):
    """Cols 0-3 fixed at their grid widths; the Duration column
    stretches so the table right edge auto-fits the container."""
    header = page.overall.horizontalHeader()
    for col in range(4):
        assert header.sectionResizeMode(col) \
            == QHeaderView.ResizeMode.Fixed, col
    assert header.sectionResizeMode(4) \
        == QHeaderView.ResizeMode.Stretch
    assert header.stretchLastSection() is False


def test_headers_centered(page):
    header = page.overall.horizontalHeader()
    assert header.defaultAlignment() == Qt.AlignmentFlag.AlignCenter


def test_row_content_unchanged(page):
    """EN checkmark + '--' placeholder + row count keep the original
    design (no business/visual change beyond widths)."""
    t = page.overall
    assert t.rowCount() == 2
    assert t.columnCount() == 5
    for r in range(2):
        assert t.item(r, 2).checkState() == Qt.CheckState.Checked
        assert t.item(r, 4).text() == "--"
        assert t.item(r, 3).text() == "Pending"
    assert [t.horizontalHeaderItem(c).text()
            for c in range(5)] == \
        ["#", "Stage", "EN", "Status", "Duration (s)"]
