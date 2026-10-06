# -*- coding: utf-8 -*-
"""Test path complexity risk evaluation (topology-based scoring).

Covers the headless core (loop_risk_score / evaluate_paths), the
GUI-configurable thresholds, the panel Risk column wiring and the
project YAML / state persistence.
"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from mtkgui.gui.yamlbuild.path_risk import (  # noqa: E402
    LEVEL_HIGH,
    LEVEL_LOW,
    LEVEL_MEDIUM,
    MAX_SCORE,
    WARNING_MESSAGE,
    evaluate_paths,
    loop_risk_score,
    normalize_thresholds,
    risk_level,
)

# VIN_24V -> R4 -> MID_A -> R5 -> MID_B -> R6 -> GND
#   (3 series passives + 2 intermediate nets = 5 -> Medium)
# CLK1 -> R8 -> CLKMID1 -> R9 -> CLKMID2 -> R10 -> CLKMID3
#        -> R11 -> GND (4 passives + 3 intermediates = 7 -> High)
# GPIO0 -> R12 -> GND (1 passive, direct = 1 -> Low)
NET_TEXT = """*SIGNAL* VIN_24V
R4.1
*SIGNAL* MID_A
R4.2 R5.1
*SIGNAL* MID_B
R5.2 R6.1
*SIGNAL* GND
R6.2
*SIGNAL* CLK1
R8.1
*SIGNAL* CLKMID1
R8.2 R9.1
*SIGNAL* CLKMID2
R9.2 R10.1
*SIGNAL* CLKMID3
R10.2 R11.1
*SIGNAL* GND
R11.2 U2.2
*SIGNAL* GPIO0
R12.1
*SIGNAL* GND
R12.2 U1.1
"""

MEMBERS = {
    "VIN_24V": ["R4.1"], "MID_A": ["R4.2", "R5.1"],
    "MID_B": ["R5.2", "R6.1"], "GND": ["R6.2", "R11.2", "R12.2",
                                       "U1.1", "U2.2"],
    "CLK1": ["R8.1"], "CLKMID1": ["R8.2", "R9.1"],
    "CLKMID2": ["R9.2", "R10.1"], "CLKMID3": ["R10.2", "R11.1"],
    "GPIO0": ["R12.1"],
}
GND = {"GND"}


# ------------------------------------------------------------ headless core
def test_direct_passive_is_low_risk():
    result = evaluate_paths(["GPIO0"], MEMBERS, GND)
    assert result["GPIO0"] == {"score": 1, "level": LEVEL_LOW,
                               "warning": False}


def test_passive_chain_scores_medium_and_high():
    result = evaluate_paths(["VIN_24V", "CLK1"], MEMBERS, GND)
    assert result["VIN_24V"]["score"] == 5
    assert result["VIN_24V"]["level"] == LEVEL_MEDIUM
    assert result["VIN_24V"]["warning"] is True
    assert result["CLK1"]["score"] == 7
    assert result["CLK1"]["level"] == LEVEL_HIGH
    assert result["CLK1"]["warning"] is True


def test_regulator_bridge_does_not_count_as_passive():
    # U1 bridges GND and CLK1 (kind "regulator"): a direct active
    # bridge adds only the bridge hop, no passive component
    score = loop_risk_score("CLK1",
                            {"CLK1": [("GND", "regulator")]}, GND)
    assert score == 0     # no passives, no intermediate nets


def test_gnd_nets_are_never_scored():
    result = evaluate_paths(["GND", "GPIO0"], MEMBERS, GND)
    assert "GND" not in result
    assert loop_risk_score("GND", {}, GND) == 0


def test_no_path_to_gnd_scores_zero():
    members = {"FLOAT1": ["R1.1"], "FLOAT2": ["R1.2"]}
    result = evaluate_paths(["FLOAT1"], members, GND)
    assert result["FLOAT1"] == {"score": 0, "level": LEVEL_LOW,
                                "warning": False}


def test_score_is_capped_at_ten():
    long_chain = {"N0": [f"R{i}.1"] for i in range(1, 2)}
    adjacency = {"N0": [("N1", "passive")]}
    # 10+ hops collapse onto the cap
    adjacency = {
        f"N{i}": [(f"N{i + 1}", "passive")] for i in range(12)}
    assert loop_risk_score("N0", adjacency, {"N12"}) == MAX_SCORE


def test_thresholds_are_gui_configurable():
    assert risk_level(5) == LEVEL_MEDIUM
    assert risk_level(5, {"medium_min": 6, "high_min": 9}) == LEVEL_LOW
    assert risk_level(7, {"medium_min": 6, "high_min": 9}) == \
        LEVEL_MEDIUM
    # normalization clamps invalid / crossed values
    assert normalize_thresholds({"medium_min": 12, "high_min": -3}) == \
        {"medium_min": 9, "high_min": 10}
    assert normalize_thresholds({"medium_min": 8, "high_min": 5}) == \
        {"medium_min": 8, "high_min": 9}
    assert normalize_thresholds(None) == {"medium_min": 4,
                                          "high_min": 7}


def test_warning_message_wording():
    assert WARNING_MESSAGE.startswith(
        "Warning: Complex test path detected.")
    assert "parasitic inductance/resistance" in WARNING_MESSAGE
    assert "review test point placement" in WARNING_MESSAGE


# ------------------------------------------------------------- GUI wiring
@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def panel(qapp):
    from mtkgui.gui.yamlbuild.parse_nets import ParseNetsPanel
    w = ParseNetsPanel()
    w.set_net_source(NET_TEXT, "board.net")
    yield w
    w.deleteLater()


def test_panel_parse_fills_risk_column(panel):
    panel.parse_nets()
    assert panel.result is not None
    # power nets are scored too (rail voltage test) even without a
    # dedicated allocation table
    assert panel.risk_scores["VIN_24V"]["score"] == 5
    headers = [panel.clock_table.horizontalHeaderItem(i).text()
               for i in range(panel.clock_table.columnCount())]
    assert "Risk (0-10)" in headers
    rows = {panel.clock_table.item(r, 0).text():
            panel.clock_table.item(r, 3).text()
            for r in range(panel.clock_table.rowCount())}
    assert rows["CLK1"] == "7 (High)"
    # GPIO0 stays Low (direct passive)
    gpio_rows = {panel.gpio_table.item(r, 0).text():
                 panel.gpio_table.item(r, 3).text()
                 for r in range(panel.gpio_table.rowCount())}
    assert gpio_rows["GPIO0"] == "1 (Low)"


def test_threshold_change_reevaluates_live(panel, qapp, monkeypatch):
    from PySide6.QtWidgets import QDialog
    panel.parse_nets()
    monkeypatch.setattr(QDialog, "exec",
                        lambda self: QDialog.DialogCode.Accepted)
    panel._edit_risk_thresholds()   # defaults 4/7 accepted unchanged
    assert panel.risk_thresholds == {"medium_min": 4, "high_min": 7}
    # engineer tightens the thresholds -> CLK1 (7) drops to Medium
    panel.risk_thresholds = {"medium_min": 6, "high_min": 8}
    panel._auto_allocate(panel.result)
    rows = {panel.clock_table.item(r, 0).text():
            panel.clock_table.item(r, 3).text()
            for r in range(panel.clock_table.rowCount())}
    assert rows["CLK1"] == "7 (Medium)"


def test_advisory_only_assignment_not_blocked(panel):
    """A High-risk net KEEPS its channel assignment (advisory only);
    the engineer manually accepts the risk."""
    panel.parse_nets()
    rows = {panel.clock_table.item(r, 0).text():
            (panel.clock_table.item(r, 2).text(),
             panel.clock_table.cellWidget(r, 1).currentText())
            for r in range(panel.clock_table.rowCount())}
    assert rows["CLK1"][0] == "Assigned"
    assert rows["CLK1"][1].startswith(("DAQM907A", "U2355A"))


# ------------------------------------------------------------ persistence
def test_model_persists_path_risk_section():
    """thresholds + scores persist into the project YAML and restore
    cleanly (legacy files without the section stay error-free)."""
    import yaml

    from tests.yamlbuild.conftest import fill_required
    from mtkgui.gui.yamlbuild.model import YamlBuildModel
    model = YamlBuildModel()
    model.enable_all()
    fill_required(model)
    model.path_risk = {
        "thresholds": {"medium_min": 5, "high_min": 8},
        "scores": {"CLK1": {"score": 7, "level": LEVEL_HIGH,
                            "warning": True}},
    }
    doc = model.to_effective_dict()
    text = yaml.safe_dump(doc, sort_keys=False, allow_unicode=True)

    fresh = YamlBuildModel()
    fresh.enable_all()
    fill_required(fresh)
    assert fresh.apply_yaml_dict(yaml.safe_load(text)) == []
    assert fresh.path_risk == model.path_risk
    # legacy file without the section: blank, no error
    legacy = YamlBuildModel()
    legacy.enable_all()
    legacy.apply_yaml_dict({"yaml_build": {"plan_version": "1.0.0",
                                           "modules": {}}})
    assert legacy.path_risk == {}


def test_model_state_round_trip_path_risk():
    from mtkgui.gui.yamlbuild.model import YamlBuildModel
    model = YamlBuildModel()
    model.path_risk = {
        "thresholds": {"medium_min": 3, "high_min": 6},
        "scores": {"GPIO0": {"score": 1, "level": LEVEL_LOW,
                             "warning": False}},
    }
    restored = YamlBuildModel()
    restored.apply_state(model.to_dict())
    assert restored.path_risk == model.path_risk
