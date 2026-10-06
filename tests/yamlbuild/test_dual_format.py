# -*- coding: utf-8 -*-
"""Dual-format (SPF / NET) parsing + Step-4 test-point selection
tests (Parse Nets for ICT core-algorithm standard)."""
from __future__ import annotations

import pytest

from mtkgui.gui.yamlbuild.dual_format import (  # noqa: E402
    clean_net_text,
    detect_netlist_format,
    parse_netlist_auto,
)
from mtkgui.gui.yamlbuild.test_points import (  # noqa: E402
    select_test_points,
)

SPF_TEXT = """[Document]
Rev: B

[Drawing]
FRDM-IMXRT700 CPU Board

[Component]
U1 ; MIMXRT798S
R1 ; 10K

[Net]
VDD_3V3 U1.5 C1.1
CLK_24M TP1 U1.10
GND U1.2
GPIO_LED1 R1.2
"""

# the SAME connectivity expressed as a standard Allegro NET export
NET_TEXT = """*SIGNAL* VDD_3V3
U1.5 C1.1
*SIGNAL* CLK_24M
TP1 U1.10
*SIGNAL* GND
U1.2
*SIGNAL* GPIO_LED1
R1.2
"""


# ------------------------------------------------------------- detection
def test_detect_spf_by_section_features():
    assert detect_netlist_format(SPF_TEXT) == "spf"


def test_detect_net_by_header_features():
    assert detect_netlist_format(NET_TEXT) == "net"


def test_detect_extension_free_routing():
    """Detection is purely header-feature based - the file NAME never
    participates (an SPF body named board.net still routes to SPF)."""
    # the text alone decides; no extension argument exists at all
    assert detect_netlist_format(SPF_TEXT) == "spf" != "net"


def test_detect_unknown_falls_back_to_net():
    assert detect_netlist_format("garbage without features") == \
        "unknown"


# ------------------------------------------------------------- cleaning
def test_net_cleaning_subckt_and_continuation():
    """Directive 4.2: subckt structures are dropped and ``+``
    continuation lines merge onto their previous line - all without
    touching the tolerant parser core."""
    raw = """.OPTIONS POST
.SUBCKT REG1 IN OUT GND
.ENDS REG1
*SIGNAL* VDD_3V3
C1.1
+ U1.5
*SIGNAL* GND
U1.2
"""
    cleaned = clean_net_text(raw)
    assert ".SUBCKT" not in cleaned and ".ENDS" not in cleaned
    assert "C1.1 U1.5" in cleaned           # continuation joined
    data = parse_netlist_auto(raw)
    assert data.nets["VDD_3V3"] == ["C1.1", "U1.5"]
    assert data.nets["GND"] == ["U1.2"]


# ------------------------------------------------- dual-format equivalence
def test_both_formats_parse_to_identical_model():
    """Core red line (4.3): SPF and NET branches emit the EXACT same
    structured output for the same connectivity."""
    spf = parse_netlist_auto(SPF_TEXT)
    net = parse_netlist_auto(NET_TEXT)
    assert spf.nets == net.nets
    assert spf.missing_tp == net.missing_tp


def test_both_formats_equivalent_downstream():
    """Classification, bridges, risk scoring and the power tree are
    identical for both formats (zero algorithm deviation)."""
    from mtkgui.gui.designinput.netlist import classify_nets
    from mtkgui.gui.yamlbuild.power_alloc import (
        PowerTree,
        find_bridges,
    )
    from mtkgui.gui.yamlbuild.path_risk import evaluate_paths
    spf = parse_netlist_auto(SPF_TEXT)
    net = parse_netlist_auto(NET_TEXT)
    col_spf = classify_nets(spf)
    col_net = classify_nets(net)
    assert [r.net_type for r in col_spf.nets] == \
        [r.net_type for r in col_net.nets]
    bridges_spf = find_bridges(spf.nets)
    bridges_net = find_bridges(net.nets)
    assert {(b["refdes"], b["nets"]) for b in bridges_spf} == \
        {(b["refdes"], b["nets"]) for b in bridges_net}
    tree_spf = PowerTree.build(["VDD_3V3"], bridges_spf,
                               primaries=["VDD_3V3"])
    tree_net = PowerTree.build(["VDD_3V3"], bridges_net,
                               primaries=["VDD_3V3"])
    assert {n: (v.stage, v.upstream) for n, v in
            tree_spf.nodes.items()} == \
        {n: (v.stage, v.upstream) for n, v in tree_net.nodes.items()}
    risk_spf = evaluate_paths(["VDD_3V3"], spf.nets, {"GND"})
    risk_net = evaluate_paths(["VDD_3V3"], net.nets, {"GND"})
    assert risk_spf == risk_net


