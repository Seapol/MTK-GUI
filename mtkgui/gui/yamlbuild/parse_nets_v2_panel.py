# -*- coding: utf-8 -*-
"""v2 node 02 Parse nets — Qt panel (two tables, four classes).

Qt skin over :mod:`mtkgui.gui.yamlbuild.parse_nets_v2`.  The panel is
read-only about the data it shows: it hosts the four-class collapse for
both routes, moves rows between the two tables on a Category change, and
exposes ``validate()`` so the wizard can block ``[Next >]`` when the
Route B impedance/voltage consistency gate fails.
"""
from __future__ import annotations

from PySide6.QtCore import QLineF, QPointF, QSize, QTimer, Qt, Signal
from PySide6.QtGui import (QColor, QFont, QFontMetrics, QIcon, QPainter,
                           QPen, QPixmap, QPolygonF)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
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

#: arrow colours - the buttons sit on the panel background, not on a
#: filled blue bar, so they need a dark glyph
_ARROW_COLOR = "#33455a"


def _arrow_icon(up: bool, color: str = _ARROW_COLOR, size: int = 16) -> QIcon:
    """One drawn arrow (stem + head) - the two move buttons are the only
    controls standing between the tables, so they have to read as arrows
    at 16 px rather than as the words they used to carry."""
    icon = QIcon()
    for scale in (1, 2):
        pixels = QPixmap(size * scale, size * scale)
        pixels.fill(Qt.GlobalColor.transparent)
        pixels.setDevicePixelRatio(scale)
        painter = QPainter(pixels)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        s = size * scale
        pen = QPen(QColor(color))
        pen.setWidthF(max(1.2, s / 9.0))
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        painter.setPen(pen)
        painter.setBrush(QColor(color))
        painter.translate(0, s)
        painter.scale(1, -1)          # one geometry, drawn upside down
        head_h, head_w = s * 0.30, s * 0.26
        stem_top, stem_bottom = s * 0.10, s * 0.88
        painter.drawLine(QLineF(s / 2, stem_bottom, s / 2,
                                stem_top + head_h * 0.9))
        head = QPolygonF([QPointF(s / 2, stem_top),
                          QPointF(s / 2 - head_w, stem_top + head_h),
                          QPointF(s / 2 + head_w, stem_top + head_h)])
        painter.drawPolygon(head)          # solid head, pen kept for the stem
        painter.end()
        icon.addPixmap(pixels)
    return icon


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
        # 1168 was the two-table requirement; the arrow gutter between
        # them costs another 26 px plus the two 10 px spacings, and the
        # table headers need the rest (M155: at 1204 the net-name column
        # fell 6 px short and every header lost its first glyph).
        self.setMinimumWidth(1320)

        # ------------------------------------------ parse control
        # M155: the toolbar keeps one button.  "Re-parse" implied the
        # tables were already filled and only needed refreshing, which is
        # not what the operator sees on a fresh node; the button reads
        # "Parse nets" and the progress dialog reports what it is doing.
        top_row = QHBoxLayout()
        self.btn_parse = QPushButton("Parse nets")
        self.btn_parse.setObjectName("parseNetsButton")
        self.btn_parse.setToolTip(
            "Reads the NET file recorded in 01 Design Input and fills both "
            "tables.  It also runs automatically when 01 locks.")
        self.btn_parse.clicked.connect(self.parse_requested.emit)
        top_row.addWidget(self.btn_parse)
        top_row.addStretch(1)
        lay.addLayout(top_row)

        # ------------------------------------------ two columns, side by side
        # M129: Parsed Nets and Other Nets used to be stacked, which left
        # two huge empty tables in the dialog.  They now share one row so
        # the four-class split reads left (used) to right (unused).
        # M137: a grid, not two VBox columns.  The Route B note under the
        # right table used to shorten that table by one text line, so the
        # two tables did not end on the same baseline; on a shared grid row
        # both tables take the same height and the note sits underneath.
        columns = QGridLayout()
        columns.setContentsMargins(0, 0, 0, 0)
        columns.setHorizontalSpacing(10)
        columns.setVerticalSpacing(4)

        lbl = QLabel("Parsed Nets:")
        lbl.setObjectName("strong")
        columns.addWidget(lbl, 0, 0)
        lbl_other = QLabel("Other Nets:")
        lbl_other.setObjectName("strong")
        columns.addWidget(lbl_other, 0, 2)

        self.table = self._make_table()
        self.table_other = self._make_table()
        columns.addWidget(self.table, 1, 0)
        columns.addWidget(self.table_other, 1, 2)

        # M155: Move Up / Move Down became two arrow buttons standing in
        # the gutter BETWEEN the tables.  They act on the selected row of
        # the left table, so they belong beside it, not in the toolbar
        # where they were two more word buttons competing with Parse.
        arrows = QVBoxLayout()
        arrows.setContentsMargins(0, 0, 0, 0)
        arrows.setSpacing(6)
        self.btn_up = QToolButton()
        self.btn_up.setObjectName("moveRowUp")
        self.btn_up.setIcon(_arrow_icon(up=True))
        self.btn_up.setIconSize(QSize(16, 16))
        self.btn_up.setAutoRaise(True)
        self.btn_up.setToolTip("Move the selected net up")
        self.btn_up.setAccessibleName("Move the selected net up")
        self.btn_up.clicked.connect(lambda: self._move(-1))
        self.btn_down = QToolButton()
        self.btn_down.setObjectName("moveRowDown")
        self.btn_down.setIcon(_arrow_icon(up=False))
        self.btn_down.setIconSize(QSize(16, 16))
        self.btn_down.setAutoRaise(True)
        self.btn_down.setToolTip("Move the selected net down")
        self.btn_down.setAccessibleName("Move the selected net down")
        self.btn_down.clicked.connect(lambda: self._move(+1))
        arrows.addStretch(1)
        arrows.addWidget(self.btn_up)
        arrows.addWidget(self.btn_down)
        arrows.addStretch(1)
        columns.addLayout(arrows, 1, 1)
        columns.setColumnMinimumWidth(1, 26)

        self.lbl_other_note = QLabel("")
        self.lbl_other_note.setObjectName("muted")
        self.lbl_other_note.setWordWrap(True)
        columns.addWidget(self.lbl_other_note, 2, 2)

        columns.setColumnStretch(0, 1)
        columns.setColumnStretch(1, 0)
        columns.setColumnStretch(2, 1)
        columns.setRowStretch(1, 1)
        lay.addLayout(columns, 1)

        # ------------------------------------------ import summary
        self.lbl_summary = QLabel("no parse yet")
        self.lbl_summary.setObjectName("muted")
        lay.addWidget(self.lbl_summary)

        # M142: one deferred column fit per show.  The timer is owned by the
        # panel so a panel closed before the event runs never fires into a
        # deleted widget.  Created before the first render: _render queues
        # a second fit through it (M155 - the immediate fit runs before the
        # tables lay out, when the vertical bar that steals 12 px from the
        # viewport does not exist yet).
        self._fit_timer = QTimer(self)
        self._fit_timer.setSingleShot(True)
        self._fit_timer.timeout.connect(self._fit_columns)

        self._render()

    # ------------------------------------------------------------- table
    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self._fit_columns()

    def showEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().showEvent(event)
        # M142: an empty netlist never resized the tables, so their columns
        # kept Qt's 100 px default and both tables carried a horizontal
        # bar inside a dialog that actually fits.  Fit once the panel is
        # shown (the viewport width is only known then).
        self._fit_timer.start(0)

    def _fit_columns(self) -> None:
        """Share the table width: the Category combo keeps what it needs, the
        net name takes the slack, and no column ever spills into a bar."""
        for table in (self.table, self.table_other):
            viewport = table.viewport().width()
            if viewport <= 0:
                continue
            # viewport() already excludes a visible vertical bar - the first
            # fit runs before the tables lay out, which is why _render also
            # queues this method through _fit_timer (M155)
            metrics = QFontMetrics(table.horizontalHeader().font())
            # +20: the section paints its own 6 px padding either side plus
            # the grid line, and a bold header that loses 4 px loses a whole
            # glyph ("Test Point" read "est Poin" at +14)
            needs = [metrics.horizontalAdvance(col) + 20 for col in V2_COLUMNS]
            # M148: a label column is also sized by what it holds - "clock
            # sense" is twice the width of "power" and used to elide.  The
            # widest text per column is measured once per render.
            cell_metrics = QFontMetrics(table.font())
            # +18: the cell's padding and the grid line are painted by the
            # delegate - visualItemRect does not report them - and the
            # Segoe UI glyphs on the bench run a few pixels wider than
            # Helvetica does here, where +12 was already enough.
            decor = 18
            for index in range(len(V2_COLUMNS)):
                if index == 1:
                    continue
                needs[index] = max(needs[index],
                                   self._widest_text(table, index,
                                                     cell_metrics) + decor)
            # M143: the Category cell is a combo box, not a label - a column
            # sized from the header alone clipped every value to "Po" / "Ot"
            # once a real netlist filled the table.  The widest category plus
            # the drop-down arrow is the real requirement, and it is settled
            # before the other columns get their share, otherwise the shared
            # width scales it back down.
            # The combo is a cell widget inside the view, so its own
            # sizeHint is measured before it is shown and comes back far too
            # small; the widest label plus room for the arrow, the padding
            # and the focus frame is what actually holds "SE Clock".
            needs[1] = max(
                needs[1],
                max(cell_metrics.horizontalAdvance(category)
                    for category in V2_CATEGORIES) + 56,
                max(metrics.horizontalAdvance(category)
                    for category in V2_CATEGORIES) + 50)
            # M148b / M155: the net name absorbs the slack but never drops
            # under its own header ("Net Name" read "let Nam" when the
            # leftovers were a few pixels short); the short label columns
            # keep their measured width and only give space back when the
            # net header cannot be paid for any other way.
            labels = [index for index in range(2, len(V2_COLUMNS))]
            labels_need = sum(needs[index] for index in labels)
            net_head = needs[0]
            room = viewport - needs[1]
            slack = room - net_head - labels_need
            if slack >= 0:
                widths = {index: needs[index] for index in labels}
                widths[0] = room - labels_need
            else:
                budget = room - net_head
                scale = budget / labels_need if labels_need else 0
                widths = {index: max(40, int(needs[index] * scale))
                          for index in labels}
                widths[0] = room - sum(widths.values())
            # the Category column absorbs the rounding so the table ends flush
            widths[1] = viewport - sum(widths.values())
            for column, width in widths.items():
                table.setColumnWidth(column, max(24, width))

    def _widest_text(self, table: QTableWidget, column: int,
                     metrics: QFontMetrics) -> int:
        """Widest rendered text in one column, cached until the next render."""
        if column in self._text_widths:
            return self._text_widths[column]
        widest = 0
        for row in range(table.rowCount()):
            item = table.item(row, column)
            if item is not None and item.text():
                widest = max(widest, metrics.horizontalAdvance(item.text()))
        self._text_widths[column] = widest
        return widest

    def _make_table(self) -> QTableWidget:
        table = QTableWidget(0, len(V2_COLUMNS))
        table.setHorizontalHeaderLabels(list(V2_COLUMNS))
        # M137: fixed pixel widths summed to 735 px while the side-by-side
        # layout gives each table ~575 px inside the dialog, so both tables
        # carried a horizontal scrollbar on a default window.  The columns
        # now share the table width; long names elide with a tooltip.
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(False)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSizePolicy(QSizePolicy.Policy.Expanding,
                            QSizePolicy.Policy.Expanding)
        table.setMinimumHeight(420)
        table.setMinimumWidth(360)
        table.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        table.setTextElideMode(Qt.TextElideMode.ElideRight)
        # M137: seven columns per table, two tables per window - the global
        # header padding (6/10) made the headers alone need 653 px per table,
        # which no default dialog can give twice.  Compact the cell/header
        # metrics here (the rest of the application keeps the roomier style)
        # so both tables fit the default window without a horizontal bar.
        # The sizes live on the widgets, not in the stylesheet: a
        # font-size in px overrides the widget font for rendering but not
        # for QFontMetrics, so columns were sized for one font and drawn
        # with another (one character short on a 125 % display).
        table.setStyleSheet(
            "QHeaderView::section { padding: 4px 6px; }"
            "QTableWidget::item { padding: 2px 4px; }")
        cell_font = QFont(table.font())
        cell_font.setPixelSize(11)
        table.setFont(cell_font)
        header_font = QFont(cell_font)
        header_font.setPixelSize(10)
        header_font.setBold(True)
        table.horizontalHeader().setFont(header_font)
        table.verticalHeader().setVisible(False)
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

    def note_parsed_on_lock(self) -> None:
        """Flag the auto-parse from node 01 without touching the table."""
        text = self.lbl_summary.text()
        if "parsed on node 01 lock" not in text:
            self.lbl_summary.setText(text + " · parsed on node 01 lock")

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
        self._text_widths: dict[int, int] = {}
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
        self._fit_columns()
        # and once more after the layout settled, when the row count and
        # the vertical bar are known
        self._fit_timer.start(0)

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
                # M137: the columns share the table width, so a long net name
                # is elided - the tooltip carries the full text.
                item.setToolTip(value)
                table.setItem(row_index, col, item)

    def _category_cell(self, table, row_index, row, current: str) -> None:
        """Route A only: an editable Category combo that moves the row."""
        combo = QComboBox()
        combo.setInsertPolicy(QComboBox.NoInsert)
        # M143: the combo sizes itself to its longest entry ("SE Clock"),
        # not to a fixed 9-character content length - the column is now
        # fitted from the table width, so a wider hint only ate the net
        # name column.
        combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToContents)
        combo.setStyleSheet(
            "QComboBox { padding: 0px 2px; }"
            "QComboBox::drop-down { width: 14px; }")
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
