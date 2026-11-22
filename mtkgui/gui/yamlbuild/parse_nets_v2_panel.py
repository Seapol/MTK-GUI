# -*- coding: utf-8 -*-
"""v2 node 02 Parse nets — Qt panel (two tables, four classes).

Qt skin over :mod:`mtkgui.gui.yamlbuild.parse_nets_v2`.  The panel is
read-only about the data it shows: it hosts the four-class collapse for
both routes, moves rows between the two tables on a Category change, and
exposes ``validate()`` so the wizard can block ``[Next >]`` when the
Route B impedance/voltage consistency gate fails.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from mtkgui.ict.netparse import ParseNetsResult
from mtkgui.ict.netparse.model import (CATEGORY_GND, CATEGORY_OTHER,
                                       CATEGORY_POWER,
                                       CATEGORY_SE_CLOCK)
from mtkgui.ict.netparse.route_b import parse_results_sheet
from mtkgui.ict.netparse.route_c import parse_mtk_sheet
from mtkgui.gui.yamlbuild.parse_nets_v2 import (
    NA, ROUTE_A, ROUTE_B, ROUTE_C, V2_COLUMNS, V2_CATEGORIES, V2ParseState,
    collapse_route_a, collapse_route_b, collapse_route_c)

#: categories shown in the LEFT table (Parsed Nets)
_LEFT_CATEGORIES = (CATEGORY_POWER, CATEGORY_SE_CLOCK, CATEGORY_GND)

#: Route B right-table note (§3.3)
ROUTE_B_OTHER_NOTE = (
    "Route B has no net file, so no net can be enumerated as Other")


class ParseNetsV2Panel(QWidget):
    """Node 02 panel: Parsed Nets + Other Nets with the shared schema."""

    content_changed = Signal()
    #: v2-12a: the operator asked to run a Route A parse from the raw NET text
    parse_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state = V2ParseState()
        # user category overrides (Route A only) - a change moves the
        # row between the two tables
        self._overrides: dict[str, str] = {}

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.setMinimumWidth(860)

        # ------------------------------------------ move controls
        move_row = QHBoxLayout()
        self.btn_parse = QPushButton("Parse Nets…")
        self.btn_parse.clicked.connect(self.parse_requested.emit)
        self.btn_up = QPushButton("Move Up")
        self.btn_down = QPushButton("Move Down")
        self.btn_up.clicked.connect(lambda: self._move(-1))
        self.btn_down.clicked.connect(lambda: self._move(+1))
        move_row.addWidget(self.btn_parse)
        move_row.addSpacing(8)
        move_row.addWidget(self.btn_up)
        move_row.addWidget(self.btn_down)
        move_row.addStretch(1)
        lay.addLayout(move_row)

        # ------------------------------------------ left: Parsed Nets
        lbl = QLabel("Parsed Nets:")
        lbl.setObjectName("strong")
        lay.addWidget(lbl)
        self.table = self._make_table()
        lay.addWidget(self.table, 1)

        # ------------------------------------------ right: Other Nets
        lbl_other = QLabel("Other Nets:")
        lbl_other.setObjectName("strong")
        lay.addWidget(lbl_other)
        self.table_other = self._make_table()
        lay.addWidget(self.table_other, 1)
        self.lbl_other_note = QLabel("")
        self.lbl_other_note.setObjectName("muted")
        self.lbl_other_note.setWordWrap(True)
        lay.addWidget(self.lbl_other_note)

        # ------------------------------------------ import summary
        self.lbl_summary = QLabel("no parse yet")
        self.lbl_summary.setObjectName("muted")
        lay.addWidget(self.lbl_summary)

        self._render()

    # ------------------------------------------------------------- table
    def _make_table(self) -> QTableWidget:
        table = QTableWidget(0, len(V2_COLUMNS))
        table.setHorizontalHeaderLabels(list(V2_COLUMNS))
        table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive)
        table.horizontalHeader().setStretchLastSection(True)
        for column, width in enumerate((180, 110, 120, 120, 110, 120, 90)):
            table.setColumnWidth(column, width)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSizePolicy(QSizePolicy.Policy.Expanding,
                            QSizePolicy.Policy.Expanding)
        table.setMinimumHeight(110)
        return table

    # ----------------------------------------------------------- loading
    def load_route_a(self, result: ParseNetsResult) -> None:
        """Load a Route A collapse (SPF + NET + BoM)."""
        self._state = collapse_route_a(result)
        self._overrides = {}
        self._render()

    def load_route_b(self, path: str) -> tuple[bool, str]:
        """Load a Route B workbook (ICT Excel).  Returns ``(ok, error)``;
        ``ok=False`` means the file could not be read."""
        try:
            result = parse_results_sheet(path)
        except ValueError as exc:
            return False, str(exc)
        self._state = collapse_route_b(result)
        self._overrides = {}
        self._render()
        return True, ""

    def load_route_c(self, path: str) -> tuple[bool, str]:
        """Load a Route C MTK ICT Excel Sheet (read-only audit view).

        Returns ``(ok, error)``; ``ok=False`` means the file could not
        be parsed and the applied nets must not be wiped.
        """
        try:
            result = parse_mtk_sheet(path)
        except ValueError as exc:
            return False, str(exc)
        self._state = collapse_route_c(result)
        self._overrides = {}
        self._render()
        return True, ""

    def set_state(self, state: V2ParseState) -> None:
        self._state = state
        self._overrides = {}
        self._render()

    def state(self) -> V2ParseState:
        return self._state

    # ------------------------------------------------------------- gate
    def validate(self) -> tuple[bool, str]:
        """The Route B consistency gate: ``(False, reason)`` blocks
        ``[Next >]`` until the workbook is fixed and re-imported."""
        if self._state.gate_ok:
            return True, ""
        return False, self._state.gate_error

    # ----------------------------------------------------------- helpers
    def _effective(self, row) -> str:
        if self._state.route == ROUTE_A:
            return self._overrides.get(row.name, row.category)
        return row.category          # Route B: category is read-only

    def _left_rows(self):
        return [r for r in self._state.rows
                if self._effective(r) in _LEFT_CATEGORIES]

    def _right_rows(self):
        return [r for r in self._state.rows
                if self._effective(r) == CATEGORY_OTHER]

    def _render(self) -> None:
        left, right = self._left_rows(), self._right_rows()
        self._fill_table(self.table, left)
        self._fill_table(self.table_other, right)
        # Route B / C: the right table is greyed (read-only route)
        read_only = self._state.route in (ROUTE_B, ROUTE_C)
        route_b = self._state.route == ROUTE_B
        self.table_other.setEnabled(not read_only)
        self.lbl_other_note.setText(ROUTE_B_OTHER_NOTE if route_b else "")
        # Move Up / Down exist on the LEFT table only, Route A only
        self.btn_up.setEnabled(not read_only and len(left) > 1)
        self.btn_down.setEnabled(not read_only and len(left) > 1)
        # Route C parses on node 01: no Parse control on this node
        self.btn_parse.setVisible(self._state.route != ROUTE_C)
        if self._state.rows:
            self.lbl_summary.setText(self._state.summary())
        else:
            self.lbl_summary.setText("no parse yet")

    def _fill_table(self, table: QTableWidget, rows) -> None:
        # drop previous cell widgets first (ghost-combo guard)
        for r in range(table.rowCount()):
            for c in range(table.columnCount()):
                old = table.cellWidget(r, c)
                if old is not None:
                    table.removeCellWidget(r, c)
                    old.hide()
                    old.deleteLater()
        table.setRowCount(len(rows))
        read_only = self._state.route in (ROUTE_B, ROUTE_C)
        for row_index, row in enumerate(rows):
            category = self._effective(row)
            values = (row.name, category, row.sub_type, row.test_point,
                      row.nominal, row.limits, row.confidence)
            for col, value in enumerate(values):
                if col == 1 and not read_only:
                    self._category_cell(table, row_index, row, category)
                    continue
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                table.setItem(row_index, col, item)

    def _category_cell(self, table, row_index, row, current: str) -> None:
        """Route A only: an editable Category combo that moves the row."""
        combo = QComboBox()
        combo.setInsertPolicy(QComboBox.NoInsert)
        combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToContents)
        combo.addItems(list(V2_CATEGORIES))
        combo.setCurrentText(current)
        combo.currentTextChanged.connect(
            lambda value, name=row.name: self._on_category(name, value))
        table.setCellWidget(row_index, 1, combo)

    def _on_category(self, name: str, category: str) -> None:
        self._overrides[name] = category
        self.content_changed.emit()
        self._render()

    def _move(self, delta: int) -> None:
        """Move the selected LEFT-table row up (-1) / down (+1)."""
        row_index = self.table.currentRow()
        left = self._left_rows()
        if row_index < 0 or not (0 <= row_index + delta < len(left)):
            return
        # reorder the underlying rows list around the two names
        names = [r.name for r in self._state.rows]
        a = names.index(left[row_index].name)
        b = names.index(left[row_index + delta].name)
        names[a], names[b] = names[b], names[a]
        by_name = {r.name: r for r in self._state.rows}
        self._state.rows = [by_name[n] for n in names]
        self.content_changed.emit()
        self._render()
        self.table.setCurrentCell(row_index + delta, 0)
