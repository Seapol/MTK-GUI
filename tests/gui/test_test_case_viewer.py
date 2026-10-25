# -*- coding: utf-8 -*-
"""M12: detachable Test Case Viewer (merged ICT + FCT read-only table).

Covers the snapshot contract, live mirroring (text + verdict colours +
EN state), the read-only guarantees, close / reopen, and the
current-step follower (merged row, cursor, scrollbar).
"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QTableWidget,
)

from mtkgui.style import saved_theme  # noqa: E402
from mtkgui.test_workflow_page import TestWorkFlowPage  # noqa: E402

HEADERS = ["#", "Phase", "Test / Operation", "EN", "Unit / Duration",
           "Measured", "Min", "Max", "Result"]


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def page(qapp):
    w = TestWorkFlowPage()
    w.resize(1200, 900)
    w.show()
    qapp.processEvents()
    yield w
    if w._case_viewer is not None:
        w._case_viewer.close()
        w._case_viewer = None
    w.close()
    w.deleteLater()


def _open(page, qapp):
    page.open_test_case_viewer()
    viewer = page._case_viewer
    qapp.processEvents()
    return viewer


# --------------------------------------------------------------- open
def test_button_opens_viewer(page, qapp):
    # M19f: a checkbox on the right of the page title, ON by default;
    # it arms the auto-open at each Run (open_test_case_viewer is the
    # entry the Run path calls)
    assert page.chk_case_viewer.text() == "Test Case Viewer"
    assert page.chk_case_viewer.isChecked()
    assert page.chk_case_viewer.toolTip() == \
        "Auto-open the ICT/FCT case viewer at each Run start and " \
        "close it when the Run finishes"
    page.open_test_case_viewer()
    qapp.processEvents()
    viewer = page._case_viewer
    assert viewer is not None and viewer.isVisible()
    assert viewer.windowTitle() == "Test Case Viewer"
    assert not viewer.isModal()
    # ONE merged read-only table with the 9 columns
    tables = viewer.findChildren(QTableWidget)
    assert len(tables) == 1
    assert [tables[0].horizontalHeaderItem(c).text()
            for c in range(tables[0].columnCount())] == HEADERS
    assert tables[0] is viewer.table
    assert viewer.minimumWidth() == 760
    assert viewer.minimumHeight() == 440
    # long names elide on one line (no wrapped rows overlapping)
    assert tables[0].wordWrap() is False


# ------------------------------------------------------------ snapshot
def test_snapshot_merges_ict_then_fct(page, qapp):
    viewer = _open(page, qapp)
    t = viewer.table
    ict, fct = page.ict, page.fct
    assert t.rowCount() == ict.rowCount() + fct.rowCount()
    # ICT rows first
    for r in range(ict.rowCount()):
        assert t.item(r, 0).text() == str(r + 1)
        assert t.item(r, 1).text() == "ICT"
        assert t.item(r, 2).text() == ict.item(r, 1).text()
        assert t.item(r, 3).checkState() == ict.item(r, 2).checkState()
        for src_col, dst_col in ((3, 4), (4, 5), (5, 6), (6, 7), (7, 8)):
            assert t.item(r, dst_col).text() \
                == ict.item(r, src_col).text(), (r, dst_col)
    # FCT rows after, global numbering continues
    base = ict.rowCount()
    for r in range(fct.rowCount()):
        merged = base + r
        assert t.item(merged, 0).text() == str(merged + 1)
        assert t.item(merged, 1).text() == "FCT"
        assert t.item(merged, 2).text() == fct.item(r, 1).text()
        assert t.item(merged, 3).checkState() == fct.item(r, 2).checkState()
        assert t.item(merged, 4).text() == fct.item(r, 3).text()  # duration
        for col in (5, 6, 7):            # no measured / min / max
            assert t.item(merged, col).text() == ""
        assert t.item(merged, 8).text() == fct.item(r, 4).text()


def test_live_mirror_of_result_text_and_colour(page, qapp):
    viewer = _open(page, qapp)
    page._set_status(page.ict, 1, 7, "PASS")
    qapp.processEvents()
    QTest.qWait(80)                      # throttled refresh (40 ms)
    assert viewer.table.item(1, 8).text() == "PASS"
    src = page.ict.item(1, 7)
    assert viewer.table.item(1, 8).foreground().color() \
        == src.foreground().color()
    if src.background().style() != Qt.BrushStyle.NoBrush:
        assert viewer.table.item(1, 8).background().color() \
            == src.background().color()


def test_en_mirrored_and_not_toggleable(page, qapp):
    viewer = _open(page, qapp)
    page.ict_enables[0] = False
    page._ict_edit_guard = False
    page.ict.item(0, 2).setCheckState(Qt.CheckState.Unchecked)
    qapp.processEvents()
    QTest.qWait(80)
    assert viewer.table.item(0, 3).checkState() == Qt.CheckState.Unchecked
    # strictly read-only
    assert viewer.table.editTriggers() \
        == QTableWidget.EditTrigger.NoEditTriggers
    assert viewer.table.contextMenuPolicy() != \
        Qt.ContextMenuPolicy.CustomContextMenu
    en = viewer.table.item(0, 3)
    assert not (en.flags() & Qt.ItemFlag.ItemIsUserCheckable)
    rect = viewer.table.visualItemRect(en)
    QTest.mouseClick(viewer.table.viewport(), Qt.MouseButton.LeftButton,
                     pos=rect.center())
    qapp.processEvents()
    assert viewer.table.item(0, 3).checkState() == Qt.CheckState.Unchecked


def test_close_and_reopen_takes_fresh_snapshot(page, qapp):
    viewer = _open(page, qapp)
    page._set_status(page.ict, 1, 7, "PASS")
    qapp.processEvents()
    QTest.qWait(80)
    assert viewer.table.item(1, 8).text() == "PASS"
    viewer.close()
    qapp.processEvents()
    # run update while the viewer is closed: no live mirror expected
    page._set_status(page.ict, 1, 7, "FAIL")
    assert viewer.table.item(1, 8).text() == "PASS"
    page.open_test_case_viewer()
    qapp.processEvents()
    assert page._case_viewer is viewer        # same instance, fresh data
    assert viewer.table.item(1, 8).text() == "FAIL"


# ---------------------------------------------------------- follow run
def test_highlight_step_ict_moves_cursor_and_marks_row(page, qapp):
    viewer = _open(page, qapp)
    viewer.resize(760, 440)
    qapp.processEvents()
    page._highlight_step("ict", 3)
    qapp.processEvents()
    assert viewer.table.currentRow() == 3
    hl = QColor("#4a4020" if saved_theme() == "Dark" else "#ffe9a8")
    assert viewer.table.item(3, 0).background().color() == hl
    # strong cue: bold Test / Operation cell
    assert viewer.table.item(3, 2).font().bold()
    # moving on clears the previous row
    page._highlight_step("ict", 0)
    qapp.processEvents()
    assert viewer.table.currentRow() == 0
    assert viewer.table.item(3, 0).background().style() \
        == Qt.BrushStyle.NoBrush or \
        viewer.table.item(3, 0).background().color() != hl


def test_highlight_step_fct_uses_merged_row_and_scrolls(page, qapp):
    viewer = _open(page, qapp)
    viewer.resize(760, 440)
    qapp.processEvents()
    viewer.table.verticalScrollBar().setValue(0)
    qapp.processEvents()
    page._highlight_step("fct", 6)      # last merged row -> off-screen
    qapp.processEvents()
    merged = page.ict.rowCount() + 6
    assert viewer.table.currentRow() == merged
    assert viewer.table.item(merged, 1).text() == "FCT"
    assert viewer.table.verticalScrollBar().value() > 0
    rect = viewer.table.visualItemRect(viewer.table.item(merged, 0))
    vp = viewer.table.viewport().rect()
    assert rect.isValid()
    assert vp.top() <= rect.top() and rect.bottom() <= vp.bottom()


def test_embedded_tables_untouched(page, qapp):
    """No regression: embedded construction / widths / row counts."""
    viewer = _open(page, qapp)
    assert page.ict.columnCount() == 8
    assert page.fct.columnCount() == 5
    page.fct.item(0, 4).setText("Virtual PASS")
    qapp.processEvents()
    QTest.qWait(80)
    assert viewer.table.item(page.ict.rowCount(), 8).text() == "Virtual PASS"
