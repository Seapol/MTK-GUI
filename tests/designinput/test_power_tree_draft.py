# -*- coding: utf-8 -*-
"""Candidate power-tree derivation tests (topology only, no params)."""
from __future__ import annotations

from mtkgui.gui.yamlbuild.parser import parse_netlist

from mtkgui.gui.designinput.components import build_library
from mtkgui.gui.designinput.netlist import classify_nets
from mtkgui.gui.designinput.power_tree_draft import (
    DRAFT_MISSING_PARAM_TOOLTIP,
    derive_candidate_tree,
    guess_domain,
)

NETLIST_SAMPLE = """
*SIGNAL* VIN_5V
J1.1 U2.VIN
*SIGNAL* VPRE
U2.VOUT U3.VIN U4.VIN
*SIGNAL* VDD_CORE
U3.VOUT U1.VDD
*SIGNAL* VDD_IO
U3.SW U1.VCC
*SIGNAL* 3V3_LDO
U4.VOUT U1.VDDIO
*SIGNAL* GND
U1.GND J1.2
"""

COMPONENTS = [
    ("U1", "MIMXRT798S"),     # main_mcu (consumer only)
    ("U2", "PF1500"),         # pmic  -> stage 1 (VPRE)
    ("U3", "TPS62840"),       # dcdc  -> stage 2 (core/io)
    ("U4", "AP2112"),         # ldo   -> stage 3 (3V3_LDO)
]


def _tree():
    lib = build_library(COMPONENTS)
    col = classify_nets(parse_netlist(NETLIST_SAMPLE))
    return derive_candidate_tree(lib, col)


def test_all_nodes_marked_draft_missing_param():
    tree = _tree()
    assert tree.nodes
    assert all(n.draft_missing_param for n in tree.nodes)


def test_no_business_parameters_present():
    """Draft nodes carry NO voltage/tolerance/jumper fields."""
    tree = _tree()
    for node in tree.nodes:
        payload = vars(node)
        for forbidden in ("nominal", "tolerance_pct", "jumper_controlled",
                          "alt_nominal", "mutually_exclusive"):
            assert forbidden not in payload


def test_pmic_output_is_stage1():
    tree = _tree()
    assert tree.by_name("VPRE").power_stage == 1


def test_dcdc_outputs_stage2():
    tree = _tree()
    assert tree.by_name("VDD_CORE").power_stage == 2
    assert tree.by_name("VDD_IO").power_stage == 2


def test_ldo_output_stage3():
    tree = _tree()
    assert tree.by_name("3V3_LDO").power_stage == 3


def test_connector_input_is_stage0_source():
    tree = _tree()
    src = tree.by_name("VIN_5V")
    assert src.power_stage == 0
    assert "VPRE" in src.children


def test_edges_link_source_to_children():
    tree = _tree()
    assert ("VIN_5V", "VPRE") in tree.edges
    vpre = tree.by_name("VPRE")
    # VPRE feeds both dcdc outputs and the LDO input
    assert set(vpre.children) == {"VDD_CORE", "VDD_IO", "3V3_LDO"}
    assert vpre.sources == ["VIN_5V"]


def test_domain_guesses():
    assert guess_domain("VDD_CORE") == "core"
    assert guess_domain("VDD_IO_A") == "io"
    assert guess_domain("AVDD") == "analog"
    assert guess_domain("3V3") == "main"


def test_regulator_without_out_pin_warns():
    lib = build_library([("U9", "TPS62840")])   # no pins in netlist
    col = classify_nets(parse_netlist(NETLIST_SAMPLE))
    tree = derive_candidate_tree(lib, col)
    assert any("U9" in w for w in tree.warnings)


def test_fixed_tooltip_constant():
    assert DRAFT_MISSING_PARAM_TOOLTIP == (
        "草稿拓扑，需要同步至Power-Tree Editor填写电压、容差、跳线信息")
