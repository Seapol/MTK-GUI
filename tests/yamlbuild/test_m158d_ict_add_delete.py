# -*- coding: utf-8 -*-
"""M158d: node 05 can add and delete test rows.

The generated sequence is a starting point; ``Add test`` gives a manual
measurement row inside the measurement area, ``Delete step`` removes a
selected test row while the fixed frame operations stay.
"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

import mtkgui.gui.yamlbuild.ict_sequence_v2_panel as panel_module  # noqa: E402
from mtkgui.gui.yamlbuild.ict_sequence_v2 import (  # noqa: E402
    KIND_OP,
    KIND_RGND,
    OP_INSTRUMENTS,
    OP_POWER,
    OP_RESET,
    POWER_OFF,
    POWER_ON,
    IctStep,
)
from mtkgui.gui.yamlbuild.ict_sequence_v2_panel import (  # noqa: E402
    BuildIctSequencePanel,
)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _frame_sequence() -> list:
    return [
        IctStep(name="Init Instruments", kind=KIND_OP,
                op_type=OP_INSTRUMENTS),
        IctStep(name="Power On DUT", kind=KIND_OP, op_type=OP_POWER,
                power_state=POWER_ON),
        IctStep(name="Power Off DUT", kind=KIND_OP, op_type=OP_POWER,
                power_state=POWER_OFF),
        IctStep(name="Reset Instruments", kind=KIND_OP, op_type=OP_RESET),
    ]


def _panel(qapp) -> BuildIctSequencePanel:
    panel = BuildIctSequencePanel()
    panel.set_sequence(_frame_sequence())
    return panel


def test_add_test_button_exists(qapp):
    panel = _panel(qapp)
    try:
        assert panel.btn_add.text() == "Add test"
        assert panel.btn_delete.text() == "Delete step"
        head = panel.layout().itemAt(0).layout()
        assert head.itemAt(2).widget() is panel.btn_add
        assert head.itemAt(3).widget() is panel.btn_delete
        assert head.itemAt(4).widget() is panel.btn_move_up
    finally:
        panel.deleteLater()


def test_add_test_inserts_measurement_row(qapp, monkeypatch):
    monkeypatch.setattr(panel_module, "_edit_ict_row",
                        lambda parent, step: False)
    panel = _panel(qapp)
    try:
        panel.btn_add.click()
        steps = panel.sequence()
        assert len(steps) == 5
        added = steps[2]
        assert added.kind == KIND_RGND
        assert added.name == "R-GND - New net"
        # inside the measurement area: after Power On, before Power Off
        assert steps[1].name == "Power On DUT"
        assert steps[3].name == "Power Off DUT"
    finally:
        panel.deleteLater()


def test_delete_step_keeps_fixed_frame_ops(qapp, monkeypatch):
    monkeypatch.setattr(panel_module, "_edit_ict_row",
                        lambda parent, step: False)
    panel = _panel(qapp)
    try:
        panel.btn_add.click()
        steps = panel.sequence()
        added = steps[2]
        for row in range(panel.table.rowCount()):
            if panel._step_at_row(row) is added:
                panel.table.setCurrentCell(row, 0)
                break
        panel._on_delete_selected()
        assert len(panel.sequence()) == 4
        assert all(step.name != "R-GND - New net"
                   for step in panel.sequence())

        # the three frame ops are not deletable
        power_off = panel.sequence()[2]
        for row in range(panel.table.rowCount()):
            if panel._step_at_row(row) is power_off:
                panel.table.setCurrentCell(row, 0)
                break
        panel._on_delete_selected()
        assert len(panel.sequence()) == 4
        names = [step.name for step in panel.sequence()]
        assert names == ["Init Instruments", "Power On DUT",
                         "Power Off DUT", "Reset Instruments"]
    finally:
        panel.deleteLater()


def test_add_test_opens_the_row_editor(qapp, monkeypatch):
    seen: list = []
    monkeypatch.setattr(panel_module, "_edit_ict_row",
                        lambda parent, step: seen.append(step) or False)
    panel = _panel(qapp)
    try:
        panel.btn_add.click()
        assert len(seen) == 1
        assert seen[0].name == "R-GND - New net"
        assert seen[0].kind == KIND_RGND
    finally:
        panel.deleteLater()
