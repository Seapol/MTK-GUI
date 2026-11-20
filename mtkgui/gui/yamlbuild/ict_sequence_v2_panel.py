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
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from mtkgui.gui.yamlbuild.ict_sequence_v2 import (
    BLOCK_LABELS, KIND_CLOCK_HZ, KIND_DELAY, KIND_OP, KIND_POWER_VOLTAGE,
    KIND_RGND, OP_DAQ_AI_END, OP_DAQ_AI_START, block_of, generate_sequence,
    to_engine_cases, validate_sequence, IctStep)

COLUMNS = ("#", "Step", "Type", "Net / TP", "Limits", "Instrument",
           "Timeout", "Not tested")

_COL_TIMEOUT = 6
_COL_NOT_TESTED = 7


def _type_label(step: IctStep) -> str:
    """The ``Type`` cell (§3)."""
    if step.kind == KIND_OP:
        return step.op_type or step.kind
    return step.kind


def _spin(decimals: int = 0, minimum: float = 0.0,
          maximum: float = 1e12) -> QDoubleSpinBox:
    """A QDoubleSpinBox with a per-type single step (v2-15 R7: the step is
    decoupled from ``10**-decimals``)."""
    box = QDoubleSpinBox()
    box.setDecimals(decimals)
    box.setRange(minimum, maximum)
    box.setSingleStep(10 ** -decimals)
    return box


def _clamp(exp: QDoubleSpinBox, mn: QDoubleSpinBox,
           mx: QDoubleSpinBox) -> None:
    """v2-15 R8: live Min <= Expected <= Max clamp."""
    def _sync(*_args):
        e = exp.value()
        if mn.value() > e:
            mn.setValue(e)
        if mx.value() < e:
            mx.setValue(e)
    exp.valueChanged.connect(_sync)
    mn.valueChanged.connect(_sync)
    mx.valueChanged.connect(_sync)


def _edit_ict_row(parent: QWidget, step: IctStep) -> bool:
    """v2-15 E: the per-type row editor (one dialog per step type)."""
    dlg = QDialog(parent)
    dlg.setWindowTitle(f"Edit {step.name}")
    form = QFormLayout()
    net = QLineEdit(step.net or "")
    net.setReadOnly(True)
    form.addRow("Net", net)

    if step.kind == KIND_RGND:
        mn = _spin(0, 0, 1e9)
        mx = _spin(0, 0, 1e9)
        mn.setValue(float(step.min_val or 0))
        mx.setValue(float(step.max_val or 0))
        mx.setSpecialValueText("none (no upper bound)")
        form.addRow("Min (ohm)", mn)
        form.addRow("Max (ohm)", mx)
    elif step.kind == KIND_POWER_VOLTAGE:
        exp = _spin(3, -1e6, 1e6)
        mn = _spin(3, -1e6, 1e6)
        mx = _spin(3, -1e6, 1e6)
        exp.setValue(float(step.expected or 0))
        mn.setValue(float(step.min_val or 0))
        mx.setValue(float(step.max_val or 0))
        form.addRow("Expected (V)", exp)
        form.addRow("Min (V)", mn)
        form.addRow("Max (V)", mx)
        _clamp(exp, mn, mx)
    elif step.kind == KIND_CLOCK_HZ:
        exp = _spin(0, 0, 1e12)
        ppm = _spin(0, 0, 1e6)
        mn = _spin(0, 0, 1e12)
        mx = _spin(0, 0, 1e12)
        exp.setValue(float(step.expected or 0))
        ppm.setValue(float(step.ppm or 0))
        mn.setValue(float(step.min_val or 0))
        mx.setValue(float(step.max_val or 0))
        form.addRow("Expected (Hz)", exp)
        form.addRow("ppm", ppm)
        form.addRow("Min (Hz)", mn)
        form.addRow("Max (Hz)", mx)
        _clamp(exp, mn, mx)
    elif step.kind == KIND_OP and step.op_type == OP_DAQ_AI_START:
        rate = _spin(0, 1, 1e9)
        lead = _spin(0, 0, 1e9)
        rate.setValue(float(step.params.get("rate_hz", 20000)))
        lead.setValue(float(step.params.get("arm_lead_ms", 100)))
        form.addRow("rate_hz", rate)
        form.addRow("arm_lead_ms", lead)
    elif step.kind == KIND_OP and step.op_type == OP_DAQ_AI_END:
        win = _spin(0, 0, 1e9)
        win.setValue(float(step.params.get("window_ms", 1000)))
        form.addRow("window_ms", win)
    elif step.kind == KIND_DELAY:
        wait = QSpinBox()
        wait.setRange(0, 1 << 30)
        wait.setValue(int(step.params.get("wait_ms", 0)))
        form.addRow("wait_ms", wait)
    else:
        form.addRow(QLabel("No editable fields for this step."))

    buttons = QDialogButtonBox(QDialogButtonBox.Ok
                               | QDialogButtonBox.Cancel)
    buttons.accepted.connect(dlg.accept)
    buttons.rejected.connect(dlg.reject)
    lay = QVBoxLayout(dlg)
    lay.addLayout(form)
    lay.addWidget(buttons)
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return False

    if step.kind == KIND_RGND:
        step.min_val = f"{mn.value():g}"
        step.max_val = f"{mx.value():g}" if mx.value() else ""
    elif step.kind == KIND_POWER_VOLTAGE:
        step.expected = f"{exp.value():.3f}"
        step.min_val = f"{mn.value():.3f}"
        step.max_val = f"{mx.value():.3f}"
    elif step.kind == KIND_CLOCK_HZ:
        step.expected = f"{int(exp.value())}"
        step.ppm = f"{int(ppm.value())}"
        step.min_val = f"{int(mn.value())}"
        step.max_val = f"{int(mx.value())}"
    elif step.kind == KIND_OP and step.op_type == OP_DAQ_AI_START:
        step.params["rate_hz"] = int(rate.value())
        step.params["arm_lead_ms"] = int(lead.value())
    elif step.kind == KIND_OP and step.op_type == OP_DAQ_AI_END:
        step.params["window_ms"] = int(win.value())
    elif step.kind == KIND_DELAY:
        step.params["wait_ms"] = wait.value()
    return True


