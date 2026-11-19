# -*- coding: utf-8 -*-
"""v2 node 05 Build ICT Test Sequence — Qt panel.

Qt skin over :mod:`mtkgui.gui.yamlbuild.ict_sequence_v2`.  Renders the
flat sequence into the six virtual blocks with the eight-column schema,
lets the operator edit the per-row ``Timeout`` and ``Not tested``, and
exposes ``validate()`` so the wizard blocks ``[Next >]`` on §8.

The two editable columns write straight back into the underlying
:class:`IctStep` objects, so ``values()`` always reflects the table.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from mtkgui.gui.yamlbuild.ict_sequence_v2 import (
    BLOCK_LABELS, KIND_OP, block_of, generate_sequence, to_engine_cases,
    validate_sequence, IctStep)

COLUMNS = ("#", "Step", "Type", "Net / TP", "Limits", "Instrument",
           "Timeout", "Not tested")

_COL_TIMEOUT = 6
_COL_NOT_TESTED = 7


def _type_label(step: IctStep) -> str:
    """The ``Type`` cell (§3)."""
    if step.kind == KIND_OP:
        return step.op_type or step.kind
    return step.kind


class BuildIctSequencePanel(QWidget):
    """Node 05: the flat sequence shown in six pinned blocks."""

    content_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._steps: list[IctStep] = []
        self._loading = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        head = QHBoxLayout()
        self.lbl_summary = QLabel("Steps: 0")
        head.addWidget(self.lbl_summary)
        head.addStretch(1)
        self.btn_reset = QPushButton("Reset to generated order")
        self.btn_reset.clicked.connect(self._on_reset)
        head.addWidget(self.btn_reset)
        lay.addLayout(head)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(list(COLUMNS))
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.SelectedClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed)
        self.table.horizontalHeader().setStretchLastSection(True)
        for column, width in enumerate((40, 220, 120, 140, 140, 130, 80, 80)):
            self.table.setColumnWidth(column, width)
        # sync the editable Timeout cell back into the step on commit
        self.table.itemChanged.connect(self._on_item_changed)
        lay.addWidget(self.table, 1)

        self.lbl_footer = QLabel("")
        self.lbl_footer.setObjectName("muted")
        lay.addWidget(self.lbl_footer)

    # ------------------------------------------------------------- loading
    def generate(self, power_nets, clock_nets, rails_enabled: bool,
                 fixture_type: str = "ate",
                 instruments: list[str] | None = None) -> None:
        self._steps = generate_sequence(power_nets, clock_nets,
                                        rails_enabled, fixture_type,
                                        instruments)
        self._render()

    def set_sequence(self, steps: list[IctStep]) -> None:
        self._steps = list(steps)
        self._render()

    def sequence(self) -> list[IctStep]:
        return list(self._steps)

    def set_values(self, steps: list[IctStep]) -> None:
        self.set_sequence(steps)

    def values(self) -> list[IctStep]:
        return self.sequence()

    def engine_cases(self, equipment_config) -> list:
        """The engine ``ict_test_cases`` rows for the current sequence."""
        return to_engine_cases(self._steps, equipment_config)

    # ------------------------------------------------------------- gate
    def validate(self) -> tuple[bool, str]:
        ok, msg = validate_sequence(self._steps)
        if not ok:
            return False, f"Not complete: {msg}"
        return True, ""

    # ------------------------------------------------------------- render
    def _render(self) -> None:
        self._loading = True
        try:
            self._clear_widgets()
            # one table row per step, plus a block-header row at each block
            # boundary; the # column is the running step number (1-based).
            rows: list[tuple[str | None, IctStep | None, int]] = []
            current_block: str | None = None
            number = 0
            for step in self._steps:
                blk = block_of(step)
                if blk != current_block:
                    current_block = blk
                    rows.append((f"── {BLOCK_LABELS[blk]} ──────", None, 0))
                number += 1
                rows.append((None, step, number))

            self.table.setRowCount(len(rows))
            for row_index, (header, step, number) in enumerate(rows):
                if step is None:
                    self._render_header(row_index, header or "")
                    continue
                self._render_step(row_index, number, step)

            test_count = sum(1 for s in self._steps if s.is_test())
            self.lbl_summary.setText(
                f"Steps: {test_count}     Power cycle: 1 up / 1 down")
        finally:
            self._loading = False

    def _clear_widgets(self) -> None:
        self.table.clearContents()
        for r in range(self.table.rowCount()):
            for c in range(self.table.columnCount()):
                w = self.table.cellWidget(r, c)
                if w is not None:
                    self.table.removeCellWidget(r, c)
                    w.deleteLater()

    def _render_header(self, row_index: int, text: str) -> None:
        item = QTableWidgetItem(text)
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        self.table.setItem(row_index, 0, item)
        self.table.setSpan(row_index, 0, 1, len(COLUMNS))

    def _render_step(self, row_index: int, number: int,
                     step: IctStep) -> None:
        values = (str(number), step.name, _type_label(step),
                  f"{step.net} / {step.tp}" if step.net else "",
                  "",  # Limits come from 04 (read-only)
                  "",  # Instrument comes from 04 (read-only)
                  "" if step.timeout_ms is None else str(step.timeout_ms))
        for col, value in enumerate(values):
            if col == _COL_TIMEOUT:
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
                item.setData(Qt.ItemDataRole.UserRole, step)
                self.table.setItem(row_index, col, item)
            elif col == _COL_NOT_TESTED:
                self._not_tested_cell(row_index, step)
            else:
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row_index, col, item)

    def _not_tested_cell(self, row_index: int, step: IctStep) -> None:
        box = QCheckBox()
        box.setChecked(step.not_tested)
        if step.kind == KIND_OP:
            box.setEnabled(False)
            box.setToolTip("standard steps are fixed - switch the feature "
                           "off in 04")
        # keep the checkbox bound to this step: on toggle, write back
        box.toggled.connect(
            lambda checked, s=step: self._on_not_tested(s, checked))
        self.table.setCellWidget(row_index, _COL_NOT_TESTED, box)

    # ------------------------------------------------------------- sync
    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._loading:
            return
        if item.column() != _COL_TIMEOUT:
            return
        step = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(step, IctStep):
            return
        text = item.text().strip()
        if not text:
            step.timeout_ms = None
        else:
            try:
                step.timeout_ms = int(text)
            except ValueError:
                # keep the old value; the gate reports it on validate()
                item.setText("" if step.timeout_ms is None
                             else str(step.timeout_ms))
                return
        self.content_changed.emit()

    def _on_not_tested(self, step: IctStep, checked: bool) -> None:
        if self._loading:
            return
        step.not_tested = checked
        self.content_changed.emit()

    def _on_reset(self) -> None:
        self.content_changed.emit()
