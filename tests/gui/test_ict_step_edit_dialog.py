# -*- coding: utf-8 -*-
"""Step edit dialog (_SequenceEditorDialog ICT): Test Method first,
Unit auto-filled, numeric Measured/Min/Max and the per-method Net
combo (choices follow the Test Method)."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

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


def test_net_choices_follow_the_method(qapp):
    """Impedance / voltage / DAQ AI -> Power nets, Clock Hz -> Clock
    nets, generic test -> GPIO nets; unknown methods only the
    placeholder."""
    dlg = make_dialog(None)
    try:
        assert dlg._net_choices("Static Impedance") == \
            ["1V8_CORE", "3V3"]
        assert dlg._net_choices("Clock Hz") == ["CLK_24M"]
        assert dlg._net_choices("test") == ["GPIO_LED1"]
        assert dlg._net_choices("op") == ["—"]
    finally:
        dlg.deleteLater()


def test_unit_map_covers_all_methods(qapp):
    dlg = make_dialog(None)
    try:
        assert dlg.ICT_METHOD_UNITS["Static Impedance"] == "Ω"
        assert dlg.ICT_METHOD_UNITS["Power Voltage"] == "V"
        assert dlg.ICT_METHOD_UNITS["Clock Hz"] == "Hz"
    finally:
        dlg.deleteLater()


def test_edit_ict_step_round_trip(qapp, monkeypatch):
    """The dialog writes the chosen net, the auto unit and the numeric
    limits back into the step tuple (exec mocked to OK)."""
    dlg = make_dialog(None)
    try:
        captured = {}

        def fake_exec(dialog_self):
            from PySide6.QtWidgets import (
                QComboBox,
                QDoubleSpinBox,
                QLineEdit,
            )
            combos = dialog_self.findChildren(QComboBox)
            # the step edit dialog is the second window-level combo
            # group: find the one with the Test Method items
            step_dlg = dialog_self
            combos = [c for c in combos
                      if c.count() and c.itemText(0) in
                      ("op", "test", "Static Impedance")]
            kind_combo = None
            for c in combos:
                if c.currentText() in ("test", "op") or \
                        c.itemText(0) == "op":
                    kind_combo = c
                    break
            assert kind_combo is not None
            kind_combo.setCurrentText("Static Impedance")
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
            from PySide6.QtWidgets import QLineEdit
            captured["unit"] = next(
                e.text() for e in step_dlg.findChildren(QLineEdit)
                if e.isReadOnly())
            return step_dlg.DialogCode.Accepted

        monkeypatch.setattr(
            "mtkgui.test_workflow_page.QDialog.exec", fake_exec)
        assert dlg._edit_ict_step(0) is True
        kind, name, unit, measured, lo, hi = dlg._steps[0][:6]
        assert kind == "Static Impedance"
        assert name == "3V3"
        assert unit == "Ω" and captured["unit"] == "Ω"
        assert measured == "2"
        assert lo == "1.2" and hi == "2.4"
    finally:
        dlg.deleteLater()