class BuildIctSequencePanel(QWidget):
    """Node 05: the flat sequence shown in six pinned blocks."""

    content_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._steps: list[IctStep] = []
        self._loading = False
        #: v2-11b C: the last seed args, so Reset / refresh regenerate
        self._seed: dict = {"power_nets": [], "clock_nets": [],
                            "rails_enabled": False, "fixture_type": "ate",
                            "instruments": []}

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        head = QHBoxLayout()
        self.lbl_summary = QLabel("Steps: 0")
        head.addWidget(self.lbl_summary)
        head.addStretch(1)
        self.btn_move_up = QPushButton("Move Up")
        self.btn_move_down = QPushButton("Move Down")
        self.btn_move_up.clicked.connect(lambda: self._move(-1))
        self.btn_move_down.clicked.connect(lambda: self._move(1))
        head.addWidget(self.btn_move_up)
        head.addWidget(self.btn_move_down)
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
        # v2-15 E: double-click a row opens its per-type editor
        self.table.cellDoubleClicked.connect(self._on_double_click)
        lay.addWidget(self.table, 1)

        self.lbl_footer = QLabel("")
        self.lbl_footer.setObjectName("muted")
        lay.addWidget(self.lbl_footer)

    # ------------------------------------------------------------- loading
    def generate(self, power_nets, clock_nets, rails_enabled: bool,
                 fixture_type: str = "ate",
                 instruments: list[str] | None = None) -> None:
        self._seed = {"power_nets": list(power_nets),
                      "clock_nets": list(clock_nets),
                      "rails_enabled": bool(rails_enabled),
                      "fixture_type": fixture_type,
                      "instruments": list(instruments or [])}
        self._steps = generate_sequence(**self._seed)
        self._render()

    def refresh(self, power_nets=None, clock_nets=None,
                rails_enabled: bool | None = None,
                fixture_type: str | None = None,
                instruments: list[str] | None = None) -> None:
        """Re-seed from the latest node 02/04 facts (wizard revisit).

        Stored seed args are reused; the wizard may push fresh ones."""
        seed = dict(self._seed)
        if power_nets is not None:
            seed["power_nets"] = list(power_nets)
        if clock_nets is not None:
            seed["clock_nets"] = list(clock_nets)
        if rails_enabled is not None:
            seed["rails_enabled"] = bool(rails_enabled)
        if fixture_type is not None:
            seed["fixture_type"] = fixture_type
        if instruments is not None:
            seed["instruments"] = list(instruments)
        self.generate(**seed)
        # keep the model in step with the re-seeded sequence
        self.content_changed.emit()

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
        """Reset to generated order: re-run the generator with the seed."""
        self.generate(**self._seed)
        self.content_changed.emit()

    # ------------------------------------------------------------- edit
    def _step_at_row(self, row: int) -> IctStep | None:
        item = self.table.item(row, _COL_TIMEOUT)
        step = item.data(Qt.ItemDataRole.UserRole) if item else None
        return step if isinstance(step, IctStep) else None

    def _on_double_click(self, row: int, _col: int) -> None:
        step = self._step_at_row(row)
        if step is None:
            return
        if _edit_ict_row(self, step):
            self._render()
            self.content_changed.emit()

    # ------------------------------------------------------------- reorder
    def _move(self, delta: int) -> None:
        """v2-15 R9: swap the selected step with its neighbour within the
        SAME block only (a cross-block move is refused)."""
        row = self.table.currentRow()
        step = self._step_at_row(row)
        if step is None:
            return
        try:
            i = self._steps.index(step)
        except ValueError:
            return
        j = i + delta
        if not (0 <= j < len(self._steps)):
            return
        if block_of(self._steps[i]) != block_of(self._steps[j]):
            return
        self._steps[i], self._steps[j] = self._steps[j], self._steps[i]
        self._render()
        self.table.setCurrentCell(row, 0)
        self.content_changed.emit()
