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


# ------------------------------------------------- parsed nets behaviour
def test_parsed_nets_single_table_no_alloc_tables(panel):
    """The SE Clock / GPIO allocation tables are GONE (redundant - the
    channel assignment lives in Channel Allocation only); the single
    Parsed Nets table lists every net with a changeable Category and
    the Do-Not-Test defaults (Signal / GND default Not Test)."""
    _parse(panel)
    assert not hasattr(panel, "clock_table")
    assert not hasattr(panel, "gpio_table")
    assert not hasattr(panel, "btn_add_signal")
    assert not hasattr(panel, "gpio_candidate_combo")
    assert panel.table.columnCount() == 4
    rows = {panel.table.item(r, 0).text():
            (panel.table.cellWidget(r, 2).currentText(),
             panel.table.cellWidget(r, 3).isChecked())
            for r in range(panel.table.rowCount())}
    assert rows["CLK1"] == ("SE Clock", False)
    assert rows["GPIO0"] == ("Signal", True)      # default DNT
    assert rows["SENSE_FB"] == ("Signal", True)   # default DNT
    assert rows["VIN_24V"] == ("Power", False)


def test_dnt_toggle_and_category_override_survive_reparse(panel):
    """The Do-Not-Test toggle wins over the category default and the
    user category override survives a re-parse."""
    _parse(panel)
    rows = {panel.table.item(r, 0).text(): r
            for r in range(panel.table.rowCount())}
    # DNT toggle on the power net (NET_TEXT has no GND net; the two
    # Signal nets GPIO0 / SENSE_FB default Do Not Test)
    panel.table.cellWidget(rows["VIN_24V"], 3).setChecked(True)
    assert panel.power_dnt_nets() == ["GPIO0", "SENSE_FB", "VIN_24V"]
    # un-check a default-DNT signal
    panel.table.cellWidget(rows["GPIO0"], 3).setChecked(False)
    assert "GPIO0" not in panel.power_dnt_nets()
    # category override survives the re-parse
    panel.table.cellWidget(rows["GPIO0"], 2).setCurrentText("Power")
    panel.parse_nets()
    rows = {panel.table.item(r, 0).text(): r
            for r in range(panel.table.rowCount())}
    assert panel.table.cellWidget(rows["GPIO0"], 2).currentText() == \
        "Power"
    assert panel.table.cellWidget(rows["GPIO0"], 3).isChecked() is False


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
