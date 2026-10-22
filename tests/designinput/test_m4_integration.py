# -*- coding: utf-8 -*-
"""M4 GUI integration: one parsing truth (PARTS 1/3/4/6).

The GUI mapping must reproduce the headless CLI result exactly -
membership, per-net test point, input_rail set and the GND sub-class
order (pcb -> chassis -> shield).  The power-tree draft takes stage-0
from netparse ``input_rail`` evidence only (no J-prefix heuristic).
"""
from __future__ import annotations

from mtkgui.ict.netparse import (parse_testable_nets, result_to_dict,
                                 select_test_points)

from mtkgui.gui.designinput.components import build_library
from mtkgui.gui.designinput.model import (capacity_hint,
                                          net_collection_from_result)
from mtkgui.gui.designinput.power_tree_draft import derive_candidate_tree

NETLIST = """
*SIGNAL* VBUS_5V
J1.1 F1.1 U2.VIN
*SIGNAL* VCC_AUX
J2.1 C5.1
*SIGNAL* 3V3
U2.VOUT C2.1
*SIGNAL* CLK_24M
U1.10
*SIGNAL* RST_B
U1.11
*SIGNAL* GND_SH_P5
R3.1
*SIGNAL* GND_EARTH
J3.1
*SIGNAL* GND
J1.2 U1.1
"""

LIBRARY = {
    "J1": {"part_number": "", "description": "CONN PWR JACK 5A"},
    "F1": {"part_number": "", "description": "FUSE 5A"},
    "J2": {"part_number": "", "description": "CONN HEADER 2.54MM"},
    "J3": {"part_number": "", "description": "CONN HEADER 2.54MM"},
    "U1": {"part_number": "MIMXRT798S", "description": "IC MCU"},
    "U2": {"part_number": "TPS62000", "description": "IC BUCK"},
    "C2": {"part_number": "", "description": "CAP CER 10uF"},
    "C5": {"part_number": "", "description": "CAP CER 0.1uF"},
    "R3": {"part_number": "", "description": "RES 0R"},
}


def _parse():
    return parse_testable_nets(NETLIST, library=LIBRARY)


def test_gui_mapping_matches_headless_json():
    """Same netlist + library -> identical buckets / probes / flags."""
    result = _parse()
    gui = net_collection_from_result(result, LIBRARY)
    payload = result_to_dict(result, library=LIBRARY)
    buckets = {
        "power": [e["net"] for e in payload["nets"]["power"]["nets"]],
        "clock": [e["net"] for e in payload["nets"]["clock"]["nets"]],
        "control_io": [
            e["net"] for e in payload["nets"]["control_io"]["nets"]],
        "others": [e["net"] for e in payload["nets"]["others"]],
        "gnd": [e["net"] for e in payload["nets"]["gnd"]],
    }
    assert buckets == {
        "power": [r.name for r in result.power],
        "clock": [r.name for r in result.clock],
        "control_io": [r.name for r in result.control_io],
        "others": [r.name for r in result.others],
        "gnd": [r.name for r in result.gnd],
    }
    assert [rec.name for rec in gui.nets] == [
        name for names in buckets.values() for name in names]
    # per-net test point identical (single headless implementation)
    entries = {e["net"]: e for e in
               (payload["nets"]["power"]["nets"]
                + payload["nets"]["clock"]["nets"]
                + payload["nets"]["control_io"]["nets"]
                + payload["nets"]["others"]
                + payload["nets"]["gnd"])}
    for rec in gui.nets:
        assert entries[rec.name]["test_point"] == \
            select_test_points(rec.members)[0]
        if rec.net_type == "power":
            assert entries[rec.name]["input_rail"] == rec.input_rail


def test_input_rails_come_from_netparse_evidence():
    """Only the fused power-inlet rail is an input rail; a plain
    connector pin is NOT (fix2 contradiction removed)."""
    result = _parse()
    gui = net_collection_from_result(result, LIBRARY)
    rails = [rec.name for rec in gui.nets
             if rec.net_type == "power" and rec.input_rail]
    assert rails == ["VBUS_5V"]
    assert gui.by_name("VCC_AUX").input_rail is False


def test_gnd_order_pcb_then_chassis_then_shield():
    """GND sub-class order is netparse rank order (pcb first)."""
    gui = net_collection_from_result(_parse(), LIBRARY)
    gnd = [(rec.name, rec.sub_class) for rec in gui.nets
           if rec.net_type == "gnd_ref"]
    assert gnd == [("GND", "pcb"), ("GND_EARTH", "chassis"),
                   ("GND_SH_P5", "shield")]


def test_capacity_hint_reads_the_parse_result():
    result = _parse()
    net_collection_from_result(result, LIBRARY)
    hint = capacity_hint(result)
    assert "power 3/80" in hint
    assert "GND ref 3" in hint
    assert "ctrl 1/24" in hint


def test_power_tree_stage0_follows_input_rail_only():
    """Input rails carry ``input_rail`` and render first; a J-prefix
    member alone never makes a stage-0 input."""
    library = build_library([("U1", "MIMXRT798S"), ("U2", "TPS62000")])
    result = _parse()
    collection = net_collection_from_result(result, LIBRARY)
    tree = derive_candidate_tree(library, collection)
    assert tree.nodes[0].rail_name == "VBUS_5V"
    assert tree.nodes[0].input_rail is True
    assert tree.by_name("VBUS_5V").power_stage == 0
    assert tree.by_name("VCC_AUX").input_rail is False
    assert tree.by_name("3V3").power_stage == 2