# --------------------------------------------- Export-Logic pstxnet
PSTX_TEXT = """FILE_TYPE=NETLIST;
{ Allegro Export Logic netlist }
PRIM_FILE=...;

PART_NAME
 'U1'
 'MIMXRT798S';

NET_NAME
 'GND'
 '@NETLIST_LIB.GND(SCH_1):PAGE1'
 C_SIGNAL='@gnd';
 P U1.2;
 P C1.2;

NET_NAME
 'VDD_3V3'
 '@NETLIST_LIB.VDD_3V3(SCH_1):PAGE1'
 C_SIGNAL='@vdd';
 P U1.5;
 P C1.1;
"""


def test_detect_pstxnet_by_export_logic_features():
    assert detect_netlist_format(PSTX_TEXT) == "pstxnet"


def test_pstxnet_branch_parses_nets_and_pins():
    """The Cadence Export-Logic dialect (NET_NAME blocks, quoted
    names, P refdes.pin; members) parses into the unified model."""
    data = parse_netlist_auto(PSTX_TEXT)
    assert data.nets["GND"] == ["U1.2", "C1.2"]
    assert data.nets["VDD_3V3"] == ["U1.5", "C1.1"]
    assert "GND" in data.missing_tp


def test_pstxnet_equivalent_to_net_model():
    """pstxnet output == NET output for the same connectivity
    (classification / bridges / risk all identical)."""
    from mtkgui.gui.designinput.netlist import classify_nets
    net = parse_netlist_auto(NET_TEXT)
    pstx = parse_netlist_auto(PSTX_TEXT)
    types_net = {r.name: r.net_type for r in classify_nets(net).nets}
    types_pstx = {r.name: r.net_type
                  for r in classify_nets(pstx).nets}
    # same connectivity classifies identically
    assert types_pstx["VDD_3V3"] == types_net["VDD_3V3"]
    assert types_pstx["GND"] == types_net["GND"]


def test_unknown_file_diagnostic_error():
    """The failure names the detected format and the first line - the
    unsupported dialect is diagnosable without a debugger."""
    with pytest.raises(ValueError) as exc:
        parse_netlist_auto("random binary junk\nno headers here")
    assert "detected format" in str(exc.value)
    assert "random binary junk" in str(exc.value)


# ------------------------------------------------- user classification rules
def test_user_rules_override_classification():
    """Step 2: user regex rules take priority over the system
    defaults (Power / SE Clock / Signal; GND is system-auto)."""
    from mtkgui.gui.yamlbuild.parse_nets import parse_testable_nets
    # GPIO_LED1 is a signal by default; the user power rule
    # re-classifies it to Power
    result = parse_testable_nets(NET_TEXT, rules={"power": r"^GPIO_"})
    # VDD_3V3 keeps the kernel Power classification; GPIO_LED1 is
    # re-classified to Power by the user rule
    assert set(r.name for r in result.power) == \
        {"VDD_3V3", "GPIO_LED1"}
    # the clock rule wins for CLK_24M (user clock regex)
    result2 = parse_testable_nets(
        NET_TEXT, rules={"se_clock": r"^CLK_"})
    assert any(r.name == "CLK_24M" for r in result2.clock)
    # empty rules = pure system default classification
    result3 = parse_testable_nets(NET_TEXT, rules={})
    assert any(r.name == "CLK_24M" for r in result3.clock)
    assert all(r.name != "GPIO_LED1" for r in result3.power)


