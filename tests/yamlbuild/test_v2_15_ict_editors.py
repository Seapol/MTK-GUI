# -*- coding: utf-8 -*-
"""v2-15 E: per-type ICT row editors (R2/R5/R6/R7/R8)."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QDialog, QDoubleSpinBox

from mtkgui.gui.yamlbuild.ict_sequence_v2 import (
    KIND_CLOCK_HZ,
    KIND_POWER_VOLTAGE,
    KIND_RGND,
    IctStep,
    emit_sequence,
    parse_sequence,
)
from mtkgui.gui.yamlbuild.ict_sequence_v2_panel import (
    _edit_ict_row,
    _spin,
    BuildIctSequencePanel,
)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_spin_step_is_decoupled():
    assert _spin(0).singleStep() == 1
    assert _spin(3).singleStep() == 0.001


def test_limit_fields_round_trip():
    step = IctStep(name="R-GND - 3V3", kind=KIND_RGND, net="3V3",
                   min_val="30", max_val="")
    back = parse_sequence(emit_sequence([step]))
    assert back[0].min_val == "30"
    assert back[0].max_val == ""


def test_rgnd_editor_has_only_min_max(qapp, monkeypatch):
    seen = {}

    def fake_exec(dlg):
        seen["spins"] = len(dlg.findChildren(QDoubleSpinBox))
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(QDialog, "exec", fake_exec)
    step = IctStep(name="R-GND - 3V3", kind=KIND_RGND, net="3V3")
    assert _edit_ict_row(None, step) is False
    assert seen["spins"] == 2          # Min + Max only, no Expected


def test_voltage_editor_writes_expected_min_max(qapp, monkeypatch):
    def fake_exec(dlg):
        spins = dlg.findChildren(QDoubleSpinBox)
        # order: Expected, Min, Max
        spins[0].setValue(1.800)
        spins[1].setValue(1.710)
        spins[2].setValue(1.890)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(QDialog, "exec", fake_exec)
    step = IctStep(name="Power Voltage - 1V8", kind=KIND_POWER_VOLTAGE,
                   net="1V8")
    assert _edit_ict_row(None, step) is True
    assert step.expected == "1.800"
    assert step.min_val == "1.710"
    assert step.max_val == "1.890"


def test_clock_editor_writes_expected_ppm_min_max(qapp, monkeypatch):
    def fake_exec(dlg):
        spins = dlg.findChildren(QDoubleSpinBox)
        # order: Expected, ppm, Min, Max
        spins[0].setValue(24000000)
        spins[1].setValue(50)
        spins[2].setValue(23998800)
        spins[3].setValue(24001200)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(QDialog, "exec", fake_exec)
    step = IctStep(name="Clock Hz - CLK_24M", kind=KIND_CLOCK_HZ,
                   net="CLK_24M")
    assert _edit_ict_row(None, step) is True
    assert step.expected == "24000000"
    assert step.ppm == "50"
    assert step.min_val == "23998800"
    assert step.max_val == "24001200"


def test_double_click_dispatches_to_editor(qapp, monkeypatch):
    panel = BuildIctSequencePanel()
    panel.generate(["3V3"], ["CLK_24M"], rails_enabled=False)
    edited = []

    def fake_edit(_parent, step):
        edited.append(step.name)
        return True

    monkeypatch.setattr("mtkgui.gui.yamlbuild.ict_sequence_v2_panel."
                        "_edit_ict_row", fake_edit)
    # the first data row is "Init Instruments" (a header precedes it)
    panel.table.cellDoubleClicked.emit(1, 0)
    assert edited and edited[0] == "Init Instruments"
    panel.deleteLater()
