# -*- coding: utf-8 -*-
"""Block-04 ICT Test Work Flow Sequence builder: generation order
(impedance -> voltage -> clock), manual adjustments (move / add /
remove / duplicate) and the test-only row set."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from mtkgui.gui.yamlbuild.ict_sequence import (  # noqa: E402
    IctWorkFlowSequenceDialog,
)

TESTABLE = {
    "3V3": {"category": "Power", "members": ["U1.5"]},
    "1V8_CORE": {"category": "Power", "members": ["U1.2"]},
    "CLK_24M": {"category": "Clock", "members": ["U1.10"]},
    "GPIO_LED1": {"category": "GPIO", "members": ["U1.20"]},
}


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def make_dialog():
    return IctWorkFlowSequenceDialog(lambda: dict(TESTABLE))


def test_generation_order_impedance_voltage_clock(qapp):
    """The generated sequence: per power net impedance then voltage,
    then the clock nets - one test per row, no standard operations."""
    dlg = make_dialog()
    try:
        rows = dlg.result_tests()
        names = [r[1] for r in rows]
        assert names == [
            "Static Impedance - 1V8_CORE", "Static Impedance - 3V3",
            "Power Voltage - 1V8_CORE", "Power Voltage - 3V3",
            "Clock Hz - CLK_24M",
        ]
        assert all(r[0] == "test" for r in rows)   # tests only
        units = [r[2] for r in rows]
        assert units == ["Ω", "Ω", "V", "V", "Hz"]
    finally:
        dlg.deleteLater()


def test_move_up_down_and_duplicate(qapp):
    dlg = make_dialog()
    try:
        dlg.table.selectRow(2)                     # Power Voltage - 1V8
        dlg._move_up()
        assert dlg.result_tests()[1][1] == "Power Voltage - 1V8_CORE"
        dlg._move_down()
        assert dlg.result_tests()[2][1] == "Power Voltage - 1V8_CORE"
        dlg._duplicate()
        assert len(dlg.result_tests()) == 6
        assert dlg.result_tests()[3][1] == "Power Voltage - 1V8_CORE"
        dlg._remove()
        assert len(dlg.result_tests()) == 5
    finally:
        dlg.deleteLater()


def test_rapid_moves_swap_in_place(qapp):
    """Smoothness contract: Move Up / Down swaps rows IN PLACE - the
    QTableWidgetItem objects are REUSED (no full table rebuild, so
    rapid clicks stay responsive) and the selection follows the row."""
    dlg = make_dialog()
    try:
        dlg.table.selectRow(2)
        item = dlg.table.item(2, 1)            # Power Voltage - 1V8
        dlg._move_up()
        assert dlg.table.item(1, 1) is item    # same objects, swapped
        dlg._move_up()
        dlg._move_up()                         # rapid repeated clicks
        assert dlg.table.currentRow() == 0     # clamped at the top
        names = [dlg.table.item(r, 1).text()
                 for r in range(dlg.table.rowCount())]
        assert names[0] == "Power Voltage - 1V8_CORE"
        assert names == [r[1] for r in dlg.result_tests()]
    finally:
        dlg.deleteLater()


def test_daq_ai_needs_no_configuration(qapp):
    """DAQ AI (user direction): the Power rails are allocated in
    Channel Allocation - the item editor disables Net / Min / Max and
    returns the fixed power-rails test row directly."""
    from mtkgui.gui.yamlbuild.ict_sequence import IctTestItemDialog
    dlg = IctTestItemDialog(lambda: dict(TESTABLE),
                            method="DAQ AI")
    try:
        assert dlg.combo_method.currentText() == "DAQ AI"
        assert not dlg.combo_net.isEnabled()
        assert not dlg.spin_lo.isEnabled()
        assert not dlg.spin_hi.isEnabled()
        assert dlg.edit_unit.text() == "V"
        assert dlg.values() == ("test", "DAQ AI - Power rails",
                                "V", "—", "—", "—")
    finally:
        dlg.deleteLater()


def test_add_row_without_operations(qapp, monkeypatch):
    """Add opens the item dialog; the accepted row lands at the end.
    Standard operations never enter the table."""
    dlg = make_dialog()
    try:
        monkeypatch.setattr(
            "mtkgui.gui.yamlbuild.ict_sequence.QDialog.exec",
            lambda self: self.DialogCode.Accepted)
        monkeypatch.setattr(
            "mtkgui.gui.yamlbuild.ict_sequence."
            "IctTestItemDialog.values",
            lambda self: ("test", "Power Voltage - 3V3", "V", "—",
                          "3.201", "3.399"))
        dlg._add()
        rows = dlg.result_tests()
        assert rows[-1][1] == "Power Voltage - 3V3"
        assert all(r[0] == "test" for r in rows)
    finally:
        dlg.deleteLater()
