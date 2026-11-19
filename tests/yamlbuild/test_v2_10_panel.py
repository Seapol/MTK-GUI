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


def test_instruments_gate_other_tabs():
    panel = EquipmentConfigPanel()
    try:
        # tabs 2-7 are disabled until the instrument check runs
        for index in range(1, panel.tabs.count()):
            assert panel.tabs.isTabEnabled(index) is False
        panel.btn_check.click()
        for index in range(1, panel.tabs.count()):
            assert panel.tabs.isTabEnabled(index) is True
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


def test_wizard_gate_blocks_next():
    wizard = YamlBuildWizard()
    try:
        wizard.goto("equipment")
        panel = wizard._panels["equipment"]
        # gate fails until the instrument check runs
        wizard._refresh()
        assert wizard.btn_next.isEnabled() is False
        panel.btn_check.click()
        wizard._refresh()
        assert wizard.btn_next.isEnabled() is True
    finally:
        wizard.deleteLater()
