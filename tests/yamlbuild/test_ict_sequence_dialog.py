# -*- coding: utf-8 -*-
"""Block-04 ICT Test Work Flow Sequence builder: generation order
(impedance -> voltage -> clock), manual adjustments (move / add /
remove / duplicate) and the whole-sequence result.

The dialog is a :class:`StepsEditorDialog` subclass (single sequence
edit source), so the manual-adjustment cases drive the shared list /
button API instead of the removed table helpers.
"""
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
    """The seed is the canonical sequence: per power net impedance then
    voltage, then the clock nets, wrapped in the standard-operation
    skeleton (R-GND before Power On DUT, voltage after it)."""
    dlg = make_dialog()
    try:
        rows = dlg.result_data()[0]
        names = [r[1] for r in rows]
        assert names == [
            "Init Instruments", "Fixture Clamp Down", "Fixture Lock",
            "Fixture E-Stop Healthy",
            "R-GND - 1V8_CORE", "R-GND - 3V3",
            "Power On DUT",
            "Power Voltage - 1V8_CORE", "Power Voltage - 3V3",
            "Clock Hz - CLK_24M",
            "Power Off DUT", "Fixture Unlock", "Fixture Release",
            "Reset Instruments",
        ]
        assert names.index("R-GND - 3V3") < names.index("Power On DUT") \
            < names.index("Power Voltage - 3V3")
        units = [r[2] for r in rows]
        assert units[4:10] == ["Ω", "Ω", "—", "V", "V", "Hz"]
    finally:
        dlg.deleteLater()


def test_move_up_down_and_duplicate(qapp):
    dlg = make_dialog()
    try:
        idx = next(i for i, r in enumerate(dlg._steps)
                   if r[1] == "Power Voltage - 1V8_CORE")
        dlg.select_row(idx)
        dlg._on_move_up()
        assert dlg._steps[idx - 1][1] == "Power Voltage - 1V8_CORE"
        dlg._on_move_down()
        assert dlg._steps[idx][1] == "Power Voltage - 1V8_CORE"
        before = len(dlg.result_data()[0])
        dlg._on_duplicate()
        assert len(dlg.result_data()[0]) == before + 1
        assert dlg._steps[idx + 1][1] == "Power Voltage - 1V8_CORE"
        dlg._on_remove()
        assert len(dlg.result_data()[0]) == before
    finally:
        dlg.deleteLater()


def test_rapid_moves_stay_clamped_and_ordered(qapp):
    """Smoothness contract: rapid Move Up clicks stay clamped at the top
    and the shared list stays in sync with result_data()."""
    dlg = make_dialog()
    try:
        name = "Power Voltage - 1V8_CORE"
        idx = next(i for i, r in enumerate(dlg._steps) if r[1] == name)
        dlg.select_row(idx)
        for _ in range(idx + 2):
            dlg._on_move_up()                      # rapid repeated clicks
        assert dlg.list_widget.currentRow() == 0   # clamped at the top
        assert dlg._steps[0][1] == name
        assert len(dlg.result_data()[0]) == dlg.list_widget.count()
        labels = [dlg.list_widget.item(r).text()
                  for r in range(dlg.list_widget.count())]
        assert name in labels[0]
    finally:
        dlg.deleteLater()


def test_double_click_opens_the_row_editor(qapp, monkeypatch):
    """Double-clicking a row opens the shared row editor for THAT row
    and the accepted values replace it (user direction)."""
    dlg = make_dialog()
    try:
        edited = []

        def fake_edit(r):
            edited.append(r)
            dlg._steps[r] = ("test", "Power Voltage - 3V3", "V",
                             "—", "3.135", "3.465")
            return True

        monkeypatch.setattr(dlg, "_edit_ict_step", fake_edit)
        dlg.list_widget.setCurrentRow(1)           # R-GND - 3V3
        dlg._on_edit()
        assert edited == [1]
        assert dlg.result_data()[0][1] == ("test", "Power Voltage - 3V3",
                                           "V", "—", "3.135", "3.465")
        assert dlg.list_widget.currentRow() == 1   # selection kept
    finally:
        dlg.deleteLater()


def test_auto_fills_limits_from_net_names(qapp):
    """Auto fills Min / Max from the parsed nominal: power +/- 5 %,
    clock +/- 50 ppm; impedance rows (no nominal) stay untouched."""
    from mtkgui.gui.yamlbuild.ict_sequence import expected_hz, expected_voltage
    assert expected_voltage("P3V3_LDO") == 3.3
    assert expected_voltage("MCU_1V8") == 1.8
    assert expected_voltage("VIN_24V") == 24.0
    # "V" followed by "_" (a word char) is still the plain form: the old
    # \b boundary rejected 12V_DECT_1 and the rail showed 0.000 V
    assert expected_voltage("12V_DECT_1") == 12.0
    assert expected_voltage("12V0_IN_PWR_EN_B") == 12.0
    assert expected_voltage("5V_SYS") == 5.0
    assert expected_voltage("VCC_OSC_AUXCLKIN") is None
    assert expected_voltage("VBAT_SENSE") is None
    assert expected_voltage("GND") is None
    assert expected_hz("CLK_24M") == 24e6
    assert expected_hz("OSC_125M") == 125e6
    assert expected_hz("CLK_32K") == 32e3
    assert expected_hz("GPIO_LED1") is None

    dlg = make_dialog()
    try:
        # the dialog seeds with auto-filled limits at construction (the
        # old table-level _auto() step is gone: Auto is the seed now)
        rows = {r[1]: r for r in dlg.result_data()[0]}
        # power: expected 1.800 V, +/- 5 %, 0.001 V precision
        assert rows["Power Voltage - 1V8_CORE"][3] == "1.800"
        assert rows["Power Voltage - 1V8_CORE"][4] == "1.710"
        assert rows["Power Voltage - 1V8_CORE"][5] == "1.890"
        # clock: expected 24000000.0 Hz, +/- 50 ppm, 0.1 Hz precision
        assert rows["Clock Hz - CLK_24M"][3] == "24000000.0"
        assert rows["Clock Hz - CLK_24M"][4] == "23998800.0"
        assert rows["Clock Hz - CLK_24M"][5] == "24001200.0"
        # impedance: no nominal parsed -> untouched
        assert rows["R-GND - 1V8_CORE"][3] == "—"
        assert rows["R-GND - 1V8_CORE"][4] == "—"
    finally:
        dlg.deleteLater()


def test_add_row_lands_at_the_end(qapp, monkeypatch):
    """The shared Add inserts the chosen step after the current row and
    the accepted row joins the whole-sequence result."""
    dlg = make_dialog()
    try:
        monkeypatch.setattr(dlg, "_on_edit", lambda *a, **k: None)
        before = len(dlg.result_data()[0])
        dlg._on_add(("test", "Power Voltage - 3V3", "V", "—",
                     "3.201", "3.399"))
        rows = dlg.result_data()[0]
        assert len(rows) == before + 1
        assert rows[-1] == ("test", "Power Voltage - 3V3", "V", "—",
                            "3.201", "3.399")
    finally:
        dlg.deleteLater()
