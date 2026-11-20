# -*- coding: utf-8 -*-
"""v2-15 G: bare-metal gating + same-type ICT reorder."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from mtkgui.engine.fct_test_config import (
    STEP_TYPE_BT_PAIR,
    STEP_TYPE_BT_TONE,
    STEP_TYPE_CONSOLE_SERIAL,
    STEP_TYPE_CONSOLE_SSH,
    STEP_TYPE_SERIAL_PULL,
    STEP_TYPE_SERIAL_PUT,
    STEP_TYPE_SFTP_GET,
    STEP_TYPE_SFTP_PUT,
    STEP_TYPE_WIFI_IPERF,
    STEP_TYPE_WIFI_PING,
)
from mtkgui.gui.yamlbuild.FCTTestConfigWidget import FCTTestConfigPanel
from mtkgui.gui.yamlbuild.ict_sequence_v2_panel import BuildIctSequencePanel


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


_BARE_METAL_DISABLED = (
    STEP_TYPE_CONSOLE_SSH, STEP_TYPE_SFTP_PUT, STEP_TYPE_SFTP_GET,
    STEP_TYPE_SERIAL_PUT, STEP_TYPE_SERIAL_PULL, STEP_TYPE_WIFI_PING,
    STEP_TYPE_WIFI_IPERF, STEP_TYPE_BT_PAIR, STEP_TYPE_BT_TONE,
)


def test_bare_metal_disables_unsupported_add_entries(qapp):
    panel = FCTTestConfigPanel()
    panel.set_values({})
    panel.dut_type.setCurrentText("bare_metal")
    for label in _BARE_METAL_DISABLED:
        act = panel._add_actions.get(label)
        assert act is not None, label
        assert not act.isEnabled(), label
    assert panel._add_actions[STEP_TYPE_CONSOLE_SERIAL].isEnabled()
    panel.deleteLater()


def _row_of(panel, name: str) -> int:
    for r in range(panel.table.rowCount()):
        step = panel._step_at_row(r)
        if step is not None and step.name == name:
            return r
    raise AssertionError(f"row {name!r} not found")


def test_same_block_move_reorders(qapp):
    panel = BuildIctSequencePanel()
    panel.generate(["3V3", "1V8"], ["CLK_24M"], rails_enabled=False)
    # two R-GND rows share the OHM block -> a same-block move works
    row = _row_of(panel, "R-GND - 3V3")
    panel.table.setCurrentCell(row, 0)
    before = [s.name for s in panel.sequence()]
    panel._move(1)
    after = [s.name for s in panel.sequence()]
    assert after != before
    assert after.index("R-GND - 3V3") == before.index("R-GND - 3V3") + 1
    assert after.index("R-GND - 1V8") == before.index("R-GND - 1V8") - 1
    panel.deleteLater()


def test_cross_block_move_refused(qapp):
    panel = BuildIctSequencePanel()
    panel.generate(["3V3"], ["CLK_24M"], rails_enabled=False)
    # Power Voltage (DCV block) -> a move down into the clock block is
    # refused (different blocks).
    row = _row_of(panel, "Power Voltage - 3V3")
    panel.table.setCurrentCell(row, 0)
    before = [s.name for s in panel.sequence()]
    panel._move(1)
    assert [s.name for s in panel.sequence()] == before
    panel.deleteLater()