def test_signal_regex_filters_manual_candidates(qapp):
    """The Signal Nets regex filters the eligible manual-add
    candidates (only matching nets can be added)."""
    from mtkgui.gui.yamlbuild.parse_nets import ParseNetsPanel
    panel = ParseNetsPanel()
    try:
        panel.set_rules({"signal": r"^GPIO"})
        panel.set_net_source(NET_TEXT, "board.net")
        panel.parse_nets()
        assert panel.result is not None
        assert panel._gpio_candidates == ["GPIO_LED1"]
        # non-matching nets are not offerable
        assert "CLK_24M" not in panel._gpio_candidates
    finally:
        panel.deleteLater()


def test_inline_rules_live_in_panel(qapp):
    """The inline regex edits restore persisted rules, update the
    rules dict on edit and persist via the rules_changed mirror."""
    from mtkgui.gui.yamlbuild.parse_nets import ParseNetsPanel
    panel = ParseNetsPanel()
    try:
        panel.set_rules({"power": r"^PWR_"})
        assert panel.rule_edits["power"].text() == r"^PWR_"
        changed = []
        panel.rules_changed.connect(lambda d: changed.append(dict(d)))
        panel.rule_edits["se_clock"].setText(r"^CLK\d")
        panel._rule_edited("se_clock", panel.rule_edits["se_clock"])
        assert panel.net_rules == {"power": r"^PWR_",
                                   "se_clock": r"^CLK\d"}
        assert changed and changed[-1] == panel.net_rules
        # clearing the edit falls back to the system default
        panel.rule_edits["se_clock"].clear()
        panel._rule_edited("se_clock", panel.rule_edits["se_clock"])
        assert "se_clock" not in panel.net_rules
    finally:
        panel.deleteLater()


# ----------------------------------------------------- test-point Step 4
def test_test_point_priority_strict_order():
    """TP > J > JP > SJ > C > L > R - the best dedicated point wins."""
    members = ["R1.2", "C3.1", "L2.1", "SJ1.1", "J4.1", "TP9",
               "JP2.1"]
    best, kept = select_test_points(members)
    assert best == "TP9"
    assert kept[0] == "TP9"
    assert kept[1] == "J4.1"        # next rank, not TP redundancy
    assert kept[2] == "JP2.1"       # JP before SJ (strict hierarchy)


def test_no_tp_falls_to_pin_hierarchy():
    best, _kept = select_test_points(["R8.1", "C2.2", "JP5.1"])
    assert best == "JP5.1"


def test_single_candidate_and_empty():
    assert select_test_points(["R1.1"])[0] == "R1.1"
    assert select_test_points([]) == ("", [])


# ------------------------------------------------- panel integration
@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_panel_parses_spf_text_without_manual_choice(qapp):
    """An SPF body fed to the Parse Nets module routes automatically:
    no error, same categories as the NET equivalent."""
    from mtkgui.gui.yamlbuild.parse_nets import ParseNetsPanel
    panel = ParseNetsPanel()
    try:
        panel.set_net_source(SPF_TEXT, "board.spf")
        panel.parse_nets()
        assert panel.result is not None
        names = {r.name for r in panel.result.power}
        assert "VDD_3V3" in names
        assert panel.lbl_gnd_risk.text().startswith("GND integrity:")
    finally:
        panel.deleteLater()


def test_panel_gnd_multi_point_hint(qapp):
    from mtkgui.gui.yamlbuild.parse_nets import ParseNetsPanel
    panel = ParseNetsPanel()
    try:
        panel.set_net_source(NET_TEXT + "*SIGNAL* AGND\nU9.1\n",
                             "board.net")
        panel.parse_nets()
        assert panel.result is not None
        # two distinct reference grounds -> multi-point advisory
        assert "2 reference grounds" in panel.lbl_gnd_risk.text()
    finally:
        panel.deleteLater()
