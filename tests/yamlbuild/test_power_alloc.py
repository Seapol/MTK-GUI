# -*- coding: utf-8 -*-
"""Item 24 Tasks 2-6: power tree / stages / pruning / channel
allocation / auto-generated net rule (headless core)."""
from __future__ import annotations

import pytest

from mtkgui.gui.yamlbuild.power_alloc import (
    ASSIGNED,
    CLOCK_CHANNELS,
    DONT_TEST,
    GPIO_DIO_CHANNELS,
    PowerTree,
    allocate_channels,
    auto_fill_voltage,
    auto_primaries,
    find_bridges,
    voltage_from_name,
)

NET_MEMBERS = {
    "VIN_24V": ["J1.1", "R5.1"],
    "VDD_12V": ["R5.2", "U1.1"],
    "VDD_5V": ["U1.2", "U2.1"],
    "VDD_3V3": ["U2.2", "U3.1"],
    "VDD_CORE": ["U3.2", "U4.1"],
}


# ------------------------------------------------- AI topology helpers
def test_voltage_from_name_parses_rail_tokens():
    assert voltage_from_name("VDD_3V3") == "3.3"
    assert voltage_from_name("DCDC_1V8") == "1.8"
    assert voltage_from_name("VDD_0V8_P2_DC") == "0.8"
    assert voltage_from_name("5V_SDA_PSW") == "5"
    assert voltage_from_name("DC_12V_IN") == "12"
    assert voltage_from_name("CPVOUTP") is None
    assert voltage_from_name("DBGIF_VREF") is None
    assert voltage_from_name("CORTEX7") is None     # no V token


def test_auto_primaries_direct_regulator_bridges_by_voltage():
    """Bridges with two decodable voltages are directed high -> low:
    the nodes without an incoming edge are the primaries (the
    regulator-fed rails and the passive-bridged lower side lose)."""
    primaries = auto_primaries(list(NET_MEMBERS),
                               find_bridges(NET_MEMBERS))
    assert "VIN_24V" in primaries        # highest rail: no incoming
    assert "VDD_CORE" in primaries       # no voltage: direction unknown
    assert "VDD_12V" not in primaries    # fed by the 24 V input (R5)
    assert "VDD_5V" not in primaries
    assert "VDD_3V3" not in primaries


def test_auto_primaries_fallback_input_name_pattern():
    """Without ANY decodable voltage pair the input-supply naming
    heuristic (VIN / VBUS / VBAT / DC_ / *_IN) picks the primaries."""
    power = ["PSW_MAIN", "VDD_CORE", "DC_5V_IN", "CPVOUTN"]
    bridges = [{"refdes": "U9", "kind": "regulator",
                "nets": ("PSW_MAIN", "VDD_CORE")}]
    assert auto_primaries(power, bridges) == ["DC_5V_IN"]


def test_auto_fill_voltage_and_tolerances():
    tree = PowerTree.build(["VIN_24V", "VDD_12V", "VDD_5V",
                            "VDD_3V3", "VDD_CORE"],
                           find_bridges(NET_MEMBERS),
                           primaries=auto_primaries(
                               list(NET_MEMBERS),
                               find_bridges(NET_MEMBERS)))
    filled = auto_fill_voltage(tree)
    assert filled == 4                   # VDD_CORE carries no voltage
    assert tree.nodes["VIN_24V"].expected_voltage == "24"
    assert tree.nodes["VDD_3V3"].expected_voltage == "3.3"
    assert tree.nodes["VDD_3V3"].tol_upper == "5%"
    assert tree.nodes["VDD_3V3"].tol_lower == "5%"
    assert tree.nodes["VDD_CORE"].expected_voltage == ""
    assert tree.nodes["VDD_CORE"].tol_upper == ""
    # manual override is never touched
    tree.nodes["VDD_5V"].expected_voltage = "5.1"
    auto_fill_voltage(tree)
    assert tree.nodes["VDD_5V"].expected_voltage == "5.1"


