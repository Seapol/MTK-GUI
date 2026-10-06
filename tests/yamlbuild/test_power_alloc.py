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
    find_bridges,
)

NET_MEMBERS = {
    "VIN_24V": ["J1.1", "R5.1"],
    "VDD_12V": ["R5.2", "U1.1"],
    "VDD_5V": ["U1.2", "U2.1"],
    "VDD_3V3": ["U2.2", "U3.1"],
    "VDD_CORE": ["U3.2", "U4.1"],
}


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
