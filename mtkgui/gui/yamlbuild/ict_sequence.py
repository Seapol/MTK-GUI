# -*- coding: utf-8 -*-
"""ICT Test Work Flow Sequence builder (block 04, user direction).

Clicking the "Build ICT Test Work Flow Sequence" card opens this
dialog: it GENERATES the ICT test sequence from the parse result as a
table - one test per row, ordered impedance -> power rails (voltage)
-> clock - and offers Move Up / Move Down / Add / Remove / Edit /
Duplicate for the manual adjustment.  The table contains ONLY the ICT
test items (no standard operations - those are added around the tests
on the Test Work Flow page when the dialog is accepted).
"""

from __future__ import annotations

import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

#: test methods offered in the sequence (standard operations excluded)
ICT_TEST_METHODS = ("Static Impedance", "Power Voltage", "Clock Hz",
                    "DAQ AI", "test")

#: Test Method -> unit (mirrors the Test Work Flow step edit dialog)
METHOD_UNITS = {
    "Static Impedance": "Ω",
    "Power Voltage": "V",
    "Clock Hz": "Hz",
    "DAQ AI": "V",
    "test": "—",
}

#: Test Method -> the parse-result category of the offered nets
METHOD_NET_CATEGORY = {
    "Static Impedance": "Power",
    "Power Voltage": "Power",
    "DAQ AI": "Power",
    "Clock Hz": "Clock",
    "test": "GPIO",
}

#: the DAQ AI test needs NO net / limits here: the Power rails are
#: already allocated in Channel Allocation - adding the test row is
#: enough (user direction)
DAQ_AI_METHOD = "DAQ AI"
DAQ_AI_NAME = "DAQ AI - Power rails"

#: the canonical generation order (user direction): impedance ->
#: power rails (voltage) -> clock
METHOD_ORDER = ("Static Impedance", "Power Voltage", "Clock Hz")

#: default Auto tolerances (user direction): power rails +/- 5 %,
#: clock +/- 50 ppm (= 0.005 %)
POWER_TOL = 0.05
CLOCK_TOL_PPM = 50.0

_V_RE = re.compile(r"(\d+)V(\d+)")            # 3V3 / 1V8 / 1V05
_V_PLAIN_RE = re.compile(r"(\d+)V\b")         # 24V / 5V


def expected_voltage(net: str) -> float | None:
    """Parse the nominal voltage from a power-net name
    (P3V3_LDO -> 3.3, MCU_1V8 -> 1.8, VIN_24V -> 24.0)."""
    m = _V_RE.search(net or "")
    if m:
        return float(f"{m.group(1)}.{m.group(2)}")
    m = _V_PLAIN_RE.search(net or "")
    if m:
        return float(m.group(1))
    return None


def expected_hz(net: str) -> float | None:
    """Parse the nominal frequency from a clock-net name
    (CLK_24M -> 24 MHz, OSC_125M -> 125 MHz, CLK_32K -> 32 kHz)."""
    for suffix, mult in (("G", 1e9), ("M", 1e6), ("K", 1e3)):
        m = re.search(rf"(\d+(?:\.\d+)?)\s*{suffix}", net or "",
                      re.IGNORECASE)
        if m:
            return float(m.group(1)) * mult
    return None


def _fmt_power(value: float) -> str:
    """Power limits / expected: 0.001 V precision (user direction)."""
    return f"{value:.3f}"


def _fmt_clock(value: float) -> str:
    """Clock limits / expected: 0.1 Hz precision (user direction)."""
    return f"{value:.1f}"


def _numeric(value: str) -> QDoubleSpinBox:
    """A numeric limit editor; the em-dash placeholder stays the
    unset state."""
    spin = QDoubleSpinBox()
    spin.setRange(-1e9, 1e9)
    spin.setDecimals(4)
    spin.setSpecialValueText("—")
    try:
        spin.setValue(float(value))
    except (TypeError, ValueError):
        spin.setValue(spin.minimum())
    return spin


def _num_text(spin: QDoubleSpinBox) -> str:
    if spin.value() <= spin.minimum():
        return "—"
    return f"{spin.value():.4f}".rstrip("0").rstrip(".")