def test_find_bridges_passive_vs_regulator():
    bridges = find_bridges(NET_MEMBERS)
    kinds = {(frozenset(b["nets"]), b["kind"]) for b in bridges}
    # R5 bridges VIN_24V <-> VDD_12V (passive R)
    assert (frozenset(("VIN_24V", "VDD_12V")), "passive") in kinds
    # U1/U2/U3 are active converters (regulator bridges)
    assert (frozenset(("VDD_12V", "VDD_5V")), "regulator") in kinds
    assert (frozenset(("VDD_5V", "VDD_3V3")), "regulator") in kinds


def test_power_tree_stages_increment_only_on_regulator():
    tree = PowerTree.build(["VIN_24V", "VDD_12V", "VDD_5V",
                            "VDD_3V3", "VDD_CORE"],
                           find_bridges(NET_MEMBERS),
                           primaries=["VIN_24V"])
    assert tree.nodes["VIN_24V"].stage == 0          # Stage 0
    assert tree.nodes["VDD_12V"].node_type == "normal"
    assert tree.nodes["VDD_12V"].stage == 0          # passive: +0
    assert tree.nodes["VDD_5V"].stage == 1           # U1 regulator
    assert tree.nodes["VDD_3V3"].stage == 2          # U2
    assert tree.nodes["VDD_CORE"].stage == 3         # U3
    # load nodes (no downstream) are locked read-only
    assert tree.nodes["VDD_CORE"].locked is True


def test_island_node_without_upstream():
    tree = PowerTree.build(["VIN_24V", "VDD_FLOAT"], [],
                           primaries=["VIN_24V"])
    assert tree.nodes["VDD_FLOAT"].node_type == "island"
    assert tree.nodes["VDD_FLOAT"].stage == 1        # first conv default


# ------------------------------------------------- manual graph edits
def test_manual_link_unique_upstream_and_rules():
    """Flow-arrow links (GUI drag): the upstream stays UNIQUE (a new
    link replaces the old edge), a primary never gets an upstream,
    self-links and cycles are rejected."""
    tree = PowerTree.build(["VIN", "VDD", "VCC", "VFLOAT"], [],
                           primaries=["VIN"])
    ok, _ = tree.link("VIN", "VDD")
    assert ok
    ok, _ = tree.link("VDD", "VCC")
    assert ok
    # multiple downstream from one node
    tree.link("VIN", "VCC")
    assert tree.nodes["VCC"].upstream == ["VIN"]     # replaced, unique
    assert "VCC" not in tree.nodes["VDD"].downstream
    assert "VDD" in tree.nodes["VIN"].downstream
    assert "VCC" in tree.nodes["VIN"].downstream
    # primary: no upstream ever
    ok, msg = tree.link("VCC", "VIN")
    assert not ok and "primary" in msg
    # self-link rejected
    ok, _ = tree.link("VDD", "VDD")
    assert not ok
    # cycle rejected: VDD -> VFLOAT -> VCC -> VDD closes a loop
    tree.link("VDD", "VFLOAT")
    tree.link("VFLOAT", "VCC")
    ok, msg = tree.link("VCC", "VDD")
    assert not ok and "cycle" in msg
    # audit trail
    assert any("manual flow link" in a["reason"]
               for a in tree.audit_log)


def test_set_stage_clamps_to_max_stage():
    tree = PowerTree.build(["VIN", "VDD"], [], primaries=["VIN"])
    assert tree.set_stage("VDD", 9) == 6             # MAX_STAGE
    assert tree.nodes["VDD"].stage_override == 6
    assert tree.set_stage("VDD", -3) == 0
    assert tree.nodes["VDD"].stage_override == 0


def test_node_row_roundtrip():
    tree = PowerTree.build(["VIN", "VDD"], [], primaries=["VIN"])
    tree.nodes["VDD"].row = 3
    clone = PowerTree.from_dict(tree.to_dict())
    assert clone.nodes["VDD"].row == 3
    assert clone.nodes["VIN"].row is None


