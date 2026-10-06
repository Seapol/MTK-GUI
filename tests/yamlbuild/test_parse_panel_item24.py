# -*- coding: utf-8 -*-
"""Item 24 GUI integration: Parse nets panel tools (rules editor
button, power tree editor, SE clock / GPIO allocation tables) and the
model YAML persistence of the new sections."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from mtkgui.gui.yamlbuild.parse_nets import ParseNetsPanel  # noqa: E402
from tests.yamlbuild.conftest import fill_required  # noqa: E402
from mtkgui.gui.yamlbuild.power_alloc import (  # noqa: E402
    CLOCK_CHANNELS,
    GPIO_DIO_CHANNELS,
)

NET_TEXT = """*SIGNAL* VIN_24V
R5.1 U1.1
*SIGNAL* VDD_12V
R5.2 U1.2
*SIGNAL* CLK1
TP_C1.1
*SIGNAL* CLK2
TP_C2.1
*SIGNAL* GPIO0
TP_G0.1
*SIGNAL* SENSE_FB
TP_S1.1
"""


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def panel(qapp):
    w = ParseNetsPanel()
    w.set_net_source(NET_TEXT, "board.net")
    yield w
    w.deleteLater()


def _parse(panel):
    panel.parse_nets()
    assert panel.result is not None


# ------------------------------------------------------------ GUI wiring
def test_rules_editor_button_exists_and_persists(qapp, panel,
                                                 monkeypatch):
    """'Edit Net Classification Rules' opens the editor; accepted
    rules land in panel.net_rules (persisted by the page)."""
    assert hasattr(panel, "btn_rules")
    from mtkgui.gui.yamlbuild.net_rules import NetRulesEditorDialog
    monkeypatch.setattr(
        NetRulesEditorDialog, "exec",
        lambda self: NetRulesEditorDialog.DialogCode.Accepted)
    monkeypatch.setattr(
        NetRulesEditorDialog, "rules",
        lambda self: {"power": r"^PWR_"})
    panel._edit_rules()
    assert panel.net_rules == {"power": r"^PWR_"}
    captured = {}
    panel.rules_changed.connect(lambda d: captured.update(d))
    panel.rules_changed.emit(dict(panel.net_rules))
    assert captured == {"power": r"^PWR_"}


def test_power_tree_editor_requires_parse(qapp, panel, monkeypatch):
    """The topology editor moved to the dedicated Power Tree page:
    the panel only offers the navigation button (no local editing)."""
    assert not hasattr(panel, "btn_tree")
    assert hasattr(panel, "btn_open_tree")


def test_power_tree_navigation_button(qapp, panel):
    """'Open Power Tree Editor' emits the navigation request (the
    dialog closes and the page switches to the Power Tree tab)."""
    captured = []
    panel.power_tree_requested.connect(lambda: captured.append(1))
    panel.btn_open_tree.click()
    assert captured == [1]


# ------------------------------------------------- allocation behaviour
def test_auto_allocate_se_clock_and_gpio_tables(panel):
    """After parse: SE clock nets sequential into CLOCK_CHANNELS; the
    GPIO (Signal) table starts EMPTY - the engineer manually adds the
    target nets from the eligible candidates (invalid signals
    excluded)."""
    _parse(panel)
    clock_rows = panel._alloc_rows(panel.clock_table)
    # CLK1/CLK2 assigned the first two pool channels
    assert [r["net"] for r in clock_rows] == ["CLK1", "CLK2"]
    assert clock_rows[0]["channel"] == CLOCK_CHANNELS[0]
    assert clock_rows[1]["channel"] == CLOCK_CHANNELS[1]
    # GPIO table starts empty; GPIO0 is an eligible candidate,
    # SENSE_FB is excluded by the fixed invalid-signal regex
    assert panel._alloc_rows(panel.gpio_table) == []
    assert "GPIO0" in panel._gpio_candidates
    assert "SENSE_FB" not in panel._gpio_candidates


def test_manual_signal_add_and_dnt_toggle(panel):
    """Manual signal add assigns the first free DAQM907A DIO channel
    and survives via the overrides; the Do-Not-Test toggle wins."""
    _parse(panel)
    # manual add GPIO0 from the candidate list
    idx = panel.gpio_candidate_combo.findText("GPIO0")
    panel.gpio_candidate_combo.setCurrentIndex(idx)
    panel._add_signal_net()
    rows = panel._alloc_rows(panel.gpio_table)
    assert [r["net"] for r in rows] == ["GPIO0"]
    assert rows[0]["channel"] == GPIO_DIO_CHANNELS[0]
    assert rows[0]["channel"].startswith("DAQM907A DIO")
    # DNT toggle on a clock row
    panel.clock_table._dnt_boxes[0].setChecked(True)
    rows = panel._alloc_rows(panel.clock_table)
    assert rows[0]["status"] == "Not Test"
    assert panel._clock_overrides["CLK1"] == "Not Test"
    # manual channel override clears the DNT flag
    panel.clock_table.cellWidget(0, 1).setCurrentText(
        CLOCK_CHANNELS[1])
    assert panel.clock_table._dnt_boxes[0].isChecked() is False
    assert panel._clock_overrides["CLK1"] == CLOCK_CHANNELS[1]


# -------------------------------------------------- model YAML persistence
def test_model_persists_item24_sections():
    """rules / power tree / allocations persist into the project YAML
    and restore cleanly (empty/legacy files stay error-free)."""
    import yaml

    from mtkgui.gui.yamlbuild.model import YamlBuildModel
    model = YamlBuildModel()
    model.enable_all()
    fill_required(model)
    model.net_classification_rules = {"power": r"^PWR_"}
    model.power_tree = {"nodes": [{"name": "VDD_12V",
                                   "node_type": "normal",
                                   "stage": 0}],
                        "audit_log": [{"net": "VIN_24V",
                                       "reason": "passive bridge"}]}
    model.se_clock_allocation = [{"net": "CLK1",
                                  "channel": CLOCK_CHANNELS[0],
                                  "status": "Assigned"}]
    model.gpio_allocation = [{"net": "GPIO0",
                              "channel": GPIO_DIO_CHANNELS[0],
                              "status": "Not Test"}]
    doc = model.to_effective_dict()
    text = yaml.safe_dump(doc, sort_keys=False, allow_unicode=True)

    fresh = YamlBuildModel()
    fresh.enable_all()
    fill_required(fresh)
    assert fresh.apply_yaml_dict(yaml.safe_load(text)) == []
    assert fresh.net_classification_rules == {"power": r"^PWR_"}
    assert fresh.power_tree == model.power_tree
    assert fresh.se_clock_allocation == model.se_clock_allocation
    assert fresh.gpio_allocation == model.gpio_allocation
    # legacy file without the sections: blank, no error
    legacy = YamlBuildModel()
    legacy.enable_all()
    legacy.apply_yaml_dict({"yaml_build": {"plan_version": "1.0.0",
                                           "modules": {}}})
    assert legacy.net_classification_rules == {}
    assert legacy.gpio_allocation == []


def test_model_state_round_trip_item24():
    from mtkgui.gui.yamlbuild.model import YamlBuildModel
    model = YamlBuildModel()
    model.net_classification_rules = {"gnd": r"^GND_"}
    model.power_tree = {"nodes": [], "audit_log": []}
    model.se_clock_allocation = [{"net": "CLK1", "channel": "X",
                                  "status": "Assigned"}]
    model.gpio_allocation = []
    restored = YamlBuildModel()
    restored.apply_state(model.to_dict())
    assert restored.net_classification_rules == {"gnd": r"^GND_"}
    assert restored.power_tree == {"nodes": [], "audit_log": []}
    assert restored.se_clock_allocation == model.se_clock_allocation