class IctTestItemDialog(QDialog):
    """Add / edit ONE ICT test row: Test Method first, the Net combo
    follows the method, the Unit auto-fills, Min / Max are numeric."""

    def __init__(self, net_provider, method: str = "Static Impedance",
                 name: str = "", lo: str = "—", hi: str = "—",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("ICT Test Item")
        form = QFormLayout(self)
        self._net_provider = net_provider
        self.combo_method = QComboBox()
        self.combo_method.addItems(ICT_TEST_METHODS)
        self.combo_method.setCurrentText(
            method if method in ICT_TEST_METHODS else "test")
        self.combo_net = QComboBox()
        self.edit_unit = QLineEdit()
        self.edit_unit.setReadOnly(True)
        self.spin_lo = _numeric(lo)
        self.spin_hi = _numeric(hi)
        if name and name not in self._net_choices():
            self.combo_net.addItem(name)
        form.addRow("Test Method:", self.combo_method)
        form.addRow("Net:", self.combo_net)
        form.addRow("Unit:", self.edit_unit)
        form.addRow("Min:", self.spin_lo)
        form.addRow("Max:", self.spin_hi)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.combo_method.currentTextChanged.connect(self._sync)
        self._sync(self.combo_method.currentText())
        if name:
            self.combo_net.setCurrentText(name)

    def _net_choices(self) -> list[str]:
        category = METHOD_NET_CATEGORY.get(
            self.combo_method.currentText(), "Power")
        catalog = (self._net_provider() if self._net_provider
                   else {}) or {}
        nets = sorted(n for n, info in catalog.items()
                      if (info or {}).get("category") == category)
        return nets or ["—"]

    def _sync(self, method: str) -> None:
        self.edit_unit.setText(METHOD_UNITS.get(method, "—"))
        if method == DAQ_AI_METHOD:
            # the Power rails are allocated in Channel Allocation -
            # a DAQ AI test needs NO net / limits here (user
            # direction): add the test row directly
            self.combo_net.setEnabled(False)
            self.spin_lo.setEnabled(False)
            self.spin_hi.setEnabled(False)
            return
        self.combo_net.setEnabled(True)
        self.spin_lo.setEnabled(True)
        self.spin_hi.setEnabled(True)
        current = self.combo_net.currentText()
        fresh = self._net_choices()
        if current and current not in fresh:
            fresh.insert(0, current)
        self.combo_net.blockSignals(True)
        self.combo_net.clear()
        self.combo_net.addItems(fresh)
        if current in fresh:
            self.combo_net.setCurrentText(current)
        self.combo_net.blockSignals(False)

    def values(self) -> tuple:
        """The step tuple of the edited row ("test" kind)."""
        method = self.combo_method.currentText()
        if method == DAQ_AI_METHOD:
            return ("test", DAQ_AI_NAME, METHOD_UNITS[method],
                    "—", "—", "—")
        return ("test", self.combo_net.currentText().strip(),
                METHOD_UNITS.get(method, "—"), "—",
                _num_text(self.spin_lo), _num_text(self.spin_hi))


class IctWorkFlowSequenceDialog(QDialog):
    """The block-04 dialog: generates the ICT test sequence from the
    parse result (impedance -> voltage -> clock, one test per row) and
    lets the operator adjust it manually."""

    COLUMNS = ("Test Method", "Net", "Unit", "Expected", "Min", "Max")

    def __init__(self, net_provider, initial_tests=None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Build ICT Test Work Flow Sequence")
        self.setMinimumSize(640, 460)
        self._net_provider = net_provider
        self._rows: list[tuple] = (
            list(initial_tests) if initial_tests
            else self._generate(
                net_provider() if net_provider else {}))
        lay = QVBoxLayout(self)
        hint = QLabel(
            "One ICT test per row, generated impedance -> power "
            "rails (voltage) -> clock from the parse result; no "
            "standard operations here (they are added on the Test "
            "Work Flow page on OK). Adjust manually, then OK.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(list(self.COLUMNS))
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        # double-click opens the row editor (user direction)
        self.table.cellDoubleClicked.connect(
            lambda row, _col: self._edit(row))
        lay.addWidget(self.table, 1)

        btns = QHBoxLayout()
        for label, slot in (
                ("Auto", self._auto),
                ("Move Up", self._move_up),
                ("Move Down", self._move_down),
                ("Add", self._add),
                ("Remove", self._remove),
                ("Edit", self._edit),
                ("Duplicate", self._duplicate)):
            btn = QPushButton(label)
            btn.clicked.connect(slot)
            btns.addWidget(btn)
        btns.addStretch(1)
        lay.addLayout(btns)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self._refresh()

    # ------------------------------------------------- generation
    def _generate(self, testable: dict) -> list[tuple]:
        """The automatic sequence: per power net one Static Impedance
        and one Power Voltage test, per clock net one Clock Hz test -
        impedance -> power rails (voltage) -> clock."""
        testable = testable or {}
        rows: list[tuple] = []
        for method in METHOD_ORDER:
            category = METHOD_NET_CATEGORY[method]
            for net in sorted(n for n, info in testable.items()
                              if (info or {}).get("category")
                              == category):
                label = {"Static Impedance": f"Static Impedance - {net}",
                         "Power Voltage": f"Power Voltage - {net}",
                         "Clock Hz": f"Clock Hz - {net}"}.get(
                    method, f"{method} - {net}")
                rows.append(("test", label,
                             METHOD_UNITS[method], "—", "—", "—"))
        return rows

    # ------------------------------------------------- table plumbing
    def _refresh(self) -> None:
        table = self.table
        table.setUpdatesEnabled(False)
        try:
            table.setRowCount(len(self._rows))
            for r, (_kind, name, unit, expected, lo, hi) in \
                    enumerate(self._rows):
                method = (name.split(" - ")[0]
                          if " - " in name else name)
                for c, text in enumerate(
                        (method, name, unit, expected, lo, hi)):
                    item = QTableWidgetItem(text)
                    item.setFlags(item.flags()
                                  & ~Qt.ItemFlag.ItemIsEditable)
                    table.setItem(r, c, item)
        finally:
            table.setUpdatesEnabled(True)

    def _swap_rows(self, a: int, b: int) -> None:
        """Swap two rows IN PLACE (item objects are reused, no full
        table rebuild) - keeps rapid Move Up / Down clicks smooth; the
        ResizeToContents header does not re-measure on a swap."""
        self._rows[a], self._rows[b] = self._rows[b], self._rows[a]
        table = self.table
        table.setUpdatesEnabled(False)
        try:
            for c in range(len(self.COLUMNS)):
                ia = table.takeItem(a, c)
                ib = table.takeItem(b, c)
                table.setItem(a, c, ib)
                table.setItem(b, c, ia)
        finally:
            table.setUpdatesEnabled(True)
        # the selection (keyboard cursor) FOLLOWS the moved row so
        # repeated Move Up / Down / Edit clicks keep working
        table.setFocus()
        table.selectRow(b)

    def _selected(self) -> int:
        return self.table.currentRow()

    def _move_up(self) -> None:
        r = self._selected()
        if r <= 0:
            return
        self._swap_rows(r, r - 1)      # swap, selection follows up

    def _move_down(self) -> None:
        r = self._selected()
        if r < 0 or r >= len(self._rows) - 1:
            return
        self._swap_rows(r, r + 1)      # swap, select lower row

    def _add(self) -> None:
        dlg = IctTestItemDialog(self._net_provider, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._rows.append(dlg.values())
            self._refresh()
            self.table.selectRow(len(self._rows) - 1)

    def _remove(self) -> None:
        r = self._selected()
        if r < 0:
            return
        del self._rows[r]
        self._refresh()

    def _edit(self, row: int | None = None, _col: int = 0) -> None:
        r = self.table.currentRow() if row is None else row
        if r < 0 or r >= len(self._rows):
            return
        _kind, name, _unit, _measured, lo, hi = self._rows[r]
        method = name.split(" - ")[0] if " - " in name else "test"
        dlg = IctTestItemDialog(self._net_provider, method=method,
                                name=name, lo=lo, hi=hi, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._rows[r] = dlg.values()
            self._refresh()
            self.table.selectRow(r)

    def _auto(self) -> None:
        """Fill Expected / Min / Max from the parsed nominal values
        (user direction): Min = Expected * (1 - tolerance), Max =
        Expected * (1 + tolerance); power voltage +/- 5 % (0.001 V
        precision), clock +/- 50 ppm (0.1 Hz precision).  The nominal
        is parsed from the net name (P3V3 -> 3.3 V, CLK_24M ->
        24 MHz).  Rows without a parseable nominal stay untouched.
        The cells are updated in place."""
        table = self.table
        table.setUpdatesEnabled(False)
        try:
            for r, step in enumerate(self._rows):
                kind, name, unit, _expected, _lo, _hi = step
                method = (name.split(" - ")[0]
                          if " - " in name else name)
                net = name.split(" - ", 1)[1] if " - " in name else ""
                nominal = fmt = None
                tol = None
                if method == "Power Voltage":
                    nominal, tol, fmt = (expected_voltage(net),
                                         POWER_TOL, _fmt_power)
                elif method == "Clock Hz":
                    nominal, tol, fmt = (expected_hz(net),
                                         CLOCK_TOL_PPM * 1e-6,
                                         _fmt_clock)
                if nominal is None or tol is None:
                    continue
                row = (kind, name, unit, fmt(nominal),
                       fmt(nominal * (1 - tol)),
                       fmt(nominal * (1 + tol)))
                self._rows[r] = row
                for c, text in ((3, row[3]), (4, row[4]), (5, row[5])):
                    table.item(r, c).setText(text)
        finally:
            table.setUpdatesEnabled(True)

    def _duplicate(self) -> None:
        r = self._selected()
        if r < 0:
            return
        self._rows.insert(r + 1, self._rows[r])
        self._refresh()
        self.table.selectRow(r + 1)

    def result_tests(self) -> list[tuple]:
        """The adjusted test rows (step tuples, "test" kind only)."""
        return list(self._rows)