def test_prune_passive_keeps_load_side_with_audit():
    tree = PowerTree.build(["VIN_24V", "VDD_12V", "VDD_5V"],
                           find_bridges(NET_MEMBERS),
                           primaries=["VIN_24V"])
    pruned = tree.prune_passive(find_bridges(NET_MEMBERS))
    nets = {p["net"] for p in pruned}
    assert "VIN_24V" in nets            # upstream side pruned
    assert tree.nodes["VIN_24V"].pruned is True
    assert tree.nodes["VDD_12V"].pruned is False
    # audit log entry + manual restore
    assert any(a["net"] == "VIN_24V" and a["kept"] == "VDD_12V"
               for a in tree.audit_log)
    assert tree.restore_pruned("VIN_24V") is True
    assert tree.nodes["VIN_24V"].pruned is False
    assert any(a["reason"] == "manual restore"
               for a in tree.audit_log)


def test_prune_skips_regulator_and_primary():
    tree = PowerTree.build(["VIN_24V", "VDD_12V", "VDD_5V"],
                           find_bridges(NET_MEMBERS),
                           primaries=["VIN_24V"])
    tree.prune_passive(find_bridges(NET_MEMBERS))
    # regulator bridges (U1/U2) never prune; R5 prune stops at the
    # load side (VDD_12V kept)
    assert tree.nodes["VDD_5V"].pruned is False
    assert tree.nodes["VDD_12V"].pruned is False
    assert tree.nodes["VIN_24V"].node_type == "primary"


# ---------------------------------------------------------- allocators
def test_se_clock_sequential_allocation_and_dnt():
    nets = ["CLK1", "CLK2", "CLK3", "CLK4"]
    rows = allocate_channels(nets, CLOCK_CHANNELS)
    assert len(rows) == 4
    assert rows[0]["status"] == ASSIGNED
    assert rows[3]["status"] == DONT_TEST       # pool exhausted
    assert rows[3]["channel"] == ""
    # manual override wins: move CLK4 to a channel, mark CLK2 Not Test
    rows2 = allocate_channels(nets, CLOCK_CHANNELS,
                              {"CLK4": CLOCK_CHANNELS[0],
                               "CLK2": DONT_TEST})
    by_net = {r["net"]: r for r in rows2}
    assert by_net["CLK4"]["status"] == ASSIGNED
    assert by_net["CLK2"]["status"] == DONT_TEST


def test_gpio_allocation_daqm907a_dio_only():
    assert len(GPIO_DIO_CHANNELS) == 16
    assert all(ch.startswith("DAQM907A DIO")
               for ch in GPIO_DIO_CHANNELS)
    nets = [f"GPIO{n}" for n in range(20)]
    rows = allocate_channels(nets, GPIO_DIO_CHANNELS)
    assigned = [r for r in rows if r["status"] == ASSIGNED]
    not_test = [r for r in rows if r["status"] == DONT_TEST]
    assert len(assigned) == 16                  # DIO exhausted at 16
    assert len(not_test) == 4
    assert all(r["channel"].startswith("DAQM907A DIO")
               for r in assigned)


# -------------------------------------------------- persistence round trip
def test_power_tree_yaml_round_trip():
    tree = PowerTree.build(["VIN_24V", "VDD_12V", "VDD_5V"],
                           find_bridges(NET_MEMBERS),
                           primaries=["VIN_24V"])
    node = tree.nodes["VDD_5V"]
    node.expected_voltage = "5.0"
    node.tol_upper = "5%"
    node.tol_lower = "5%"
    node.dependencies = "EN1 high"
    node.stage_override = 4
    node.stage = 4                    # the dialog sets both
    node.dont_test = True
    tree.prune_passive(find_bridges(NET_MEMBERS))
    data = tree.to_dict()
    restored = PowerTree.from_dict(data)
    assert restored.to_dict() == data
    r5 = restored.nodes["VDD_5V"]
    assert r5.expected_voltage == "5.0"
    assert r5.stage_override == 4 and r5.stage == 4
    assert r5.dont_test is True
    assert restored.audit_log == tree.audit_log
