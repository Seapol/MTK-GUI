# -*- coding: utf-8 -*-
"""v2-11 (node 05) Build ICT Test Sequence Qt panel."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from mtkgui.gui.yamlbuild.ict_sequence_v2_panel import (  # noqa: E402
    BuildIctSequencePanel)
from mtkgui.gui.yamlbuild.wizard_shell import YamlBuildWizard  # noqa: E402


def test_panel_renders_blocks():
    panel = BuildIctSequencePanel()
    try:
        panel.generate(["VDD1"], ["CLK1"], rails_enabled=False)
        # Init + Fixture Ready + R-GND + Power On + Voltage + Clock
        # + Power Off + Reset = 8 steps
        assert len(panel.sequence()) == 8
        # block headers are rendered as extra spanned rows
        assert panel.table.rowCount() > 8
    finally:
        panel.deleteLater()


def test_panel_validate_ok_and_bad():
    panel = BuildIctSequencePanel()
    try:
        panel.generate(["VDD1"], ["CLK1"], rails_enabled=False)
        assert panel.validate() == (True, "")
        # drop the Reset step -> the gate fails
        panel.set_sequence(panel.sequence()[:-1])
        ok, msg = panel.validate()
        assert not ok
        assert "end with Reset Instruments" in msg
    finally:
        panel.deleteLater()


def test_panel_timeout_edit_syncs_to_step():
    panel = BuildIctSequencePanel()
    try:
        panel.generate(["VDD1"], [], rails_enabled=False)
        # find the Timeout cell of the R-GND step (row index 2 after two
        # block headers are gone - walk the column until a UserRole step)
        rgnd = next(s for s in panel.sequence() if s.kind == "R-GND")
        # set the timeout through the model and re-render, then edit a cell
        from PySide6.QtCore import Qt
        for r in range(panel.table.rowCount()):
            item = panel.table.item(r, 6)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) is rgnd:
                item.setText("1500")
                break
        assert rgnd.timeout_ms == 1500
        # empty string -> None
        for r in range(panel.table.rowCount()):
            item = panel.table.item(r, 6)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) is rgnd:
                item.setText("")
                break
        assert rgnd.timeout_ms is None
    finally:
        panel.deleteLater()


def test_wizard_build_ict_panel_generates():
    wizard = YamlBuildWizard()
    try:
        panel = wizard._panels["build_ict"]
        assert panel is not None
        # no power/clock nets yet -> a minimal, still-valid sequence
        # (Init + Fixture Ready + Power On + Power Off + Reset)
        assert len(panel.sequence()) == 5
    finally:
        wizard.deleteLater()
