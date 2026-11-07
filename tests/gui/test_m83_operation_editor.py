# -*- coding: utf-8 -*-
"""M83 C9: Operation editor - no Enable/Wait/Timeout, passive power rows."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QCheckBox,
    QDialog,
    QDoubleSpinBox,
    QLabel,
    QSpinBox,
)

from mtkgui.gui.steps_editor import edit_op_step_dialog  # noqa: E402

EQUIPMENT = {"psu": {"params": {"Voltage set (V)": "5.0",
                                "Current limit (A)": "1.0",
                                "OVP (V)": "15.0"}}}


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _open(monkeypatch, name, params, equipment=EQUIPMENT) -> QDialog:
    seen: list = []

    def fake_exec(dlg):
        seen.append(dlg)
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(QDialog, "exec", fake_exec)
    edit_op_step_dialog(None, name, dict(params), True, 100, 5000,
                        equipment=equipment)
    assert seen, "the operation dialog never opened"
    return seen[0]


def _labels(dlg) -> list:
    return [label.text() for label in dlg.findChildren(QLabel)]


def test_m83_operation_dialog_has_no_enable_wait_timeout(qapp, monkeypatch):
    dlg = _open(monkeypatch, "Init Instruments",
                {"type": "instruments", "instruments": ["DAQM", "PSU"]})
    texts = _labels(dlg)
    assert not any(text.startswith("Enable:") for text in texts)
    assert not any(text.startswith("Wait:") for text in texts)
    assert not any(text.startswith("Timeout:") for text in texts)
    # no enable checkbox at all
    assert not any(cb.text() == "" for cb in dlg.findChildren(QCheckBox))


def test_m83_power_on_setpoints_are_read_only_from_equipment(
        qapp, monkeypatch):
    dlg = _open(monkeypatch, "Power On DUT", {"type": "power", "state": "on"})
    line = " ".join(_labels(dlg))
    assert "Voltage 5 V" in line
    assert "Current limit 1 A" in line
    assert "OVP 15 V" in line
    assert "(from Equipment ▸ N5747A)" in line
    assert "Setpoints are configured on the Equipment page (N5747A)." \
        in line


def test_m83_power_on_dialog_has_no_setpoint_inputs(qapp, monkeypatch):
    dlg = _open(monkeypatch, "Power On DUT", {"type": "power", "state": "on"})
    assert not dlg.findChildren(QDoubleSpinBox)
    assert not dlg.findChildren(QSpinBox)


def test_m83_power_off_shows_no_setpoint_controls(qapp, monkeypatch):
    dlg = _open(monkeypatch, "Power Off DUT", {"type": "power", "state": "off"},
                equipment={})
    texts = _labels(dlg)
    assert any("N5747A output OFF — no setpoints." in text for text in texts)
    assert not any("from Equipment" in text for text in texts)
    assert not dlg.findChildren(QDoubleSpinBox)


def test_m83_power_on_missing_equipment_params_is_build_error(qapp):
    from mtkgui.gui.yamlbuild.FCTTestConfigWidget import FCTTestConfigPanel

    panel = FCTTestConfigPanel(
        equipment_provider=lambda: {"equipment": {"psu": {"params": {}}}})
    panel.set_values({})
    panel._add_operation_row("Power On DUT")
    errors = panel.validation_errors()
    assert any("'Voltage set (V)'" in error and "'Current limit (A)'" in error
               for error in errors)
    panel.deleteLater()
