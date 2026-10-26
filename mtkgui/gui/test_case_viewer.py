# -*- coding: utf-8 -*-
"""M12: detachable Test Case Viewer for ICT / FCT.

One merged, strictly read-only table showing ALL ICT rows followed by
ALL FCT rows of the Test Work Flow page.  The embedded tables stay the
single source of truth: a throttled full refresh mirrors their content
(text, EN checkbox state, verdict colours) while the dialog is open and
``highlight_step`` follows the currently executing test case.

Editing stays exclusively on the embedded tables - the viewer has no
edit triggers, no context menu and its EN items are not checkable.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QDialog,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from mtkgui.gui.dialog_sizing import fit_dialog
from mtkgui.style import saved_theme

#: one merged table - ICT first, then FCT
HEADERS = [
    "#", "Phase", "Test / Operation", "EN", "Unit / Duration",
    "Measured", "Min", "Max", "Result",
]
ICT_PHASE = "ICT"
FCT_PHASE = "FCT"

#: theme-aware current-step highlight, identical to the embedded tables
HIGHLIGHT_DARK = "#4a4020"
HIGHLIGHT_LIGHT = "#ffe9a8"

#: refresh throttle while a run writes results cell by cell
REFRESH_MS = 40

#: read-only: no editing AND no user-checkable EN (painting only)
CELL_FLAGS = (
    Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
)

_COL_NUM = 0
_COL_PHASE = 1
_COL_NAME = 2
_COL_EN = 3


class TestCaseViewer(QDialog):
    """Detachable viewer dialog (non-modal)."""

    def __init__(self, page, parent=None):
        super().__init__(parent if parent is not None else page.window())
        self._page = page
        self._ict_rows = 0
        self._highlight_row = -1

        self.setWindowTitle("Test Case Viewer")
        fit_dialog(self, 1080, 680)
        self.setMinimumSize(760, 440)
        self.setSizeGripEnabled(True)
        self.setModal(False)

        layout = QVBoxLayout(self)
        self.table = QTableWidget(0, len(HEADERS))
        self.table.setHorizontalHeaderLabels(HEADERS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(
            QTableWidget.SelectionMode.SingleSelection)
        # one line per row: long names elide instead of wrapping into a
        # taller row (wrapped text overlapped the next row at min width)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.TextElideMode.ElideRight)
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        for col in (3, 4, 5, 6, 7, 8):
            header.setSectionResizeMode(
                col, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(
            _COL_NAME, QHeaderView.ResizeMode.Stretch)
        # # and Phase fit their header / content (theme QSS padding
        # differs from the plain widget default, so never hard-code)
        for col in (_COL_NUM, _COL_PHASE):
            header.setSectionResizeMode(
                col, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.table)

        # throttled full refresh: embedded setItem / checkbox / verdict
        # colour changes all arrive here
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(REFRESH_MS)
        self._timer.timeout.connect(self.refresh)
        for table in (page.ict, page.fct):
            table.itemChanged.connect(self._schedule_refresh)
            table.model().rowsInserted.connect(self._schedule_refresh)
            table.model().rowsRemoved.connect(self._schedule_refresh)

    # ------------------------------------------------------------ sync
    def _schedule_refresh(self, *_args):
        """Mirror changes only while the viewer is on screen."""
        if not self.isVisible():
            return
        if not self._timer.isActive():
            self._timer.start()

    def showEvent(self, event):
        # every open takes a fresh snapshot (post-run results included)
        self.refresh()
        super().showEvent(event)

    def refresh(self):
        """Full snapshot of both embedded tables (single source)."""
        ict, fct = self._page.ict, self._page.fct
        self._ict_rows = ict.rowCount()
        total = self._ict_rows + fct.rowCount()
        self.table.setRowCount(total)
        for row in range(self._ict_rows):
            self._copy_row(row, ict, row, ICT_PHASE)
        for row in range(fct.rowCount()):
            self._copy_row(self._ict_rows + row, fct, row, FCT_PHASE)
        if self._highlight_row >= total:
            self._highlight_row = -1
        if self._highlight_row >= 0:
            self._paint_highlight(self._highlight_row)

    def _cell(self, row, col):
        item = self.table.item(row, col)
        if item is None:
            item = QTableWidgetItem()
            item.setFlags(CELL_FLAGS)
            self.table.setItem(row, col, item)
        return item

    def _copy_row(self, merged, src, src_row, phase):
        num = self._cell(merged, _COL_NUM)
        num.setText(str(merged + 1))
        num.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        num.setForeground(QBrush())
        num.setBackground(QBrush())
        num.setFont(QFont())

        phase_item = self._cell(merged, _COL_PHASE)
        phase_item.setText(phase)
        phase_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        phase_item.setForeground(QBrush())
        phase_item.setBackground(QBrush())
        phase_item.setFont(QFont())

        # Test / Operation: keep blue-bold op styling and comments tooltip
        name_src = src.item(src_row, 1)
        self._copy_item(merged, _COL_NAME, name_src,
                        Qt.AlignmentFlag.AlignLeft)

        # EN: painted checked / unchecked, never user-toggleable
        en_src = src.item(src_row, 2)
        en = self._cell(merged, _COL_EN)
        en.setText("")
        en.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        wanted = (en_src.checkState() if en_src is not None
                  else Qt.CheckState.Unchecked)
        if en.checkState() != wanted:
            en.setCheckState(wanted)
        en.setForeground(QBrush())
        en.setBackground(QBrush())
        en.setFont(QFont())

        if phase == ICT_PHASE:
            self._copy_item(merged, 4, src.item(src_row, 3),
                            Qt.AlignmentFlag.AlignCenter)
            self._copy_item(merged, 5, src.item(src_row, 4),
                            Qt.AlignmentFlag.AlignCenter)
            self._copy_item(merged, 6, src.item(src_row, 5),
                            Qt.AlignmentFlag.AlignCenter)
            self._copy_item(merged, 7, src.item(src_row, 6),
                            Qt.AlignmentFlag.AlignCenter)
            self._copy_item(merged, 8, src.item(src_row, 7),
                            Qt.AlignmentFlag.AlignCenter)
        else:
            # FCT: Duration (s) in Unit / Duration; no measured / limits
            self._copy_item(merged, 4, src.item(src_row, 3),
                            Qt.AlignmentFlag.AlignCenter)
            for col in (5, 6, 7):
                empty = self._cell(merged, col)
                if empty.text():
                    empty.setText("")
                empty.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                empty.setForeground(QBrush())
                empty.setBackground(QBrush())
                empty.setFont(QFont())
            self._copy_item(merged, 8, src.item(src_row, 4),
                            Qt.AlignmentFlag.AlignCenter)

    def _copy_item(self, row, col, src_item, align):
        """Copy text + verdict foreground/background + font from a cell."""
        item = self._cell(row, col)
        text = src_item.text() if src_item is not None else ""
        if item.text() != text:
            item.setText(text)
        item.setTextAlignment(align)
        item.setForeground(src_item.foreground() if src_item
                           else QBrush())
        item.setBackground(src_item.background() if src_item
                           else QBrush())
        item.setFont(src_item.font() if src_item else QFont())
        item.setToolTip(src_item.toolTip() if src_item else "")

    # ------------------------------------------------------- follow run
    def highlight_step(self, kind, row):
        """Follow the executing test case: merged row, cursor, scroll."""
        if not self.isVisible():
            return
        merged = row if kind == "ict" else self._ict_rows + row
        self._clear_highlight()
        if merged < 0 or merged >= self.table.rowCount():
            return
        self._highlight_row = merged
        self._paint_highlight(merged)
        self.table.setCurrentCell(merged, _COL_NUM)
        # scroll only when the row left the visible viewport (mirrors
        # the embedded _highlight_row behaviour)
        viewport = self.table.viewport().rect()
        rect = self.table.visualItemRect(self.table.item(merged, _COL_NUM))
        if not rect.isValid() or rect.top() < viewport.top() \
                or rect.bottom() > viewport.bottom():
            self.table.scrollToItem(
                self.table.item(merged, _COL_NUM),
                QTableWidget.ScrollHint.PositionAtCenter)

    def _clear_highlight(self):
        row = self._highlight_row
        self._highlight_row = -1
        if not 0 <= row < self.table.rowCount():
            return
        # restore the source row (verdict colours stay intact)
        if row < self._ict_rows:
            self._copy_row(row, self._page.ict, row, ICT_PHASE)
        else:
            self._copy_row(row, self._page.fct,
                           row - self._ict_rows, FCT_PHASE)

    def _paint_highlight(self, row):
        """Theme-aware amber row + bold Test / Operation (strong cue)."""
        hl = QColor(HIGHLIGHT_DARK if saved_theme() == "Dark"
                    else HIGHLIGHT_LIGHT)
        for col in range(self.table.columnCount()):
            item = self.table.item(row, col)
            if item is not None:
                item.setBackground(hl)
        name = self.table.item(row, _COL_NAME)
        if name is not None:
            bold = QFont(name.font())
            bold.setBold(True)
            name.setFont(bold)
