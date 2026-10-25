# -*- coding: utf-8 -*-
"""Step edit dialog (_SequenceEditorDialog ICT): Test Method first,
Unit auto-filled, numeric Measured/Min/Max and the per-method Net
combo (choices follow the Test Method)."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import (QApplication, QComboBox,  # noqa: E402
                               QDialog)

from mtkgui.test_workflow_page import _SequenceEditorDialog  # noqa: E402

TESTABLE = {
    "3V3": {"category": "Power", "members": ["U1.5"]},
    "1V8_CORE": {"category": "Power", "members": ["U1.2"]},
    "CLK_24M": {"category": "Clock", "members": ["U1.10"]},
    "GPIO_LED1": {"category": "GPIO", "members": ["U1.20"]},
}

STEPS = [
    ("test", "Power Voltage (80 pts)", "V", "80/80", "3.201", "3.399"),
    ("test", "CLKOUT1 (CTR0)", "Hz", "4000200", "3996000", "4004000"),
]


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def page(qapp):
    w = QApplication.instance()
    yield w


def make_dialog(page):
    dlg = _SequenceEditorDialog("ict", list(STEPS), [True, True],
                                [100, 100], [5000, 5000])
    dlg.net_catalog_provider = lambda: dict(TESTABLE)
    return dlg


def test_flash_step_editor_writes_the_dual_path_params(qapp, monkeypatch):
    """user direction 2026-10-17 (R1): the Flash step editor exposes
    the dual-path switch, the programmer tool and the image.  Picking
    "manual" rebuilds the form with the third-party GUI rows, and the
    edited values must land in the step op_params (the YAML keeps
    them)."""
    flash = ("op", "Flash FAT Firmware", "—", "—", "—", "—",
             {"type": "flash", "slot": "fat", "mode": "auto"})
    dlg = _SequenceEditorDialog("ict", [flash], [True], [100], [5000])
    try:
        def fake_exec(widget):
            for cb in widget.findChildren(QComboBox):
                if [cb.itemText(i) for i in range(cb.count())] == \
                        ["auto", "manual"]:
                    cb.setCurrentText("manual")   # rebuilds the form
                    break
            return QDialog.DialogCode.Accepted

        monkeypatch.setattr(QDialog, "exec", fake_exec)
        assert dlg._edit_op_step(0, dlg._steps[0]) is True
        params = dlg._steps[0][6]
        assert params["type"] == "flash"
        assert params["slot"] == "fat"
        assert params["mode"] == "manual"
        assert params["tool"]                 # the programmer tool name
        assert "launch" in params             # manual-only rows present
        assert "message" in params
        assert "message_timeout_s" in params
        assert params["verify"] is True
        assert params["reset_run"] is True
        assert params["erase"] is False
    finally:
        dlg.deleteLater()


def test_net_choices_follow_the_method(qapp):
    """Impedance / voltage / DAQ AI -> Power nets, Clock Hz -> Clock
    nets, generic test -> GPIO nets; unknown methods only the
    placeholder."""
    dlg = make_dialog(None)
    try:
        assert dlg._net_choices("R-GND") == \
            ["1V8_CORE", "3V3"]
        assert dlg._net_choices("Clock Hz") == ["CLK_24M"]
        assert dlg._net_choices("test") == ["GPIO_LED1"]
        assert dlg._net_choices("op") == ["—"]
    finally:
        dlg.deleteLater()


def test_unit_map_covers_all_methods(qapp):
    dlg = make_dialog(None)
    try:
        assert dlg.ICT_METHOD_UNITS["R-GND"] == "Ω"
        assert dlg.ICT_METHOD_UNITS["Power Voltage"] == "V"
        assert dlg.ICT_METHOD_UNITS["Clock Hz"] == "Hz"
        # the plain Delay wait step reuses the per-step Wait (ms) field
        assert dlg.ICT_METHOD_UNITS["delay"] == "ms"
    finally:
        dlg.deleteLater()


def test_ict_add_menu_offers_ops_flash_and_delay(qapp):
    """Single sequence source: the ICT Add menu offers the standard
    operations (incl. the flash operations) AND the Delay step - the
    three categories the user asked for live in the ONE editor."""
    dlg = make_dialog(None)
    try:
        actions = [a.text() for a in dlg.btn_add.menu().actions()]
        assert "Operation: Init Instruments" in actions
        assert "Operation: Flash FAT Firmware" in actions
        assert "Operation: Flash OOBE Firmware" in actions
        assert "Delay — plain wait (ms)" in actions
    finally:
        dlg.deleteLater()


def test_remove_last_row_allowed(qapp):
    """User direction 2026-10-14: zero test items are legal per stage
    (ICT-only / FCT-only - only the BOTH-empty case warns elsewhere):
    the Remove button stays enabled at one row and the dialog can OK
    an EMPTY sequence."""
    dlg = make_dialog(None)
    try:
        assert len(dlg._steps) == 2
        dlg.list_widget.setCurrentRow(1)
        assert dlg.btn_remove.isEnabled()
        dlg.btn_remove.click()
        assert len(dlg._steps) == 1
        dlg.list_widget.setCurrentRow(0)
        dlg.btn_remove.click()
        assert dlg._steps == []
        assert not dlg.btn_remove.isEnabled()
        assert dlg.result_data()[0] == []
    finally:
        dlg.deleteLater()

    fct = _SequenceEditorDialog(
        "fct", ["MessageOK: All Done"], [True], [100], [5000],
        kinds=["MessageOK"], op_params=[None])
    try:
        fct.list_widget.setCurrentRow(0)
        fct.btn_remove.click()
        assert fct._steps == []
        assert fct.result_data() == ([], [], [], [], [], [])
    finally:
        fct.deleteLater()


def test_edit_ict_step_round_trip(qapp, monkeypatch):
    """M19f: a Voltage row saves 3 decimals; the R-GND row saves an
    integer Min with Expected/Max locked to "—" (exec mocked to OK)."""
    dlg = make_dialog(None)
    try:
        captured = {}

        def fake_exec(dialog_self):
            from PySide6.QtWidgets import (
                QComboBox,
                QDoubleSpinBox,
                QLineEdit,
            )
            step_dlg = dialog_self
            combos = [c for c in step_dlg.findChildren(QComboBox)
                      if c.count() and c.itemText(0) in
                      ("R-GND", "Voltage", "DAQ AI Sequences",
                       "Clock Hz", "delay")]
            # M19f: the Test Method combo offers the concrete labels
            kind_combo = next(c for c in combos
                              if c.currentText() in
                              ("R-GND", "Voltage", "DAQ AI Sequences",
                               "Clock Hz", "delay"))
            # row 0 is a legacy "test" / Power Voltage row -> switch the
            # Test Method to the Voltage label first
            kind_combo.setCurrentText("Voltage")
            # net combo: the combo whose items contain a catalog net
            net_combo = next(c for c in
                             step_dlg.findChildren(QComboBox)
                             if "3V3" in [c.itemText(i) for i in
                                          range(c.count())])
            net_combo.setCurrentText("3V3")
            spins = [s for s in
                     step_dlg.findChildren(QDoubleSpinBox)]
            # Measured / Min / Max are the last three numeric fields
            spins[-3].setValue(2.0)
            spins[-2].setValue(1.2)
            spins[-1].setValue(2.4)
            captured["unit"] = next(
                e.text() for e in step_dlg.findChildren(QLineEdit)
                if e.isReadOnly())
            return step_dlg.DialogCode.Accepted

        monkeypatch.setattr(
            "mtkgui.test_workflow_page.QDialog.exec", fake_exec)
        assert dlg._edit_ict_step(0) is True
        kind, name, unit, measured, lo, hi = dlg._steps[0][:6]
        # M19f: Voltage keeps 3 decimals for Expected / Min / Max
        assert kind == "Power Voltage", kind
        assert name == "3V3"
        assert unit == "V" and captured["unit"] == "V"
        assert measured == "2.000"
        assert lo == "1.200" and hi == "2.400"

        # M19f: the R-GND row saves an INTEGER Min; Expected / Max are
        # locked to "—" even if the caller set a numeric value
        def fake_exec_rgnd(dialog_self):
            from PySide6.QtWidgets import (
                QComboBox,
                QDoubleSpinBox,
            )
            step_dlg = dialog_self
            combos = [c for c in step_dlg.findChildren(QComboBox)
                      if c.count() and c.itemText(0) in
                      ("R-GND", "Voltage", "DAQ AI Sequences",
                       "Clock Hz", "delay")]
            kind_combo = next(c for c in combos
                              if c.currentText() in
                              ("R-GND", "Voltage", "DAQ AI Sequences",
                               "Clock Hz", "delay"))
            kind_combo.setCurrentText("R-GND")
            net_combo = next(c for c in
                             step_dlg.findChildren(QComboBox)
                             if "3V3" in [c.itemText(i) for i in
                                          range(c.count())])
            net_combo.setCurrentText("3V3")
            spins = [s for s in
                     step_dlg.findChildren(QDoubleSpinBox)]
            # Expected stays locked at "—" (a numeric set would count
            # as a bound and clamp the Min below it - correct policy)
            spins[-2].setValue(30.0)     # Min: integer
            spins[-1].setValue(2.4)      # ignored: Max locked
            return step_dlg.DialogCode.Accepted

        monkeypatch.setattr(
            "mtkgui.test_workflow_page.QDialog.exec", fake_exec_rgnd)
        assert dlg._edit_ict_step(0) is True
        kind, name, unit, measured, lo, hi = dlg._steps[0][:6]
        assert kind == "R-GND", kind
        assert measured == "—", measured
        assert lo == "30", lo
        assert hi == "—", hi
    finally:
        dlg.deleteLater()
