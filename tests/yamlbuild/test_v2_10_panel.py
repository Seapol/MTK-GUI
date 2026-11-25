# -*- coding: utf-8 -*-
"""v2-10 (node 04) Equipment Config Qt panel."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from mtkgui.gui.yamlbuild.equipment_config import (  # noqa: E402
    PowerRow, SOURCE_ADAPTER, EquipmentConfig)
from mtkgui.gui.yamlbuild.equipment_panel import (  # noqa: E402
    EquipmentConfigPanel)
from mtkgui.gui.yamlbuild.wizard_shell import YamlBuildWizard  # noqa: E402


def test_instruments_gate_other_tiles():
    panel = EquipmentConfigPanel()
    try:
        # M131: every tile but Instruments is locked until the check runs
        assert panel.tiles["instruments"].isEnabled() is True
        for key, tile in panel.tiles.items():
            if key == "instruments":
                continue
            assert tile.isEnabled() is False
        panel.btn_check.click()
        for key, tile in panel.tiles.items():
            assert tile.isEnabled() is True
    finally:
        panel.deleteLater()


def test_validate_blocks_until_check():
    panel = EquipmentConfigPanel()
    try:
        ok, item = panel.validate()
        assert not ok
        assert "instrument check not run" in item
        panel.btn_check.click()
        # a freshly checked, fully-default config still needs channels
        ok, item = panel.validate()
        # empty power/clock rows means nothing to allocate -> valid
        assert ok is True
    finally:
        panel.deleteLater()


def test_set_values_round_trip():
    panel = EquipmentConfigPanel()
    try:
        cfg = EquipmentConfig()
        cfg.check_run = True
        cfg.source = SOURCE_ADAPTER
        cfg.power_rows = [PowerRow(net="VDD1", channel="daqm908a_1:1")]
        panel.set_values(cfg)
        out = panel.values()
        assert out.source == SOURCE_ADAPTER
        assert out.power_rows[0].channel == "daqm908a_1:1"
    finally:
        panel.deleteLater()


def test_wizard_equipment_node_marks_invalid_until_checked():
    wizard = YamlBuildWizard()
    try:
        wizard.goto("equipment")
        # M128: 03/04 need 01 and 02 (and 03) locked to be reachable
        for key in ("design_input", "firmware", "parse_ict"):
            wizard.model.set_locked(key, True)
        wizard._refresh()
        # the gate fails until the instrument check runs -> invalid node
        assert wizard.flow.step_state("equipment") == "invalid"
        # M127: no page-level [Next] any more - the node windows carry
        # the actions (Save Draft / Next) themselves
        assert not hasattr(wizard, "btn_next")
        assert not hasattr(wizard, "btn_save_draft")
        wizard._panels["equipment"].btn_check.click()
        wizard._refresh()
        assert wizard.flow.step_state("equipment") == "valid"
    finally:
        wizard.deleteLater()
