# -*- coding: utf-8 -*-
"""v2-4 (node 02) parse-nets panel + four-class collapse."""
from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QComboBox  # noqa: E402

from mtkgui.ict.netparse.model import (NetRecord, ParseNetsResult)  # noqa: E402
from mtkgui.gui.yamlbuild.parse_nets_v2 import (  # noqa: E402
    V2ParseState, V2NetRow, collapse_route_a, collapse_route_b)
from mtkgui.gui.yamlbuild.parse_nets_v2_panel import (  # noqa: E402
    ParseNetsV2Panel, ROUTE_B_OTHER_NOTE)
from mtkgui.gui.yamlbuild.wizard_shell import YamlBuildWizard  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures")
VARIANT = os.path.join(
    FIXTURES,
    "96317_FRDM-IMXRT700_SPREADSHEET_revA_for_production_variant_TP11.xlsx")


# ------------------------------------------------------- headless collapse
def _route_a_result() -> ParseNetsResult:
    result = ParseNetsResult()
    result.power = [NetRecord(name="VDD1", members=["TP1.1"],
                              net_type="power")]
    result.clock = [NetRecord(name="CLK", members=["TP2.1"],
                              net_type="clock_single")]
    result.gnd = [NetRecord(name="GND", members=["TP3.1"],
                            net_type="gnd_ref")]
    result.control_io = [NetRecord(name="EN", members=["TP4.1"],
                                   net_type="signal")]
    result.others = [NetRecord(name="MISC", members=["TP5.1"],
                               net_type="signal")]
    result.filtered_records = [
        NetRecord(name="CLK_P", members=["TP6.1"], net_type="diff_pair")]
    return result


def test_collapse_route_a_four_classes():
    state = collapse_route_a(_route_a_result())
    assert state.count("Power") == 1
    assert state.count("SE Clock") == 1
    assert state.count("GND") == 1
    # control IO + others + diff pair all collapse to Other
    assert state.count("Other") == 3
    other_names = {r.name for r in state.rows if r.category == "Other"}
    assert other_names == {"EN", "MISC", "CLK_P"}


def test_collapse_route_b_carries_gate():
    from mtkgui.ict.netparse.route_b import parse_results_sheet
    state = collapse_route_b(parse_results_sheet(VARIANT))
    assert state.route == "excel"
    assert state.count("Power") == 16
    assert state.count("SE Clock") == 1
    assert state.gate_ok is True


# --------------------------------------------------------------- Qt panel
def _panel_with_rows():
    panel = ParseNetsV2Panel()
    state = V2ParseState(rows=[
        V2NetRow("VDD1", "Power", "power"),
        V2NetRow("CLK", "SE Clock", "clock_single"),
        V2NetRow("GND", "GND", "gnd_ref"),
        V2NetRow("EN", "Other", "control_io"),
    ])
    panel.set_state(state)
    return panel


def test_category_change_moves_row():
    panel = _panel_with_rows()
    assert panel.table.rowCount() == 3          # Power / SE Clock / GND
    assert panel.table_other.rowCount() == 1    # Other
    # change "VDD1" (Power, left) to Other -> moves to the right table
    combo = panel.table.cellWidget(0, 1)
    assert isinstance(combo, QComboBox)
    combo.setCurrentText("Other")
    assert panel.table.rowCount() == 2
    assert panel.table_other.rowCount() == 2
    other_names = {panel.table_other.item(r, 0).text()
                   for r in range(panel.table_other.rowCount())}
    assert other_names == {"EN", "VDD1"}


def test_route_b_category_readonly():
    panel = ParseNetsV2Panel()
    ok, _err = panel.load_route_b(VARIANT)
    assert ok
    assert panel.table.rowCount() == 17         # 16 Power + 1 SE Clock
    # the Category cell is a read-only item, not an editable combo
    assert panel.table.cellWidget(0, 1) is None
    item = panel.table.item(0, 1)
    assert item.text() == "Power"
    assert not (item.flags() & item.flags().ItemIsEditable)
    # the right table is greyed with the named note
    assert not panel.table_other.isEnabled()
    assert panel.lbl_other_note.text() == ROUTE_B_OTHER_NOTE


def test_gate_mismatch_marks_parse_ict_invalid():
    wizard = YamlBuildWizard()
    try:
        # complete node 01 so node 02 becomes editable (not just locked)
        wizard._panels["design_input"].set_values({
            "part_number": "MTK12345", "product_id": "96317",
            "sw_version": "1.2.3", "hw_version": "A",
            "batch": "EVT (Proto-1)", "ict_block_enabled": "true",
            "spf_file": "s.spf", "net_file": "n.net", "bom_file": "b.csv",
        })
        panel = wizard._panels["parse_ict"]
        panel.set_state(V2ParseState(
            route="excel", gate_ok=False,
            gate_error="impedance power nets do not match voltage"))
        wizard._refresh()
        assert wizard.flow.step_state("parse_ict") == "invalid"
        assert wizard.btn_next.isEnabled() is True
    finally:
        wizard.deleteLater()


def test_gate_ok_marks_parse_ict_valid():
    wizard = YamlBuildWizard()
    try:
        wizard._panels["design_input"].set_values({
            "part_number": "MTK12345", "product_id": "96317",
            "sw_version": "1.2.3", "hw_version": "A",
            "batch": "EVT (Proto-1)", "ict_block_enabled": "true",
            "spf_file": "s.spf", "net_file": "n.net", "bom_file": "b.csv",
        })
        panel = wizard._panels["parse_ict"]
        panel.set_state(V2ParseState(route="excel", gate_ok=True))
        wizard._refresh()
        assert wizard.flow.step_state("parse_ict") == "valid"
    finally:
        wizard.deleteLater()
